(() => {
  const data = window.DASHBOARD_DATA;
  if (!data) throw new Error("Dashboard data is missing. Run the data builder first.");
  const $ = (id) => document.getElementById(id);
  const caseSelect = $("case-select");
  const leadSelect = $("lead-select");
  let scenario = "success";

  const levelZh = { low: "低", medium: "中", high: "高" };
  const splitZh = { development: "development（开发集）", independent_test: "independent_test（独立集）" };
  const fmt = (n, digits = 2) => Number(n).toFixed(digits).replace(/\.00$/, "");
  const date = (iso) => new Date(iso).toLocaleString("zh-CN", { timeZone: "UTC", hour12: false });

  function polygons(geometry) {
    return geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  }

  function drawMap() {
    const svg = $("saudi-map");
    const all = data.regions.flatMap(r => polygons(r.geometry).flatMap(p => p.flatMap(ring => ring)));
    const xs = all.map(p => p[0]), ys = all.map(p => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const project = ([x, y]) => [55 + (x - minX) / (maxX - minX) * 650, 520 - (y - minY) / (maxY - minY) * 470];
    data.regions.forEach(region => {
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      polygons(region.geometry).forEach(poly => {
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        const d = poly.map(ring => ring.map((p, i) => `${i ? "L" : "M"}${project(p).join(" ")}`).join(" ") + " Z").join(" ");
        path.setAttribute("d", d); path.setAttribute("class", "region");
        path.setAttribute("data-region", region.region_id); path.setAttribute("tabindex", "0");
        path.setAttribute("aria-label", `${region.region_name} ${region.region_id}`);
        group.appendChild(path);
      });
      svg.appendChild(group);
    });
  }

  function availableCases() {
    const filter = scenario === "success"
      ? r => r.dataset_split === "independent_test" && r.region_id === "SA-14" && r.case_id.startsWith("20200725_00")
      : r => r.dataset_split === "development" && r.region_id === data.known_miss.region_id && r.case_id.startsWith(data.known_miss.case);
    return data.risks.filter(filter);
  }

  function populateCases() {
    const risks = availableCases();
    const keys = [...new Set(risks.map(r => `${r.case_id.slice(0, 11)}|${r.region_id}`))];
    caseSelect.innerHTML = keys.map(key => {
      const [caseId, regionId] = key.split("|");
      const region = data.regions.find(r => r.region_id === regionId);
      return `<option value="${key}">${caseId} · ${region.region_name}</option>`;
    }).join("");
    populateLeads();
  }

  function populateLeads() {
    const [caseId, regionId] = caseSelect.value.split("|");
    const rows = availableCases().filter(r => r.case_id.startsWith(caseId) && r.region_id === regionId);
    leadSelect.innerHTML = rows.map(r => `<option value="${r.risk_id}">+${r.lead_time_hours} h</option>`).join("");
    if (scenario === "success" && rows.some(r => r.lead_time_hours === 72)) leadSelect.value = rows.find(r => r.lead_time_hours === 72).risk_id;
    render();
  }

  const evidenceText = e => `${e.indicator} · ${e.metric}: ${fmt(e.value)} ${e.unit || ""} ${e.comparison} ${fmt(e.threshold)}`;
  function render() {
    const row = data.risks.find(r => r.risk_id === leadSelect.value);
    if (!row) return;
    document.querySelectorAll(".region").forEach(path => {
      path.classList.remove("selected", "low", "medium", "high");
      if (path.dataset.region === row.region_id) path.classList.add("selected", row.risk_level);
    });
    $("map-region").textContent = `${row.region_name} · ${row.region_id}`;
    $("map-level").textContent = `${levelZh[row.risk_level]}风险`;
    $("risk-level").textContent = `${levelZh[row.risk_level]}风险`;
    $("confidence").textContent = row.confidence === "medium" ? "中" : row.confidence;
    $("rule-badge").textContent = row.rule_status === "frozen" ? "规则已冻结" : row.rule_status;
    $("valid-window").textContent = `${date(row.valid_start_time)} — ${date(row.valid_end_time)} UTC`;
    $("dataset-split").textContent = splitZh[row.dataset_split];
    $("precip-value").textContent = `${fmt(row.summary.precip_spatial_p95_mm)} mm`;
    $("precip-threshold").textContent = `中 ${fmt(row.summary.precip_medium_threshold_mm)} / 高 ${fmt(row.summary.precip_high_threshold_mm)} mm`;
    $("support-list").innerHTML = row.supporting_evidence.map(e => `<li>${evidenceText(e)}</li>`).join("") || "<li>无</li>";
    $("against-list").innerHTML = row.contradicting_evidence.map(e => `<li>${evidenceText(e)}</li>`).join("") || "<li>无</li>";
    $("source-path").textContent = row.source_path;
    const miss = $("miss-box");
    if (scenario === "miss") {
      const record = data.known_miss.records.find(x => Number(x.lead_time_hours) === row.lead_time_hours);
      miss.classList.remove("hidden");
      miss.innerHTML = `<strong>为何这是已知漏报？</strong><br>${record ? `观测 P95 ${fmt(record.observed_spatial_p95_mm)} mm，预报 P95 ${fmt(record.forecast_spatial_p95_mm)} mm；主要归因为 ${record.primary_attribution}。` : "该案例属于已知影响事件，但当前时效未达到中风险阈值。"}<br><em>${data.known_miss.scope_note}</em>`;
    } else miss.classList.add("hidden");
  }

  function renderMetrics() {
    const rain = data.evaluation.heavy_rain, heat = data.evaluation.heatwave;
    $("disclaimer").textContent = data.meta.disclaimer;
    $("rain-score").textContent = `${rain.hits} / ${rain.misses} / ${rain.false_alarms}`;
    $("heat-score").textContent = `${heat.candidate_hits} / ${heat.target_windows}`;
    $("graph-score").textContent = `${data.evaluation.knowledge_graph.nodes} / ${data.evaluation.knowledge_graph.relationships}`;
    $("rain-confusion").textContent = `${rain.hits} 命中 · ${rain.misses} 漏报 · ${rain.false_alarms} 空报 · ${rain.correct_negatives} 正确否定`;
    $("heat-recall").textContent = `${heat.candidate_hits} / ${heat.target_windows}`;
    $("heat-note").textContent = `偏差订正 +${fmt(heat.bias_correction_degc, 3)} °C；事件案例检出 3/${heat.event_cases}，对照窗正确否定 ${heat.controls_rejected}/${heat.controls}。当前仅为开发集证据。`;
    const impact = data.evaluation.impact;
    $("impact-score").textContent = `${impact.detected_positive_units} / ${impact.eligible_positive_units}`;
  }

  document.querySelectorAll(".scenario").forEach(button => button.addEventListener("click", () => {
    document.querySelectorAll(".scenario").forEach(x => x.classList.remove("active"));
    button.classList.add("active"); scenario = button.dataset.scenario; populateCases();
  }));
  caseSelect.addEventListener("change", populateLeads); leadSelect.addEventListener("change", render);
  drawMap(); renderMetrics(); populateCases();
})();
