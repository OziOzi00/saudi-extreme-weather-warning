$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$PWD\src"

python -m saudi_warning.verification.run_impact_evaluation
python -m saudi_warning.verification.run_impact_attribution
python -m pytest -q tests/test_impact_evaluation.py tests/test_impact_attribution.py
