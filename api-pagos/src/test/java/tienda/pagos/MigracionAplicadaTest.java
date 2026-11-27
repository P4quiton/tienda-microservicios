package tienda.pagos;

import org.flywaydb.core.api.MigrationInfo;
import org.flywaydb.core.api.MigrationInfoService;
import org.flywaydb.core.api.MigrationState;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class MigracionAplicadaTest {

    private static MigrationInfo migracion(MigrationState estado) {
        var migracion = mock(MigrationInfo.class);
        when(migracion.getState()).thenReturn(estado);
        return migracion;
    }

    @Test
    void esListoConMigracionesAplicadasSinPendientesNiFallos() {
        var aplicada = migracion(MigrationState.SUCCESS);
        var info = mock(MigrationInfoService.class);
        when(info.current()).thenReturn(aplicada);
        when(info.pending()).thenReturn(new MigrationInfo[0]);
        when(info.all()).thenReturn(new MigrationInfo[] {aplicada});

        assertTrue(PagosRepository.migracionesAplicadas(info));
    }

    @Test
    void noEsListoConMigracionPendiente() {
        var aplicada = migracion(MigrationState.SUCCESS);
        var pendiente = migracion(MigrationState.PENDING);
        var info = mock(MigrationInfoService.class);
        when(info.current()).thenReturn(aplicada);
        when(info.pending()).thenReturn(new MigrationInfo[] {pendiente});
        when(info.all()).thenReturn(new MigrationInfo[] {aplicada, pendiente});

        assertFalse(PagosRepository.migracionesAplicadas(info));
    }

    @Test
    void noEsListoSinNingunaMigracionAplicada() {
        var pendiente = migracion(MigrationState.PENDING);
        var info = mock(MigrationInfoService.class);
        when(info.current()).thenReturn(null);
        when(info.pending()).thenReturn(new MigrationInfo[] {pendiente});
        when(info.all()).thenReturn(new MigrationInfo[] {pendiente});

        assertFalse(PagosRepository.migracionesAplicadas(info));
    }

    @Test
    void noEsListoConMigracionFallida() {
        var fallida = migracion(MigrationState.FAILED);
        var info = mock(MigrationInfoService.class);
        when(info.current()).thenReturn(fallida);
        when(info.pending()).thenReturn(new MigrationInfo[0]);
        when(info.all()).thenReturn(new MigrationInfo[] {fallida});

        assertFalse(PagosRepository.migracionesAplicadas(info));
    }
}
