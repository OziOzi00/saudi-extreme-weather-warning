$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$PWD\src"

python -m saudi_warning.risk.run_development_review `
    --heavy-rule configs/heavy_rain_rules_v2.yaml `
    --heat-rule configs/heatwave_rules_v2.yaml `
    --output-dir handoff/risk_dry_runs/development_v2_results `
    --audit-output handoff/risk_dry_runs/development_v2_rule_review.csv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.risk.assess_development_freeze
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.risk.run_frozen_development
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.knowledge_graph.build_bundle `
    --risk handoff/risk_results/development_heavy_rain `
    --output handoff/knowledge_graph/formal_development_bundle.json `
    --generated-at 2026-07-17T00:00:00Z
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.reporting.generate_formal_reports
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest -q `
    tests/test_development_freeze_assessment.py `
    tests/test_frozen_development_risk.py `
    tests/test_formal_development_kg_reports.py
exit $LASTEXITCODE
