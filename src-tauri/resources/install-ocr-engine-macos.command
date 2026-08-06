#!/bin/zsh

set -u

pause_before_close() {
  echo ""
  read -r "?Press Enter to close..."
}

finish_with_error() {
  local status=$?
  echo ""
  echo "Installation did not finish. Existing downloads are normally cached."
  echo "Run this installer again when the network is stable."
  pause_before_close
  exit "$status"
}

trap finish_with_error ZERR

printf "\nPDF Text Repair v0.2.2 - PaddleOCR + compatibility engine installer\n\n"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is not installed. Install Homebrew first, then run this file again."
  echo "https://brew.sh"
  pause_before_close
  exit 1
fi

export HOMEBREW_NO_AUTO_UPDATE=1
export HOMEBREW_API_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles/api"
export HOMEBREW_BOTTLE_DOMAIN="https://mirrors.ustc.edu.cn/homebrew-bottles"
unset HOMEBREW_ARTIFACT_DOMAIN 2>/dev/null || true

cat <<'TEXT'
This installer prepares two local OCR paths:
  1. PaddleOCR 3.7 / PP-OCRv6 for high-accuracy scanned Chinese books.
  2. OCRmyPDF + Tesseract for broken text layers and compatibility mode.

Python packages are installed into:
  ~/Library/Application Support/PDF Text Repair/venv
They do not modify the system Python.
TEXT

install_formula() {
  local formula="$1"
  local attempt=1
  if brew list --versions "$formula" >/dev/null 2>&1; then
    echo ""
    echo "$formula is already installed."
    return 0
  fi
  while (( attempt <= 3 )); do
    echo ""
    echo "Installing $formula (attempt $attempt of 3)..."
    if brew install "$formula"; then
      return 0
    fi
    if (( attempt < 3 )); then
      echo "Download interrupted. Waiting 5 seconds before retrying..."
      sleep 5
    fi
    attempt=$((attempt + 1))
  done
  echo "Failed to install $formula after three attempts."
  return 1
}

install_formula ocrmypdf
install_formula tesseract-lang
install_formula python@3.13

PYTHON_BIN=""
for candidate in \
  "/opt/homebrew/bin/python3.13" \
  "/usr/local/bin/python3.13" \
  "$(brew --prefix python@3.13 2>/dev/null)/bin/python3.13"
do
  if [[ -x "$candidate" ]]; then
    PYTHON_BIN="$candidate"
    break
  fi
done
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python 3.13 was not found after installation."
  exit 1
fi

APP_SUPPORT="$HOME/Library/Application Support/PDF Text Repair"
VENV="$APP_SUPPORT/venv"
mkdir -p "$APP_SUPPORT"

if [[ -x "$VENV/bin/python" ]]; then
  VENV_MINOR=$("$VENV/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
  if [[ "$VENV_MINOR" != "3.13" ]]; then
    echo ""
    echo "Recreating the private environment with Python 3.13 (old version: $VENV_MINOR)..."
    rm -rf "$VENV"
  fi
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  echo ""
  echo "Creating private Python 3.13 environment..."
  "$PYTHON_BIN" -m venv "$VENV"
fi

pip_install() {
  local package="$1"
  local attempt=1
  while (( attempt <= 3 )); do
    echo ""
    echo "Installing $package (attempt $attempt of 3)..."
    if "$VENV/bin/python" -m pip install --upgrade "$package" \
      --index-url "https://pypi.tuna.tsinghua.edu.cn/simple" \
      --timeout 180; then
      return 0
    fi
    if (( attempt == 2 )); then
      echo "Mirror unavailable; trying the official Python index..."
      if "$VENV/bin/python" -m pip install --upgrade "$package" --timeout 180; then
        return 0
      fi
    fi
    sleep 5
    attempt=$((attempt + 1))
  done
  return 1
}

pip_install pip
pip_install "pymupdf>=1.26,<1.27"
pip_install "paddleocr==3.7.0"

ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
  echo ""
  echo "Apple Silicon detected. Trying the official PaddlePaddle 3.3 CPU wheel..."
  PADDLE_OK=0
  for attempt in 1 2 3; do
    if "$VENV/bin/python" -m pip install --upgrade "paddlepaddle==3.3.0" \
      -i "https://www.paddlepaddle.org.cn/packages/stable/cpu/" \
      --timeout 240; then
      PADDLE_OK=1
      break
    fi
    sleep 5
  done
  if (( PADDLE_OK == 0 )); then
    echo "PaddlePaddle could not be installed. Installing the ONNX Runtime fallback..."
    pip_install "onnxruntime>=1.20"
  else
    "$VENV/bin/python" -m pip uninstall -y onnxruntime onnxruntime-gpu >/dev/null 2>&1 || true
  fi
else
  echo ""
  echo "Intel Mac detected. Current PaddlePaddle macOS wheels target Apple Silicon,"
  echo "so PDF Text Repair will use PaddleOCR's official ONNX Runtime backend."
  pip_install "onnxruntime>=1.20"
fi

if ! "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import importlib.util
import paddleocr
import pymupdf
assert importlib.util.find_spec("paddle") or importlib.util.find_spec("onnxruntime")
print(paddleocr.__version__)
PY
then
  echo "PaddleOCR could not be verified in the private environment."
  exit 1
fi

if ! command -v ocrmypdf >/dev/null 2>&1 || ! command -v tesseract >/dev/null 2>&1; then
  echo "OCRmyPDF or Tesseract is still unavailable."
  exit 1
fi

trap - ZERR

echo ""
echo "Installation completed."
echo "PP-OCRv6 models are prepared from ModelScope first, with BOS and Hugging Face fallbacks.
Run scripts/prepare-paddle-models-macos.command before the OCR test."
echo "Next: run scripts/test-paddle-scan-macos.command."
pause_before_close
