param([int]$Port = 8765)

$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $repoRoot "src"
python -m saudi_warning.dashboard.server --port $Port
