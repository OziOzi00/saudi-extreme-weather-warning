// Parameters: $region_id
MATCH (region:Region {id: $region_id})<-[:CONCERNS]-(case:ForecastCase)
OPTIONAL MATCH (case)-[:VALID_FOR]->(event:HistoricalEvent)
RETURN region, case, event
ORDER BY case.initial_time;
