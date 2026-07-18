param(
    [string]$Risk = "handoff/risk_results/development_heavy_rain/risk_20200501_00_024_SA-09_heavy_rain.json",
    [ValidateSet("auto", "deterministic", "openai")]
    [string]$Provider = "auto",
    [string]$EnvFile = ".env.agent.local",
    [string]$OutputJson = "outputs/verification_report.json",
    [string]$OutputMarkdown = "outputs/verification_report.md"
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

# Explicit post-event verification mode; this entry may read the evaluation bundle.
python -m saudi_warning.agent.run_report `
    --risk $Risk `
    --provider $Provider `
    --mode formal `
    --output-json $OutputJson `
    --output-markdown $OutputMarkdown
exit $LASTEXITCODE
