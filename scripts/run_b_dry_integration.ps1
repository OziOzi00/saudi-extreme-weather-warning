$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$PWD\src"

python -m saudi_warning.risk.run_draft --created-at 2026-07-15T00:00:00Z
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.risk.validate_results handoff/risk_dry_runs/results
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest -q `
    tests/test_candidate_risk_engine.py `
    tests/test_risk_engine_boundaries.py `
    tests/test_risk_validation.py `
    tests/test_weather_verification.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Output "Member B draft integration completed; rules remain draft."
