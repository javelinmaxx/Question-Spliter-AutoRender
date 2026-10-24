#!/bin/bash
# Compatible with the Bash 3.2 shipped with macOS.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./scripts/setup_macos.sh [--bootstrap] [--with-model] [--download-model] [--no-start]

Install Homebrew Python 3.12 and English Tesseract OCR, prepare .venv,
install development dependencies, run the test suite, and start the app.
The app opens your default browser after binding its local port.

  --with-model      Also build the optional local language-model runtime.
  --bootstrap       Install Homebrew if missing using its official installer.
                    macOS may ask for your password or developer tools.
  --download-model  Also download and verify official Qwen 1.5B GGUF weights.
                    Implies --with-model; needs Internet access and disk space.
  --no-start        Install and test only, without starting the application.
  --start           Start after setup (the default; retained for compatibility).
  -h, --help        Show this help.

Requires macOS, Homebrew (https://brew.sh), and Xcode Command Line Tools.
Does not modify your shell profile or delete an existing virtual environment.
EOF
}

fail() { printf 'Setup failed: %s\n' "$*" >&2; exit 1; }

with_model=0
download_model=0
start_app=1
bootstrap=0
for argument in "$@"; do
  case "$argument" in
    --with-model) with_model=1 ;;
    --bootstrap) bootstrap=1 ;;
    --download-model) with_model=1; download_model=1 ;;
    --start) start_app=1 ;;
    --no-start) start_app=0 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; fail "Unknown option: $argument" ;;
  esac
done

[ "$(uname -s)" = Darwin ] || fail 'This script is for macOS. See README.md for other systems.'
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/.." && pwd)"
cd "$repo_dir"

if [ "$bootstrap" -eq 1 ] && ! command -v brew >/dev/null 2>&1 &&
   [ ! -x /opt/homebrew/bin/brew ] && [ ! -x /usr/local/bin/brew ]; then
  printf 'Installing Homebrew from https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh\n'
  bootstrap_file="$(mktemp -t physics-homebrew)"
  trap 'rm -f "$bootstrap_file"' EXIT
  /usr/bin/curl --fail --show-error --location --proto '=https' --tlsv1.2 \
    https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$bootstrap_file"
  /bin/bash "$bootstrap_file"
  rm -f "$bootstrap_file"
  trap - EXIT
fi

# A fresh macOS shell may not yet have Homebrew on PATH.
if command -v brew >/dev/null 2>&1; then
  brew_command="$(command -v brew)"
elif [ -x /opt/homebrew/bin/brew ]; then
  brew_command=/opt/homebrew/bin/brew
elif [ -x /usr/local/bin/brew ]; then
  brew_command=/usr/local/bin/brew
else
  fail 'Install Homebrew from https://brew.sh, then rerun this script.'
fi
if ! command -v xcode-select >/dev/null 2>&1 || ! xcode-select -p >/dev/null 2>&1; then
  if [ "$bootstrap" -eq 1 ]; then
    /usr/bin/xcode-select --install || true
    fail 'Finish the macOS developer-tools installation dialog, then double-click Install and Start.command again.'
  fi
  fail 'Install Xcode Command Line Tools with: xcode-select --install; then rerun.'
fi

printf 'Installing Python 3.12 and Tesseract through Homebrew…\n'
"$brew_command" install python@3.12 tesseract
python_prefix="$("$brew_command" --prefix python@3.12)"
ocr_prefix="$("$brew_command" --prefix tesseract)"
brew_prefix="$("$brew_command" --prefix)"
export PATH="$python_prefix/bin:$ocr_prefix/bin:$brew_prefix/bin:$PATH"
python_command="$python_prefix/bin/python3.12"
[ -x "$python_command" ] || fail 'Homebrew Python 3.12 was not found after installation.'

venv_dir="$repo_dir/.venv"
if [ -e "$venv_dir" ]; then
  [ -x "$venv_dir/bin/python" ] || fail '.venv exists but is not a usable virtual environment. Preserve or move it before retrying.'
else
  "$python_command" -m venv "$venv_dir"
