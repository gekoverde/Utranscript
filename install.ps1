# Installs the `transcript` command for the current user (Windows).
# Usage:  powershell -ExecutionPolicy Bypass -File install.ps1           -> installs this checkout
#         powershell -ExecutionPolicy Bypass -File install.ps1 -Speech   -> also speech recognition
param([switch]$Speech)
$ErrorActionPreference = "Stop"

if (Test-Path (Join-Path $PSScriptRoot "pyproject.toml")) {
    $Source = $PSScriptRoot
    $Spec = if ($Speech) { "$Source[speech]" } else { $Source }
} else {
    $Source = "git+https://github.com/gekoverde/Utranscript.git"
    $Spec = if ($Speech) { "transcript-cli[speech] @ $Source" } else { $Source }
}

if (Get-Command pipx -ErrorAction SilentlyContinue) {
    pipx install --force "$Spec"
} elseif (Get-Command uv -ErrorAction SilentlyContinue) {
    uv tool install --force "$Spec"
} else {
    $Python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { $null }
    if (-not $Python) {
        Write-Error "Python 3.10+ is required: https://www.python.org/downloads/ (tick 'Add python.exe to PATH')"
    }
    & $Python -m pip install --user pipx
    & $Python -m pipx ensurepath
    & $Python -m pipx install --force "$Spec"
    Write-Host "Close and reopen the terminal so that the 'transcript' command is found."
}

Write-Host "Done. Try: transcript --doctor"
