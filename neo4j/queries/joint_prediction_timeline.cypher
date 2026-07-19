// Parameters: $hazard, $dataset_split, $case_id, $region_id
MATCH (c:JointPredictionCase {
  id: 'joint-case:' + $hazard + ':' + $dataset_split + ':' + $case_id
})-[:HAS_JOINT_WINDOW]->(w:JointForecastWindow)
  -[:CONCERNS_PREDICTION_REGION]->(g:JointPredictionRegion {region_id: $region_id})
MATCH (w)-[:USES_JOINT_RULE]->(rule:JointRule)
RETURN c.case_id AS case_id,
       g.region_id AS region_id,
       w.lead_time_hours AS lead_time_hours,
       w.base_risk_level AS base_risk_level,
       w.knowledge_triggered AS knowledge_triggered,
       w.joint_final_risk_level AS joint_final_risk_level,
       w.forecast_features_json AS forecast_features_json,
       rule.id AS selected_rule,
       w.truth_accessed AS truth_accessed
ORDER BY lead_time_hours;
