[CmdletBinding()]
param()

& (Join-Path $PSScriptRoot "dev.ps1") lint
exit $LASTEXITCODE
