package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
)

func (p *Postgres) LookupIdempotency(ctx context.Context, key, identity, operation, requestHash string, result any) (bool, error) {
	var storedIdentity, storedOperation, storedHash string
	var storedResult []byte
	err := p.pool.QueryRow(ctx, `
		SELECT identidad, operacion, request_hash, resultado
		FROM operaciones_idempotentes
		WHERE idempotency_key = $1`, key).Scan(&storedIdentity, &storedOperation, &storedHash, &storedResult)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("consultar clave de idempotencia: %w", err)
	}
	if (storedIdentity != identity && storedIdentity != "admin:legacy") || storedOperation != operation || storedHash != requestHash {
		return false, ErrConflict
	}
	if len(storedResult) == 0 || string(storedResult) == "{}" {
		return false, ErrInProgress
	}
	if err := json.Unmarshal(storedResult, result); err != nil {
		return false, fmt.Errorf("decodificar resultado idempotente: %w", err)
	}
	return true, nil
}

func beginIdempotentOperation(ctx context.Context, tx pgx.Tx, key, identity, operation, requestHash string) (json.RawMessage, bool, error) {
	var insertedKey string
	err := tx.QueryRow(ctx, `
		INSERT INTO operaciones_idempotentes (idempotency_key, identidad, operacion, request_hash, resultado)
		VALUES ($1, $2, $3, $4, '{}'::jsonb)
		ON CONFLICT (idempotency_key) DO NOTHING
		RETURNING idempotency_key`, key, identity, operation, requestHash).Scan(&insertedKey)
	if err == nil {
		return nil, false, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return nil, false, fmt.Errorf("registrar clave de idempotencia: %w", err)
	}

	var storedIdentity, storedOperation, storedHash string
	var result []byte
	err = tx.QueryRow(ctx, `
		SELECT identidad, operacion, request_hash, resultado
		FROM operaciones_idempotentes
		WHERE idempotency_key = $1
		FOR UPDATE`, key).Scan(&storedIdentity, &storedOperation, &storedHash, &result)
	if err != nil {
		return nil, false, fmt.Errorf("leer operación idempotente existente: %w", err)
	}
	if storedIdentity != identity || storedOperation != operation || storedHash != requestHash {
		return nil, false, ErrConflict
	}
	if len(result) == 0 || string(result) == "{}" {
		return nil, false, ErrInProgress
	}
	return json.RawMessage(result), true, nil
}

func saveIdempotentResult(ctx context.Context, tx pgx.Tx, key string, result any) error {
	serialized, err := json.Marshal(result)
	if err != nil {
		return fmt.Errorf("serializar resultado idempotente: %w", err)
	}
	if _, err := tx.Exec(ctx, `
		UPDATE operaciones_idempotentes
		SET resultado = $2::jsonb
		WHERE idempotency_key = $1`, key, serialized); err != nil {
		return fmt.Errorf("guardar resultado idempotente: %w", err)
	}
	return nil
}
