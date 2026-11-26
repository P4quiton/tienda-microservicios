package tienda.pagos;

import java.io.IOException;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.json.JsonMapper;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.InvalidMediaTypeException;
import org.springframework.http.MediaType;

/**
 * Lectura estricta del cuerpo JSON, ejecutada DESPUES de autenticar al llamador.
 * Origen: HttpServletRequest -> bytes acotados -> JsonNode -> PagoRequest.parse (validacion de campos).
 * Reglas: solo application/json, maximo {@value #MAX_BYTES} bytes (sin confiar en Content-Length),
 * sin claves duplicadas ni texto tras el documento. Todo fallo es 400 "JSON incorrecto".
 */
final class CuerpoJson {
    static final int MAX_BYTES = 4096;
    private static final JsonMapper MAPPER = JsonMapper.builder()
        .enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
        .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
        .build();

    private CuerpoJson() {}

    static JsonNode read(HttpServletRequest request) {
        requireJson(request.getContentType());
        try {
            byte[] bytes = request.getInputStream().readNBytes(MAX_BYTES + 1);
            if (bytes.length > MAX_BYTES) {
                throw new ApiError(400, "JSON incorrecto");
            }
            JsonNode node = MAPPER.readTree(bytes);
            if (node == null || node.isMissingNode()) {
                throw new ApiError(400, "JSON incorrecto");
            }
            return node;
        } catch (JsonProcessingException | IllegalArgumentException exception) {
            throw new ApiError(400, "JSON incorrecto");
        } catch (IOException exception) {
            throw new ApiError(400, "JSON incorrecto");
        }
    }

    private static void requireJson(String contentType) {
        try {
            if (contentType == null || !MediaType.APPLICATION_JSON.equalsTypeAndSubtype(MediaType.parseMediaType(contentType))) {
                throw new ApiError(400, "JSON incorrecto");
            }
        } catch (InvalidMediaTypeException exception) {
            throw new ApiError(400, "JSON incorrecto");
        }
    }
}