fi
"$venv_dir/bin/python" -c 'import sys; sys.exit(sys.version_info[:2] != (3, 12))' ||
  fail 'The existing .venv uses a different Python version. Preserve or move it, then rerun with Python 3.12.'

if [ -n "${TESSDATA_PREFIX:-}" ]; then
  tessdata_dir="$TESSDATA_PREFIX"
else
  tessdata_dir="$ocr_prefix/share/tessdata"
fi
[ -f "$tessdata_dir/eng.traineddata" ] || fail "English OCR data is missing from $tessdata_dir. Check TESSDATA_PREFIX and your Homebrew Tesseract installation."
export TESSDATA_PREFIX="$tessdata_dir"

printf 'Installing repository dependencies…\n'
"$venv_dir/bin/python" -m pip install -r "$repo_dir/requirements-dev.txt"
if [ "$with_model" -eq 1 ]; then
  "$brew_command" install cmake
  c_compiler="$(xcrun --find clang)"
  cxx_compiler="$(xcrun --find clang++)"
  case "$(uname -m)" in
    arm64) model_cmake_args='-DGGML_METAL=ON -DGGML_NATIVE=ON -DLLAMA_CURL=OFF' ;;
    x86_64) model_cmake_args='-DGGML_METAL=OFF -DGGML_NATIVE=ON -DLLAMA_CURL=OFF' ;;
    *) fail 'The optional model runtime supports Apple Silicon and Intel Macs.' ;;
  esac
  CC="$c_compiler" CXX="$cxx_compiler" CMAKE_ARGS="$model_cmake_args" \
    CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-4}" \
    "$venv_dir/bin/python" -m pip install -r "$repo_dir/requirements-model.txt"
fi

"$venv_dir/bin/python" - <<'PY'
from pathlib import Path
import fitz
assert (Path(fitz.get_tessdata()) / 'eng.traineddata').is_file(), 'English OCR data is unavailable to PyMuPDF'
print('English OCR data verified.')
PY

model_path="${QUESTION_BANK_MODEL_PATH:-}"
if [ "$download_model" -eq 1 ]; then
  printf 'Downloading and verifying the local model…\n'
  model_path="$("$venv_dir/bin/python" "$repo_dir/tools/download_model.py" --destination "$repo_dir/instance/models")"
  [ -f "$model_path" ] && [ -f "$model_path.json" ] || fail 'The verified model and checksum manifest were not created.'
fi

printf 'Running tests…\n'
"$venv_dir/bin/python" -m pytest -q

# Keep local environment initialization inside the ignored virtual environment.
helper="$venv_dir/physics-env.sh"
marker='# Generated by scripts/setup_macos.sh'
if [ -e "$helper" ] && ! /usr/bin/grep -Fqx "$marker" "$helper"; then
  fail "Preserving an existing custom file at $helper. Move it before regenerating setup instructions."
fi
{
  printf '%s\n' "$marker"
  printf 'export PATH=%q:"$PATH"\n' "$python_prefix/bin:$ocr_prefix/bin:$brew_prefix/bin"
  printf 'source %q\n' "$venv_dir/bin/activate"
  printf 'export TESSDATA_PREFIX=%q\n' "$tessdata_dir"
  if [ -n "$model_path" ]; then
    printf 'export QUESTION_BANK_MODEL_PATH=%q\n' "$model_path"
  fi
} > "$helper"

printf '\nSetup complete. Double-click "Install and Start.command" to launch again later.\nOr run:\n'
printf '  source .venv/physics-env.sh\n  python app.py\n'
if [ "$with_model" -eq 1 ] && [ "$download_model" -eq 0 ] && [ -z "$model_path" ]; then
  printf '\nModel runtime installed; weights are not configured. Rerun with --download-model to fetch them.\n'
fi
if [ "$start_app" -eq 1 ]; then
  printf '\nStarting the question bank; keep this Terminal open. Press Ctrl+C to stop.\n'
  if [ -n "$model_path" ]; then export QUESTION_BANK_MODEL_PATH="$model_path"; fi
  exec "$venv_dir/bin/python" "$repo_dir/app.py"
fi
