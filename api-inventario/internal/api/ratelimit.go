package api

import (
	"net/http"
	"strconv"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

// Límite de peticiones por cliente con ventana fija de un minuto.
//
// Alcance: el estado vive en memoria de ESTA instancia. Con varias réplicas el
// límite efectivo por cliente es (límite × réplicas); no es un límite global.
// Una ventana fija permite, en el borde de dos ventanas, hasta el doble de
// peticiones en un lapso corto; se acepta por simplicidad y es conservador
// frente al límite de memoria.
//
// Memoria acotada: los contadores vencidos se purgan al cambiar de ventana y
// cuando se llega al tope de clientes. Si aun así se alcanza el tope, los
// clientes nuevos comparten un único contador de desbordamiento (cierra el
// camino a crecer sin límite a costa de limitar a todos los desconocidos
// mientras dure la saturación).
const (
	rateLimitWindow   = time.Minute
	overflowBucketKey = "\x00desbordamiento"
	capSweepInterval  = time.Second
)

type rateBucket struct {
	count   int
	resetAt time.Time
}

type rateLimiter struct {
	mu         sync.Mutex
	limit      int
	maxClients int
	now        func() time.Time
	buckets    map[string]*rateBucket
	lastSweep  time.Time
}

func newRateLimiter(limit, maxClients int, now func() time.Time) *rateLimiter {
	if now == nil {
		now = time.Now
	}
	return &rateLimiter{
		limit:      limit,
		maxClients: maxClients,
		now:        now,
		buckets:    make(map[string]*rateBucket),
		lastSweep:  now(),
	}
}

// allow registra una petición de key. Si supera el límite devuelve false y el
// tiempo que falta para que se reinicie la ventana.
func (l *rateLimiter) allow(key string) (bool, time.Duration) {
	l.mu.Lock()
	defer l.mu.Unlock()

	now := l.now()
	if now.Sub(l.lastSweep) >= rateLimitWindow {
		l.sweep(now)
	}

	if _, known := l.buckets[key]; !known && len(l.buckets) >= l.maxClients {
		if now.Sub(l.lastSweep) >= capSweepInterval {
			l.sweep(now)
		}
		if len(l.buckets) >= l.maxClients {
			key = overflowBucketKey
		}
	}

	bucket := l.buckets[key]
	if bucket == nil || !now.Before(bucket.resetAt) {
		bucket = &rateBucket{resetAt: now.Add(rateLimitWindow)}
		l.buckets[key] = bucket
	}

	if bucket.count >= l.limit {
		return false, bucket.resetAt.Sub(now)
	}
	bucket.count++
	return true, 0
}

// sweep elimina los contadores vencidos. Se invoca con el cerrojo tomado.
func (l *rateLimiter) sweep(now time.Time) {
	for key, bucket := range l.buckets {
		if !now.Before(bucket.resetAt) {
			delete(l.buckets, key)
		}
	}
	l.lastSweep = now
}

// rateLimitMiddleware limita por c.ClientIP(). Gin solo toma X-Forwarded-For
// cuando la conexión directa procede de un proxy de confianza (TRUSTED_PROXIES);
// en otro caso usa la dirección del socket y el encabezado se ignora.
func rateLimitMiddleware(limiter *rateLimiter) gin.HandlerFunc {
	return func(c *gin.Context) {
		allowed, retryAfter := limiter.allow(c.ClientIP())
		if allowed {
			c.Next()
			return
		}

		seconds := int((retryAfter + time.Second - 1) / time.Second)
		if seconds < 1 {
			seconds = 1
		}
		c.Header("Retry-After", strconv.Itoa(seconds))
		writeError(c, http.StatusTooManyRequests, "Demasiadas solicitudes. Intenta de nuevo más tarde.", nil)
		c.Abort()
	}
}
