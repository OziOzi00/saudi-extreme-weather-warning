param(
    [switch]$SkipSelection
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$PWD\src"

if (-not $SkipSelection) {
    python -m saudi_warning.risk.select_joint_pipeline
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

python -m saudi_warning.risk.evaluate_joint_pipeline
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.agent.run_joint_forecast_report `
    --hazard heavy_rain `
    --split development `
    --case-id 20200501_00 `
    --region-id SA-09 `
    --lead-time-hours 48 `
    --output-json handoff/reports/joint_pipeline_demo/heavy_rain_joint_report.json `
    --output-markdown handoff/reports/joint_pipeline_demo/heavy_rain_joint_report.md
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.agent.run_joint_forecast_report `
    --hazard heatwave `
    --split independent_test `
    --case-id 20200729_00 `
    --region-id SA-04 `
    --lead-time-hours 48 `
    --output-json handoff/reports/joint_pipeline_demo/heatwave_joint_report.json `
    --output-markdown handoff/reports/joint_pipeline_demo/heatwave_joint_report.md
exit $LASTEXITCODE
