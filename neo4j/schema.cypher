// Neo4j 5.x constraints for the member-C development graph.
CREATE CONSTRAINT region_id IF NOT EXISTS FOR (n:Region) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT forecast_case_id IF NOT EXISTS FOR (n:ForecastCase) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT historical_event_id IF NOT EXISTS FOR (n:HistoricalEvent) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT risk_assessment_id IF NOT EXISTS FOR (n:RiskAssessment) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT rule_id IF NOT EXISTS FOR (n:Rule) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.id IS UNIQUE;
