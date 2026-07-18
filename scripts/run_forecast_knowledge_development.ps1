param(
    [string]$GeneratedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "$PWD\src"

python -m saudi_warning.knowledge_graph.static_context `
    --generated-at $GeneratedAt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.knowledge_graph.spatial_diagnostics `
    --generated-at $GeneratedAt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.knowledge_graph.assess_forecast_context `
    --generated-at $GeneratedAt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest -q `
    tests/test_static_knowledge_context.py `
    tests/test_spatial_diagnostics.py `
    tests/test_forecast_context_assessment.py `
    tests/test_agent_forecast_boundary.py
exit $LASTEXITCODE
