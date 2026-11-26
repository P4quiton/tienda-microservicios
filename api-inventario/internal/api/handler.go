package api

import (
	"context"
	"errors"
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
