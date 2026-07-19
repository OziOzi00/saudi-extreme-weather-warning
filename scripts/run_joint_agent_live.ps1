param(
    [ValidateSet("heavy_rain", "heatwave")]
    [string]$Hazard = "heavy_rain",
    [ValidateSet("development", "independent_test")]
    [string]$Split = "development",
    [string]$CaseId = "20200501_00",
    [string]$RegionId = "SA-09",
    [int]$LeadTimeHours = 48,
    [string]$AgentEnvFile = ".env.agent.local",
    [string]$Neo4jEnvFile = ".env.neo4j.local",
    [string]$Model = "",
    [string]$EscalationModel = "",
    [string]$OutputPrefix = "outputs/joint_agent_live"
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

if (-not $Model) { $Model = $env:SAUDI_WARNING_AGENT_MODEL }
if (-not $EscalationModel) { $EscalationModel = $env:SAUDI_WARNING_AGENT_ESCALATION_MODEL }

python -m saudi_warning.agent.run_joint_live_report `
    --hazard $Hazard `
    --split $Split `
    --case-id $CaseId `
    --region-id $RegionId `
    --lead-time-hours $LeadTimeHours `
    --model $Model `
    --escalation-model $EscalationModel `
    --output-json "$OutputPrefix.json" `
    --output-markdown "$OutputPrefix.md" `
    --evidence-output "$OutputPrefix.evidence.json"
exit $LASTEXITCODE
