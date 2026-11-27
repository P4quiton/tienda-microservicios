package store

// Pruebas contra PostgreSQL real. Se omiten si no hay base de pruebas.
// Variables: TEST_PG_HOST, TEST_PG_PORT, TEST_PG_DATABASE, TEST_PG_USER,
// TEST_PG_PASSWORD (base desechable; las pruebas usan UUID nuevos y no truncan).

import (
	"context"
	"errors"
	"os"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
)

const testIdentity = "service:pedidos"

func newTestStore(t *testing.T) *Postgres {
	t.Helper()
	host := os.Getenv("TEST_PG_HOST")
	if host == "" {
		t.Skip("TEST_PG_HOST no definido: se omiten las pruebas con PostgreSQL real")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	st, err := Open(ctx, host, os.Getenv("TEST_PG_PORT"), os.Getenv("TEST_PG_DATABASE"),
		os.Getenv("TEST_PG_USER"), os.Getenv("TEST_PG_PASSWORD"), "disable")
	if err != nil {
		t.Fatalf("abrir PostgreSQL de pruebas: %v", err)
	}
	t.Cleanup(st.Close)
	return st
}

func newID() string { return uuid.NewString() }

// seedStock fija el stock físico de un producto nuevo (reservado = 0).
func seedStock(t *testing.T, st *Postgres, productID string, physical int64) {
	t.Helper()
	if _, err := st.pool.Exec(context.Background(),
		`INSERT INTO inventarios (producto_id, stock_fisico, reservado) VALUES ($1, $2, 0)
		 ON CONFLICT (producto_id) DO UPDATE SET stock_fisico = EXCLUDED.stock_fisico`, productID, physical); err != nil {
		t.Fatalf("sembrar stock: %v", err)
	}
}

func addStock(t *testing.T, st *Postgres, productID string, extra int64) {
	t.Helper()
	if _, err := st.pool.Exec(context.Background(),
		`UPDATE inventarios SET stock_fisico = stock_fisico + $2 WHERE producto_id = $1`, productID, extra); err != nil {
		t.Fatalf("reabastecer: %v", err)
	}
}

func stockOf(t *testing.T, st *Postgres, productID string) (physical, reserved int64) {
	t.Helper()
	if err := st.pool.QueryRow(context.Background(),
		`SELECT stock_fisico, reservado FROM inventarios WHERE producto_id = $1`, productID).Scan(&physical, &reserved); err != nil {
		t.Fatalf("leer stock: %v", err)
	}
	return physical, reserved
}

func countRows(t *testing.T, st *Postgres, query string, args ...any) int {
	t.Helper()
	var n int
	if err := st.pool.QueryRow(context.Background(), query, args...).Scan(&n); err != nil {
		t.Fatalf("contar filas: %v", err)
	}
	return n
}

func reserveHashes(t *testing.T, orderID string, items []Item) (string, string) {
	t.Helper()
	normalized := NormalizeItems(items)
	idem, err := Hash(struct {
		PedidoID string `json:"pedido_id"`
		Items    []Item `json:"items"`
	}{orderID, items})
	if err != nil {
		t.Fatal(err)
	}
	reservation, err := Hash(normalized)
	if err != nil {
		t.Fatal(err)
	}
	return idem, reservation
}

func doReserve(t *testing.T, st *Postgres, key, orderID string, items []Item) (Reservation, error) {
	t.Helper()
	idem, reservation := reserveHashes(t, orderID, items)
	return st.Reserve(context.Background(), key, testIdentity, idem, reservation, orderID, NormalizeItems(items))
}

func TestReserveRejectionIsPersistedPerKey(t *testing.T) {
	st := newTestStore(t)
	product, order, key1, key2 := newID(), newID(), newID(), newID()
	items := []Item{{ProductoID: product, Cantidad: 5}}
	seedStock(t, st, product, 3)

	if _, err := doReserve(t, st, key1, order, items); !errors.Is(err, ErrInsufficientStock) {
		t.Fatalf("primera reserva: se esperaba ErrInsufficientStock, got %v", err)
	}
	if n := countRows(t, st, `SELECT COUNT(*) FROM reservas WHERE pedido_id = $1`, order); n != 0 {
		t.Fatalf("un rechazo no debe dejar reserva (hay %d)", n)
	}
	if n := countRows(t, st, `SELECT COUNT(*) FROM operaciones_idempotentes
		WHERE idempotency_key = $1 AND resultado->>'estado' = 'stock_insuficiente'`, key1); n != 1 {
		t.Fatalf("el rechazo debe quedar guardado bajo la clave (filas=%d)", n)
	}

	// Se reabastece: la MISMA clave sigue devolviendo el mismo rechazo.
	addStock(t, st, product, 10)
	if _, err := doReserve(t, st, key1, order, items); !errors.Is(err, ErrInsufficientStock) {
		t.Fatalf("misma clave tras reabastecer: se esperaba el mismo rechazo, got %v", err)
	}
	if _, reserved := stockOf(t, st, product); reserved != 0 {
		t.Fatalf("la repetición del rechazo no debe reservar (reservado=%d)", reserved)
	}

	// Una clave NUEVA para el mismo pedido se evalúa de nuevo y ahora procede.
	reservation, err := doReserve(t, st, key2, order, items)
	if err != nil || reservation.Estado != "reservada" {
		t.Fatalf("clave nueva tras reabastecer: got %+v, %v", reservation, err)
	}
	if _, reserved := stockOf(t, st, product); reserved != 5 {
		t.Fatalf("reservado = %d, se esperaba 5", reserved)
	}

	// La clave rechazada sigue siendo un rechazo aunque el pedido ya esté reservado.
	if _, err := doReserve(t, st, key1, order, items); !errors.Is(err, ErrInsufficientStock) {
		t.Fatalf("la clave rechazada debe seguir rechazada, got %v", err)
	}
	if _, reserved := stockOf(t, st, product); reserved != 5 {
		t.Fatalf("reservado cambió tras repetir el rechazo: %d", reserved)
	}
}

func TestReservePartialFailureRollsBackEverything(t *testing.T) {
	st := newTestStore(t)
	// Se ordenan para que el artículo con stock se procese ANTES que el que falla.
	first, second := newID(), newID()
	if first > second {
		first, second = second, first
	}
	order, key := newID(), newID()
	seedStock(t, st, first, 10)
	seedStock(t, st, second, 1)

	items := []Item{{ProductoID: first, Cantidad: 4}, {ProductoID: second, Cantidad: 2}}
	if _, err := doReserve(t, st, key, order, items); !errors.Is(err, ErrInsufficientStock) {
		t.Fatalf("se esperaba ErrInsufficientStock, got %v", err)
	}
	if _, reserved := stockOf(t, st, first); reserved != 0 {
		t.Fatalf("reserva parcial: el primer artículo quedó reservado (%d)", reserved)
	}
	if _, reserved := stockOf(t, st, second); reserved != 0 {
		t.Fatalf("reserva parcial: el segundo artículo quedó reservado (%d)", reserved)
	}
	if n := countRows(t, st, `SELECT COUNT(*) FROM reservas WHERE pedido_id = $1`, order); n != 0 {
		t.Fatalf("no debe existir fila de reserva (hay %d)", n)
	}

	// Producto inexistente en inventario cuenta como stock insuficiente.
	ghost := newID()
	if _, err := doReserve(t, st, newID(), newID(), []Item{{ProductoID: ghost, Cantidad: 1}}); !errors.Is(err, ErrInsufficientStock) {
		t.Fatalf("producto sin inventario: got %v", err)
	}
}

func TestReserveSameKeyWithDifferentRequestIsIdempotencyConflict(t *testing.T) {
	st := newTestStore(t)
	product, order, key := newID(), newID(), newID()
	seedStock(t, st, product, 10)
	items := []Item{{ProductoID: product, Cantidad: 2}}
	if _, err := doReserve(t, st, key, order, items); err != nil {
		t.Fatalf("reserva inicial: %v", err)
	}

	// Mismo pedido, otra cantidad, misma clave.
	other := []Item{{ProductoID: product, Cantidad: 3}}
	if _, err := doReserve(t, st, key, order, other); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("payload distinto: se esperaba ErrIdempotencyConflict, got %v", err)
	}
	// Otro pedido con la misma clave.
	if _, err := doReserve(t, st, key, newID(), items); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("otro pedido: se esperaba ErrIdempotencyConflict, got %v", err)
	}
	// Otra identidad con la misma clave.
	idem, reservation := reserveHashes(t, order, items)
	if _, err := st.Reserve(context.Background(), key, "admin:otro", idem, reservation, order, NormalizeItems(items)); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("otra identidad: se esperaba ErrIdempotencyConflict, got %v", err)
	}
	// Otra operación con la misma clave.
	confirmHash, _ := Hash(struct {
		PedidoID string `json:"pedido_id"`
	}{order})
	if _, err := st.ChangeReservationState(context.Background(), key, testIdentity, confirmHash, order, "confirmada"); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("otra operación: se esperaba ErrIdempotencyConflict, got %v", err)
	}
	if _, reserved := stockOf(t, st, product); reserved != 2 {
		t.Fatalf("los conflictos no deben alterar el stock (reservado=%d)", reserved)
	}

	// Un rechazo guardado también entra en conflicto con otro payload.
	poor, rejectedKey := newID(), newID()
	seedStock(t, st, poor, 1)
	if _, err := doReserve(t, st, rejectedKey, newID(), []Item{{ProductoID: poor, Cantidad: 9}}); !errors.Is(err, ErrInsufficientStock) {
		t.Fatalf("rechazo inicial: %v", err)
	}
	if _, err := doReserve(t, st, rejectedKey, newID(), []Item{{ProductoID: poor, Cantidad: 1}}); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("rechazo guardado con otro payload: se esperaba ErrIdempotencyConflict, got %v", err)
	}
}

