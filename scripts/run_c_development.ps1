param(
    [string]$Risk = "handoff/risk_results/example_risk_result.json",
    [string]$Bundle = "handoff/knowledge_graph/import_bundle.json",
    [string]$Report = "handoff/reports/example_warning_report.md"
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$PWD\src"

python -m saudi_warning.knowledge_graph.build_bundle `
    --risk $Risk `
    --output $Bundle
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.reporting.generate_report `
    --risk $Risk `
    --output $Report
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest -q tests/test_member_c_workflow.py
exit $LASTEXITCODE
