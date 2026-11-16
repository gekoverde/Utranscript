# Installs the `transcript` command for the current user (Windows).
# Usage:  powershell -ExecutionPolicy Bypass -File install.ps1           -> installs this checkout
#         powershell -ExecutionPolicy Bypass -File install.ps1 -Speech   -> also speech recognition
param([switch]$Speech)
$ErrorActionPreference = "Stop"

# Every dependency has prebuilt Windows packages for Python 3.10 to 3.14, but not all of them for
# 3.15 yet, where pip would have to compile them. Installing with 3.13 avoids that whatever the
# default Python is: uv and pipx download it when it is missing.
$PythonVersion = "3.13"

if (Test-Path (Join-Path $PSScriptRoot "pyproject.toml")) {
    $Source = $PSScriptRoot
    $Spec = if ($Speech) { "$Source[speech]" } else { $Source }
} else {
    $Source = "git+https://github.com/gekoverde/Utranscript.git"
    $Spec = if ($Speech) { "transcript-cli[speech] @ $Source" } else { $Source }
}

if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv tool install --force --python $PythonVersion "$Spec"
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
} else {
    $Python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { $null }
    if (-not $Python) {
        Write-Error "Python is required (3.13 recommended): https://www.python.org/downloads/ (tick 'Add python.exe to PATH')"
    }
    # --fetch-missing-python needs pipx 1.5 or later.
    & $Python -m pip install --user --upgrade pipx
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    & $Python -m pipx ensurepath
    & $Python -m pipx install --force --python $PythonVersion --fetch-missing-python "$Spec"
    if ($LASTEXITCODE) { exit $LASTEXITCODE }
    Write-Host "Close and reopen the terminal so that the 'transcript' command is found."
}

Write-Host "Done. Try: transcript --doctor"
