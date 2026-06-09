# Proteger sitio GitHub Pages con StatiCrypt

## Goal

Agregar protección por contraseña al sitio estático en GitHub Pages usando StatiCrypt,
de modo que el contenido no sea visible para visitantes casuales. El repo permanece público;
la protección es de la UI del sitio, no de los datos crudos.

## Requirements

* Los 5 HTML del sitio (`index`, `kino`, `loto`, `sugerencias`, `jugadas`) requieren contraseña
* Los HTML fuente (sin encriptar) se mueven de `docs/` a `docs_src/`
* GitHub Actions encripta `docs_src/*.html` → `docs/*.html` en cada run
* El script local `actualizar_loto.ps1` también encripta antes del push
* La contraseña vive como GitHub Secret `STATICRYPT_PASSWORD`
* StatiCrypt se instala vía `npx staticrypt` (sin agregar a package.json como dependencia global)

## Acceptance Criteria

* [ ] Visitar cualquier página del sitio muestra prompt de contraseña StatiCrypt
* [ ] Con contraseña correcta el sitio funciona igual que antes
* [ ] Sin contraseña el HTML en `docs/` es ilegible
* [ ] `scrape-kino.yml` encripta los HTML después del scrape y antes del commit
* [ ] `actualizar_loto.ps1` encripta los HTML antes del commit
* [ ] Los JSONs en `docs/data/` no cambian de ubicación ni comportamiento

## Definition of Done

* CI verde en el próximo run de `scrape-kino.yml`
* Script local probado localmente (sin necesidad de sorteo real)
* Password configurado como GitHub Secret por el usuario

## Technical Approach

**Arquitectura:**
- `docs_src/` — HTML fuente sin encriptar (nuevo directorio, commiteado)
- `docs/` — HTML encriptado por StatiCrypt + JSONs de datos (igual que hoy)
- GH Actions: paso `Encrypt HTML with StatiCrypt` tras métricas, antes del auto-commit
- Script local: función `Invoke-StaticryptEncrypt` añadida antes del `git add`

**Decisión (ADR-lite):**
- Contexto: GitHub Pages solo funciona en repos públicos con plan gratuito
- Decisión: StatiCrypt en HTML + repo público (protección casual, no criptográfica fuerte)
- Consecuencias: JSONs en `docs/data/` siguen accesibles por URL directa; el fuente HTML
  es visible en el repo. Acceptable para el caso de uso.

**Pasos de implementación:**
1. Crear `docs_src/` y mover los 5 HTML actuales de `docs/` a `docs_src/`
2. Actualizar `scrape-kino.yml`: agregar paso StatiCrypt + actualizar `file_pattern` del commit
3. Actualizar `actualizar_loto.ps1`: agregar encriptación antes del `git add`
4. Agregar `docs/index.html`, `docs/kino/index.html`, etc. al `.gitignore` para que solo se
   commiteen los encriptados generados en CI (o manejar de otra forma)

**Nota sobre idempotencia:**
StatiCrypt siempre encripta desde `docs_src/` (fuente limpia), así que re-ejecutarlo
produce un HTML encriptado fresco sin problema de "double encryption".

## Out of Scope

* Protección de los JSONs en `docs/data/`
* Hacer el repo privado
* Autenticación con usuario/contraseña individual (StatiCrypt es password global)

## Technical Notes

* StatiCrypt CLI: `npx staticrypt docs_src/index.html --password $PASSWORD -d docs/`
* GH Actions puede leer el secret con `${{ secrets.STATICRYPT_PASSWORD }}`
* PowerShell local puede leer de env var: `$env:STATICRYPT_PASSWORD`
* `scrape-kino.yml` usa Node (disponible por defecto en ubuntu-latest)
* El `file_pattern` del auto-commit action necesita incluir los HTML encriptados
