package tienda.pagos;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertThrows;

class PaymentAccessConfigTest {
    @Test
    void refusesToStartWithSameTokenForBothDirections() {
        assertThrows(IllegalStateException.class,
            () -> new PaymentAccess("mismo-token", "mismo-token", "http://localhost:8006", ""));
    }
}
