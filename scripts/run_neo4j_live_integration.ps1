param(
    [string]$Neo4jHome = $env:NEO4J_HOME,
    [string]$EnvFile = ".env.neo4j.local",
    [string]$Bundle = "handoff/knowledge_graph/heavy_rain_evaluation_bundle.json"
)

$ErrorActionPreference = "Stop"

if (-not $Neo4jHome) {
    throw "Neo4jHome is required. Pass -Neo4jHome or set NEO4J_HOME."
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Missing ignored local credential file: $EnvFile"
}

$settings = Get-Content -LiteralPath $EnvFile | ConvertFrom-StringData
$env:NEO4J_URI = $settings.NEO4J_URI
$env:NEO4J_USER = $settings.NEO4J_USER
$env:NEO4J_PASSWORD = $settings.NEO4J_PASSWORD
$env:PYTHONPATH = "$PWD\src"

$cypherShell = Join-Path $Neo4jHome "bin\cypher-shell.bat"
if (-not (Test-Path -LiteralPath $cypherShell)) {
    throw "cypher-shell.bat not found under Neo4jHome: $Neo4jHome"
}

Get-Content -Raw -Encoding UTF8 "neo4j/schema.cypher" |
    & $cypherShell -a $env:NEO4J_URI -u $env:NEO4J_USER -p $env:NEO4J_PASSWORD

# Import twice: the second pass proves the MERGE strategy is idempotent.
python -m saudi_warning.knowledge_graph.load_neo4j --bundle $Bundle
python -m saudi_warning.knowledge_graph.load_neo4j --bundle $Bundle
python -m saudi_warning.knowledge_graph.verify_neo4j --bundle $Bundle
