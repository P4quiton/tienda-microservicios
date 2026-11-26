package store

type Item struct {
	ProductoID string `json:"producto_id"`
	Cantidad   int64  `json:"cantidad"`
}

type Reservation struct {
	PedidoID string `json:"pedido_id"`
	Items    []Item `json:"items"`
	Estado   string `json:"estado"`
}

type ReplenishmentResult struct {
	ProductoID  string `json:"producto_id"`
	Disponibles int64  `json:"disponibles"`
}
