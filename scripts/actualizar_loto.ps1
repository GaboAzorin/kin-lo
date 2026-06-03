# actualizar_loto.ps1
# Descarga resultados nuevos de Loto (polla.cl), recalcula métricas
# y actualiza pozos. Luego hace commit y push automático.
#
# Uso: desde la raíz del proyecto
#   .\scripts\actualizar_loto.ps1
#
# Correr después de cada sorteo (mar/jue/dom, ~22:15 CLT).
#
# Blindaje anti-conflicto con GitHub:
#   El cron de Kino (GitHub Actions) empuja commits al mismo `main` y escribe
#   varios JSON compartidos (pozos.json, historial_index.json, suggestions_*).
#   Para evitar pushes rechazados ("fetch first"):
#     1) Se sincroniza con el remoto ANTES de generar nada (pull --rebase).
#     2) El push reintenta: si el remoto avanzó, se hace reset al remoto y se
#        regenera todo el pipeline (el scraper es idempotente: solo agrega
#        sorteos nuevos; los JSON son artefactos derivados del CSV).

Set-Location $PSScriptRoot\..

# Archivos que produce el pipeline de Loto.
$archivos = @(
    "data/polla_historial.csv",
    "docs/data/loto_metrics.json",
    "docs/data/pozos.json",
    "data/loto_suggestions_pending.json",
    "data/suggestions_history.csv",
    "docs/data/suggestions_history.json",
    "docs/data/suggestions_detail.json",
    "data/jugadas.json",
    "docs/data/historial_index.json"
)

# Corre scraper + métricas + pozos. Idempotente: re-ejecutarlo sobre un CSV ya
# actualizado no duplica sorteos y simplemente regenera los JSON.
function Invoke-Pipeline {
    Write-Host "`n--- Scraper polla.cl ---" -ForegroundColor Cyan
    python src/scrapers/scraper_polla.py
    if ($LASTEXITCODE -ne 0) { throw "scraper_polla.py falló (exit $LASTEXITCODE)" }

    Write-Host "`n--- Métricas Loto ---" -ForegroundColor Cyan
    python src/analytics/metrics.py --game loto
    if ($LASTEXITCODE -ne 0) { throw "metrics.py falló (exit $LASTEXITCODE)" }

    Write-Host "`n--- Pozos ---" -ForegroundColor Cyan
    python src/scrapers/fetch_pozos.py   # no es crítico si falla
}

# === 1/4  Sincronizar con el remoto ANTES de trabajar =======================
# El árbol debe estar limpio aquí; así corremos con el código y datos más
# recientes (incluye los commits del cron de Kino) y evitamos divergencias.
Write-Host "`n=== 1/4  Sincronizar con remoto ===" -ForegroundColor Cyan
git fetch origin
if (git status --porcelain) {
    Write-Host "Hay cambios locales sin commitear. Commitéalos o descártalos antes de correr." -ForegroundColor Red
    exit 1
}
git pull --rebase origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "El rebase contra origin/main falló. Resuélvelo manualmente (git status)." -ForegroundColor Red
    git rebase --abort 2>$null
    exit 1
}

# === 2/4  Pipeline (scraper + métricas + pozos) =============================
Write-Host "`n=== 2/4  Pipeline Loto ===" -ForegroundColor Cyan
try {
    Invoke-Pipeline
} catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    exit 1
}

# === 3/4  Commit ============================================================
Write-Host "`n=== 3/4  Commit ===" -ForegroundColor Cyan
git add $archivos
if (-not (git status --porcelain)) {
    Write-Host "Sin cambios que commitear." -ForegroundColor Yellow
    exit 0
}
$fecha = Get-Date -Format "yyyy-MM-dd"
git commit -m "data(loto): actualizar historial $fecha"

# === 4/4  Push con reintentos ===============================================
Write-Host "`n=== 4/4  Push (con reintentos anti-conflicto) ===" -ForegroundColor Cyan
$maxIntentos = 4
for ($i = 1; $i -le $maxIntentos; $i++) {
    git push origin main
    if ($LASTEXITCODE -eq 0) {
        Write-Host "`nListo (push OK en intento $i)." -ForegroundColor Green
        exit 0
    }

    Write-Host "`nPush rechazado (intento $i/$maxIntentos): el remoto avanzó. Re-sincronizando..." -ForegroundColor Yellow
    git fetch origin
    # El remoto manda: descartamos nuestros JSON regenerados y volvemos a generar
    # sobre la última versión. El scraper re-agrega el/los sorteo(s) que falten.
    git reset --hard origin/main
    try {
        Invoke-Pipeline
    } catch {
        Write-Host "ERROR al regenerar: $_" -ForegroundColor Red
        exit 1
    }
    git add $archivos
    if (-not (git status --porcelain)) {
        Write-Host "`nEl remoto ya contenía todo. Nada que pushear." -ForegroundColor Green
        exit 0
    }
    git commit -m "data(loto): actualizar historial $fecha"
}

Write-Host "`nNo se pudo pushear tras $maxIntentos intentos. Revisa manualmente (git status)." -ForegroundColor Red
exit 1