func TestReserveConcurrentSameKeyHasSingleEffect(t *testing.T) {
	st := newTestStore(t)
	product, order, key := newID(), newID(), newID()
	seedStock(t, st, product, 10)
	items := []Item{{ProductoID: product, Cantidad: 4}}

	const workers = 24
	var wg sync.WaitGroup
	var failures atomic.Int32
	start := make(chan struct{})
	results := make([]Reservation, workers)
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			reservation, err := doReserve(t, st, key, order, items)
			if err != nil {
				t.Errorf("worker %d: %v", i, err)
				failures.Add(1)
				return
			}
			results[i] = reservation
		}(i)
	}
	close(start)
	wg.Wait()
	if failures.Load() > 0 {
		t.FailNow()
	}
	for i, reservation := range results {
		if reservation.Estado != "reservada" || reservation.PedidoID != order {
			t.Fatalf("worker %d devolvió %+v", i, reservation)
		}
	}
	if _, reserved := stockOf(t, st, product); reserved != 4 {
		t.Fatalf("reservado = %d, se esperaba un único efecto de 4", reserved)
	}
	if n := countRows(t, st, `SELECT COUNT(*) FROM reservas WHERE pedido_id = $1`, order); n != 1 {
		t.Fatalf("filas de reserva = %d, se esperaba 1", n)
	}
	if n := countRows(t, st, `SELECT COUNT(*) FROM operaciones_idempotentes WHERE idempotency_key = $1`, key); n != 1 {
		t.Fatalf("filas de clave = %d, se esperaba 1", n)
	}
}

