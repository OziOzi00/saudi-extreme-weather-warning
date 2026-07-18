(() => {
  const data = window.DASHBOARD_DATA;
  if (!data) throw new Error("Dashboard data is missing. Run the data builder first.");
  const $ = (id) => document.getElementById(id);
  const caseSelect = $("case-select");
  const leadSelect = $("lead-select");
  let scenario = "success";
  let statusTimer;

  const levelZh = { low: "低", medium: "中", high: "高" };
  const splitZh = { development: "development（开发集）", independent_test: "independent_test（独立集）" };
  const fmt = (n, digits = 2) => Number(n).toFixed(digits).replace(/\.00$/, "");
  const date = (iso) => new Date(iso).toLocaleString("zh-CN", { timeZone: "UTC", hour12: false });
  const currentRisk = () => data.risks.find(r => r.risk_id === leadSelect.value);

  function notify(message) {
    const status = $("export-status");
    status.textContent = message;
    status.classList.add("show");
    clearTimeout(statusTimer);
    statusTimer = setTimeout(() => status.classList.remove("show"), 2600);
  }

  function downloadBlob(blob, filename) {
    const link = document.createElement("a");
    const url = URL.createObjectURL(blob);
    link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

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
    const row = currentRisk();
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

  function exportSummary() {
    const row = currentRisk();
    if (!row) return;
    const miss = scenario === "miss"
      ? data.known_miss.records.find(x => Number(x.lead_time_hours) === row.lead_time_hours)
      : null;
    const evidence = items => items.length
      ? items.map(item => `- ${evidenceText(item)}`).join("\n")
      : "- 无";
    const missSection = miss ? `\n## 已知漏报归因\n\n- 观测区域 P95：${fmt(miss.observed_spatial_p95_mm)} mm\n- 预报区域 P95：${fmt(miss.forecast_spatial_p95_mm)} mm\n- 主要归因：${miss.primary_attribution}\n- 次要归因：${miss.secondary_attribution || "无"}\n- 边界：${data.known_miss.scope_note}\n` : "";
    const markdown = `# 沙特极端天气风险案例摘要\n\n` +
      `- 场景：${scenario === "success" ? "独立测试命中案例" : "已知影响事件漏报"}\n` +
      `- 案例：${row.case_id}\n- 区域：${row.region_name}（${row.region_id}）\n` +
      `- 预报时效：+${row.lead_time_hours} h\n- 风险等级：${levelZh[row.risk_level]}风险\n` +
      `- 规则状态：${row.rule_status}\n- 数据分区：${row.dataset_split}\n` +
      `- 有效窗口：${row.valid_start_time} — ${row.valid_end_time}\n` +
      `- 区域降水 P95：${fmt(row.summary.precip_spatial_p95_mm)} mm\n` +
      `- 中/高阈值：${fmt(row.summary.precip_medium_threshold_mm)} / ${fmt(row.summary.precip_high_threshold_mm)} mm\n\n` +
      `## 支持证据\n\n${evidence(row.supporting_evidence)}\n\n` +
      `## 不支持证据\n\n${evidence(row.contradicting_evidence)}\n${missSection}\n` +
      `## 使用边界\n\n${data.meta.disclaimer} 本摘要由版本化仓库产物生成，不得解释为官方预警。\n\n` +
      `来源：\`${row.source_path}\`\n`;
    downloadBlob(new Blob([markdown], { type: "text/markdown;charset=utf-8" }), `${row.case_id}_${row.region_id}_案例摘要.md`);
    notify("案例摘要已生成");
  }

  function roundedRect(ctx, x, y, width, height, radius) {
    ctx.beginPath();
    ctx.roundRect(x, y, width, height, radius);
    ctx.fill();
  }

  function drawWrapped(ctx, text, x, y, maxWidth, lineHeight, maxLines = 3) {
    const chars = [...text];
    let line = "", lines = [];
    chars.forEach(char => {
      const next = line + char;
      if (ctx.measureText(next).width > maxWidth && line) { lines.push(line); line = char; }
      else line = next;
    });
    if (line) lines.push(line);
    lines.slice(0, maxLines).forEach((value, index) => ctx.fillText(value, x, y + index * lineHeight));
    return y + Math.min(lines.length, maxLines) * lineHeight;
  }

  async function exportPng() {
    const row = currentRisk();
    if (!row) return;
    notify("正在生成答辩图…");
    const canvas = document.createElement("canvas");
    canvas.width = 1600; canvas.height = 900;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#f5f1e8"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#123832"; ctx.fillRect(0, 0, canvas.width, 150);
    ctx.fillStyle = "#9ad5ca"; ctx.font = "700 18px Microsoft YaHei, sans-serif";
    ctx.fillText("GRAPHCAST → MAZU-LIKE · RESEARCH PROTOTYPE", 64, 45);
    ctx.fillStyle = "#fffdfa"; ctx.font = "700 44px Microsoft YaHei, sans-serif";
    ctx.fillText("沙特极端天气风险案例", 64, 105);
    ctx.font = "500 21px Microsoft YaHei, sans-serif";
    ctx.fillText(`${row.case_id} · ${row.region_name} · +${row.lead_time_hours} h`, 920, 92);

    const svg = $("saudi-map").cloneNode(true);
    svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    svg.querySelectorAll(".region").forEach(path => {
      const selected = path.dataset.region === row.region_id;
      const colors = { low: "#99aaa3", medium: "#e8c982", high: "#b84435" };
      path.setAttribute("fill", selected ? colors[row.risk_level] : "#d7ded9");
      path.setAttribute("stroke", "#fffdfa"); path.setAttribute("stroke-width", "2");
    });
    const svgBlob = new Blob([new XMLSerializer().serializeToString(svg)], { type: "image/svg+xml;charset=utf-8" });
    const svgUrl = URL.createObjectURL(svgBlob);
    const image = new Image(); image.src = svgUrl;
    await image.decode();
    ctx.fillStyle = "#eaf2ee"; roundedRect(ctx, 48, 185, 820, 640, 24);
    ctx.drawImage(image, 68, 205, 780, 575); URL.revokeObjectURL(svgUrl);
    ctx.fillStyle = "#173b35"; ctx.font = "700 26px Microsoft YaHei, sans-serif";
    ctx.fillText(`${row.region_name} · ${row.region_id}`, 82, 785);
    const levelColors = { low: "#64716d", medium: "#a96314", high: "#b84435" };
    ctx.fillStyle = levelColors[row.risk_level]; ctx.fillText(`${levelZh[row.risk_level]}风险`, 690, 785);

    ctx.fillStyle = "#fffdfa"; roundedRect(ctx, 905, 185, 647, 640, 24);
    ctx.fillStyle = "#0b6b62"; ctx.font = "700 18px Microsoft YaHei, sans-serif"; ctx.fillText("判定与证据链", 950, 235);
    ctx.fillStyle = levelColors[row.risk_level]; ctx.font = "700 46px Microsoft YaHei, sans-serif";
    ctx.fillText(`${levelZh[row.risk_level]}风险`, 950, 300);
    ctx.fillStyle = "#64716d"; ctx.font = "500 18px Microsoft YaHei, sans-serif";
    ctx.fillText(`有效窗口  ${row.valid_start_time.slice(0, 10)} — ${row.valid_end_time.slice(0, 10)} UTC`, 950, 350);
    ctx.fillText(`区域降水 P95  ${fmt(row.summary.precip_spatial_p95_mm)} mm`, 950, 385);
    ctx.fillText(`中 / 高阈值  ${fmt(row.summary.precip_medium_threshold_mm)} / ${fmt(row.summary.precip_high_threshold_mm)} mm`, 950, 420);
    ctx.fillStyle = "#172522"; ctx.font = "700 19px Microsoft YaHei, sans-serif"; ctx.fillText("主要支持证据", 950, 475);
    ctx.font = "500 17px Microsoft YaHei, sans-serif";
    let y = 510;
    row.supporting_evidence.slice(0, 4).forEach(item => {
      ctx.fillStyle = "#0b6b62"; ctx.fillText("●", 950, y);
      ctx.fillStyle = "#394743"; y = drawWrapped(ctx, evidenceText(item), 980, y, 520, 25, 2) + 9;
    });
    if (scenario === "miss") {
      ctx.fillStyle = "#b84435"; ctx.font = "700 17px Microsoft YaHei, sans-serif";
      drawWrapped(ctx, "已知影响事件漏报：此视图用于误差归因，不代表独立测试性能。", 950, 760, 530, 25, 2);
    }
    ctx.fillStyle = "#64716d"; ctx.font = "500 16px Microsoft YaHei, sans-serif";
    ctx.fillText("研究原型 · 不构成官方气象预警 · 边界年份 2017", 64, 867);
    const png = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
    if (!png) throw new Error("PNG generation failed");
    downloadBlob(png, `${row.case_id}_${row.region_id}_答辩图.png`);
    notify("答辩图 PNG 已生成");
  }

  document.querySelectorAll(".scenario").forEach(button => button.addEventListener("click", () => {
    document.querySelectorAll(".scenario").forEach(x => x.classList.remove("active"));
    button.classList.add("active"); scenario = button.dataset.scenario; populateCases();
  }));
  caseSelect.addEventListener("change", populateLeads); leadSelect.addEventListener("change", render);
  $("export-summary").addEventListener("click", exportSummary);
  $("export-png").addEventListener("click", () => exportPng().catch(error => {
    console.error(error); notify("PNG 生成失败，请查看浏览器控制台");
  }));
  drawMap(); renderMetrics(); populateCases();
})();
