package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"
)

var ErrProductNotFound = errors.New("producto no encontrado")

type ProductVerifier struct {
	BaseURL    string
	HTTPClient *http.Client
}

func NewProductVerifier(baseURL string) ProductVerifier {
	return ProductVerifier{
		BaseURL: strings.TrimRight(baseURL, "/"),
		HTTPClient: &http.Client{
			Timeout: 3 * time.Second,
		},
	}
}

func (v ProductVerifier) Exists(ctx context.Context, productID string) error {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, v.BaseURL+"/api/productos/"+productID, nil)
	if err != nil {
		return fmt.Errorf("crear solicitud a productos: %w", err)
	}
	response, err := v.HTTPClient.Do(request)
	if err != nil {
		return fmt.Errorf("api-productos no disponible: %w", err)
	}
	defer response.Body.Close()

	switch response.StatusCode {
	case http.StatusOK:
		var envelope struct {
			Success bool `json:"success"`
		}
		if err := json.NewDecoder(response.Body).Decode(&envelope); err != nil || !envelope.Success {
			return fmt.Errorf("respuesta inesperada de api-productos")
		}
		return nil
	case http.StatusNotFound:
		return ErrProductNotFound
	default:
		return fmt.Errorf("api-productos respondió HTTP %d", response.StatusCode)
	}
}
