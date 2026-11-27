package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/config"
)

func TestRateLimitHTTPDefaultQuotas(t *testing.T) {
	router := testInventoryRouter()
	for _, group := range []struct {
		name, method  string
		paths         []string
		limit, status int
	}{
		{"consultas", http.MethodGet, []string{"/api/inventario/invalido"}, 120, http.StatusUnprocessableEntity},
		{"mutaciones", http.MethodPost, []string{"/api/inventario/reabastecer"}, 30, http.StatusUnauthorized},
		{"internas", http.MethodPost, []string{"/api/inventario/reservar", "/api/inventario/confirmar", "/api/inventario/liberar"}, 300, http.StatusUnprocessableEntity},
	} {
		t.Run(group.name, func(t *testing.T) {
			for i := 0; i <= group.limit; i++ {
				req := httptest.NewRequest(group.method, group.paths[i%len(group.paths)], strings.NewReader("{}"))
				req.Header.Set("X-Service-Token", testServiceToken)
				res := httptest.NewRecorder()
				router.ServeHTTP(res, req)
				if i < group.limit {
					assertResponseStatus(t, res, group.status)
					continue
				}
				assertResponseStatus(t, res, http.StatusTooManyRequests)
				retry, err := strconv.Atoi(res.Header().Get("Retry-After"))
				if err != nil || retry < 1 || retry > 60 {
					t.Fatalf("Retry-After inválido: %q", res.Header().Get("Retry-After"))
				}
				assertJSONError(t, res, "", "")
			}
		})
	}
}

func TestRateLimitForwardedIPRequiresTrustedProxy(t *testing.T) {
	const proxy = "192.0.2.1"
	for _, tc := range []struct {
		name         string
		proxies      []string
		secondStatus int
	}{
		{"directo", nil, http.StatusTooManyRequests},
		{"proxy ajeno", []string{"192.0.2.2"}, http.StatusTooManyRequests},
		{"proxy autorizado", []string{proxy + "/32"}, http.StatusUnprocessableEntity},
		{"configuración inválida", []string{proxy, "inválido"}, http.StatusTooManyRequests},
	} {
		t.Run(tc.name, func(t *testing.T) {
			router := NewRouter(config.Config{TrustedProxies: tc.proxies, RateLimitQuery: 1}, nil)
			request := func(forwarded string) *httptest.ResponseRecorder {
				req := httptest.NewRequest(http.MethodGet, "/api/inventario/invalido", nil)
				req.RemoteAddr = proxy + ":4321"
				req.Header.Set("X-Forwarded-For", forwarded)
				req.Header.Set("X-Real-IP", forwarded)
				res := httptest.NewRecorder()
				router.ServeHTTP(res, req)
				return res
			}
			assertResponseStatus(t, request("198.51.100.1"), http.StatusUnprocessableEntity)
			assertResponseStatus(t, request("198.51.100.2"), tc.secondStatus)
			assertResponseStatus(t, request("198.51.100.1"), http.StatusTooManyRequests)
		})
	}
}

func TestRateLimitPurgesExpiredClientsAndBoundsBuckets(t *testing.T) {
	now := time.Unix(0, 0)
	limiter := newRateLimiter(1, 2, func() time.Time { return now })
	for _, client := range []string{"a", "b", "c"} {
		if allowed, _ := limiter.allow(client); !allowed {
			t.Fatalf("primera solicitud de %s rechazada", client)
		}
	}
	now = now.Add(500 * time.Millisecond)
	if allowed, retry := limiter.allow("d"); allowed || retry != 59500*time.Millisecond {
		t.Fatalf("cupo compartido desbordado: permitido=%v espera=%v", allowed, retry)
	}
	if size := len(limiter.buckets); size != 3 {
		t.Fatalf("se esperaban dos contadores y uno compartido; hay %d", size)
	}
	now = now.Add(rateLimitWindow)
	if allowed, _ := limiter.allow("d"); !allowed {
		t.Fatal("el cupo se debe renovar al vencer la ventana")
	}
	if size := len(limiter.buckets); size != 1 {
		t.Fatalf("quedaron contadores vencidos: total=%d", size)
	}
}

func assertJSONError(t *testing.T, res *httptest.ResponseRecorder, field, code string) {
	t.Helper()
	var payload struct {
		Success *bool               `json:"success"`
		Message string              `json:"message"`
		Errors  map[string][]string `json:"errors"`
	}
	if err := json.Unmarshal(res.Body.Bytes(), &payload); err != nil ||
		payload.Success == nil || *payload.Success || payload.Message == "" || payload.Errors == nil {
		t.Fatalf("se esperaba un error JSON válido: %s", res.Body)
	}
	if field == "" {
		if len(payload.Errors) != 0 {
			t.Fatalf("se esperaba errors vacío: %s", res.Body)
		}
		return
	}
	if values := payload.Errors[field]; len(values) != 1 || values[0] != code {
		t.Fatalf("se esperaba el código %q en %q: %s", code, field, res.Body)
	}
}
