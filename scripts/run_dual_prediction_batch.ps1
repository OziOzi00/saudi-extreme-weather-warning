param(
    [string]$AgentEnvFile = ".env.agent.local",
    [string]$Neo4jEnvFile = ".env.neo4j.local",
    [string]$OutputDir = "handoff/reports/dual_prediction_batch_v1",
    [string]$RainModel = "gpt-5.6-luna",
    [string]$HeatModel = "gpt-5.6-terra",
    [string]$FallbackModel = "gpt-5.6-luna"
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "$PWD\src"

foreach ($envFile in @($AgentEnvFile, $Neo4jEnvFile)) {
    if (-not (Test-Path -LiteralPath $envFile)) {
        throw "Missing ignored local environment file: $envFile"
    }
    foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
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

python -m saudi_warning.agent.run_dual_prediction_batch `
    --output-dir $OutputDir `
    --rain-model $RainModel `
    --heat-model $HeatModel `
    --fallback-model $FallbackModel
exit $LASTEXITCODE
