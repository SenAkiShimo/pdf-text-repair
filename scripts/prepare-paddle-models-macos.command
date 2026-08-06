#!/bin/zsh

set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$HOME/Library/Application Support/PDF Text Repair/venv"
HELPER="$ROOT/src-tauri/resources/paddle_scan_pipeline.py"
TIER="${1:-medium}"

if [[ "$TIER" != "tiny" && "$TIER" != "small" && "$TIER" != "medium" ]]; then
  echo "Model tier must be tiny, small, or medium."
  exit 2
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "PaddleOCR is not installed. Run scripts/install-ocr-engine-macos.command first."
  [[ "${PDF_TEXT_REPAIR_NO_PAUSE:-0}" == "1" ]] || read -r "?Press Enter to close..."
  exit 1
fi

printf "\nPDF Text Repair v0.2.2 - PP-OCRv6 model preparation\n\n"
echo "Model: PP-OCRv6 $TIER"
echo "Sources: ModelScope -> BOS -> Hugging Face"
echo "Interrupted partial model folders will be removed automatically before retrying."
echo "Completed model folders remain cached in ~/.paddlex/official_models."
echo ""

export PYTHONUNBUFFERED=1
export PADDLE_PDX_MODEL_SOURCE=modelscope
export PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
export PDF_TEXT_REPAIR_MODEL_SOURCES=modelscope,bos,huggingface

if "$VENV/bin/python" "$HELPER" \
  --prepare-models \
  --model-tier "$TIER" \
  --languages "chi_sim+eng+fra" \
  --use-orientation; then
  echo ""
  echo "PP-OCRv6 $TIER is ready."
  [[ "${PDF_TEXT_REPAIR_NO_PAUSE:-0}" == "1" ]] || read -r "?Press Enter to close..."
  exit 0
fi

echo ""
echo "Model preparation was interrupted or all sources failed."
echo "Running this file again is safe; completed downloads stay cached."
[[ "${PDF_TEXT_REPAIR_NO_PAUSE:-0}" == "1" ]] || read -r "?Press Enter to close..."
exit 1
