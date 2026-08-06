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
  INPUT=$(osascript -e 'POSIX path of (choose file with prompt "Choose a scanned Chinese novel" of type {"com.adobe.pdf"})')
fi
if [[ ! -f "$INPUT" ]]; then
  echo "Input file does not exist: $INPUT"
  read -r "?Press Enter to close..."
  exit 1
fi

BASE="${INPUT%.[Pp][Dd][Ff]}"
OUTPUT="${BASE}-paddle-novel-layout-test.pdf"
TEXT_OUTPUT="${BASE}-paddle-novel-layout-test-text.txt"
REPORT_OUTPUT="${BASE}-paddle-novel-layout-test-ocr-report.json"
REVIEW_OUTPUT="${BASE}-paddle-novel-layout-test-review.txt"
COUNT=2
while [[ -e "$OUTPUT" || -e "$TEXT_OUTPUT" || -e "$REPORT_OUTPUT" || -e "$REVIEW_OUTPUT" ]]; do
  OUTPUT="${BASE}-paddle-novel-layout-test-${COUNT}.pdf"
  TEXT_OUTPUT="${BASE}-paddle-novel-layout-test-${COUNT}-text.txt"
  REPORT_OUTPUT="${BASE}-paddle-novel-layout-test-${COUNT}-ocr-report.json"
  REVIEW_OUTPUT="${BASE}-paddle-novel-layout-test-${COUNT}-review.txt"
  COUNT=$((COUNT + 1))
done

PAGE_COUNT=$("$VENV/bin/python" - "$INPUT" <<'PY'
import pymupdf
import sys
with pymupdf.open(sys.argv[1]) as document:
    print(document.page_count)
PY
)

if [[ -n "${PDF_TEXT_REPAIR_TEST_PAGES:-}" ]]; then
  PAGE_SPEC="$PDF_TEXT_REPAIR_TEST_PAGES"
elif (( PAGE_COUNT >= 8 )); then
  PAGE_SPEC="1-8"
else
  PAGE_SPEC="1-${PAGE_COUNT}"
fi
PAGE_ARGS=(--pages "$PAGE_SPEC")
DESCRIPTION="source pages $PAGE_SPEC"

printf "\nInput : %s\nOutput: %s\n\n" "$INPUT" "$OUTPUT"
echo "Testing $DESCRIPTION."
echo "Auto content start should skip contents pages, retain sparse chapter-title pages, ignore blank pages, and preserve speaker turns."

PADDLE_PDX_MODEL_SOURCE=modelscope \
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
PDF_TEXT_REPAIR_MODEL_SOURCES=modelscope,bos,huggingface \
"$VENV/bin/python" "$HELPER" "$INPUT" "$OUTPUT" \
  "${PAGE_ARGS[@]}" \
  --languages "chi_sim+eng" \
  --dpi 300 \
  --model-tier medium \
  --score-threshold 0.45 \
  --use-orientation \
  --filter-margins \
  --drop-diagram-labels \
  --reading-profile novel \
  --content-start-mode auto \
  --text-output "$TEXT_OUTPUT" \
  --debug-json "$REPORT_OUTPUT" \
  --review-output "$REVIEW_OUTPUT"

echo ""
echo "Completed: $OUTPUT"
echo "Text     : $TEXT_OUTPUT"
echo "Report   : $REPORT_OUTPUT"
echo "Review   : $REVIEW_OUTPUT"
echo ""
echo "Check that the TXT starts with a chapter title or body text, while contents pages and bottom footnotes are omitted from speech."
open -R "$OUTPUT"
read -r "?Press Enter to close..."
