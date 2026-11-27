import { createHash, timingSafeEqual } from 'node:crypto';
import { jwtVerify } from 'jose';
import { ApiError } from './errors.js';

export const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function digest(text) {
  return createHash('sha256').update(text).digest();
}

export function authentication({ publicKey, serviceToken }) {
  const expected = serviceToken ? digest(serviceToken) : null;

  function service(req) {
    const provided = req.get('X-Service-Token');
    if (!expected || !provided || !timingSafeEqual(expected, digest(provided))) {
      throw new ApiError(401, 'Credencial interna inválida');
    }
  }

  async function owner(req, userId) {
    const authorization = req.get('Authorization');
    const match = authorization?.match(/^Bearer ([^\s]+)$/i);
    if (!match) throw new ApiError(401, 'Credencial inválida');

    let claims;
    try {
      ({ payload: claims } = await jwtVerify(match[1], publicKey, {
        algorithms: ['RS256'],
        issuer: 'api-usuarios',
        audience: 'tienda-microservicios',
        requiredClaims: ['sub', 'role', 'iat', 'exp'],
        maxTokenAge: '60m',
      }));
    } catch {
      throw new ApiError(401, 'Credencial inválida');
    }
    if (typeof claims.sub !== 'string' || !uuidV4.test(claims.sub) ||
        !['cliente', 'admin'].includes(claims.role) || claims.exp - claims.iat > 3600) {
      throw new ApiError(401, 'Credencial inválida');
    }
    const actorId = claims.sub.toLowerCase();
    if (claims.role !== 'admin' && actorId !== userId) {
      throw new ApiError(403, 'Permiso insuficiente');
    }
    return actorId;
  }

  return { service, owner };
}
