package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
)

func NewRouter() *gin.Engine {
	router := gin.New()
	router.Use(gin.Logger(), gin.Recovery())

	router.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "api-inventario"})
	})
	router.GET("/ready", func(c *gin.Context) {
		c.JSON(http.StatusServiceUnavailable, gin.H{"status": "unavailable", "service": "api-inventario"})
	})
	router.NoRoute(func(c *gin.Context) {
		c.JSON(http.StatusNotFound, gin.H{
			"success": false,
			"message": "Recurso no encontrado.",
			"errors":  gin.H{},
		})
	})

	return router
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
