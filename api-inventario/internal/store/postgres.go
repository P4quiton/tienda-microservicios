package store

import (
	"context"
	"embed"
	"fmt"
	"net"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

//go:embed migrations/*.sql
var migrationFiles embed.FS

type Postgres struct {
	pool *pgxpool.Pool
}

func Open(ctx context.Context, host, port, database, user, password, sslMode string) (*Postgres, error) {
	dsn := (&url.URL{
		Scheme: "postgres",
		User:   url.UserPassword(user, password),
		Host:   net.JoinHostPort(host, port),
		Path:   "/" + database,
		RawQuery: url.Values{
			"sslmode": []string{sslMode},
		}.Encode(),
	}).String()

	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return nil, fmt.Errorf("configurar pool de PostgreSQL: %w", err)
	}

	var lastError error
	for attempt := 0; attempt < 30; attempt++ {
		pingCtx, cancel := context.WithTimeout(ctx, 2*time.Second)
		lastError = pool.Ping(pingCtx)
		cancel()

		if lastError == nil {
			store := &Postgres{pool: pool}
			if err := store.migrate(ctx); err != nil {
				pool.Close()
				return nil, err
			}

			return store, nil
		}

		select {
		case <-ctx.Done():
			pool.Close()
			return nil, ctx.Err()
		case <-time.After(time.Second):
		}
	}

	pool.Close()
	return nil, fmt.Errorf("conectar a PostgreSQL después de reintentos: %w", lastError)
}

func (p *Postgres) Ping(ctx context.Context) error {
	return p.pool.Ping(ctx)
}

func (p *Postgres) Close() {
	p.pool.Close()
}

func (p *Postgres) migrate(ctx context.Context) error {
	tx, err := p.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return fmt.Errorf("iniciar migración: %w", err)
	}
	defer tx.Rollback(ctx)

	if _, err := tx.Exec(ctx, `CREATE TABLE IF NOT EXISTS schema_migrations (
		version INTEGER PRIMARY KEY,
		aplicada_en TIMESTAMPTZ NOT NULL DEFAULT NOW()
	)`); err != nil {
		return fmt.Errorf("crear control de migraciones: %w", err)
	}

	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(8004)`); err != nil {
		return fmt.Errorf("bloquear migraciones concurrentes: %w", err)
	}

	migrations, err := migrationFiles.ReadDir("migrations")
	if err != nil {
		return fmt.Errorf("listar migraciones: %w", err)
	}
	for _, file := range migrations {
		if file.IsDir() || !strings.HasSuffix(file.Name(), ".sql") {
			continue
		}
		versionText, _, found := strings.Cut(file.Name(), "_")
		if !found {
			return fmt.Errorf("nombre de migración inválido: %s", file.Name())
		}
		version, err := strconv.Atoi(versionText)
		if err != nil {
			return fmt.Errorf("versión de migración inválida %s: %w", file.Name(), err)
		}

		var applied bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version = $1)`, version).Scan(&applied); err != nil {
			return fmt.Errorf("consultar estado de migración %d: %w", version, err)
		}
		if applied {
			continue
		}

		migration, err := migrationFiles.ReadFile("migrations/" + file.Name())
		if err != nil {
			return fmt.Errorf("leer migración %s: %w", file.Name(), err)
		}
		for _, statement := range strings.Split(string(migration), ";") {
			if strings.TrimSpace(statement) == "" {
				continue
			}
			if _, err := tx.Exec(ctx, statement); err != nil {
				return fmt.Errorf("aplicar migración %s: %w", file.Name(), err)
			}
		}
		if _, err := tx.Exec(ctx, `INSERT INTO schema_migrations (version) VALUES ($1)`, version); err != nil {
			return fmt.Errorf("registrar migración %s: %w", file.Name(), err)
		}
	}

	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("confirmar migración: %w", err)
	}

	return nil
}