func TestReserveConcurrentSameKeyRejectionIsStable(t *testing.T) {
	st := newTestStore(t)
	product, order, key := newID(), newID(), newID()
	seedStock(t, st, product, 1)
	items := []Item{{ProductoID: product, Cantidad: 4}}

	const workers = 24
	var wg sync.WaitGroup
	start := make(chan struct{})
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			if _, err := doReserve(t, st, key, order, items); !errors.Is(err, ErrInsufficientStock) {
				t.Errorf("worker %d: se esperaba ErrInsufficientStock, got %v", i, err)
			}
		}(i)
	}
	close(start)
	wg.Wait()
	if _, reserved := stockOf(t, st, product); reserved != 0 {
		t.Fatalf("reservado = %d, se esperaba 0", reserved)
	}
	if n := countRows(t, st, `SELECT COUNT(*) FROM operaciones_idempotentes WHERE idempotency_key = $1`, key); n != 1 {
		t.Fatalf("filas de clave = %d, se esperaba 1", n)
	}
}

func TestReserveConcurrentSameOrderDifferentKeysReservesOnce(t *testing.T) {
	st := newTestStore(t)
	product, order := newID(), newID()
	seedStock(t, st, product, 10)
	items := []Item{{ProductoID: product, Cantidad: 4}}

	const workers = 12
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			reservation, err := doReserve(t, st, newID(), order, items)
			if err != nil || reservation.Estado != "reservada" {
				t.Errorf("worker %d: %+v, %v", i, reservation, err)
			}
		}(i)
	}
	wg.Wait()
	if _, reserved := stockOf(t, st, product); reserved != 4 {
		t.Fatalf("reservado = %d, se esperaba 4 (una sola reserva por pedido)", reserved)
	}
}

