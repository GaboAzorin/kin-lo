// gh-api.js — helpers compartidos para leer/escribir data/jugadas.json vía la GitHub API.
// Cargado por las 4 páginas con <script src> antes de su script inline.
const GH_OWNER = 'GaboAzorin', GH_REPO = 'kin-lo', GH_FILE = 'data/jugadas.json';

// Fecha local de hoy en ISO. No usar toISOString(): es UTC y en Chile
// desplaza el día después de las ~20:00.
function hoyISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

// ── Fechas y sorteos (helpers compartidos por todas las páginas) ─────────────
const _DAYS_ES   = ['domingo','lunes','martes','miércoles','jueves','viernes','sábado'];
const _MONTHS_ES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
// Días de sorteo (0=domingo). Loto: dom/mar/jue. Kino: dom/mié/vie.
const DRAW_DAYS  = { loto: [0,2,4], kino: [0,3,5] };

// Hoy en zona horaria de Chile como yyyy-mm-dd (en-CA da ese formato).
function hoyISO_CL() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Santiago', year:'numeric', month:'2-digit', day:'2-digit'
  }).format(new Date());
}
// yyyy-mm-dd → epoch UTC-medianoche, para aritmética por calendario (sin DST).
function _isoToUTC(iso) {
  const [y,m,d] = iso.slice(0,10).split('-').map(Number);
  return Date.UTC(y, m-1, d);
}
function _utcToISO(ms) {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,'0')}-${String(d.getUTCDate()).padStart(2,'0')}`;
}
// Diferencia en días de calendario (b - a), ambos yyyy-mm-dd.
function diasEntre(aISO, bISO) {
  return Math.round((_isoToUTC(bISO) - _isoToUTC(aISO)) / 86400000);
}
// "miércoles 17 de junio"
function fmtFechaLarga(iso) {
  const d = new Date(_isoToUTC(iso));
  return `${_DAYS_ES[d.getUTCDay()]} ${d.getUTCDate()} de ${_MONTHS_ES[d.getUTCMonth()]}`;
}
// "lanzado ayer domingo 14 de junio" (relativo solo hoy/ayer/anteayer).
function fmtLanzado(iso) {
  if (!iso) return '';
  const dias  = diasEntre(iso.slice(0,10), hoyISO_CL());
  const larga = fmtFechaLarga(iso);
  if (dias === 0) return `lanzado hoy ${larga}`;
  if (dias === 1) return `lanzado ayer ${larga}`;
  if (dias === 2) return `lanzado anteayer ${larga}`;
  return `lanzado el ${larga}`;
}
// Primer día de sorteo estrictamente posterior a la fecha dada (yyyy-mm-dd|null).
function proximoSorteoFecha(ultimaISO, juego) {
  const days = DRAW_DAYS[juego] || [];
  const base = _isoToUTC(ultimaISO.slice(0,10));
  for (let i = 1; i <= 14; i++) {
    const probe = base + i * 86400000;
    if (days.includes(new Date(probe).getUTCDay())) return _utcToISO(probe);
  }
  return null;
}
// "Sugerencias para el sorteo del próximo miércoles 17 de junio, #N (en 2 días más)"
function fmtSorteoProximo(sorteoNum, ultimaISO, juego) {
  const prox = ultimaISO ? proximoSorteoFecha(ultimaISO, juego) : null;
  if (!prox) return `Sugerencias para el sorteo #${sorteoNum}`;
  const dias = diasEntre(hoyISO_CL(), prox);
  let cuando = '';
  if (dias === 1)      cuando = ' (mañana)';
  else if (dias === 2) cuando = ' (en 2 días más)';
  else if (dias > 2)   cuando = ` (en ${dias} días más)`;
  else if (dias === 0) cuando = ' (hoy)';
  return `Sugerencias para el sorteo del próximo ${fmtFechaLarga(prox)}, #${sorteoNum}${cuando}`;
}
// Sorteos pasados ya publicados que faltan por scrapear (días de sorteo entre
// la última fecha (excl.) y hoy (excl.); el sorteo de hoy no se cuenta aún).
function sorteosFaltantes(ultimaISO, juego) {
  if (!ultimaISO) return 0;
  const days  = DRAW_DAYS[juego] || [];
  const hoyMs = _isoToUTC(hoyISO_CL());
  let ms = _isoToUTC(ultimaISO.slice(0,10)) + 86400000, count = 0, guard = 0;
  while (ms < hoyMs && guard++ < 500) {
    if (days.includes(new Date(ms).getUTCDay())) count++;
    ms += 86400000;
  }
  return count;
}
// Mensaje de alerta (singular/plural) o '' si no falta nada.
function msgFaltantes(ultimaISO, juego, juegoLabel) {
  const n = sorteosFaltantes(ultimaISO, juego);
  if (n < 1) return '';
  return n === 1
    ? `⚠ Falta 1 sorteo de ${juegoLabel} por scrapear`
    : `⚠ Faltan ${n} sorteos de ${juegoLabel} por scrapear`;
}
// HTML del banner de alerta (vacío si no falta nada).
function bannerFaltantes(ultimaISO, juego, juegoLabel) {
  const msg = msgFaltantes(ultimaISO, juego, juegoLabel);
  if (!msg) return '';
  return `<div style="margin-top:8px;padding:8px 12px;background:rgba(245,158,11,0.12);`
       + `border:1px solid rgba(245,158,11,0.35);border-radius:8px;color:#fbbf24;`
       + `font-size:0.82rem;font-weight:600">${msg}</div>`;
}

// Token (PAT fine-grained, solo contents:write de este repo) guardado en
// localStorage. Configurar visitando: #setup=BASE64_DEL_TOKEN
function getToken() {
  const hash = location.hash;
  if (hash.startsWith('#setup=')) {
    localStorage.setItem('kl_gh_token', hash.slice(7).trim());
    history.replaceState(null, '', location.pathname + location.search);
  }
  const stored = localStorage.getItem('kl_gh_token');
  if (!stored) return '';
  try {
    const b64 = stored.trim().replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64 + '==='.slice(0, (4 - b64.length % 4) % 4);
    return atob(padded);
  } catch { return ''; }
}

// Lee jugadas.json. Funciona anónimo (sin token) o autenticado.
async function ghGetFile() {
  const token = getToken();
  const headers = { Accept: 'application/vnd.github+json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(
    `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/${GH_FILE}`,
    { headers, cache: 'no-store' }
  );
  if (r.status === 404) return { content: [], sha: null };
  if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.message || `GitHub ${r.status}`); }
  const d = await r.json();
  return { content: JSON.parse(atob(d.content.replace(/\n/g, ''))), sha: d.sha };
}

// Dispara un evento repository_dispatch (requiere token con contents:write).
// Lo usa /ingresar/ para gatillar la Action que agrega un sorteo en vivo.
async function ghDispatch(eventType, payload) {
  const token = getToken();
  if (!token) throw new Error('Token no configurado');
  const r = await fetch(
    `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/dispatches`,
    { method: 'POST',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
      body: JSON.stringify({ event_type: eventType, client_payload: payload }) }
  );
  if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.message || `GitHub ${r.status}`); }
}

// Escribe jugadas.json (requiere token).
async function ghPutFile(content, sha, msg) {
  const token = getToken();
  if (!token) throw new Error('Token no configurado');
  const body = { message: msg, content: btoa(unescape(encodeURIComponent(JSON.stringify(content, null, 2)))) };
  if (sha) body.sha = sha;
  const r = await fetch(
    `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/${GH_FILE}`,
    { method: 'PUT',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body) }
  );
  if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.message || `GitHub ${r.status}`); }
}
