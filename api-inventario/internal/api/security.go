package api

import (
	"crypto"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/subtle"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/config"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

type jwtHeader struct {
	Algorithm string `json:"alg"`
}

type jwtClaims struct {
	Subject   string          `json:"sub"`
	Role      string          `json:"role"`
	Issuer    string          `json:"iss"`
	Audience  json.RawMessage `json:"aud"`
	IssuedAt  int64           `json:"iat"`
	ExpiresAt int64           `json:"exp"`
}

func ServiceAuth(serviceToken string) gin.HandlerFunc {
	return func(c *gin.Context) {
		if serviceToken == "" {
			writeError(c, http.StatusServiceUnavailable, "La autenticación entre servicios no está configurada.", nil)
			c.Abort()
			return
		}

		providedToken := c.GetHeader("X-Service-Token")
		if len(providedToken) != len(serviceToken) || subtle.ConstantTimeCompare([]byte(providedToken), []byte(serviceToken)) != 1 {
			writeError(c, http.StatusUnauthorized, "Credencial de servicio inválida.", nil)
			c.Abort()
			return
		}

		c.Set("caller_identity", "service:pedidos")
		c.Next()
	}
}

func AdminJWTAuth(config config.Config) gin.HandlerFunc {
	return func(c *gin.Context) {
		authorization := c.GetHeader("Authorization")
		if !strings.HasPrefix(authorization, "Bearer ") {
			writeError(c, http.StatusUnauthorized, "Credencial inválida.", nil)
			c.Abort()
			return
		}

		claims, err := verifyJWT(strings.TrimPrefix(authorization, "Bearer "), config)
		if err != nil {
			if err == errJWTConfiguration {
				writeError(c, http.StatusServiceUnavailable, "La validación JWT no está configurada.", nil)
			} else {
				writeError(c, http.StatusUnauthorized, "Credencial inválida.", nil)
			}
			c.Abort()
			return
		}

		if claims.Role != "admin" {
			writeError(c, http.StatusForbidden, "Permiso insuficiente.", nil)
			c.Abort()
			return
		}

		c.Set("caller_identity", "admin:"+claims.Subject)
		c.Next()
	}
}

var errJWTConfiguration = &jwtConfigurationError{}

type jwtConfigurationError struct{}

func (*jwtConfigurationError) Error() string { return "clave pública JWT no configurada" }

func verifyJWT(token string, configuration config.Config) (*jwtClaims, error) {
	if token == "" || len(token) > 8192 {
		return nil, errInvalidJWT
	}
	if configuration.JWTPublicKeyPath == "" {
		return nil, errJWTConfiguration
	}

	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil, errInvalidJWT
	}

	var header jwtHeader
	headerBytes, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil || json.Unmarshal(headerBytes, &header) != nil || header.Algorithm != "RS256" {
		return nil, errInvalidJWT
	}

	claimsBytes, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return nil, errInvalidJWT
	}
	var claims jwtClaims
	if err := json.Unmarshal(claimsBytes, &claims); err != nil {
		return nil, errInvalidJWT
	}

	publicKeyPEM, err := os.ReadFile(configuration.JWTPublicKeyPath)
	if err != nil || len(publicKeyPEM) == 0 {
		return nil, errJWTConfiguration
	}
	publicKey, err := parseRSAPublicKey(publicKeyPEM)
	if err != nil {
		return nil, errJWTConfiguration
	}

	signature, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil {
		return nil, errInvalidJWT
	}
	digest := sha256.Sum256([]byte(parts[0] + "." + parts[1]))
	if err := rsa.VerifyPKCS1v15(publicKey, crypto.SHA256, digest[:], signature); err != nil {
		return nil, errInvalidJWT
	}

	if claims.Issuer != configuration.JWTIssuer || !hasAudience(claims.Audience, configuration.JWTAudience) {
		return nil, errInvalidJWT
	}
	if claims.IssuedAt == 0 || claims.ExpiresAt == 0 || claims.IssuedAt > time.Now().Add(30*time.Second).Unix() || claims.ExpiresAt <= time.Now().Unix() {
		return nil, errInvalidJWT
	}
	parsedSubject, err := uuid.Parse(claims.Subject)
	if err != nil || parsedSubject.Version() != 4 {
		return nil, errInvalidJWT
	}

	return &claims, nil
}

var errInvalidJWT = &invalidJWTError{}

type invalidJWTError struct{}

func (*invalidJWTError) Error() string { return "token JWT inválido" }

func parseRSAPublicKey(publicKeyPEM []byte) (*rsa.PublicKey, error) {
	block, _ := pem.Decode(publicKeyPEM)
	if block == nil {
		return nil, errInvalidJWT
	}

	parsedKey, err := x509.ParsePKIXPublicKey(block.Bytes)
	if err == nil {
		key, ok := parsedKey.(*rsa.PublicKey)
		if !ok {
			return nil, errInvalidJWT
		}
		return key, nil
	}

	key, err := x509.ParsePKCS1PublicKey(block.Bytes)
	if err != nil {
		return nil, errInvalidJWT
	}
	return key, nil
}

func hasAudience(rawAudience json.RawMessage, expected string) bool {
	var singleAudience string
	if json.Unmarshal(rawAudience, &singleAudience) == nil {
		return singleAudience == expected
	}

	var audiences []string
	if json.Unmarshal(rawAudience, &audiences) != nil {
		return false
	}
	for _, audience := range audiences {
		if audience == expected {
			return true
		}
	}

	return false
}