func TestReserveConcurrentOrdersNeverOversell(t *testing.T) {
	st := newTestStore(t)
	product := newID()
	const stock, workers = 10, 40
	seedStock(t, st, product, stock)

	var wg sync.WaitGroup
	var accepted, rejected atomic.Int32
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := doReserve(t, st, newID(), newID(), []Item{{ProductoID: product, Cantidad: 1}})
			switch {
			case err == nil:
				accepted.Add(1)
			case errors.Is(err, ErrInsufficientStock):
				rejected.Add(1)
			default:
				t.Errorf("error inesperado: %v", err)
			}
		}()
	}
	wg.Wait()
	if accepted.Load() != stock || rejected.Load() != workers-stock {
		t.Fatalf("aceptadas=%d rechazadas=%d, se esperaba %d/%d", accepted.Load(), rejected.Load(), stock, workers-stock)
	}
	if _, reserved := stockOf(t, st, product); reserved != stock {
		t.Fatalf("reservado = %d, se esperaba %d", reserved, stock)
	}
}

func TestConfirmReleaseAndReplenishStayIdempotent(t *testing.T) {
	st := newTestStore(t)
	product, order := newID(), newID()
	seedStock(t, st, product, 10)
	items := []Item{{ProductoID: product, Cantidad: 3}}
	if _, err := doReserve(t, st, newID(), order, items); err != nil {
		t.Fatal(err)
	}

	hash, _ := Hash(struct {
		PedidoID string `json:"pedido_id"`
	}{order})
	confirmKey := newID()
	for attempt := 0; attempt < 3; attempt++ {
		reservation, err := st.ChangeReservationState(context.Background(), confirmKey, testIdentity, hash, order, "confirmada")
		if err != nil || reservation.Estado != "confirmada" {
			t.Fatalf("confirmar #%d: %+v, %v", attempt, reservation, err)
		}
	}
	if physical, reserved := stockOf(t, st, product); physical != 7 || reserved != 0 {
		t.Fatalf("tras confirmar: físico=%d reservado=%d, se esperaba 7/0", physical, reserved)
	}
	// Confirmada es terminal: liberar con otra clave es un conflicto de estado.
	if _, err := st.ChangeReservationState(context.Background(), newID(), testIdentity, hash, order, "liberada"); !errors.Is(err, ErrConflict) {
		t.Fatalf("liberar tras confirmar: se esperaba ErrConflict, got %v", err)
	}

	replenishKey := newID()
	replenishHash, _ := Hash(map[string]any{"producto_id": product, "cantidad": 5})
	first, err := st.Replenish(context.Background(), replenishKey, "admin:x", replenishHash, product, 5)
	if err != nil || first.Disponibles != 12 {
		t.Fatalf("reabastecer: %+v, %v", first, err)
	}
	again, err := st.Replenish(context.Background(), replenishKey, "admin:x", replenishHash, product, 5)
	if err != nil || again.Disponibles != 12 {
		t.Fatalf("repetición de reabastecer: %+v, %v", again, err)
	}
	if physical, _ := stockOf(t, st, product); physical != 12 {
		t.Fatalf("físico = %d, se esperaba 12 (sin doble efecto)", physical)
	}
	if _, err := st.Replenish(context.Background(), replenishKey, "admin:x", "otro-hash", product, 9); !errors.Is(err, ErrIdempotencyConflict) {
		t.Fatalf("reabastecer con payload distinto: got %v", err)
	}
}
