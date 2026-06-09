#!/usr/bin/env bash
# Encripta las páginas HTML del sitio con StatiCrypt.
# Lee scripts/staticrypt-pages.txt (salt + lista de páginas), compartido con encrypt_html.ps1.
# Requiere STATICRYPT_PASSWORD en el entorno y npx (Node).
set -euo pipefail

if [ -z "${STATICRYPT_PASSWORD:-}" ]; then
  echo "ERROR: define STATICRYPT_PASSWORD antes de correr este script." >&2
  exit 1
fi

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="$DIR/scripts/staticrypt-pages.txt"
SALT=""

while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    ''|\#*) continue ;;
    SALT=*) SALT="${line#SALT=}" ;;
    *)
      src="${line%%|*}"; out="${line##*|}"
      echo "  $src -> $out"
      npx --yes staticrypt "$DIR/$src" --password "$STATICRYPT_PASSWORD" --salt "$SALT" --short -d "$DIR/$out"
      ;;
  esac
done < "$CONF"

mkdir -p "$DIR/docs/js"
cp "$DIR/docs_src/js/gh-api.js" "$DIR/docs/js/gh-api.js"
echo "  copiado js/gh-api.js -> docs/js/"

echo "Encriptación completa."
