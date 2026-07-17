$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$PWD\src"

python scripts/screen_imerg_candidates.py `
    --additional-plan configs/imerg_development_gap_plan.csv `
    --additional-plan configs/imerg_independent_heavy_rain_gap_plan.csv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.risk.run_independent_heavy_rain
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.knowledge_graph.build_bundle `
    --risk handoff/risk_results/development_heavy_rain `
    --risk handoff/risk_results/independent_heavy_rain `
    --output handoff/knowledge_graph/heavy_rain_evaluation_bundle.json `
    --generated-at 2026-07-17T03:35:02Z
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.reporting.generate_formal_reports `
    --risk-dir handoff/risk_results/independent_heavy_rain `
    --output-dir handoff/reports/independent_heavy_rain `
    --manifest manifests/independent_heavy_rain_report_manifest.csv `
    --expected-count 18
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest -q `
    tests/test_independent_heavy_rain_evaluation.py `
    tests/test_independent_heavy_rain_kg_reports.py
exit $LASTEXITCODE
