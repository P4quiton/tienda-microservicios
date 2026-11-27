import { HttpErrorResponse } from '@angular/common/http';
import { ApiFailure, ApiProblem } from '../models/api.models';

export function toApiProblem(error: unknown): ApiProblem {
  if (error && typeof error === 'object' && 'status' in error && 'message' in error) {
    const candidate = error as Partial<ApiProblem>;
    if (typeof candidate.status === 'number' && typeof candidate.message === 'string') {
      return {
        status: candidate.status,
        message: candidate.message,
        errors: candidate.errors ?? {},
        retryAfterSeconds: candidate.retryAfterSeconds,
        uncertainOutcome: candidate.uncertainOutcome ?? candidate.status === 503,
      };
    }
  }

  if (!(error instanceof HttpErrorResponse)) {
    return {
      status: 0,
      message: error instanceof Error ? error.message : 'No se pudo completar la solicitud.',
      errors: {},
      uncertainOutcome: false,
    };
  }

  const body = error.error as Partial<ApiFailure> | null;
  const retryAfter = error.headers.get('Retry-After');
  const status = error.status;
  const uncertainOutcome = status === 503;
  const knownMessages: Record<number, string> = {
    401: 'Inicia sesión para continuar.',
    403: 'No tienes permiso para realizar esta acción.',
    404: 'No se encontró la información solicitada.',
    409: 'La operación entra en conflicto con el estado actual. Revisa y vuelve a intentar.',
    413: 'La solicitud es demasiado grande.',
    422: 'Revisa los datos ingresados.',
    429: 'Se alcanzó el límite de solicitudes. Intenta de nuevo más tarde.',
    503: 'El resultado de la compra todavía no está confirmado. Reintenta usando la misma clave de idempotencia.',
  };

  return {
    status,
    message: body?.message ?? knownMessages[status] ?? 'Ocurrió un error al comunicarse con la tienda.',
    errors: body?.errors ?? {},
    retryAfterSeconds: retryAfter ? Number(retryAfter) || undefined : undefined,
    uncertainOutcome,
  };
}
