[CmdletBinding()]
param()

& (Join-Path $PSScriptRoot "dev.ps1") check
exit $LASTEXITCODE
