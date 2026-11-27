package config

import (
	"fmt"
	"net"
	"os"
	"strconv"
	"strings"
)

// Límites por defecto acordados por el equipo (peticiones por minuto y cliente).
const (
	DefaultRateLimitQuery      = 120
	DefaultRateLimitMutation   = 30
	DefaultRateLimitInternal   = 300
	DefaultRateLimitMaxClients = 10000
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

	// Límites por minuto y por cliente (acordados por el equipo). Alcance: por
	// instancia del proceso; con varias réplicas el límite efectivo se multiplica.
	RateLimitQuery    int // consultas públicas
	RateLimitMutation int // mutaciones de administrador
	RateLimitInternal int // rutas internas (X-Service-Token)
	// Tope de clientes distintos con contador vivo; acota la memoria.
	RateLimitMaxClients int
	// Proxies de confianza (IP o CIDR). Solo si la conexión directa viene de uno
	// de ellos se acepta X-Forwarded-For. Vacío: la IP del cliente es la del socket.
	TrustedProxies []string
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
		PedidosServiceToken: os.Getenv("SERVICE_TOKEN_PEDIDOS_INVENTARIO"),
		ProductosAPIBaseURL: getEnv("PRODUCTOS_API_BASE_URL", "http://api-productos:8002"),
	}

	if config.DatabasePassword == "" {
		return Config{}, fmt.Errorf("DB_PASSWORD es obligatorio")
	}

	var err error
	if config.RateLimitQuery, err = positiveIntEnv("RATE_LIMIT_CONSULTA_POR_MIN", DefaultRateLimitQuery); err != nil {
		return Config{}, err
	}
	if config.RateLimitMutation, err = positiveIntEnv("RATE_LIMIT_MUTACION_POR_MIN", DefaultRateLimitMutation); err != nil {
		return Config{}, err
	}
	if config.RateLimitInternal, err = positiveIntEnv("RATE_LIMIT_INTERNA_POR_MIN", DefaultRateLimitInternal); err != nil {
		return Config{}, err
	}
	if config.RateLimitMaxClients, err = positiveIntEnv("RATE_LIMIT_MAX_CLIENTES", DefaultRateLimitMaxClients); err != nil {
		return Config{}, err
	}
	if config.TrustedProxies, err = parseTrustedProxies(os.Getenv("TRUSTED_PROXIES")); err != nil {
		return Config{}, err
	}

	return config, nil
}

func getEnv(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}

	return fallback
}

func positiveIntEnv(name string, fallback int) (int, error) {
	raw := os.Getenv(name)
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value < 1 {
		return 0, fmt.Errorf("%s debe ser un entero positivo", name)
	}
	return value, nil
}

// parseTrustedProxies valida una lista separada por comas de IP o CIDR.
func parseTrustedProxies(raw string) ([]string, error) {
	var proxies []string
	for _, entry := range strings.Split(raw, ",") {
		entry = strings.TrimSpace(entry)
		if entry == "" {
			continue
		}
		_, network, cidrErr := net.ParseCIDR(entry)
		if cidrErr != nil && net.ParseIP(entry) == nil {
			return nil, fmt.Errorf("TRUSTED_PROXIES contiene un valor inválido: %q", entry)
		}
		if cidrErr == nil {
			ones, _ := network.Mask.Size()
			if ones == 0 {
				return nil, fmt.Errorf("TRUSTED_PROXIES no puede incluir rangos /0: %q", entry)
			}
		}
		proxies = append(proxies, entry)
	}
	return proxies, nil
}
