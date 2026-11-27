package tienda.pagos;

import java.util.List;
import java.util.Map;

import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

final class ApiError extends RuntimeException {
    final int status;
    final Map<String, List<String>> errors;

    ApiError(int status, String message) {
        this(status, message, Map.of());
    }

    ApiError(int status, String message, Map<String, List<String>> errors) {
        super(message);
        this.status = status;
        this.errors = errors;
    }
}

@RestControllerAdvice
class ApiErrorHandler {
    private static final org.slf4j.Logger LOG = org.slf4j.LoggerFactory.getLogger(ApiErrorHandler.class);
    record ErrorResponse(boolean success, String message, Map<String, List<String>> errors) {}

    @ExceptionHandler(ApiError.class)
    ResponseEntity<ErrorResponse> apiError(ApiError error) {
        return ResponseEntity.status(error.status).body(new ErrorResponse(false, error.getMessage(), error.errors));
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    ResponseEntity<ErrorResponse> invalidBody(HttpMessageNotReadableException error) {
        return apiError(new ApiError(400, "JSON incorrecto"));
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<ErrorResponse> other(Exception error) {
        // Excepciones de Spring MVC (404 de ruta, 405, 415...) conservan su estado, pero con el sobre del contrato.
        if (error instanceof org.springframework.web.ErrorResponse mvc) {
            int status = mvc.getStatusCode().value();
            String message = status == 404 ? "No encontrado" : status == 405 ? "Metodo no permitido" : "Solicitud incorrecta";
            return ResponseEntity.status(status).headers(mvc.getHeaders()).body(new ErrorResponse(false, message, Map.of()));
        }
        LOG.error("Error interno no controlado", error);
        return apiError(new ApiError(500, "Error interno"));
    }

    @ExceptionHandler({DataAccessException.class, org.springframework.transaction.TransactionException.class})
    ResponseEntity<ErrorResponse> unavailable(Exception error) {
        return apiError(new ApiError(503, "Persistencia no disponible"));
    }
}
