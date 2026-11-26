package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"

	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/config"
	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/store"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

type Handler struct {
	store    *store.Postgres
	products ProductVerifier
}

type successEnvelope struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
	Data    any    `json:"data"`
}

func NewRouter(configuration config.Config, inventoryStore *store.Postgres) *gin.Engine {
	handler := &Handler{
		store:    inventoryStore,
		products: NewProductVerifier(configuration.ProductosAPIBaseURL),
	}

	router := gin.New()
	router.Use(gin.Logger(), gin.Recovery())
	router.GET("/health", handler.health)
	router.GET("/ready", handler.ready)
	router.GET("/api/inventario/:producto_id", handler.getAvailability)
	router.POST("/api/inventario/reabastecer", AdminJWTAuth(configuration), handler.replenish)
	router.NoRoute(func(c *gin.Context) {
		writeError(c, http.StatusNotFound, "Recurso no encontrado.", nil)
	})

	return router
}

func (h *Handler) health(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "api-inventario"})
}

func (h *Handler) ready(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	if err := h.store.Ping(ctx); err != nil {
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
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, 1<<20)
	decoder := json.NewDecoder(c.Request.Body)
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
	case errors.Is(err, store.ErrConflict):
		writeError(c, http.StatusConflict, "La clave de idempotencia ya se usó con otros datos.", nil)
	case errors.Is(err, store.ErrInProgress):
		writeError(c, http.StatusServiceUnavailable, "La operación sigue en curso; puede reintentarse con la misma clave.", nil)
	default:
		writeError(c, http.StatusServiceUnavailable, "La base de datos no está disponible.", nil)
	}
}
