package store

import "errors"

var (
	ErrNotFound   = errors.New("recurso no encontrado")
	ErrConflict   = errors.New("conflicto de inventario")
	ErrInProgress = errors.New("operación idempotente en curso")
)
