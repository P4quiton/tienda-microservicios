package tienda.pagos;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Clock;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Rate limiting configurable. Primero identifica al llamador (sin rechazar: la credencial invalida la sigue
 * rechazando el controlador con 401) y despues aplica el cupo de su categoria:
 * servicio de Pedidos (X-Service-Token valido) => "interna", clave fija de servicio;
 * JWT valido => "consulta" (GET/HEAD/OPTIONS) o "mutacion" (resto), clave = sub;
 * sin credencial valida => mismas categorias por metodo, clave = IP remota (no se confia en X-Forwarded-For).
 * "checkout" se lee por consistencia de configuracion, pero Pagos no tiene operaciones de checkout.
 * /health y /ready estan exentos. Exceso => 429 con Retry-After y el sobre de error del contrato.
 */
@Component
class RateLimitFilter extends OncePerRequestFilter {
    private final PaymentAccess access;
    private final RateLimiter limiter = new RateLimiter(Clock.systemUTC());
    private final int consulta;
    private final int mutacion;
    private final int interna;

    RateLimitFilter(
        PaymentAccess access,
        @Value("${pagos.rate-limit.consulta-por-min}") int consulta,
        @Value("${pagos.rate-limit.mutacion-por-min}") int mutacion,
        @Value("${pagos.rate-limit.checkout-por-min}") int checkout,
        @Value("${pagos.rate-limit.interna-por-min}") int interna
    ) {
        for (int value : new int[] {consulta, mutacion, checkout, interna}) {
            if (value < 1) {
                throw new IllegalStateException("Los limites RATE_LIMIT_*_POR_MIN deben ser enteros >= 1");
            }
        }
        this.access = access;
        this.consulta = consulta;
        this.mutacion = mutacion;
        this.interna = interna;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return "/health".equals(path) || "/ready".equals(path);
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
        throws ServletException, IOException {
        boolean read = switch (request.getMethod()) { case "GET", "HEAD", "OPTIONS" -> true; default -> false; };
        String bucket = read ? "consulta" : "mutacion";
        int limit = read ? consulta : mutacion;
        String key;
        String serviceToken = request.getHeader("X-Service-Token");
        String authorization = request.getHeader("Authorization");
        if (access.isPedidos(serviceToken)) {
            bucket = "interna";
            limit = interna;
            key = "servicio:pedidos";
        } else {
            key = "ip:" + request.getRemoteAddr();
            if (serviceToken == null && authorization != null) {
                try {
                    key = "sub:" + access.authenticate(authorization).id();
                } catch (ApiError invalid) {
                    // Credencial invalida: se limita por IP y el controlador responde 401.
                }
            }
        }
        var decision = limiter.tryAcquire(bucket, key, limit);
        if (decision.allowed()) {
            chain.doFilter(request, response);
            return;
        }
        response.setStatus(429);
        response.setHeader("Retry-After", Long.toString(decision.retryAfterSeconds()));
        response.setContentType("application/json");
        response.setCharacterEncoding("UTF-8");
        response.getOutputStream().write(
            "{\"success\":false,\"message\":\"Límite de peticiones excedido\",\"errors\":{}}".getBytes(StandardCharsets.UTF_8));
    }
}
