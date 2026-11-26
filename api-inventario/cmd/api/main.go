package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/api"
	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/config"
	"github.com/P4quiton/tienda-microservicios/api-inventario/internal/store"
)

func main() {
	if err := run(); err != nil {
		slog.Error("api-inventario terminó con error", "error", err)
		os.Exit(1)
	}
}

func run() error {
	configuration, err := config.Load()
	if err != nil {
		return err
	}

	startupContext, cancelStartup := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancelStartup()

	inventoryStore, err := store.Open(
		startupContext,
		configuration.DatabaseHost,
		configuration.DatabasePort,
		configuration.DatabaseName,
		configuration.DatabaseUser,
		configuration.DatabasePassword,
		configuration.DatabaseSSLMode,
	)
	if err != nil {
		return err
	}
	defer inventoryStore.Close()

	server := &http.Server{
		Addr:              ":" + configuration.Port,
		Handler:           api.NewRouter(configuration, inventoryStore),
		ReadHeaderTimeout: 5 * time.Second,
	}

	serverErrors := make(chan error, 1)
	go func() {
		slog.Info("api-inventario escuchando", "port", configuration.Port)
		serverErrors <- server.ListenAndServe()
	}()

	shutdownContext, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	select {
	case err := <-serverErrors:
		if !errors.Is(err, http.ErrServerClosed) {
			return err
		}
	case <-shutdownContext.Done():
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := server.Shutdown(ctx); err != nil {
		return err
	}

	return nil
}
