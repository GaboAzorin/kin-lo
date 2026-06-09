# encrypt_html.ps1
# Encripta las páginas HTML del sitio usando StatiCrypt.
# Requiere Node.js / npx instalado localmente.
#
# Uso: desde la raíz del proyecto
#   $env:STATICRYPT_PASSWORD = "tu_contraseña"
#   .\scripts\encrypt_html.ps1
#
# Correr cuando se modifiquen archivos en docs_src/*.html

Set-Location $PSScriptRoot\..

if (-not $env:STATICRYPT_PASSWORD) {
    Write-Host "ERROR: Define la variable de entorno STATICRYPT_PASSWORD antes de correr este script." -ForegroundColor Red
    Write-Host "  Ejemplo: `$env:STATICRYPT_PASSWORD = 'tu_contraseña'" -ForegroundColor Yellow
    exit 1
}

$PASS = $env:STATICRYPT_PASSWORD

# Config compartida con encrypt_html.sh (salt + lista de páginas).
$conf  = Join-Path $PSScriptRoot "staticrypt-pages.txt"
$SALT  = ""
$pages = @()
foreach ($line in Get-Content $conf) {
    $t = $line.Trim()
    if ($t -eq "" -or $t.StartsWith("#")) { continue }
    if ($t.StartsWith("SALT=")) { $SALT = $t.Substring(5); continue }
    $parts = $t.Split("|")
    $pages += [pscustomobject]@{ src = $parts[0]; out = $parts[1] }
}

Write-Host "`n--- Encriptando HTML con StatiCrypt ---" -ForegroundColor Cyan

foreach ($page in $pages) {
    Write-Host "  $($page.src) → $($page.out)" -ForegroundColor Gray
    npx --yes staticrypt $page.src --password $PASS --salt $SALT --short -d $page.out
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR al encriptar $($page.src)" -ForegroundColor Red
        exit 1
    }
}

Write-Host "`nEncriptación completa. Archivos listos en docs/." -ForegroundColor Green
Write-Host "Para commitear: git add docs/*.html docs/*/index.html && git commit -m 'chore: actualizar HTML encriptado'" -ForegroundColor Yellow
