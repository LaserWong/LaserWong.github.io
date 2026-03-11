#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
VENV="$ROOT/.venv"
REQ="$ROOT/requirements.txt"
SCRIPT="$ROOT/tools/generate_arxiv_portal.py"

log() {
  printf '%s\n' "$1"
}

version_ok() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'
}

choose_python() {
  if command -v python3 >/dev/null 2>&1 && version_ok python3; then
    printf '%s' python3
    return 0
  fi
  if command -v python >/dev/null 2>&1 && version_ok python; then
    printf '%s' python
    return 0
  fi
  return 1
}

install_python() {
  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        brew install python@3.12
      else
        log "[arXiv Daily] Homebrew not found. Please install Python 3.10+ manually."
        return 1
      fi
      ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y python3 python3-venv python3-pip
      elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-pip
      elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y python3 python3-pip
      elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -Sy --noconfirm python python-pip
      elif command -v zypper >/dev/null 2>&1; then
        sudo zypper install -y python310 python310-pip
      else
        log "[arXiv Daily] No supported package manager found. Please install Python 3.10+ manually."
        return 1
      fi
      ;;
    *)
      log "[arXiv Daily] Unsupported platform. Please install Python 3.10+ manually."
      return 1
      ;;
  esac
}

log "[arXiv Daily] Starting..."
PYTHON_CMD="$(choose_python || true)"
if [ -z "$PYTHON_CMD" ]; then
  log "[arXiv Daily] Python 3.10+ not found. Attempting installation..."
  install_python
  PYTHON_CMD="$(choose_python || true)"
fi
if [ -z "$PYTHON_CMD" ]; then
  exit 1
fi

if [ -x "$VENV/bin/python" ] && ! "$VENV/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  rm -rf "$VENV"
fi
if [ ! -x "$VENV/bin/python" ]; then
  log "[arXiv Daily] Creating local virtual environment..."
  "$PYTHON_CMD" -m venv "$VENV"
fi

log "[arXiv Daily] Installing / updating dependencies..."
"$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$REQ"

log "[arXiv Daily] Running both archive generators..."
"$VENV/bin/python" -u "$SCRIPT" "$@"

if [ -f "$ROOT/index.html" ]; then
  case "$(uname -s)" in
    Darwin) open "$ROOT/index.html" >/dev/null 2>&1 & ;;
    Linux) command -v xdg-open >/dev/null 2>&1 && xdg-open "$ROOT/index.html" >/dev/null 2>&1 & ;;
  esac
fi

