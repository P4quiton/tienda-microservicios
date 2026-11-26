package tienda.pagos;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.flyway.FlywayMigrationStrategy;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Si la BD no esta disponible al arrancar, el proceso debe seguir vivo (/health 200, /ready 503)
 * y migrar en cuanto la BD responda. Flyway toma un bloqueo en la BD, asi que varias replicas
 * reintentando a la vez son seguras; una migracion ya aplicada es un no-op.
 */
@Configuration
class MigracionResiliente {
    private static final Logger LOG = LoggerFactory.getLogger(MigracionResiliente.class);
    static final long REINTENTO_MS = 3000;

    @Bean
    FlywayMigrationStrategy migrationStrategy() {
        return flyway -> {
            try {
                flyway.migrate();
            } catch (RuntimeException exception) {
                LOG.warn("Migracion diferida: la base de datos no esta disponible ({})", exception.getClass().getSimpleName());
                var retry = new Thread(() -> {
                    while (true) {
                        try {
                            Thread.sleep(REINTENTO_MS);
                            flyway.migrate();
                            LOG.info("Migracion aplicada tras reintento");
                            return;
                        } catch (InterruptedException interrupted) {
                            Thread.currentThread().interrupt();
                            return;
                        } catch (RuntimeException again) {
                            LOG.warn("Migracion pendiente ({})", again.getClass().getSimpleName());
                        }
                    }
                }, "migracion-reintento");
                retry.setDaemon(true);
                retry.start();
            }
        };
    }
}
