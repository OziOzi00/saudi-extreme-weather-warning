// Parameters: $case_id
MATCH (c:ForecastCase {id: $case_id})
OPTIONAL MATCH (c)-[:VALID_FOR]->(event:HistoricalEvent)
OPTIONAL MATCH (c)-[:CONCERNS]->(region:Region)
OPTIONAL MATCH (event)-[evaluation:EVALUATED_BY]->(evidence:Evidence)
RETURN c, event, collect(DISTINCT region) AS regions,
       collect(DISTINCT {evaluation: evaluation, evidence: evidence}) AS impact_evidence;
