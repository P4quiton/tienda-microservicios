package tienda.pagos;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class RateLimiterTest {
    private static final class MutableClock extends Clock {
        long millis = 1_000_000;
        @Override public ZoneOffset getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(java.time.ZoneId zone) { return this; }
        @Override public Instant instant() { return Instant.ofEpochMilli(millis); }
        @Override public long millis() { return millis; }
    }

    @Test
    void blocksAfterLimitReportsRetryAfterAndResetsWithNextWindow() {
        var clock = new MutableClock();
        var limiter = new RateLimiter(clock);
        assertTrue(limiter.tryAcquire("consulta", "a", 2).allowed());
        assertTrue(limiter.tryAcquire("consulta", "a", 2).allowed());
        clock.millis += 20_500;
        var blocked = limiter.tryAcquire("consulta", "a", 2);
        assertFalse(blocked.allowed());
        assertEquals(40, blocked.retryAfterSeconds());
        assertTrue(limiter.tryAcquire("consulta", "b", 2).allowed(), "otra clave");
        assertTrue(limiter.tryAcquire("mutacion", "a", 2).allowed(), "otra categoria");
        clock.millis += Duration.ofSeconds(40).toMillis() - 500;
        assertTrue(limiter.tryAcquire("consulta", "a", 2).allowed(), "ventana nueva");
    }
}
