// gh-api.js — helpers compartidos para leer/escribir data/jugadas.json vía la GitHub API.
// Cargado por las 4 páginas con <script src> antes de su script inline.
const GH_OWNER = 'GaboAzorin', GH_REPO = 'kin-lo', GH_FILE = 'data/jugadas.json';

// Fecha local de hoy en ISO. No usar toISOString(): es UTC y en Chile
// desplaza el día después de las ~20:00.
function hoyISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
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
