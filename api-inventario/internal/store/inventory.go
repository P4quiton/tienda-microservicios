package store

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
)

func Hash(value any) (string, error) {
	serialized, err := json.Marshal(value)
	if err != nil {
		return "", fmt.Errorf("serializar solicitud para idempotencia: %w", err)
	}

	hash := sha256.Sum256(serialized)
	return hex.EncodeToString(hash[:]), nil
}

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

func (p *Postgres) Replenish(ctx context.Context, idempotencyKey, identity, requestHash, productID string, quantity int64) (ReplenishmentResult, error) {
	tx, err := p.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return ReplenishmentResult{}, fmt.Errorf("iniciar reabastecimiento: %w", err)
	}
	defer tx.Rollback(ctx)

	storedResult, replay, err := beginIdempotentOperation(ctx, tx, idempotencyKey, identity, "reabastecer", requestHash)
	if err != nil {
		return ReplenishmentResult{}, err
	}
	if replay {
		var result ReplenishmentResult
		if err := json.Unmarshal(storedResult, &result); err != nil {
			return ReplenishmentResult{}, fmt.Errorf("decodificar reabastecimiento repetido: %w", err)
		}
		if err := tx.Commit(ctx); err != nil {
			return ReplenishmentResult{}, fmt.Errorf("confirmar respuesta idempotente: %w", err)
		}
		return result, nil
	}

	var result ReplenishmentResult
	result.ProductoID = productID
	err = tx.QueryRow(ctx, `
		INSERT INTO inventarios (producto_id, stock_fisico, reservado)
		VALUES ($1, $2, 0)
		ON CONFLICT (producto_id) DO UPDATE
		SET stock_fisico = inventarios.stock_fisico + EXCLUDED.stock_fisico,
		    actualizado_en = NOW()
		WHERE inventarios.stock_fisico <= 9223372036854775807 - EXCLUDED.stock_fisico
		RETURNING stock_fisico - reservado`, productID, quantity).Scan(&result.Disponibles)
	if errors.Is(err, pgx.ErrNoRows) {
		return ReplenishmentResult{}, ErrConflict
	}
	if err != nil {
		return ReplenishmentResult{}, fmt.Errorf("incrementar existencias: %w", err)
	}

	if err := saveIdempotentResult(ctx, tx, idempotencyKey, result); err != nil {
		return ReplenishmentResult{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return ReplenishmentResult{}, fmt.Errorf("confirmar reabastecimiento: %w", err)
	}
	return result, nil
}
