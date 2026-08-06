#!/bin/zsh
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/test-paddle-scan-macos.command" "$@"
