[CmdletBinding()]
param()

& (Join-Path $PSScriptRoot "dev.ps1") test
exit $LASTEXITCODE
