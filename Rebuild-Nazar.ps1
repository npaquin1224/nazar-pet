param(
    [Parameter(Mandatory)]
    [string]$OutputDir,

    [string]$DirectionSemantics = (Join-Path $PSScriptRoot 'qa/direction-semantics.json'),

    [switch]$OptimizePng
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$python = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } else { 'python3' }
$buildOptions = @('--output-dir', $OutputDir, '--direction-semantics', $DirectionSemantics)
if ($OptimizePng) {
    $buildOptions += '--optimize-png'
}
& $python (Join-Path $PSScriptRoot 'rebuild_nazar.py') @buildOptions
