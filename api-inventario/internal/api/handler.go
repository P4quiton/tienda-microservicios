package api

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"math"
	"net/http"
	"os"
	"time"

	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/config"
	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/store"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

// maxBodyBytes es el límite de cuerpo JSON acordado (256 KiB); por encima, 413.
const maxBodyBytes = 262144

type Handler struct {
	configuration config.Config
	store         *store.Postgres
	products      ProductVerifier
}

type reserveRequest struct {
	PedidoID string       `json:"pedido_id"`
	Items    []store.Item `json:"items"`
}

type transitionRequest struct {
	PedidoID string `json:"pedido_id"`
}

type successEnvelope struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
	Data    any    `json:"data"`
}

func NewRouter(configuration config.Config, inventoryStore *store.Postgres) *gin.Engine {
	if os.Getenv("APP_ENV") == "production" {
		gin.SetMode(gin.ReleaseMode)
	}

	handler := &Handler{
		configuration: configuration,
		store:         inventoryStore,
		products:      NewProductVerifier(configuration.ProductosAPIBaseURL),
	}

	router := gin.New()
	configureTrustedProxies(router, configuration.TrustedProxies)
	router.Use(gin.Logger(), gin.Recovery())

	// /health y /ready quedan fuera del límite: son sondas de Compose/Kubernetes.
	queryLimit := rateLimitMiddleware(newRateLimiter(
		limitOrDefault(configuration.RateLimitQuery, config.DefaultRateLimitQuery),
		limitOrDefault(configuration.RateLimitMaxClients, config.DefaultRateLimitMaxClients), nil))
	mutationLimit := rateLimitMiddleware(newRateLimiter(
		limitOrDefault(configuration.RateLimitMutation, config.DefaultRateLimitMutation),
		limitOrDefault(configuration.RateLimitMaxClients, config.DefaultRateLimitMaxClients), nil))
	internalLimit := rateLimitMiddleware(newRateLimiter(
		limitOrDefault(configuration.RateLimitInternal, config.DefaultRateLimitInternal),
		limitOrDefault(configuration.RateLimitMaxClients, config.DefaultRateLimitMaxClients), nil))

	router.GET("/health", handler.health)
	router.GET("/ready", handler.ready)
	router.GET("/api/inventario/:producto_id", queryLimit, handler.getAvailability)
	// El límite va antes de la autenticación: frena también los intentos con
	// credenciales inválidas (fuerza bruta del token o JWT costosos de verificar).
	router.POST("/api/inventario/reabastecer", mutationLimit, AdminJWTAuth(configuration), handler.replenish)
	internal := router.Group("/api/inventario", internalLimit, ServiceAuth(configuration.PedidosServiceToken))
	internal.POST("/reservar", handler.reserve)
	internal.POST("/confirmar", handler.confirm)
	internal.POST("/liberar", handler.release)
	router.NoRoute(func(c *gin.Context) {
		writeError(c, http.StatusNotFound, "Recurso no encontrado.", nil)
	})

	return router
}

func limitOrDefault(value, fallback int) int {
	if value < 1 {
		return fallback
	}
	return value
}

// configureTrustedProxies fija la frontera de confianza para c.ClientIP().
// Gin confía por defecto en TODOS los proxies (cualquiera podría falsificar
// X-Forwarded-For y evadir el límite); aquí se reemplaza por la lista
// explícita de TRUSTED_PROXIES, vacía por defecto, y solo se lee
// X-Forwarded-For (no X-Real-IP).
func configureTrustedProxies(router *gin.Engine, proxies []string) {
	router.RemoteIPHeaders = []string{"X-Forwarded-For"}
	if err := router.SetTrustedProxies(proxies); err != nil {
		slog.Error("TRUSTED_PROXIES inválido; no se confía en ningún proxy", "error", err)
		_ = router.SetTrustedProxies(nil)
	}
}

func (h *Handler) health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "api-inventario"})
}

func (h *Handler) ready(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	if err := h.store.ReadyMigrado(ctx); err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"status": "unavailable", "service": "api-inventario"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "api-inventario"})
}

func (h *Handler) getAvailability(c *gin.Context) {
	productID, err := uuid.Parse(c.Param("producto_id"))
	if err != nil || productID.Version() != 4 {
		writeValidationError(c, "producto_id", "Debe ser un UUID v4 válido.")
		return
	}

	id := productID.String()
	available, err := h.store.Available(c.Request.Context(), id)
	if errors.Is(err, store.ErrNotFound) {
		if productErr := h.products.Exists(c.Request.Context(), id); productErr != nil {
			if errors.Is(productErr, ErrProductNotFound) {
				writeError(c, http.StatusNotFound, "El producto no existe.", nil)
			} else {
				writeError(c, http.StatusServiceUnavailable, "No se pudo validar el producto.", nil)
			}
			return
		}
		available = 0
	} else if err != nil {
		writeError(c, http.StatusServiceUnavailable, "La base de datos no está disponible.", nil)
		return
	}

	c.JSON(http.StatusOK, successEnvelope{
		Success: true,
		Message: "Existencias consultadas correctamente.",
		Data:    gin.H{"producto_id": id, "disponibles": available},
	})
}

