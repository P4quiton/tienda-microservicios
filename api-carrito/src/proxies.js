// Frontera de confianza para X-Forwarded-For.
// Origen: TRUSTED_PROXIES (lista separada por comas de IP o CIDR) -> parseTrustedProxies -> createApp ('trust proxy').
// Por defecto (vacío o ausente) no se confía en ningún proxy: req.ip es la dirección del socket.
// Se rechazan a propósito '*', 'true', saltos numéricos y alias ('loopback'...): confiar "en todo" permite
// falsificar la IP con una cabecera y evadir el limitador.
// Alcance: igual que Productos e Inventario (TRUSTED_PROXIES). Retirada: borrar este módulo y su uso en app.js.
import { isIP } from 'node:net';

function validEntry(entry) {
  const [address, prefix, ...rest] = entry.split('/');
  const version = isIP(address);
  if (!version || rest.length) return false;
  if (prefix === undefined) return true;
  return /^\d{1,3}$/.test(prefix) && Number(prefix) > 0 && Number(prefix) <= (version === 4 ? 32 : 128);
}

export function parseTrustedProxies(raw) {
  const entries = (raw ?? '').split(',').map((entry) => entry.trim()).filter(Boolean);
  const invalid = entries.find((entry) => !validEntry(entry));
  if (invalid !== undefined) {
    const detail = invalid.endsWith('/0')
      ? 'no puede incluir rangos /0'
      : 'contiene un valor inválido';
    throw new Error(`TRUSTED_PROXIES ${detail}`);
  }
  return entries;
}
