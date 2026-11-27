package api

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"reflect"
	"testing"

	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/config"
	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/store"
	"github.com/jackc/pgx/v5/pgxpool"
)

// openReadyTestStore abre la BD de prueba (TEST_PG_*); sin esa configuración la prueba se omite.
func openReadyTestStore(t *testing.T) *store.Postgres {
	t.Helper()
	host := os.Getenv("TEST_PG_HOST")
	if host == "" {
		t.Skip("TEST_PG_HOST no definido: se omite la prueba de /ready con PostgreSQL real")
	}
	db, err := store.Open(t.Context(), host, os.Getenv("TEST_PG_PORT"), os.Getenv("TEST_PG_DATABASE"),
		os.Getenv("TEST_PG_USER"), os.Getenv("TEST_PG_PASSWORD"), "disable")
	if err != nil {
		t.Fatalf("abrir PostgreSQL de pruebas: %v", err)
	}
	t.Cleanup(db.Close)
	return db
}

func readyResponse(db *store.Postgres) *httptest.ResponseRecorder {
	router := NewRouter(config.Config{PedidosServiceToken: testServiceToken}, db)
	request := httptest.NewRequest(http.MethodGet, "/ready", nil)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	return response
}

func assertReadyBody(t *testing.T, response *httptest.ResponseRecorder, status string) {
	t.Helper()
	var body map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatalf("cuerpo de /ready no es JSON: %v (%s)", err, response.Body.String())
	}
	expected := map[string]any{"status": status, "service": "api-inventario"}
	if !reflect.DeepEqual(body, expected) {
		t.Fatalf("cuerpo de /ready = %v, se esperaba %v", body, expected)
	}
}

func TestReadyReturnsOKWhenDatabaseIsUp(t *testing.T) {
	db := openReadyTestStore(t)

	response := readyResponse(db)

	assertResponseStatus(t, response, http.StatusOK)
	assertReadyBody(t, response, "ok")
}

func TestReadyReturnsUnavailableWhenMigrationsTableIsMissing(t *testing.T) {
	db := openReadyTestStore(t)
	pool, err := pgxpool.New(t.Context(), readyTestDSN())
	if err != nil {
		t.Fatalf("abrir pool auxiliar de prueba: %v", err)
	}
	t.Cleanup(pool.Close)
	if _, err := pool.Exec(t.Context(), `DROP TABLE schema_migrations`); err != nil {
		t.Fatalf("quitar temporalmente schema_migrations: %v", err)
	}
	t.Cleanup(func() {
		ctx := context.Background()
		_, err := pool.Exec(ctx, `CREATE TABLE schema_migrations (
			version INTEGER PRIMARY KEY,
			aplicada_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
		)`)
		if err == nil {
			_, err = pool.Exec(ctx, `INSERT INTO schema_migrations (version) VALUES (1), (2)`)
		}
		if err != nil {
			t.Errorf("restaurar schema_migrations en la BD temporal: %v", err)
		}
	})

	response := readyResponse(db)

	assertResponseStatus(t, response, http.StatusServiceUnavailable)
	assertReadyBody(t, response, "unavailable")
}

func readyTestDSN() string {
	return (&url.URL{
		Scheme: "postgres",
		User:   url.UserPassword(os.Getenv("TEST_PG_USER"), os.Getenv("TEST_PG_PASSWORD")),
		Host:   net.JoinHostPort(os.Getenv("TEST_PG_HOST"), os.Getenv("TEST_PG_PORT")),
		Path:   "/" + os.Getenv("TEST_PG_DATABASE"),
		RawQuery: url.Values{
			"sslmode": []string{"disable"},
		}.Encode(),
	}).String()
}

func TestReadyReturnsUnavailableWhenDatabaseIsDown(t *testing.T) {
	db := openReadyTestStore(t)
	// Simula la caída: un pool cerrado rechaza las adquisiciones, igual que una BD inalcanzable para Ping.
	db.Close()

	response := readyResponse(db)

	assertResponseStatus(t, response, http.StatusServiceUnavailable)
	assertReadyBody(t, response, "unavailable")
}
