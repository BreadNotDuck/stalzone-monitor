$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
& "$Root\.venv\Scripts\python.exe" "$Root\deploy\push.py" @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
