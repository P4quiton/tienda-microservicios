package tienda.pagos;

import java.time.Clock;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Contador de ventana fija de 60 s por (categoria, clave), en memoria de ESTE proceso: con varias replicas
 * cada instancia lleva su propio contador (el limite efectivo es por instancia).
 */
final class RateLimiter {
    private static final long WINDOW_MS = 60_000;
    private static final int PURGE_THRESHOLD = 10_000;

    /** Resultado: permitido o, si no, segundos hasta que se reinicie la ventana. */
    record Decision(boolean allowed, long retryAfterSeconds) {}

    private static final class Window {
        long start;
        int count;
    }

    private final Clock clock;
    private final ConcurrentHashMap<String, Window> windows = new ConcurrentHashMap<>();

    RateLimiter(Clock clock) {
        this.clock = clock;
    }

    Decision tryAcquire(String bucket, String key, int limit) {
        long now = clock.millis();
        if (windows.size() > PURGE_THRESHOLD) {
            windows.entrySet().removeIf(entry -> now - entry.getValue().start >= WINDOW_MS);
        }
        var window = windows.computeIfAbsent(bucket + '|' + key, k -> new Window());
        synchronized (window) {
            if (now - window.start >= WINDOW_MS) {
                window.start = now;
                window.count = 0;
            }
            if (window.count < limit) {
                window.count++;
                return new Decision(true, 0);
            }
            long remainingMs = WINDOW_MS - (now - window.start);
            return new Decision(false, Math.max(1, (remainingMs + 999) / 1000));
        }
    }

    int trackedKeys() {
        return windows.size();
    }
}
