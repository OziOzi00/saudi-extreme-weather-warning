// Parameters: $risk_id
MATCH (risk:RiskAssessment {id: $risk_id})
OPTIONAL MATCH (risk)-[:BASED_ON]->(case:ForecastCase)
OPTIONAL MATCH (risk)-[:CONCERNS]->(region:Region)
OPTIONAL MATCH (risk)-[:EVALUATED_BY]->(rule:Rule)
RETURN risk, case, region, rule;
