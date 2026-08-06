#!/bin/zsh
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/Library/Application Support/PDF Text Repair/venv"
HELPER="$ROOT/src-tauri/resources/readest_text_layer.py"

if ! command -v ocrmypdf >/dev/null 2>&1; then
  echo "OCRmyPDF is not installed. Run scripts/install-ocr-engine-macos.command."
  read -r "?Press Enter to close..."
  exit 1
fi
if [[ ! -x "$VENV/bin/python" ]] || ! "$VENV/bin/python" -c 'import pymupdf' >/dev/null 2>&1; then
  echo "The Readest optimizer is not installed. Run scripts/install-ocr-engine-macos.command again."
  read -r "?Press Enter to close..."
  exit 1
fi

INPUT="$1"
if [[ -z "$INPUT" ]]; then
  INPUT=$(osascript -e 'POSIX path of (choose file with prompt "Choose a PDF to repair" of type {"com.adobe.pdf"})')
fi
if [[ ! -f "$INPUT" ]]; then
  echo "Input file does not exist: $INPUT"
  read -r "?Press Enter to close..."
  exit 1
fi

BASE="${INPUT%.[Pp][Dd][Ff]}"
OUTPUT="${BASE}-readest-optimized.pdf"
COUNT=2
while [[ -e "$OUTPUT" ]]; do
  OUTPUT="${BASE}-readest-optimized-${COUNT}.pdf"
  COUNT=$((COUNT + 1))
done

TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/pdf-text-repair.XXXXXX")
trap 'rm -rf "$TMP_DIR"' EXIT
OCR_STAGE="$TMP_DIR/ocr-stage.pdf"
SIDECAR="$TMP_DIR/ocr.txt"

printf "\nInput : %s\nOutput: %s\n\n" "$INPUT" "$OUTPUT"
echo "Step 1/2: OCR with Simplified Chinese + English..."
env PATH="/opt/homebrew/bin:/usr/local/bin:/opt/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH" \
  ocrmypdf \
  --force-ocr \
  --language chi_sim+eng \
  --output-type pdf \
  --sidecar "$SIDECAR" \
  --rotate-pages \
  --deskew \
  --optimize 1 \
  "$INPUT" \
  "$OCR_STAGE"

echo ""
echo "Step 2/2: merging the continuous Readest reading layer..."
"$VENV/bin/python" "$HELPER" "$OCR_STAGE" "$OUTPUT" --sidecar "$SIDECAR" --font-size 3.2

echo ""
echo "Completed: $OUTPUT"
open -R "$OUTPUT"
read -r "?Press Enter to close..."
