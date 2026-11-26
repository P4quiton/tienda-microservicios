// Importar PRIMERO en cada suite: fija límites altos por env para que ninguna prueba ajena
// a los límites choque con ellos (createApp lee process.env al construirse).
for (const name of ['CONSULTA', 'MUTACION', 'INTERNA']) {
  process.env[`RATE_LIMIT_${name}_POR_MIN`] = '1000000';
}
