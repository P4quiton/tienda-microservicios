package api

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/config"
	"github.com/gin-gonic/gin"
)

const (
	testServiceToken = "test-service-token"
	testOrderID      = "e1d467c6-8c1d-4f4f-b06d-0fc91d66bd28"
	testProductID    = "fa635e83-eb49-46f3-8248-af1690795ab9"
	testIdempotency  = "a6d976a2-542e-463a-8b29-4e0b69fe4687"
)

func testInventoryRouter() *gin.Engine {
	gin.SetMode(gin.TestMode)
	return NewRouter(config.Config{PedidosServiceToken: testServiceToken}, nil)
}

func performInventoryRequest(router http.Handler, path, body, serviceToken, idempotencyKey string) *httptest.ResponseRecorder {
	request := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
	request.Header.Set("Content-Type", "application/json")
	if serviceToken != "" {
		request.Header.Set("X-Service-Token", serviceToken)
	}
	if idempotencyKey != "" {
		request.Header.Set("Idempotency-Key", idempotencyKey)
	}
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	return response
}

func TestInternalMutationsRequireServiceAuthentication(t *testing.T) {
	router := testInventoryRouter()
	cases := []struct {
		name string
		path string
		body string
	}{
		{"reserve", "/api/inventario/reservar", `{"pedido_id":"` + testOrderID + `","items":[{"producto_id":"` + testProductID + `","cantidad":1}]}`},
		{"confirm", "/api/inventario/confirmar", `{"pedido_id":"` + testOrderID + `"}`},
		{"release", "/api/inventario/liberar", `{"pedido_id":"` + testOrderID + `"}`},
	}

	for _, testCase := range cases {
		t.Run(testCase.name+" missing token", func(t *testing.T) {
			response := performInventoryRequest(router, testCase.path, testCase.body, "", testIdempotency)
			assertResponseStatus(t, response, http.StatusUnauthorized)
		})
		t.Run(testCase.name+" invalid token", func(t *testing.T) {
			response := performInventoryRequest(router, testCase.path, testCase.body, "wrong-token", testIdempotency)
			assertResponseStatus(t, response, http.StatusUnauthorized)
		})
	}
}

func TestInternalMutationsRequireIdempotencyKey(t *testing.T) {
	router := testInventoryRouter()
	cases := []struct {
		name string
		path string
		body string
	}{
		{"reserve", "/api/inventario/reservar", `{"pedido_id":"` + testOrderID + `","items":[{"producto_id":"` + testProductID + `","cantidad":1}]}`},
		{"confirm", "/api/inventario/confirmar", `{"pedido_id":"` + testOrderID + `"}`},
		{"release", "/api/inventario/liberar", `{"pedido_id":"` + testOrderID + `"}`},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			response := performInventoryRequest(router, testCase.path, testCase.body, testServiceToken, "")
			assertResponseStatus(t, response, http.StatusUnprocessableEntity)
			if !strings.Contains(response.Body.String(), "Idempotency-Key") {
				t.Fatalf("expected validation error for Idempotency-Key, got %s", response.Body.String())
			}
		})
	}
}

func TestReservationRequestsValidateContractBeforeDatabaseAccess(t *testing.T) {
	router := testInventoryRouter()
	cases := []struct {
		name   string
		path   string
		body   string
		key    string
		status int
		field  string
	}{
		{"malformed idempotency key", "/api/inventario/reservar", `{"pedido_id":"` + testOrderID + `","items":[{"producto_id":"` + testProductID + `","cantidad":1}]}`, "not-a-uuid", http.StatusUnprocessableEntity, "Idempotency-Key"},
		{"invalid order id", "/api/inventario/reservar", `{"pedido_id":"invalid","items":[{"producto_id":"` + testProductID + `","cantidad":1}]}`, testIdempotency, http.StatusUnprocessableEntity, "pedido_id"},
		{"empty items", "/api/inventario/reservar", `{"pedido_id":"` + testOrderID + `","items":[]}`, testIdempotency, http.StatusUnprocessableEntity, "items"},
		{"nonpositive quantity", "/api/inventario/reservar", `{"pedido_id":"` + testOrderID + `","items":[{"producto_id":"` + testProductID + `","cantidad":0}]}`, testIdempotency, http.StatusUnprocessableEntity, "items.0.cantidad"},
		{"unknown request field", "/api/inventario/confirmar", `{"pedido_id":"` + testOrderID + `","unexpected":true}`, testIdempotency, http.StatusBadRequest, "JSON válido"},
		{"invalid order on release", "/api/inventario/liberar", `{"pedido_id":"invalid"}`, testIdempotency, http.StatusUnprocessableEntity, "pedido_id"},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			response := performInventoryRequest(router, testCase.path, testCase.body, testServiceToken, testCase.key)
			assertResponseStatus(t, response, testCase.status)
			if !strings.Contains(response.Body.String(), testCase.field) {
				t.Fatalf("expected error mentioning %q, got %s", testCase.field, response.Body.String())
			}
		})
	}
}

func assertResponseStatus(t *testing.T, response *httptest.ResponseRecorder, expected int) {
	t.Helper()
	if response.Code != expected {
		t.Fatalf("expected HTTP %d, got %d: %s", expected, response.Code, response.Body.String())
	}
}

func TestJSONBodySizeLimitHTTP(t *testing.T) {
	router := testInventoryRouter()
	valid := `{"pedido_id":"invalid"}`
	atLimit := valid + strings.Repeat(" ", maxBodyBytes-len(valid))
	for _, tc := range []struct {
		name, body  string
		unknownSize bool
		status      int
	}{
		{"límite exacto", atLimit, false, http.StatusUnprocessableEntity},
		{"longitud declarada", atLimit + " ", false, http.StatusRequestEntityTooLarge},
		{"longitud desconocida", atLimit + " ", true, http.StatusRequestEntityTooLarge},
		{"longitud desconocida y JSON inválido", "!" + atLimit, true, http.StatusRequestEntityTooLarge},
	} {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/api/inventario/confirmar", strings.NewReader(tc.body))
			if tc.unknownSize {
				req.ContentLength = -1
				req.TransferEncoding = []string{"chunked"}
			}
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("X-Service-Token", testServiceToken)
			res := httptest.NewRecorder()
			router.ServeHTTP(res, req)
			assertResponseStatus(t, res, tc.status)
			if tc.status == http.StatusRequestEntityTooLarge {
				assertJSONError(t, res, "", "")
			}
		})
	}
}