type replenishRequest struct {
	ProductoID string `json:"producto_id"`
	Cantidad   int64  `json:"cantidad"`
}

func (h *Handler) replenish(c *gin.Context) {
	var request replenishRequest
	if !decodeJSON(c, &request) {
		return
	}
	productID, valid := parseUUIDv4Value(c, "producto_id", request.ProductoID)
	if !valid {
		return
	}
	if request.Cantidad < 1 {
		writeValidationError(c, "cantidad", "La cantidad debe ser un entero positivo.")
		return
	}
	idempotencyKey, valid := parseUUIDv4Value(c, "Idempotency-Key", c.GetHeader("Idempotency-Key"))
	if !valid {
		return
	}
	request.ProductoID = productID

	requestHash, err := store.Hash(request)
	if err != nil {
		writeError(c, http.StatusInternalServerError, "No se pudo procesar la solicitud.", nil)
		return
	}
	identity := callerIdentity(c)
	var previous store.ReplenishmentResult
	found, err := h.store.LookupIdempotency(
		c.Request.Context(), idempotencyKey, identity, "reabastecer", requestHash, &previous,
	)
	if err != nil {
		writeStoreError(c, err)
		return
	}
	if found {
		writeSuccess(c, http.StatusOK, "Inventario reabastecido correctamente.", previous)
		return
	}

	if err := h.products.Exists(c.Request.Context(), productID); err != nil {
		if errors.Is(err, ErrProductNotFound) {
			writeError(c, http.StatusNotFound, "El producto no existe.", nil)
		} else {
			writeError(c, http.StatusServiceUnavailable, "No se pudo validar el producto.", nil)
		}
		return
	}

	result, err := h.store.Replenish(
		c.Request.Context(), idempotencyKey, identity, requestHash, productID, request.Cantidad,
	)
	if err != nil {
		writeStoreError(c, err)
		return
	}
	writeSuccess(c, http.StatusOK, "Inventario reabastecido correctamente.", result)
}

func (h *Handler) reserve(c *gin.Context) {
	var request reserveRequest
	if !decodeJSON(c, &request) {
		return
	}
	orderID, valid := parseUUIDv4Value(c, "pedido_id", request.PedidoID)
	if !valid {
		return
	}
	idempotencyKey, valid := parseUUIDv4Value(c, "Idempotency-Key", c.GetHeader("Idempotency-Key"))
	if !valid {
		return
	}
	if len(request.Items) == 0 {
		writeValidationError(c, "items", "Debe incluir al menos un artículo.")
		return
	}

	quantities := make(map[string]int64, len(request.Items))
	for index := range request.Items {
		productID, productValid := parseUUIDv4Value(c, fmt.Sprintf("items.%d.producto_id", index), request.Items[index].ProductoID)
		if !productValid {
			return
		}
		if request.Items[index].Cantidad < 1 {
			writeValidationError(c, fmt.Sprintf("items.%d.cantidad", index), "La cantidad debe ser un entero positivo.")
			return
		}
		request.Items[index].ProductoID = productID
		if quantities[productID] > math.MaxInt64-request.Items[index].Cantidad {
			writeValidationError(c, fmt.Sprintf("items.%d.cantidad", index), "La cantidad acumulada está fuera de rango.")
			return
		}
		quantities[productID] += request.Items[index].Cantidad
	}

	items := make([]store.Item, 0, len(quantities))
	for productID, quantity := range quantities {
		items = append(items, store.Item{ProductoID: productID, Cantidad: quantity})
	}
	items = store.NormalizeItems(items)
	idempotencyHash, err := store.Hash(struct {
		PedidoID string       `json:"pedido_id"`
		Items    []store.Item `json:"items"`
	}{PedidoID: orderID, Items: request.Items})
	if err != nil {
		writeError(c, http.StatusInternalServerError, "No se pudo procesar la solicitud.", nil)
		return
	}
	reservationHash, err := store.Hash(items)
	if err != nil {
		writeError(c, http.StatusInternalServerError, "No se pudo procesar la solicitud.", nil)
		return
	}

	reservation, err := h.store.Reserve(c.Request.Context(), idempotencyKey, callerIdentity(c), idempotencyHash, reservationHash, orderID, items)
	if err != nil {
		writeStoreError(c, err)
		return
	}
	writeSuccess(c, http.StatusOK, "Existencias reservadas correctamente.", reservation)
}

