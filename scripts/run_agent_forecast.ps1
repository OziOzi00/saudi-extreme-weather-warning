param(
    [string]$Risk = "handoff/risk_results/development_heavy_rain/risk_20200501_00_024_SA-09_heavy_rain.json",
    [ValidateSet("auto", "deterministic", "openai")]
    [string]$Provider = "auto",
    [string]$EnvFile = ".env.agent.local",
    [string]$OutputJson = "outputs/forecast_report.json",
    [string]$OutputMarkdown = "outputs/forecast_report.md",
    [string]$BundleOutput = "outputs/prediction_context_bundle.json"
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$PWD\src"

if (Test-Path -LiteralPath $EnvFile) {
    foreach ($line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        $name = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        if ($name -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

python -m saudi_warning.agent.run_forecast_report `
    --risk $Risk `
    --provider $Provider `
    --output-json $OutputJson `
    --output-markdown $OutputMarkdown `
    --bundle-output $BundleOutput
exit $LASTEXITCODE
