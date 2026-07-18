param(
    [string]$Risk = "handoff/risk_results/development_heavy_rain/risk_20200501_00_024_SA-09_heavy_rain.json",
    [ValidateSet("auto", "deterministic", "openai")]
    [string]$Provider = "auto",
    [string]$EnvFile = ".env.agent.local",
    [string]$OutputJson = "outputs/forecast_report.json",
    [string]$OutputMarkdown = "outputs/forecast_report.md",
    [string]$BundleOutput = "outputs/prediction_context_bundle.json"
)

# The default Agent entry point is forecast-only and must not read evaluation truth.
& "$PSScriptRoot/run_agent_forecast.ps1" `
    -Risk $Risk `
    -Provider $Provider `
    -EnvFile $EnvFile `
    -OutputJson $OutputJson `
    -OutputMarkdown $OutputMarkdown `
    -BundleOutput $BundleOutput
exit $LASTEXITCODE
