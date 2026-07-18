param(
    [string]$EnvFile = ".env.agent.local",
    [string]$Output = "outputs/heatwave_agent_research.json"
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$PWD\src"

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing local Agent environment file: $EnvFile"
}
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

python -m saudi_warning.agent.run_heatwave_research --output $Output
exit $LASTEXITCODE
