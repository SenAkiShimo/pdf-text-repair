#!/bin/zsh
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/Library/Application Support/PDF Text Repair/venv"
HELPER="$ROOT/src-tauri/resources/paddle_scan_pipeline.py"

if [[ ! -x "$VENV/bin/python" ]] || ! "$VENV/bin/python" -c 'import paddleocr, pymupdf' >/dev/null 2>&1; then
  echo "PaddleOCR is not installed. Run scripts/install-ocr-engine-macos.command first."
  read -r "?Press Enter to close..."
  exit 1
fi

INPUT="${1:-}"
if [[ -z "$INPUT" ]]; then
  INPUT=$(osascript -e 'POSIX path of (choose file with prompt "Choose a scanned or image-only PDF" of type {"com.adobe.pdf"})')
fi
BASE="${INPUT%.[Pp][Dd][Ff]}"
OUTPUT="${BASE}-paddle-readest.pdf"
TEXT_OUTPUT="${BASE}-paddle-readest-text.txt"
REPORT_OUTPUT="${BASE}-paddle-readest-ocr-report.json"
REVIEW_OUTPUT="${BASE}-paddle-readest-review.txt"

if [[ -e "$OUTPUT" || -e "$TEXT_OUTPUT" || -e "$REPORT_OUTPUT" || -e "$REVIEW_OUTPUT" ]]; then
  echo "Output files already exist. Move or rename them first."
  read -r "?Press Enter to close..."
  exit 1
fi

PADDLE_PDX_MODEL_SOURCE=modelscope \
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
PDF_TEXT_REPAIR_MODEL_SOURCES=modelscope,bos,huggingface \
"$VENV/bin/python" "$HELPER" "$INPUT" "$OUTPUT" \
  --languages "chi_sim+eng+fra" \
  --dpi 300 \
  --model-tier medium \
  --score-threshold 0.45 \
  --use-orientation \
  --filter-margins \
  --drop-diagram-labels \
  --text-output "$TEXT_OUTPUT" \
  --debug-json "$REPORT_OUTPUT" \
  --review-output "$REVIEW_OUTPUT"

open -R "$OUTPUT"
read -r "?Press Enter to close..."