func (h *Handler) confirm(c *gin.Context) {
	h.transitionReservation(c, "confirmada")
}

func (h *Handler) release(c *gin.Context) {
	h.transitionReservation(c, "liberada")
}

func (h *Handler) transitionReservation(c *gin.Context, targetState string) {
	var request transitionRequest
	if !decodeJSON(c, &request) {
		return
	}
	orderID, valid := parseUUIDv4Value(c, "pedido_id", request.PedidoID)
	if !valid {
		return
	}
	idempotencyKey, valid := parseUUIDv4Value(c, "Idempotency-Key", c.GetHeader("Idempotency-Key"))
	if !valid {
		return
	}
	requestHash, err := store.Hash(struct {
		PedidoID string `json:"pedido_id"`
	}{PedidoID: orderID})
	if err != nil {
		writeError(c, http.StatusInternalServerError, "No se pudo procesar la solicitud.", nil)
		return
	}

	reservation, err := h.store.ChangeReservationState(c.Request.Context(), idempotencyKey, callerIdentity(c), requestHash, orderID, targetState)
	if err != nil {
		writeStoreError(c, err)
		return
	}
	writeSuccess(c, http.StatusOK, "Estado de reserva actualizado.", reservation)
}

func writeError(c *gin.Context, status int, message string, fields map[string][]string) {
	if fields == nil {
		fields = map[string][]string{}
	}
	c.JSON(status, gin.H{
		"success": false,
		"message": message,
		"errors":  fields,
	})
}

func writeValidationError(c *gin.Context, field, message string) {
	writeError(c, http.StatusUnprocessableEntity, "Los datos enviados no son válidos.", map[string][]string{field: {message}})
}

func decodeJSON(c *gin.Context, destination any) bool {
	if c.Request.ContentLength > maxBodyBytes {
		writeError(c, http.StatusRequestEntityTooLarge, "Cuerpo demasiado grande.", nil)
		return false
	}
	// Se comprueba el tamaño antes de analizar JSON también con longitud
	// desconocida, aunque el cuerpo empiece con JSON inválido.
	body, err := io.ReadAll(http.MaxBytesReader(c.Writer, c.Request.Body, maxBodyBytes))
	if err != nil {
		var sizeError *http.MaxBytesError
		if errors.As(err, &sizeError) {
			writeError(c, http.StatusRequestEntityTooLarge, "Cuerpo demasiado grande.", nil)
			return false
		}
		writeError(c, http.StatusBadRequest, "No se pudo leer el cuerpo de la solicitud.", nil)
		return false
	}
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		writeError(c, http.StatusBadRequest, "El cuerpo debe ser JSON válido y respetar el contrato.", nil)
		return false
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		writeError(c, http.StatusBadRequest, "La solicitud debe contener un solo objeto JSON.", nil)
		return false
	}
	return true
}

func parseUUIDv4Value(c *gin.Context, field, raw string) (string, bool) {
	parsed, err := uuid.Parse(raw)
	if err != nil || parsed.Version() != 4 {
		writeValidationError(c, field, "Debe ser un UUID v4 válido.")
		return "", false
	}
	return parsed.String(), true
}

func callerIdentity(c *gin.Context) string {
	identity, _ := c.Get("caller_identity")
	value, _ := identity.(string)
	return value
}

func writeSuccess(c *gin.Context, status int, message string, data any) {
	c.JSON(status, successEnvelope{Success: true, Message: message, Data: data})
}

func writeStoreError(c *gin.Context, err error) {
	switch {
	case errors.Is(err, store.ErrNotFound):
		writeError(c, http.StatusNotFound, "Recurso no encontrado.", nil)
	case errors.Is(err, store.ErrInsufficientStock):
		writeError(c, http.StatusConflict, "Inventario insuficiente.", map[string][]string{"stock": {"stock_insuficiente"}})
	case errors.Is(err, store.ErrIdempotencyConflict):
		writeError(c, http.StatusConflict, "La clave de idempotencia ya se usó con otros datos.",
			map[string][]string{"idempotency_key": {"conflicto_idempotencia"}})
	case errors.Is(err, store.ErrConflict):
		writeError(c, http.StatusConflict, "La operación es incompatible con el estado actual del inventario.", nil)
	case errors.Is(err, store.ErrInProgress):
		writeError(c, http.StatusServiceUnavailable, "La operación sigue en curso; puede reintentarse con la misma clave.", nil)
	default:
		writeError(c, http.StatusServiceUnavailable, "La base de datos no está disponible.", nil)
	}
}
