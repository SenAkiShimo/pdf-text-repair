#!/bin/zsh
set -e
cd "$(dirname "$0")/.."

pause() {
  echo ""
  read -r "?Press Enter to close..."
}

fail() {
  echo ""
  echo "$1"
  pause
  exit 1
}

if ! command -v npm >/dev/null 2>&1; then
  fail "Node.js/npm is required."
fi
if ! command -v cargo >/dev/null 2>&1; then
  fail "Rust/Cargo is required. Install it from https://rustup.rs"
fi

NPM_CACHE="$PWD/.npm-cache"
mkdir -p "$NPM_CACHE"
export npm_config_cache="$NPM_CACHE"
export npm_config_audit="false"
export npm_config_fund="false"
export npm_config_update_notifier="false"

install_dependencies() {
  echo "Installing JavaScript dependencies with a project-local npm cache..."
  echo "Cache: $NPM_CACHE"

  if npm install \
    --registry="https://registry.npmmirror.com" \
    --cache="$NPM_CACHE" \
    --no-audit \
    --no-fund; then
    return 0
  fi

  echo ""
  echo "China mirror failed. Retrying with the official npm registry..."
  npm install \
    --registry="https://registry.npmjs.org" \
    --cache="$NPM_CACHE" \
    --no-audit \
    --no-fund
}

if [[ ! -x node_modules/.bin/tauri || ! -x node_modules/.bin/vite ]]; then
  install_dependencies || fail "JavaScript dependency installation failed."
fi

export CARGO_REGISTRIES_CRATES_IO_PROTOCOL="sparse"
echo "Building PDF Text Repair v0.2.2..."
npm run tauri build

APP="$(find src-tauri/target/release/bundle/macos -maxdepth 1 -type d -name '*.app' -print -quit 2>/dev/null || true)"
echo ""
if [[ -n "$APP" ]]; then
  echo "Build completed: $APP"
  open -R "$APP" || true
else
  echo "Build output: src-tauri/target/release/bundle/"
fi
pause
