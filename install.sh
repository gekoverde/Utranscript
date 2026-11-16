#!/usr/bin/env sh
# Installs the `transcript` command for the current user (Linux / macOS).
# Usage: ./install.sh            -> installs this checkout
#        ./install.sh --speech   -> also installs speech recognition (faster-whisper)
set -e

# Every dependency has prebuilt packages for Python 3.10 to 3.14, but not all of them for 3.15 yet,
# where pip would have to compile them. With a newer Python, install with 3.13 instead (uv and
# pipx download it when it is missing).
SAFE_PYTHON=3.13

HERE=$(cd "$(dirname "$0")" && pwd)
if [ -f "$HERE/pyproject.toml" ]; then
    SOURCE="$HERE"
else
    SOURCE="git+https://github.com/gekoverde/Utranscript.git"
fi
if [ "$1" = "--speech" ]; then
    SPEC="transcript-cli[speech] @ $SOURCE"
    [ "$SOURCE" = "$HERE" ] && SPEC="${HERE}[speech]"
else
    SPEC="$SOURCE"
fi

# The pipx options that switch to $SAFE_PYTHON when the Python given as $1 is 3.15 or newer.
python_options() {
    if [ -n "$1" ] && "$1" -c 'import sys; sys.exit(sys.version_info < (3, 15))' 2>/dev/null; then
        echo "--python $SAFE_PYTHON --fetch-missing-python"
    fi
}

if command -v pipx >/dev/null 2>&1; then
    DEFAULT_PYTHON=$(pipx environment --value PIPX_DEFAULT_PYTHON 2>/dev/null || command -v python3 || true)
    # The options are meant to be split into separate words.
    # shellcheck disable=SC2046
    pipx install --force $(python_options "$DEFAULT_PYTHON") "$SPEC"
elif command -v uv >/dev/null 2>&1; then
    uv tool install --force --python "$SAFE_PYTHON" "$SPEC"
else
    PYTHON=$(command -v python3 || command -v python || true)
    if [ -z "$PYTHON" ]; then
        echo "Python is required (3.13 recommended): https://www.python.org/downloads/" >&2
        exit 1
    fi
    # --fetch-missing-python needs pipx 1.5 or later.
    "$PYTHON" -m pip install --user --upgrade pipx || "$PYTHON" -m pip install --user --upgrade --break-system-packages pipx
    "$PYTHON" -m pipx ensurepath
    # shellcheck disable=SC2046
    "$PYTHON" -m pipx install --force $(python_options "$PYTHON") "$SPEC"
    echo "Open a new terminal so that the 'transcript' command is found."
fi

echo "Done. Try: transcript --doctor"
