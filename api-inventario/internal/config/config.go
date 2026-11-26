package config

import (
	"fmt"
	"os"
	"strconv"
)

type Config struct {
	Port                string
	DatabaseHost        string
	DatabasePort        string
	DatabaseName        string
	DatabaseUser        string
	DatabasePassword    string
	DatabaseSSLMode     string
	JWTIssuer           string
	JWTAudience         string
	JWTPublicKeyPath    string
	PedidosServiceToken string
	ProductosAPIBaseURL string
}

func Load() (Config, error) {
	port := getEnv("PORT", "8004")
	if _, err := strconv.Atoi(port); err != nil {
		return Config{}, fmt.Errorf("PORT debe ser un número: %w", err)
	}

	config := Config{
		Port:                port,
		DatabaseHost:        getEnv("DB_HOST", "127.0.0.1"),
		DatabasePort:        getEnv("DB_PORT", "15432"),
		DatabaseName:        getEnv("DB_DATABASE", "db_inventario"),
		DatabaseUser:        getEnv("DB_USERNAME", "usr_inventario"),
		DatabasePassword:    os.Getenv("DB_PASSWORD"),
		DatabaseSSLMode:     getEnv("DB_SSLMODE", "prefer"),
		JWTIssuer:           getEnv("JWT_ISSUER", "api-usuarios"),
		JWTAudience:         getEnv("JWT_AUDIENCE", "tienda-microservicios"),
		JWTPublicKeyPath:    os.Getenv("JWT_PUBLIC_KEY_PATH"),
		PedidosServiceToken: os.Getenv("PEDIDOS_SERVICE_TOKEN"),
		ProductosAPIBaseURL: getEnv("PRODUCTOS_API_BASE_URL", "http://api-productos:8002"),
	}

	if config.DatabasePassword == "" {
		return Config{}, fmt.Errorf("DB_PASSWORD es obligatorio")
	}

	return config, nil
}

func getEnv(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}

	return fallback
}
