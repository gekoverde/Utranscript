#!/usr/bin/env sh
# Installs the `transcript` command for the current user (Linux / macOS).
# Usage: ./install.sh            -> installs this checkout
#        ./install.sh --speech   -> also installs speech recognition (faster-whisper)
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
if [ -f "$HERE/pyproject.toml" ]; then
    SOURCE="$HERE"
else
    SOURCE="git+https://github.com/gekoverde/Transcript.git"
fi
if [ "$1" = "--speech" ]; then
    SPEC="transcript-cli[speech] @ $SOURCE"
    [ "$SOURCE" = "$HERE" ] && SPEC="$HERE[speech]"
else
    SPEC="$SOURCE"
fi

if command -v pipx >/dev/null 2>&1; then
    pipx install --force "$SPEC"
elif command -v uv >/dev/null 2>&1; then
    uv tool install --force "$SPEC"
else
    PYTHON=$(command -v python3 || command -v python)
    if [ -z "$PYTHON" ]; then
        echo "Python 3.10+ is required: https://www.python.org/downloads/" >&2
        exit 1
    fi
    "$PYTHON" -m pip install --user pipx || "$PYTHON" -m pip install --user --break-system-packages pipx
    "$PYTHON" -m pipx ensurepath
    "$PYTHON" -m pipx install --force "$SPEC"
    echo "Open a new terminal so that the 'transcript' command is found."
fi

echo "Done. Try: transcript --doctor"
