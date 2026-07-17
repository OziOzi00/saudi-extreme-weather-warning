$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$PWD\src"

python -m saudi_warning.demo.build_summary
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.risk.validate_results `
    handoff/risk_results/development_heavy_rain `
    --require-frozen
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.risk.validate_results `
    handoff/risk_results/independent_heavy_rain `
    --require-frozen
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest -q tests/test_prototype_demo.py
exit $LASTEXITCODE
