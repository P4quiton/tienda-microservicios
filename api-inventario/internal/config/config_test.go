package config

import (
	"slices"
	"strings"
	"testing"
)

func TestLoadReadsPedidosTokenFromSharedName(t *testing.T) {
	t.Setenv("DB_PASSWORD", "solo-pruebas")
	t.Setenv("SERVICE_TOKEN_PEDIDOS_INVENTARIO", "token-compartido")
	t.Setenv("PEDIDOS_SERVICE_TOKEN", "nombre-antiguo")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if cfg.PedidosServiceToken != "token-compartido" {
		t.Fatalf("PedidosServiceToken = %q, se esperaba el valor de SERVICE_TOKEN_PEDIDOS_INVENTARIO", cfg.PedidosServiceToken)
	}
}

func TestLoadIgnoresLegacyPedidosTokenName(t *testing.T) {
	t.Setenv("DB_PASSWORD", "solo-pruebas")
	t.Setenv("SERVICE_TOKEN_PEDIDOS_INVENTARIO", "")
	t.Setenv("PEDIDOS_SERVICE_TOKEN", "nombre-antiguo")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if cfg.PedidosServiceToken != "" {
		t.Fatalf("PedidosServiceToken = %q, el nombre antiguo PEDIDOS_SERVICE_TOKEN no debe leerse", cfg.PedidosServiceToken)
	}
}

func TestLoadTrustedProxiesFromEnv(t *testing.T) {
	t.Setenv("DB_PASSWORD", "solo-pruebas")
	for _, tc := range []struct {
		name, env string
		want      []string
		invalid   bool
	}{
		{"vacío", "", nil, false},
		{"IP y CIDR", "192.0.2.1, 2001:db8::/64", []string{"192.0.2.1", "2001:db8::/64"}, false},
		{"CIDR IPv4 /8", "10.0.0.0/8", []string{"10.0.0.0/8"}, false},
		{"inválido", "192.0.2.1, proxy.local", nil, true},
		{"rechaza /0 IPv4", "0.0.0.0/0", nil, true},
		{"rechaza /0 IPv6", "::/0", nil, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("TRUSTED_PROXIES", tc.env)
			cfg, err := Load()
			if tc.invalid {
				if err == nil || !strings.Contains(err.Error(), "TRUSTED_PROXIES") {
					t.Fatalf("se esperaba un error de TRUSTED_PROXIES, se obtuvo %v", err)
				}
				return
			}
			if err != nil || !slices.Equal(cfg.TrustedProxies, tc.want) {
				t.Fatalf("proxies=%v, error=%v, se esperaba %v", cfg.TrustedProxies, err, tc.want)
			}
		})
	}
}
