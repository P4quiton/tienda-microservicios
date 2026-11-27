package api

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"

	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/config"
	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/store"
	"github.com/google/uuid"
)

func TestReserveHTTPReplaysStockRejectionAfterReplenishment(t *testing.T) {
	host := os.Getenv("TEST_PG_HOST")
	if host == "" {
		t.Skip("TEST_PG_HOST no definido: se omite la prueba con PostgreSQL real")
	}
	ctx := t.Context()
	db, err := store.Open(ctx, host, os.Getenv("TEST_PG_PORT"), os.Getenv("TEST_PG_DATABASE"),
		os.Getenv("TEST_PG_USER"), os.Getenv("TEST_PG_PASSWORD"), "disable")
	if err != nil {
		t.Fatalf("abrir PostgreSQL de pruebas: %v", err)
	}
	t.Cleanup(db.Close)

	product, order, key := uuid.NewString(), uuid.NewString(), uuid.NewString()
	payload := func(quantity int) string {
		return fmt.Sprintf(`{"pedido_id":%q,"items":[{"producto_id":%q,"cantidad":%d}]}`, order, product, quantity)
	}
	router := NewRouter(config.Config{PedidosServiceToken: testServiceToken}, db)
	reserve := func(idempotencyKey string, quantity int) *httptest.ResponseRecorder {
		return performInventoryRequest(router, "/api/inventario/reservar", payload(quantity), testServiceToken, idempotencyKey)
	}
	rejected := reserve(key, 2)
	assertResponseStatus(t, rejected, http.StatusConflict)
	assertJSONError(t, rejected, "stock", "stock_insuficiente")

	if _, err := db.Replenish(ctx, uuid.NewString(), "admin:prueba", "reabastecimiento-de-prueba", product, 5); err != nil {
		t.Fatalf("reabastecer: %v", err)
	}
	replay := reserve(key, 2)
	assertResponseStatus(t, replay, http.StatusConflict)
	if replay.Body.String() != rejected.Body.String() {
		t.Fatalf("la respuesta repetida cambió: %s", replay.Body)
	}
	conflict := reserve(key, 1)
	assertResponseStatus(t, conflict, http.StatusConflict)
	assertJSONError(t, conflict, "idempotency_key", "conflicto_idempotencia")
	assertResponseStatus(t, reserve(uuid.NewString(), 2), http.StatusOK)
	if available, err := db.Available(ctx, product); err != nil || available != 3 {
		t.Fatalf("disponibles=%d, error=%v, se esperaban 3 disponibles", available, err)
	}
}
