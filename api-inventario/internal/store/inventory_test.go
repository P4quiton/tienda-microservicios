package store

import (
	"reflect"
	"testing"
)

func TestNormalizeItemsAggregatesAndSortsProducts(t *testing.T) {
	items := []Item{
		{ProductoID: "b", Cantidad: 2},
		{ProductoID: "a", Cantidad: 1},
		{ProductoID: "b", Cantidad: 3},
	}

	got := NormalizeItems(items)
	want := []Item{
		{ProductoID: "a", Cantidad: 1},
		{ProductoID: "b", Cantidad: 5},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("NormalizeItems() = %#v, want %#v", got, want)
	}
}

func TestHashIsStableForEqualValues(t *testing.T) {
	first, err := Hash([]Item{{ProductoID: "a", Cantidad: 2}})
	if err != nil {
		t.Fatalf("Hash() error = %v", err)
	}
	second, err := Hash([]Item{{ProductoID: "a", Cantidad: 2}})
	if err != nil {
		t.Fatalf("Hash() error = %v", err)
	}
	if first != second {
		t.Fatalf("equal requests produced different hashes: %q != %q", first, second)
	}
}
