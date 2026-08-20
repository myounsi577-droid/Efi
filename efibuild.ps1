# Lanceur efibuild pour PowerShell (Windows, macOS, Linux).
# Necessite Python 3.9 ou plus recent.
$here = Split-Path -Parent $MyInvocation.MyCommand.Definition
Push-Location $here
try {
    $python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" }
              elseif (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" }
              else { "python" }
    if ($python -eq "py") { & py -3 -m efibuilder @args }
    else { & $python -m efibuilder @args }
    exit $LASTEXITCODE
} finally { Pop-Location }
