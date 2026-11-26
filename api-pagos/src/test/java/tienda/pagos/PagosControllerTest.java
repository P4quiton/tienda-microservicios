package tienda.pagos;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class PagosControllerTest {
    private static final String TOKEN = "solo-pruebas";
    private static final UUID ORDER = UUID.randomUUID();
    private static final UUID KEY = UUID.randomUUID();

    private final PagosRepository repository = mock(PagosRepository.class);
    private MockMvc mvc;

    @BeforeEach
    void setUp() {
        var access = new PaymentAccess(TOKEN, "", "http://localhost:8006", "");
        mvc = MockMvcBuilders.standaloneSetup(new PagosController(repository, access))
            .setControllerAdvice(new ApiErrorHandler()).build();
    }

    @Test
    void healthIsIndependentOfDatabase() throws Exception {
        mvc.perform(get("/health")).andExpect(status().isOk())
            .andExpect(jsonPath("$.service").value("api-pagos"));
        verifyNoInteractions(repository);
    }

    @Test
    void readyReportsDatabaseOutage() throws Exception {
        when(repository.ready()).thenThrow(new DataAccessResourceFailureException("test"));
        mvc.perform(get("/ready")).andExpect(status().isServiceUnavailable())
            .andExpect(jsonPath("$.status").value("unavailable"));
    }

    @Test
    void rejectsUntrustedPaymentRequest() throws Exception {
        mvc.perform(post("/api/pagos/procesar").header("X-Service-Token", "incorrecto")
                .contentType("application/json").content("{}"))
            .andExpect(status().isUnauthorized()).andExpect(jsonPath("$.success").value(false));
        verifyNoInteractions(repository);
    }

    @Test
    void requiresAmountAsString() throws Exception {
        mvc.perform(post("/api/pagos/procesar").header("X-Service-Token", TOKEN)
                .header("Idempotency-Key", KEY).contentType("application/json")
                .content("{\"pedido_id\":\"" + ORDER + "\",\"monto\":12.75,\"metodo_pago\":\"tarjeta_simulada\"}"))
            .andExpect(status().isUnprocessableEntity()).andExpect(jsonPath("$.errors.monto").isArray());
        verifyNoInteractions(repository);
    }

    @Test
    void rejectedPaymentIsPersistedAsSuccessfulApiResult() throws Exception {
        var pago = new Pago(UUID.randomUUID(), ORDER, "12.75", "transferencia_simulada", "rechazado", Instant.now());
        when(repository.process(any(), eq(KEY))).thenReturn(pago);
        when(repository.find(ORDER)).thenReturn(Optional.of(pago));
        mvc.perform(post("/api/pagos/procesar").header("X-Service-Token", TOKEN)
                .header("Idempotency-Key", KEY).contentType("application/json")
                .content("{\"pedido_id\":\"" + ORDER + "\",\"monto\":\"12.75\",\"metodo_pago\":\"transferencia_simulada\"}"))
            .andExpect(status().isCreated()).andExpect(jsonPath("$.data.estado").value("rechazado"));

        mvc.perform(get("/api/pagos/pedido/{id}", ORDER).header("X-Service-Token", TOKEN))
            .andExpect(status().isOk()).andExpect(jsonPath("$.data.id").value(pago.id().toString()));
    }
}
