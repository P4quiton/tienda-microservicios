package store

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
)

func (p *Postgres) Available(ctx context.Context, productID string) (int64, error) {
	var available int64
	err := p.pool.QueryRow(ctx,
		`SELECT stock_fisico - reservado FROM inventarios WHERE producto_id = $1`,
		productID,
	).Scan(&available)
	if errors.Is(err, pgx.ErrNoRows) {
		return 0, ErrNotFound
	}
	if err != nil {
		return 0, fmt.Errorf("consultar existencias: %w", err)
	}
	return available, nil
}
