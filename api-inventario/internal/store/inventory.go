package store

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"sort"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

func Hash(value any) (string, error) {
	serialized, err := json.Marshal(value)
	if err != nil {
		return "", fmt.Errorf("serializar solicitud para idempotencia: %w", err)
	}

	hash := sha256.Sum256(serialized)
	return hex.EncodeToString(hash[:]), nil
}

func NormalizeItems(items []Item) []Item {
	quantities := make(map[string]int64, len(items))
	for _, item := range items {
		quantities[item.ProductoID] += item.Cantidad
	}

	normalized := make([]Item, 0, len(quantities))
	for productID, quantity := range quantities {
		normalized = append(normalized, Item{ProductoID: productID, Cantidad: quantity})
	}

	sort.Slice(normalized, func(left, right int) bool {
		return normalized[left].ProductoID < normalized[right].ProductoID
	})

	return normalized
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

func (p *Postgres) Reserve(ctx context.Context, idempotencyKey, identity, idempotencyHash, reservationHash, orderID string, items []Item) (Reservation, error) {
	tx, err := p.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return Reservation{}, fmt.Errorf("iniciar reserva: %w", err)
	}
	defer tx.Rollback(ctx)

	storedResult, replay, err := beginIdempotentOperation(ctx, tx, idempotencyKey, identity, "reservar", idempotencyHash)
	if err != nil {
		return Reservation{}, err
	}
	if replay {
		var result Reservation
		if err := json.Unmarshal(storedResult, &result); err != nil {
			return Reservation{}, fmt.Errorf("decodificar reserva repetida: %w", err)
		}
		if err := tx.Commit(ctx); err != nil {
			return Reservation{}, fmt.Errorf("confirmar respuesta idempotente: %w", err)
		}
		if result.Estado == "stock_insuficiente" {
            return Reservation{}, ErrInsufficientStock
        }
        return result, nil
	}

	serializedItems, err := json.Marshal(items)
	if err != nil {
		return Reservation{}, fmt.Errorf("serializar artículos de reserva: %w", err)
	}

	if _, err := tx.Exec(ctx, "SAVEPOINT reserva_stock"); err != nil {
return Reservation{}, err
}

rejectStock := func() (Reservation, error) {
if _, err := tx.Exec(ctx, "ROLLBACK TO SAVEPOINT reserva_stock"); err != nil {
return Reservation{}, err
}

result := Reservation{
PedidoID: orderID,
Items: items,
Estado: "stock_insuficiente",
}

if err := saveIdempotentResult(ctx, tx, idempotencyKey, result); err != nil {
return Reservation{}, err
}

if err := tx.Commit(ctx); err != nil {
return Reservation{}, err
}

return Reservation{}, ErrInsufficientStock
}

var insertedOrderID string
	err = tx.QueryRow(ctx, `
		INSERT INTO reservas (pedido_id, request_hash, items, estado)
		VALUES ($1, $2, $3, 'reservada')
		ON CONFLICT (pedido_id) DO NOTHING
		RETURNING pedido_id`, orderID, reservationHash, serializedItems).Scan(&insertedOrderID)
	if errors.Is(err, pgx.ErrNoRows) {
		reservation, err := getReservationForUpdate(ctx, tx, orderID)
		if err != nil {
			return Reservation{}, err
		}
		if reservation.requestHash != reservationHash {
			return Reservation{}, ErrConflict
		}
		if err := saveIdempotentResult(ctx, tx, idempotencyKey, reservation.Reservation); err != nil {
			return Reservation{}, err
		}
		if err := tx.Commit(ctx); err != nil {
			return Reservation{}, fmt.Errorf("confirmar reserva idempotente: %w", err)
		}
		return reservation.Reservation, nil
	}
	if err != nil {
		return Reservation{}, fmt.Errorf("registrar reserva: %w", err)
	}

	for _, item := range items {
		var physical, reserved int64
		err := tx.QueryRow(ctx, `
			SELECT stock_fisico, reservado
			FROM inventarios
			WHERE producto_id = $1
			FOR UPDATE`, item.ProductoID).Scan(&physical, &reserved)
		if errors.Is(err, pgx.ErrNoRows) {
			return rejectStock()
		}
		if err != nil {
			return Reservation{}, fmt.Errorf("bloquear existencias: %w", err)
		}
		if physical-reserved < item.Cantidad {
			return rejectStock()
		}

		if _, err := tx.Exec(ctx, `
			UPDATE inventarios
			SET reservado = reservado + $2, actualizado_en = NOW()
			WHERE producto_id = $1`, item.ProductoID, item.Cantidad); err != nil {
			return Reservation{}, fmt.Errorf("reservar existencias: %w", err)
		}
	}

	result := Reservation{PedidoID: orderID, Items: items, Estado: "reservada"}
	if err := saveIdempotentResult(ctx, tx, idempotencyKey, result); err != nil {
		return Reservation{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return Reservation{}, fmt.Errorf("confirmar reserva: %w", err)
	}

return result, nil
}

type lockedReservation struct {
	Reservation
	requestHash string
}

func getReservationForUpdate(ctx context.Context, tx pgx.Tx, orderID string) (lockedReservation, error) {
	var result lockedReservation
	var serializedItems []byte
	err := tx.QueryRow(ctx, `
		SELECT request_hash, items, estado
		FROM reservas
		WHERE pedido_id = $1
		FOR UPDATE`, orderID).Scan(&result.requestHash, &serializedItems, &result.Estado)
	if errors.Is(err, pgx.ErrNoRows) {
		return lockedReservation{}, ErrNotFound
	}
	if err != nil {
		return lockedReservation{}, fmt.Errorf("consultar reserva: %w", err)
	}
	result.PedidoID = orderID
	if err := json.Unmarshal(serializedItems, &result.Items); err != nil {
		return lockedReservation{}, fmt.Errorf("leer artículos de reserva: %w", err)
	}

	return result, nil
}

func (p *Postgres) ChangeReservationState(ctx context.Context, idempotencyKey, identity, requestHash, orderID, targetState string) (Reservation, error) {
	tx, err := p.pool.BeginTx(ctx, pgx.TxOptions{})
	if err != nil {
		return Reservation{}, fmt.Errorf("iniciar transición de reserva: %w", err)
	}
	defer tx.Rollback(ctx)

	operation := targetState
	if targetState == "confirmada" {
		operation = "confirmar"
	} else {
		operation = "liberar"
	}
	storedResult, replay, err := beginIdempotentOperation(ctx, tx, idempotencyKey, identity, operation, requestHash)
	if err != nil {
		return Reservation{}, err
	}
	if replay {
		var result Reservation
		if err := json.Unmarshal(storedResult, &result); err != nil {
			return Reservation{}, fmt.Errorf("decodificar transición repetida: %w", err)
		}
		if err := tx.Commit(ctx); err != nil {
			return Reservation{}, fmt.Errorf("confirmar transición idempotente: %w", err)
		}
		return result, nil
	}

	reservation, err := getReservationForUpdate(ctx, tx, orderID)
	if err != nil {
		return Reservation{}, err
	}
	if reservation.Estado == targetState {
		if err := saveIdempotentResult(ctx, tx, idempotencyKey, reservation.Reservation); err != nil {
			return Reservation{}, err
		}
		if err := tx.Commit(ctx); err != nil {
			return Reservation{}, fmt.Errorf("confirmar transición repetida: %w", err)
		}
		return reservation.Reservation, nil
	}
	if reservation.Estado != "reservada" {
		return Reservation{}, ErrConflict
	}

	for _, item := range reservation.Items {
		var commandTag pgconn.CommandTag
		if targetState == "confirmada" {
			commandTag, err = tx.Exec(ctx, `
				UPDATE inventarios
				SET stock_fisico = stock_fisico - $2,
				    reservado = reservado - $2,
				    actualizado_en = NOW()
				WHERE producto_id = $1 AND stock_fisico >= $2 AND reservado >= $2`, item.ProductoID, item.Cantidad)
		} else {
			commandTag, err = tx.Exec(ctx, `
				UPDATE inventarios
				SET reservado = reservado - $2, actualizado_en = NOW()
				WHERE producto_id = $1 AND reservado >= $2`, item.ProductoID, item.Cantidad)
		}
		if err != nil {
			return Reservation{}, fmt.Errorf("actualizar existencias de la reserva: %w", err)
		}
		if commandTag.RowsAffected() != 1 {
			return Reservation{}, ErrConflict
		}
	}

	if _, err := tx.Exec(ctx, `UPDATE reservas SET estado = $2, actualizado_en = NOW() WHERE pedido_id = $1`, orderID, targetState); err != nil {
		return Reservation{}, fmt.Errorf("actualizar estado de reserva: %w", err)
	}
	reservation.Estado = targetState
	if err := saveIdempotentResult(ctx, tx, idempotencyKey, reservation.Reservation); err != nil {
		return Reservation{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return Reservation{}, fmt.Errorf("confirmar transición de reserva: %w", err)
	}
	return reservation.Reservation, nil
}
