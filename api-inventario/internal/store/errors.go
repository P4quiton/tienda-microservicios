package store

import "errors"

var (
	ErrNotFound   = errors.New("recurso no encontrado")
	ErrConflict   = errors.New("conflicto de inventario")
    ErrInsufficientStock = errors.New("inventario insuficiente")
	ErrInProgress = errors.New("operación idempotente en curso")
)
