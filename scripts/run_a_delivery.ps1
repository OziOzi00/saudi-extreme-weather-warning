param(
    [string]$Catalog = "configs/case_catalog_template.csv",
    [string]$CacheDir = "data/raw/graphcast_2020",
    [string]$OutputDir = "handoff/mazu_like",
    [string]$ProcessingManifest = "manifests/processing_manifest.csv",
    [string]$DeliveryManifest = "manifests/delivery_manifest.csv"
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$PWD\src"

python -m saudi_warning.forecasting.preflight_catalog `
    --catalog $Catalog `
    --cache-dir $CacheDir `
    --output-dir $OutputDir `
    --report outputs/case_catalog_preflight_before.csv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.forecasting.run_batch `
    --catalog $Catalog `
    --cache-dir $CacheDir `
    --output-dir $OutputDir `
    --manifest $ProcessingManifest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.forecasting.validate_mazu_like `
    $OutputDir `
    --report outputs/mazu_like_validation.json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m scripts.summarize_mazu_like_adm1 `
    --input-dir $OutputDir `
    --output handoff/region_summaries/mazu_like_adm1_indicator_summaries.csv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.forecasting.build_delivery_manifest `
    --catalog $Catalog `
    --input-dir $OutputDir `
    --output $DeliveryManifest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m saudi_warning.forecasting.preflight_catalog `
    --catalog $Catalog `
    --cache-dir $CacheDir `
    --output-dir $OutputDir `
    --report outputs/case_catalog_preflight_after.csv `
    --fail-on-invalid-existing
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest -q `
    tests/test_batch_catalog.py `
    tests/test_contract_basics.py `
    tests/test_forecast_delivery.py `
    tests/test_mazu_like_region_summaries.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Output "Member A delivery completed and validated."
