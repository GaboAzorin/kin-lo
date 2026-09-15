/**
 * relay/worker.js
 * Relay HTTP mínimo para alcanzar polla.cl desde una IP que no sea de Azure.
 *
 * polla.cl bloquea las IPs de GitHub Actions, así que el workflow no puede pegarle
 * directo. Este worker corre en un free tier serverless (IP de Cloudflare / GCP /
 * AWS según la plataforma), recibe la petición desde Actions, la reenvía a polla.cl
 * y devuelve la respuesta envuelta en JSON.
 *
 * El mismo archivo corre sin cambios en las tres plataformas: detecta el runtime al
 * final y se engancha como corresponde.
 *
 *   Cloudflare Workers  wrangler deploy      (secret: RELAY_TOKEN)
 *   Deno Deploy         deployctl deploy     (env: RELAY_TOKEN)
 *   Val.town            pegar el archivo     (env: RELAY_TOKEN)
 *
 * Protocolo:
 *   POST /  con header  X-Relay-Token: <secreto>
 *   body:   {"url": "...", "method": "GET|POST", "headers": {...}, "body": "..."}
 *   →       {"status": 200, "headers": {...}, "body": "...", "url_final": "..."}
 *
 * El status de la respuesta del relay es el del relay, no el de polla.cl. Lo que
 * polla.cl respondió va en el campo `status` del JSON — distinguirlos importa para
 * saber si falló el relay o si falló el destino.
 */

// Solo se proxea a estos hosts. El token es la autenticación; esto es la red de
// seguridad si el token se filtra: evita que el relay quede de proxy abierto para
// cualquier destino, que es lo que hace que estas cosas terminen en listas negras.
const HOSTS_PERMITIDOS = ["www.polla.cl", "polla.cl", "api.polla.cl"];

// Cuerpos más grandes que esto se truncan. Una respuesta de la API de sorteos son
// unos pocos KB; algo mucho mayor significa que llegó una página de error o un
// challenge, y no vale la pena moverlo entero.
const MAX_BODY = 512 * 1024;

const TIMEOUT_MS = 25000;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

/**
 * Compara dos strings en tiempo constante.
 *
 * Una comparación normal con === corta en el primer byte distinto, lo que filtra
 * el prefijo correcto del token a quien mida los tiempos. Aquí el volumen es
 * ridículo y el riesgo teórico, pero cuesta cinco líneas.
 */
function tokenValido(recibido, esperado) {
  if (!recibido || !esperado || recibido.length !== esperado.length) return false;
  let diff = 0;
  for (let i = 0; i < recibido.length; i++) {
    diff |= recibido.charCodeAt(i) ^ esperado.charCodeAt(i);
  }
  return diff === 0;
}

async function manejar(request, tokenEsperado) {
  if (request.method === "GET") {
    // Sonda de salud: confirma que el worker está vivo sin exponer nada ni
    // requerir token. Útil para verificar el deploy antes de configurar secrets.
    return json({ ok: true, servicio: "relay-polla", hosts: HOSTS_PERMITIDOS });
  }

  if (request.method !== "POST") {
    return json({ error: "Solo GET (salud) y POST (relay)" }, 405);
  }

  if (!tokenEsperado) {
    return json({ error: "RELAY_TOKEN no está configurado en el worker" }, 500);
  }

  if (!tokenValido(request.headers.get("X-Relay-Token"), tokenEsperado)) {
    return json({ error: "Token inválido" }, 401);
  }

  let peticion;
  try {
    peticion = await request.json();
  } catch {
    return json({ error: "Body no es JSON válido" }, 400);
  }

  if (!peticion.url) {
    return json({ error: "Falta 'url'" }, 400);
  }

  let destino;
  try {
    destino = new URL(peticion.url);
  } catch {
    return json({ error: `URL inválida: ${peticion.url}` }, 400);
  }

  if (!HOSTS_PERMITIDOS.includes(destino.hostname)) {
    return json({ error: `Host no permitido: ${destino.hostname}` }, 403);
  }

  // Sin esto una petición colgada consume el tiempo de ejecución del free tier
  // hasta que la plataforma mate el worker, y Actions se queda esperando.
  const abort = new AbortController();
  const temporizador = setTimeout(() => abort.abort(), TIMEOUT_MS);

  try {
    const upstream = await fetch(destino.toString(), {
      method: peticion.method || "GET",
      headers: peticion.headers || {},
      body: peticion.body || undefined,
      redirect: "follow",
      signal: abort.signal,
    });

    const texto = await upstream.text();
    const cabeceras = {};
    upstream.headers.forEach((v, k) => { cabeceras[k] = v; });

    return json({
      status: upstream.status,
      headers: cabeceras,
      body: texto.slice(0, MAX_BODY),
      truncado: texto.length > MAX_BODY,
      body_len: texto.length,
      url_final: upstream.url,
    });
  } catch (e) {
    const abortado = e.name === "AbortError";
    return json({
      error: abortado ? `Timeout tras ${TIMEOUT_MS} ms` : `${e.name}: ${e.message}`,
      status: null,
    }, abortado ? 504 : 502);
  } finally {
    clearTimeout(temporizador);
  }
}

// --- Enganche por plataforma -------------------------------------------------
// Cada runtime expone el arranque y las variables de entorno a su manera. Las tres
// ramas llaman al mismo `manejar`, así que el comportamiento no diverge entre
// plataformas y la comparación del diagnóstico es justa.

// Val.town y Deno Deploy leen el secreto del entorno del proceso.
const tokenDeno = typeof Deno !== "undefined" ? Deno.env.get("RELAY_TOKEN") : null;

// Cloudflare Workers lo inyecta por parámetro en cada fetch, no por entorno.
export default {
  async fetch(request, env) {
    return manejar(request, (env && env.RELAY_TOKEN) || tokenDeno);
  },
};

// Deno Deploy arranca con Deno.serve; Val.town usa el export default de arriba.
// `Deno.serve` existe en ambos, pero en Val.town llamarlo rompe el despliegue, así
// que solo se invoca cuando no estamos dentro de Val.town.
if (typeof Deno !== "undefined" && !Deno.env.get("VALTOWN")) {
  Deno.serve((request) => manejar(request, tokenDeno));
}
