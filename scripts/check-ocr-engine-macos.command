#!/bin/zsh
set -u

VENV="$HOME/Library/Application Support/PDF Text Repair/venv"

printf "PDF Text Repair v0.2.2 - environment check\n\n"
printf "PaddleOCR / PP-OCRv6:\n"
if [[ -x "$VENV/bin/python" ]]; then
  "$VENV/bin/python" - <<'PY' || true
import importlib.util
import platform
import sys

print("Python:", sys.version.split()[0], "(" + platform.machine() + ")")
try:
    import paddleocr
    print("PaddleOCR:", getattr(paddleocr, "__version__", "unknown"))
except Exception as exc:
    print("PaddleOCR: not ready -", exc)

try:
    import pymupdf
    print("PyMuPDF:", getattr(pymupdf, "__version__", "unknown"))
except Exception as exc:
    print("PyMuPDF: not ready -", exc)

if importlib.util.find_spec("paddle"):
    try:
        import paddle
        print("Inference backend: PaddlePaddle", getattr(paddle, "__version__", "unknown"))
    except Exception as exc:
        print("PaddlePaddle import failed:", exc)
elif importlib.util.find_spec("onnxruntime"):
    import onnxruntime
    print("Inference backend: ONNX Runtime", getattr(onnxruntime, "__version__", "unknown"))
else:
    print("Inference backend: not installed")
PY
else
  echo "Private Python environment is not installed."
fi

printf "\nOCRmyPDF compatibility mode:\n"
if command -v ocrmypdf >/dev/null 2>&1; then
  command -v ocrmypdf
  ocrmypdf --version
else
  echo "Not installed"
fi

printf "\nTesseract compatibility mode:\n"
if command -v tesseract >/dev/null 2>&1; then
  command -v tesseract
  tesseract --version | head -n 1
  echo ""
  tesseract --list-langs
else
  echo "Not installed"
fi

read -r "?Press Enter to close..."
