param(
    [Parameter(Mandatory = $true)][string]$RunId,
    [Parameter(Mandatory = $true)][string]$CaseId,
    [Parameter(Mandatory = $true)][string]$InitialTime,
    [Parameter(Mandatory = $true)][ValidateSet("heavy_rain", "heatwave")][string]$Hazard,
    [Parameter(Mandatory = $true)][string[]]$RegionId,
    [int]$FocusLeadTimeHours = 48,
    [string]$Model = "",
    [string]$EscalationModel = "",
    [string]$AgentEnvFile = ".env.agent.local",
    [string]$Neo4jEnvFile = ".env.neo4j.local"
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

$arguments = @(
    "-m", "saudi_warning.orchestration.run_workflow",
    "--run-id", $RunId,
    "--case-id", $CaseId,
    "--initial-time", $InitialTime,
    "--hazard", $Hazard,
    "--focus-lead-time-hours", $FocusLeadTimeHours
)
foreach ($region in $RegionId) {
    $arguments += @("--region-id", $region)
}
if ($Model) {
    $arguments += @("--model", $Model)
}
if ($EscalationModel) {
    $arguments += @("--escalation-model", $EscalationModel)
}
python @arguments
exit $LASTEXITCODE
