# actualizar_loto.ps1
# Descarga resultados nuevos de Loto (polla.cl), recalcula métricas
# y actualiza pozos. Luego hace commit y push automático.
#
# Uso: desde la raíz del proyecto
#   .\scripts\actualizar_loto.ps1
#
# Correr después de cada sorteo (mar/jue/dom, ~22:15 CLT).

Set-Location $PSScriptRoot\..

Write-Host "`n=== 1/4  Scraper polla.cl ===" -ForegroundColor Cyan
python src/scrapers/scraper_polla.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR en scraper_polla.py (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== 2/4  Métricas Loto ===" -ForegroundColor Cyan
python src/analytics/metrics.py --game loto
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR en metrics.py (exit $LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

Write-Host "`n=== 3/4  Pozos ===" -ForegroundColor Cyan
python src/scrapers/fetch_pozos.py
# No es crítico si falla

Write-Host "`n=== 4/4  Commit y push ===" -ForegroundColor Cyan
git add data/polla_historial.csv docs/data/loto_metrics.json docs/data/pozos.json data/loto_suggestions_pending.json data/suggestions_history.csv docs/data/suggestions_history.json

$status = git status --porcelain
if (-not $status) {
    Write-Host "Sin cambios que commitear." -ForegroundColor Yellow
    exit 0
}

$fecha = Get-Date -Format "yyyy-MM-dd"
git commit -m "data(loto): actualizar historial $fecha"
git push origin main

Write-Host "`nListo." -ForegroundColor Green
