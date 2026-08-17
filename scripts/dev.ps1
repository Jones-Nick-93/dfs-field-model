[CmdletBinding()]
param(
    [ValidateSet("setup", "doctor", "lint", "test", "demo", "check")]
    [string]$Command = "doctor",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repoRoot

if ($Command -eq "setup") {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw "uv is required. Install it, reopen PowerShell, then rerun '.\dev.cmd setup'."
    }
    uv sync --extra dev --python 3.12
    exit $LASTEXITCODE
}

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing .venv. Run '.\dev.cmd setup' first."
}

& $python (Join-Path $PSScriptRoot "dev.py") $Command @RemainingArgs
exit $LASTEXITCODE
