#!/bin/zsh
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/Library/Application Support/PDF Text Repair/venv"
HELPER="$ROOT/src-tauri/resources/paddle_scan_pipeline.py"

if [[ ! -x "$VENV/bin/python" ]] || ! "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import importlib.util
import paddleocr
import pymupdf
assert importlib.util.find_spec("paddle") or importlib.util.find_spec("onnxruntime")
PY
then
  echo "PaddleOCR is not installed. Run scripts/install-ocr-engine-macos.command first."
  read -r "?Press Enter to close..."
  exit 1
fi

INPUT="${1:-}"
if [[ -z "$INPUT" ]]; then
  INPUT=$(osascript -e 'POSIX path of (choose file with prompt "Choose a scanned or image-only PDF" of type {"com.adobe.pdf"})')
fi
if [[ ! -f "$INPUT" ]]; then
  echo "Input file does not exist: $INPUT"
  read -r "?Press Enter to close..."
  exit 1
fi

BASE="${INPUT%.[Pp][Dd][Ff]}"
OUTPUT="${BASE}-paddle-test-pages.pdf"
TEXT_OUTPUT="${BASE}-paddle-test-pages-text.txt"
REPORT_OUTPUT="${BASE}-paddle-test-pages-ocr-report.json"
REVIEW_OUTPUT="${BASE}-paddle-test-pages-review.txt"
COUNT=2
while [[ -e "$OUTPUT" || -e "$TEXT_OUTPUT" || -e "$REPORT_OUTPUT" || -e "$REVIEW_OUTPUT" ]]; do
  OUTPUT="${BASE}-paddle-test-pages-${COUNT}.pdf"
  TEXT_OUTPUT="${BASE}-paddle-test-pages-${COUNT}-text.txt"
  REPORT_OUTPUT="${BASE}-paddle-test-pages-${COUNT}-ocr-report.json"
  REVIEW_OUTPUT="${BASE}-paddle-test-pages-${COUNT}-review.txt"
  COUNT=$((COUNT + 1))
done

PAGE_COUNT=$("$VENV/bin/python" - "$INPUT" <<'PY'
import pymupdf
import sys
with pymupdf.open(sys.argv[1]) as document:
    print(document.page_count)
PY
)

PAGE_SPEC=$("$VENV/bin/python" - "$PAGE_COUNT" <<'PY'
import sys
count = int(sys.argv[1])
limit = min(8, count)
if count <= limit:
    pages = list(range(1, count + 1))
else:
    pages = sorted({1, count, *[round(1 + i * (count - 1) / (limit - 1)) for i in range(limit)]})
print(",".join(str(page) for page in pages))
PY
)
PAGE_ARGS=(--pages "$PAGE_SPEC")
TEST_DESCRIPTION="sampled source pages $PAGE_SPEC"

printf "\nInput : %s\nOutput: %s\n\n" "$INPUT" "$OUTPUT"
echo "Preparing PP-OCRv6 Medium before processing pages..."
PDF_TEXT_REPAIR_NO_PAUSE=1 "$ROOT/scripts/prepare-paddle-models-macos.command" medium
echo ""
echo "Testing $TEST_DESCRIPTION with PP-OCRv6 Medium."
echo "The first run downloads model files from ModelScope first, with BOS and Hugging Face fallbacks and may take several minutes."

PADDLE_PDX_MODEL_SOURCE=modelscope \
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
PDF_TEXT_REPAIR_MODEL_SOURCES=modelscope,bos,huggingface \
"$VENV/bin/python" "$HELPER" "$INPUT" "$OUTPUT" \
  "${PAGE_ARGS[@]}" \
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

echo ""
echo "Completed: $OUTPUT"
echo "Text     : $TEXT_OUTPUT"
echo "Report   : $REPORT_OUTPUT"
echo "Review   : $REVIEW_OUTPUT"
open -R "$OUTPUT"
read -r "?Press Enter to close..."
