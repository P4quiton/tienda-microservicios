package store

import "errors"

var (
	ErrNotFound = errors.New("recurso no encontrado")
	// ErrConflict: conflicto con el estado actual (transición incompatible,
	// pedido ya reservado con otro contenido, desbordamiento de existencias).
	ErrConflict = errors.New("conflicto de inventario")
	// ErrIdempotencyConflict: la Idempotency-Key ya se registró con otra
	// identidad, operación o payload. Es un 409 distinto de ErrConflict.
	ErrIdempotencyConflict = errors.New("conflicto de idempotencia")
	// ErrInsufficientStock: rechazo explícito y definitivo para esa clave
	// (se guarda en operaciones_idempotentes y se repite tal cual).
	ErrInsufficientStock = errors.New("inventario insuficiente")
	ErrInProgress        = errors.New("operación idempotente en curso")
)
