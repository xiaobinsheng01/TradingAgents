const REPORT_TITLES = {
  swing_tape: "价量 Tape",
  market_report: "Market",
  sentiment_report: "Sentiment",
  news_report: "News",
  fundamentals_report: "Fundamentals",
  investment_plan: "Research",
  trader_investment_plan: "Trader",
  final_trade_decision: "Portfolio",
  complete_report: "完整报告",
};

let options = null;
let reports = {};
let currentView = "full";
const TAPE_ANALYSTS = ["market", "news", "fundamentals"];
const QUOTE_UP = "#e5484d";
const QUOTE_DOWN = "#16a36a";

function $(id) {
  return document.getElementById(id);
}

function setHidden(id, hidden) {
  $(id).classList.toggle("hidden", hidden);
}

function fillSelect(el, items, valueKey, labelKey, current) {
  el.innerHTML = "";
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = String(item[valueKey]);
    opt.textContent = item[labelKey];
    el.appendChild(opt);
  }
  if (current != null && [...el.options].some((o) => o.value === String(current))) {
    el.value = String(current);
  }
}

function selectedAnalysts() {
  return [...document.querySelectorAll("#analysts input:checked:not(:disabled)")].map(
    (el) => el.value
  );
}

function switchView(view) {
  currentView = view;
  for (const name of ["full", "tape", "screen", "index", "trend", "tomorrow-rise"]) {
    $(`view-${name}`).classList.toggle("active", view === name);
  }
  $("tape-hint").classList.toggle("hidden", view !== "tape");
  $("screen-view").classList.toggle("hidden", view !== "screen");
  $("index-view").classList.toggle("hidden", view !== "index");
  $("trend-view").classList.toggle("hidden", view !== "trend");
  $("tomorrow-rise-view").classList.toggle("hidden", view !== "tomorrow-rise");
  $("console-layout").classList.toggle(
    "hidden",
    view === "screen" || view === "index" || view === "trend" || view === "tomorrow-rise"
  );
  $("run-btn").textContent = view === "tape" ? "开始价量分析" : "开始分析";
  if (view === "tape") {
    document.querySelectorAll("#analysts input").forEach((el) => {
      el.checked = TAPE_ANALYSTS.includes(el.value) && !el.disabled;
    });
    $("ingest_news").checked = true;
  }
}

function isCryptoTicker(ticker) {
  const upper = ticker.trim().toUpperCase();
  return (options.crypto_suffixes || []).some((suffix) =>
    upper.endsWith(String(suffix).toUpperCase())
  );
}

function syncAnalystAvailability() {
  const crypto = isCryptoTicker($("ticker").value);
  document.querySelectorAll("#analysts input").forEach((el) => {
    if (el.value === "fundamentals") {
      el.disabled = crypto;
      if (crypto) el.checked = false;
    }
  });
}

function ensureModelOption(items, id) {
  if (!id || items.some((m) => m.id === id)) {
    return items;
  }
  return [{ id, label: id }, ...items];
}

function refreshModels() {
  const provider = $("llm_provider").value;
  const catalog = (options.models[provider] || { quick: [], deep: [] });
  const defaults = options.defaults;
  const quick = ensureModelOption(catalog.quick || [], defaults.shallow_thinker);
  const deep = ensureModelOption(catalog.deep || [], defaults.deep_thinker);
  fillSelect($("shallow_thinker"), quick, "id", "label", defaults.shallow_thinker);
  fillSelect($("deep_thinker"), deep, "id", "label", defaults.deep_thinker);
  onModelChange("shallow");
  onModelChange("deep");
  const meta = options.providers.find((p) => p.key === provider);
  $("key-status").textContent = meta?.key_env
    ? (meta.key_configured
      ? `${meta.key_env} 已在环境中配置`
      : `${meta.key_env} 未设置，请写进本机 .env`)
    : "该供应商不需要 API key";
  $("key-status").className = "hint " + (meta?.key_configured ? "ok" : "warn");
  if (meta?.default_url) {
    $("backend_url").value = meta.default_url;
  }
  setHidden("google-wrap", provider !== "google");
  setHidden("openai-wrap", provider !== "openai" && provider !== "azure");
  setHidden("anthropic-wrap", provider !== "anthropic");
}

function onModelChange(which) {
  const select = which === "shallow" ? $("shallow_thinker") : $("deep_thinker");
  setHidden(`${which}-custom-wrap`, select.value !== "custom");
}

function modelValue(which) {
  const select = which === "shallow" ? $("shallow_thinker") : $("deep_thinker");
  if (select.value === "custom") {
    return $(`${which}_custom`).value.trim();
  }
  return select.value;
}

function renderAgents(status) {
  const ul = $("agents");
  ul.innerHTML = "";
  for (const [name, state] of Object.entries(status || {})) {
    const li = document.createElement("li");
    li.innerHTML = `<span>${name}</span><span class="status-${state}">${state}</span>`;
    ul.appendChild(li);
  }
}

function appendLog(text) {
  const item = document.createElement("li");
  item.textContent = text;
  $("log").prepend(item);
}

function showReports() {
  const tabs = $("report-tabs");
  tabs.innerHTML = "";
  const keys = Object.keys(reports);
  keys.forEach((key, index) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = REPORT_TITLES[key] || key;
    btn.className = index === 0 ? "active" : "";
    btn.addEventListener("click", () => {
      [...tabs.children].forEach((el) => el.classList.remove("active"));
      btn.classList.add("active");
      $("report-body").textContent = reports[key] || "";
    });
    tabs.appendChild(btn);
  });
  if (keys.length) {
    $("report-body").textContent = reports[keys[0]];
  }
}

function handleEvent(event) {
  if (event.notice) {
    $("notice").textContent = event.notice;
  }
  if (event.agents) {
    renderAgents(event.agents);
  }
  if (event.stats) {
    const s = event.stats;
    $("stats").textContent = `LLM ${s.llm_calls || 0} · Tools ${s.tool_calls || 0} · Tokens ${s.tokens_in || 0}/${s.tokens_out || 0}`;
  }
  if (event.type === "message") {
    appendLog(`${event.message_type}: ${String(event.content || "").slice(0, 240)}`);
  }
  if (event.type === "tool") {
    appendLog(`tool ${event.name}`);
  }
  if (event.type === "report" && event.section) {
    reports[event.section] = event.content;
    showReports();
  }
  if (event.type === "complete") {
    reports = event.reports || reports;
    $("decision").textContent = event.decision || "";
    showReports();
    appendLog(event.wall_time_summary || "complete");
  }
  if (event.type === "error") {
    $("form-error").hidden = false;
    $("form-error").textContent = event.message || "run failed";
  }
}

async function readSse(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const chunks = buf.split("\n\n");
    buf = chunks.pop();
    for (const chunk of chunks) {
      const data = chunk
        .split("\n")
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6))
        .join("");
      if (!data) continue;
      handleEvent(JSON.parse(data));
    }
  }
}

async function onSubmit(event) {
  event.preventDefault();
  $("form-error").hidden = true;
  $("run-btn").disabled = true;
  reports = {};
  $("log").innerHTML = "";
  $("decision").textContent = "";
  const payload = {
    ticker: $("ticker").value.trim(),
    analysis_date: $("analysis_date").value,
    output_language: $("output_language").value,
    analysts: selectedAnalysts(),
    research_depth: Number($("research_depth").value),
    llm_provider: $("llm_provider").value,
    shallow_thinker: modelValue("shallow"),
    deep_thinker: modelValue("deep"),
    backend_url: $("backend_url").value.trim() || null,
    google_thinking_level: $("google_thinking_level").value || null,
    openai_reasoning_effort: $("openai_reasoning_effort").value || null,
    anthropic_effort: $("anthropic_effort").value || null,
    checkpoint: $("checkpoint").checked,
    ingest_news: $("ingest_news").checked,
    swing_tape_window: $("swing_tape_window").value,
  };
  if (currentView === "tape") {
    payload.analysts = TAPE_ANALYSTS.filter((key) =>
      [...document.querySelectorAll("#analysts input")].some(
        (el) => el.value === key && !el.disabled
      )
    );
    if (!payload.analysts.includes("market")) {
      payload.analysts.unshift("market");
    }
    if (!payload.analysts.includes("news")) {
      payload.analysts.push("news");
    }
    payload.ingest_news = true;
    $("ingest_news").checked = true;
  }
  try {
    const res = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(payload),
    });
    if (res.status === 409) {
      throw new Error("已有一次分析在跑，请等它结束。");
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const detail = body.detail;
      const message = Array.isArray(detail)
        ? detail.map((item) => item.msg || JSON.stringify(item)).join("; ")
        : (detail || res.statusText);
      throw new Error(message);
    }
    await readSse(res);
  } catch (err) {
    $("form-error").hidden = false;
    $("form-error").textContent = err.message || String(err);
  } finally {
    $("run-btn").disabled = false;
  }
}

async function onLatest() {
  $("form-error").hidden = true;
  $("latest-btn").disabled = true;
  try {
    const res = await fetch("/api/runs/latest");
    if (res.status === 404) {
      const body = await res.json().catch(() => ({}));
      $("report-body").innerHTML =
        `<p class="hint">${body.detail || "还没有落盘的分析。先跑一次「开始分析」。"}</p>`;
      $("decision").textContent = "";
      $("report-tabs").innerHTML = "";
      return;
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || res.statusText);
    }
    const data = await res.json();
    reports = data.reports || {};
    $("decision").textContent = data.decision || "";
    const when = data.analysis_date || data.generated_at || "";
    $("notice").textContent =
      `最近一次：${data.ticker || ""} ${when} · 研究评级，永不下单`;
    showReports();
    if (!Object.keys(reports).length) {
      $("report-body").innerHTML = `<p class="hint">最近一次已找到，但报告正文为空。</p>`;
    }
  } catch (err) {
    $("form-error").hidden = false;
    $("form-error").textContent = err.message || String(err);
  } finally {
    $("latest-btn").disabled = false;
  }
}

function fmtNum(value, digits) {
  if (value == null || value === "") return "不可用";
  const n = Number(value);
  if (!Number.isFinite(n)) return "不可用";
  return n.toFixed(digits);
}

function fmtSigned(value, digits) {
  const text = fmtNum(value, digits);
  if (text === "不可用") return text;
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return text;
  return `+${text}`;
}

function quoteClass(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "num flat";
  return n > 0 ? "num up" : "num down";
}

function fillRow(tr, cells) {
  for (const cell of cells) {
    const td = document.createElement("td");
    td.textContent = cell.text == null ? "" : String(cell.text);
    if (cell.cls) td.className = cell.cls;
    tr.appendChild(td);
  }
}

function mountCandleChart(el) {
  const lwc = LightweightCharts;
  const chart = lwc.createChart(el, {
    autoSize: true,
    layout: {
      background: { type: "solid", color: "#0e131b" },
      textColor: "#8b98ab",
      fontFamily: '"SF Mono", "Menlo", "PingFang SC", ui-monospace, sans-serif',
    },
    grid: {
      vertLines: { color: "rgba(42,51,68,0.7)" },
      horzLines: { color: "rgba(42,51,68,0.7)" },
    },
    rightPriceScale: { borderColor: "#2a3344" },
    timeScale: { borderColor: "#2a3344" },
    crosshair: {
      vertLine: { color: "rgba(230,237,245,0.28)", labelBackgroundColor: "#243044" },
      horzLine: { color: "rgba(230,237,245,0.28)", labelBackgroundColor: "#243044" },
    },
  });
  const candles = chart.addSeries(lwc.CandlestickSeries, {
    upColor: QUOTE_UP,
    downColor: QUOTE_DOWN,
    borderUpColor: QUOTE_UP,
    borderDownColor: QUOTE_DOWN,
    wickUpColor: QUOTE_UP,
    wickDownColor: QUOTE_DOWN,
  });
  const volume = chart.addSeries(lwc.HistogramSeries, { priceFormat: { type: "volume" } }, 1);
  const panes = chart.panes();
  if (panes[1]) panes[1].setHeight(88);
  lwc.createTextWatermark(panes[0], {
    horzAlign: "center",
    vertAlign: "center",
    lines: [{ text: "研究 · 不下单", color: "rgba(230,237,245,0.12)", fontSize: 28 }],
  });
  return { chart, candles, volume };
}

function volumeColor(bar) {
  return bar.close >= bar.open ? "rgba(229,72,77,0.5)" : "rgba(22,163,106,0.5)";
}

function fmtMoney(value) {
  if (value == null || value === "") return "不可用";
  const n = Number(value);
  if (!Number.isFinite(n)) return "不可用";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(2)} 亿`;
  if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(2)} 万`;
  return `${sign}${abs.toFixed(0)}`;
}

function fmtYi(value) {
  if (value == null || value === "") return "不可用";
  const n = Number(value);
  if (!Number.isFinite(n)) return "不可用";
  return `${(n / 1e8).toFixed(2)} 亿`;
}

let screenChart = null;
let screenCandles = null;
let screenVolume = null;
let selectedScreenTicker = null;

function ensureScreenChart() {
  if (screenChart) return true;
  if (!window.LightweightCharts) return false;
  const el = $("screen-chart");
  ({ chart: screenChart, candles: screenCandles, volume: screenVolume } = mountCandleChart(el));
  return true;
}

function paintScreenBars(payload) {
  if (!ensureScreenChart()) {
    $("screen-chart-note").textContent = "图表库没有加载。";
    return;
  }
  const candles = [];
  const volume = [];
  for (const bar of payload.bars || []) {
    if (!bar || !bar.time || bar.open == null || bar.high == null || bar.low == null || bar.close == null) {
      continue;
    }
    candles.push({
      time: bar.time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    });
    if (bar.volume != null) {
      volume.push({
        time: bar.time,
        value: bar.volume,
        color: volumeColor(bar),
      });
    }
  }
  screenCandles.setData(candles);
  screenVolume.setData(volume);
  if (candles.length) {
    screenChart.timeScale().fitContent();
    $("screen-chart-note").textContent = payload.note || "日K用于观察，不是委托。";
  } else {
    $("screen-chart-note").textContent = "没有可画的日K。";
  }
}

async function loadScreenChart(ticker, name) {
  selectedScreenTicker = ticker;
  $("ticker").value = ticker;
  syncAnalystAvailability();
  $("screen-open-full").disabled = false;
  $("screen-chart-title").textContent = `${name || ""} ${ticker}`.trim();
  $("screen-chart-note").textContent = "正在读取日K…";
  try {
    const res = await fetch(`/api/screen/bars?ticker=${encodeURIComponent(ticker)}`);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(body.detail || res.statusText);
    }
    if (selectedScreenTicker !== ticker) return;
    paintScreenBars(body);
  } catch (err) {
    if (selectedScreenTicker !== ticker) return;
    $("screen-chart-note").textContent = err.message || String(err);
  }
}

function renderScreen(data) {
  const amount = data.market_amount_yuan;
  const amountText =
    amount == null ? "成交额不可用" : `两市成交约 ${(Number(amount) / 1e12).toFixed(2)} 万亿`;
  const premium =
    data.prev_zt_premium == null ? "不可用" : `${fmtNum(data.prev_zt_premium, 2)}%`;
  const rows = data.rows || [];
  const rowText = rows.length ? `主板前排 ${rows.length} 只。` : "";
  $("screen-summary").textContent =
    `${data.as_of} · ${data.regime_label || "容错未知"} · ${amountText} · 昨日涨停溢价 ${premium} · ` +
    `涨停 ${data.limit_up_count ?? "不可用"} / 跌停 ${data.limit_down_count ?? "不可用"}。${rowText}${data.note || ""}`;
  const body = document.querySelector("#screen-table tbody");
  body.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    const emptyText = data.quote_source
      ? "今天没有进入观察区的沪深主板前排。"
      : "现货榜没有返回，不能列出主板前排。";
    tr.innerHTML = `<td colspan="20">${emptyText}</td>`;
    body.appendChild(tr);
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.title = row.t1_reason || "";
    if (row.ticker === selectedScreenTicker) tr.classList.add("active");
    fillRow(tr, [
      { text: row.ticker, cls: "ticker" },
      { text: row.name },
      { text: (row.sources || []).join(" / ") },
      { text: row.sector || "—" },
      { text: fmtPct(row.pct_chg), cls: quoteClass(row.pct_chg) },
      { text: fmtPct(row.speed), cls: quoteClass(row.speed) },
      { text: fmtPct(row.pct_5m), cls: quoteClass(row.pct_5m) },
      { text: fmtPct(row.turnover), cls: "num" },
      { text: fmtNum(row.volume_ratio, 2), cls: "num" },
      { text: fmtYi(row.amount), cls: "num" },
      { text: fmtPct(row.amplitude), cls: "num" },
      { text: fmtYi(row.float_mv), cls: "num" },
      { text: row.summary || row.t1_bias, cls: biasClass(row.t1_bias) },
      { text: fmtMoney(row.lhb_net_buy), cls: quoteClass(row.lhb_net_buy) },
      { text: row.top_buy || "不可用" },
      { text: row.top_sell || "不可用" },
      { text: row.seat_side || "不可用" },
      { text: row.holder_flow || "不可用" },
      { text: row.margin_flow || "不可用" },
      { text: row.short_flow || "不可用" },
    ]);
    tr.addEventListener("click", () => {
      document.querySelectorAll("#screen-table tbody tr").forEach((item) => {
        item.classList.remove("active");
      });
      tr.classList.add("active");
      loadScreenChart(row.ticker, row.name);
    });
    body.appendChild(tr);
  }
}

function fmtPct(value) {
  const text = fmtSigned(value, 2);
  return text === "不可用" ? text : `${text}%`;
}

function biasClass(bias) {
  if (bias === "BUY") return "bias-buy";
  if (bias === "SELL") return "bias-sell";
  if (bias === "HOLD") return "bias-hold";
  return "";
}

let indexChart = null;
let indexCandles = null;
let indexVolume = null;
let selectedIndexSymbol = null;

function ensureIndexChart() {
  if (indexChart) return true;
  if (!window.LightweightCharts) return false;
  const el = $("index-chart");
  ({ chart: indexChart, candles: indexCandles, volume: indexVolume } = mountCandleChart(el));
  return true;
}

function paintIndexBars(payload) {
  if (!ensureIndexChart()) {
    $("index-chart-note").textContent = "图表库没有加载。";
    return;
  }
  const candles = [];
  const volume = [];
  for (const bar of payload.bars || []) {
    if (!bar || !bar.time || bar.open == null || bar.high == null || bar.low == null || bar.close == null) {
      continue;
    }
    candles.push({
      time: bar.time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    });
    if (bar.volume != null) {
      volume.push({
        time: bar.time,
        value: bar.volume,
        color: volumeColor(bar),
      });
    }
  }
  indexCandles.setData(candles);
  indexVolume.setData(volume);
  if (candles.length) {
    indexChart.timeScale().fitContent();
    $("index-chart-note").textContent = payload.note || "日K用于观察指数，不是委托。";
  } else {
    $("index-chart-note").textContent = "没有可画的日K。";
  }
}

async function loadIndexChart(symbol, name) {
  selectedIndexSymbol = symbol;
  $("index-chart-title").textContent = `${name || ""} ${symbol}`.trim();
  $("index-chart-note").textContent = "正在读取日K…";
  try {
    const res = await fetch(`/api/index-outlook/bars?symbol=${encodeURIComponent(symbol)}`);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || res.statusText);
    paintIndexBars(body);
  } catch (err) {
    $("index-chart-note").textContent = err.message || String(err);
  }
}

function renderIndex(data) {
  const amount = data.market_amount_yuan;
  const amountText =
    amount == null ? "两市成交额不可用" : `两市成交约 ${(Number(amount) / 1e12).toFixed(2)} 万亿`;
  const session =
    data.session_date && data.session_date !== data.as_of
      ? `最新交易日 ${data.session_date}`
      : data.as_of;
  const up = data.limit_up_count == null ? "不可用" : data.limit_up_count;
  const down = data.limit_down_count == null ? "不可用" : data.limit_down_count;
  $("index-summary").textContent =
    `${session} · ${data.regime_label || "容错未知"} · ${amountText} · ` +
    `涨停 ${up} / 跌停 ${down} · 沪深300次日${data.t1_label || "观望"} · ` +
    `5–20日${data.swing_label || "观望"}。${data.t1_reason || ""} ${data.swing_reason || ""} ${data.note || ""}`;
  const body = document.querySelector("#index-table tbody");
  body.innerHTML = "";
  const rows = data.rows || [];
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 11;
    td.textContent = "指数日线没有返回。";
    tr.appendChild(td);
    body.appendChild(tr);
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.title = `${row.t1_reason || ""} ${row.swing_reason || ""}`.trim();
    if (row.symbol === selectedIndexSymbol) tr.classList.add("active");
    fillRow(tr, [
      { text: row.symbol, cls: "ticker" },
      { text: row.name },
      { text: fmtNum(row.close, 2), cls: "num" },
      { text: fmtPct(row.ret_1d), cls: quoteClass(row.ret_1d) },
      { text: fmtPct(row.ret_5d), cls: quoteClass(row.ret_5d) },
      { text: fmtPct(row.ret_20d), cls: quoteClass(row.ret_20d) },
      { text: row.range_pos == null ? "不可用" : `${fmtNum(row.range_pos, 0)}%`, cls: "num" },
      { text: row.structure || "不成段" },
      { text: row.t1_label || row.t1_bias, cls: biasClass(row.t1_bias) },
      { text: row.swing_label || row.swing_bias, cls: biasClass(row.swing_bias) },
      { text: fmtYi(row.amount), cls: "num" },
    ]);
    tr.addEventListener("click", () => {
      document.querySelectorAll("#index-table tbody tr").forEach((item) => {
        item.classList.remove("active");
      });
      tr.classList.add("active");
      loadIndexChart(row.symbol, row.name);
    });
    body.appendChild(tr);
  }
  const picked =
    rows.find((row) => row.symbol === selectedIndexSymbol && row.close != null) ||
    rows.find((row) => row.symbol === data.benchmark && row.close != null) ||
    rows.find((row) => row.close != null);
  if (picked) {
    document.querySelectorAll("#index-table tbody tr").forEach((item) => {
      item.classList.toggle("active", item.firstChild && item.firstChild.textContent === picked.symbol);
    });
    loadIndexChart(picked.symbol, picked.name);
  }
}

function renderTrend(data) {
  const label = data.window_label || data.window || "";
  $("trend-summary").textContent = `${data.as_of || ""} · ${label} · ${data.note || ""}`;
  const body = $("trend-table").querySelector("tbody");
  body.innerHTML = "";
  for (const row of data.rows || []) {
    const tr = document.createElement("tr");
    fillRow(tr, [
      { text: row.ticker || row.code || "", cls: "ticker" },
      { text: row.name || "" },
      { text: row.close == null ? "不可用" : Number(row.close).toFixed(2), cls: "num" },
      { text: fmtPct(row.ret_window), cls: quoteClass(row.ret_window) },
      { text: fmtPct(row.ret_5), cls: quoteClass(row.ret_5) },
      { text: fmtPct(row.ret_10), cls: quoteClass(row.ret_10) },
      { text: fmtPct(row.vs_hs300), cls: quoteClass(row.vs_hs300) },
      {
        text: row.range_pos == null ? "不可用" : `${Number(row.range_pos).toFixed(1)}%`,
        cls: "num",
      },
      { text: row.structure || "不可用" },
      { text: row.trend_label || row.trend_bias || "观望", cls: biasClass(row.trend_bias) },
      { text: row.trend_reason || "" },
    ]);
    body.appendChild(tr);
  }
  if (data.errors?.length) {
    const note = data.errors.map((item) => `${item.ticker}: ${item.error}`).join("；");
    $("trend-summary").textContent += ` · 跳过 ${note}`;
  }
}

async function onTrendPredict() {
  $("trend-error").hidden = true;
  $("trend-btn").disabled = true;
  $("trend-summary").textContent = "正在读取价量窗口与缠论结构…";
  const payload = {
    tickers: $("trend_tickers").value,
    swing_tape_window: $("trend_swing_window").value,
  };
  const asOf = $("trend_as_of").value;
  if (asOf) payload.as_of = asOf;
  try {
    const res = await fetch("/api/trend-predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || res.statusText);
    renderTrend(body);
  } catch (err) {
    $("trend-error").hidden = false;
    $("trend-error").textContent = err.message || String(err);
    $("trend-summary").textContent = "";
  } finally {
    $("trend-btn").disabled = false;
  }
}

async function onIndex() {
  $("index-error").hidden = true;
  $("index-btn").disabled = true;
  $("index-summary").textContent = "正在读取当天指数日线…";
  try {
    const res = await fetch("/api/index-outlook");
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || res.statusText);
    renderIndex(body);
  } catch (err) {
    $("index-error").hidden = false;
    $("index-error").textContent = err.message || String(err);
    $("index-summary").textContent = "";
  } finally {
    $("index-btn").disabled = false;
  }
}

async function onScreen() {
  $("screen-error").hidden = true;
  $("screen-btn").disabled = true;
  $("screen-summary").textContent = "正在读取当天公开榜单…";
  try {
    const res = await fetch("/api/screen");
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(body.detail || res.statusText);
    }
    renderScreen(body);
  } catch (err) {
    $("screen-error").hidden = false;
    $("screen-error").textContent = err.message || String(err);
    $("screen-summary").textContent = "";
  } finally {
    $("screen-btn").disabled = false;
  }
}

let tomorrowRiseChart = null;
let tomorrowRiseCandles = null;
let tomorrowRiseVolume = null;
let selectedTomorrowRiseTicker = null;

function ensureTomorrowRiseChart() {
  if (tomorrowRiseChart) return true;
  if (!window.LightweightCharts) return false;
  const el = $("tomorrow-rise-chart");
  ({ chart: tomorrowRiseChart, candles: tomorrowRiseCandles, volume: tomorrowRiseVolume } =
    mountCandleChart(el));
  return true;
}

function paintTomorrowRiseBars(payload) {
  if (!ensureTomorrowRiseChart()) {
    $("tomorrow-rise-chart-note").textContent = "图表库没有加载。";
    return;
  }
  const candles = [];
  const volume = [];
  for (const bar of payload.bars || []) {
    if (!bar || !bar.time || bar.open == null || bar.high == null || bar.low == null || bar.close == null) {
      continue;
    }
    candles.push({
      time: bar.time,
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    });
    if (bar.volume != null) {
      volume.push({
        time: bar.time,
        value: bar.volume,
        color: volumeColor(bar),
      });
    }
  }
  tomorrowRiseCandles.setData(candles);
  tomorrowRiseVolume.setData(volume);
  if (candles.length) {
    tomorrowRiseChart.timeScale().fitContent();
    $("tomorrow-rise-chart-note").textContent = payload.note || "日K用于观察，不是委托。";
  } else {
    $("tomorrow-rise-chart-note").textContent = "没有可画的日K。";
  }
}

async function loadTomorrowRiseChart(ticker, name) {
  selectedTomorrowRiseTicker = ticker;
  $("ticker").value = ticker;
  syncAnalystAvailability();
  $("tomorrow-rise-open-full").disabled = false;
  $("tomorrow-rise-chart-title").textContent = `${name || ""} ${ticker}`.trim();
  $("tomorrow-rise-chart-note").textContent = "正在读取日K…";
  try {
    const res = await fetch(`/api/screen/bars?ticker=${encodeURIComponent(ticker)}`);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(body.detail || res.statusText);
    }
    if (selectedTomorrowRiseTicker !== ticker) return;
    paintTomorrowRiseBars(body);
  } catch (err) {
    if (selectedTomorrowRiseTicker !== ticker) return;
    $("tomorrow-rise-chart-note").textContent = err.message || String(err);
  }
}

function renderTomorrowRise(data) {
  const amount = data.market_amount_yuan;
  const amountText =
    amount == null ? "成交额不可用" : `两市成交约 ${(Number(amount) / 1e12).toFixed(2)} 万亿`;
  const premium =
    data.prev_zt_premium == null ? "不可用" : `${fmtNum(data.prev_zt_premium, 2)}%`;
  const rows = data.rows || [];
  const rowText = rows.length ? `T+1 偏多 ${rows.length} 只。` : "";
  $("tomorrow-rise-summary").textContent =
    `${data.as_of} · ${data.regime_label || "容错未知"} · ${amountText} · 昨日涨停溢价 ${premium} · ` +
    `涨停 ${data.limit_up_count ?? "不可用"} / 跌停 ${data.limit_down_count ?? "不可用"}。${rowText}${data.note || ""}`;
  const body = document.querySelector("#tomorrow-rise-table tbody");
  body.innerHTML = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    const emptyText = data.quote_source
      ? "今天没有进入 T+1 偏多名单的非创业板股票。"
      : "现货榜没有返回，不能扫描明日上涨。";
    tr.innerHTML = `<td colspan="8">${emptyText}</td>`;
    body.appendChild(tr);
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.title = row.t1_reason || "";
    if (row.ticker === selectedTomorrowRiseTicker) tr.classList.add("active");
    fillRow(tr, [
      { text: row.ticker, cls: "ticker" },
      { text: row.name },
      { text: (row.sources || []).join(" / ") },
      { text: row.sector || "—" },
      { text: fmtPct(row.pct_chg), cls: quoteClass(row.pct_chg) },
      { text: fmtPct(row.speed), cls: quoteClass(row.speed) },
      { text: row.summary || row.t1_bias, cls: biasClass(row.t1_bias) },
      { text: row.t1_reason || "" },
    ]);
    tr.addEventListener("click", () => {
      document.querySelectorAll("#tomorrow-rise-table tbody tr").forEach((item) => {
        item.classList.remove("active");
      });
      tr.classList.add("active");
      loadTomorrowRiseChart(row.ticker, row.name);
    });
    body.appendChild(tr);
  }
}

async function onTomorrowRise() {
  $("tomorrow-rise-error").hidden = true;
  $("tomorrow-rise-btn").disabled = true;
  $("tomorrow-rise-summary").textContent = "正在扫描 T+1 偏多名单…";
  try {
    const res = await fetch("/api/tomorrow-rise");
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(body.detail || res.statusText);
    }
    renderTomorrowRise(body);
  } catch (err) {
    $("tomorrow-rise-error").hidden = false;
    $("tomorrow-rise-error").textContent = err.message || String(err);
    $("tomorrow-rise-summary").textContent = "";
  } finally {
    $("tomorrow-rise-btn").disabled = false;
  }
}

async function boot() {
  try {
    const res = await fetch("/api/options");
    if (!res.ok) {
      throw new Error(
        `无法加载选项（${res.status}）。确认 web-api 在跑后刷新；Docker 下可重启 web-ui。`
      );
    }
    options = await res.json();
  } catch (err) {
    $("form-error").hidden = false;
    $("form-error").textContent = err.message || String(err);
    return;
  }
  $("notice").textContent = options.notice;
  $("ticker").value = options.defaults.ticker;
  $("analysis_date").value = options.defaults.analysis_date;
  fillSelect($("output_language"), options.languages, "value", "label", options.defaults.output_language);
  fillSelect($("research_depth"), options.research_depth, "value", "label", options.defaults.research_depth);
  fillSelect(
    $("swing_tape_window"),
    options.swing_windows || [
      { key: "half_month", label: "近半个月（15 个日历日）" },
      { key: "three_months", label: "近3个月（90 个日历日）" },
      { key: "half_year", label: "近半年（180 个日历日）" },
    ],
    "key",
    "label",
    options.defaults.swing_tape_window
  );
  fillSelect(
    $("trend_swing_window"),
    options.swing_windows || [],
    "key",
    "label",
    "three_months"
  );
  $("trend_as_of").value = options.defaults.analysis_date;
  fillSelect($("llm_provider"), options.providers, "key", "label", options.defaults.llm_provider);
  const box = $("analysts");
  box.innerHTML = "";
  for (const analyst of options.analysts) {
    const label = document.createElement("label");
    label.className = "check";
    const checked = options.defaults.analysts.includes(analyst.key) ? "checked" : "";
    label.innerHTML = `<input type="checkbox" value="${analyst.key}" ${checked} /> ${analyst.label}`;
    box.appendChild(label);
  }
  $("checkpoint").checked = Boolean(options.defaults.checkpoint);
  $("ingest_news").checked = Boolean(options.defaults.ingest_news);
  $("llm_provider").addEventListener("change", refreshModels);
  $("shallow_thinker").addEventListener("change", () => onModelChange("shallow"));
  $("deep_thinker").addEventListener("change", () => onModelChange("deep"));
  $("ticker").addEventListener("input", syncAnalystAvailability);
  $("run-form").addEventListener("submit", onSubmit);
  $("latest-btn").addEventListener("click", onLatest);
  $("view-full").addEventListener("click", () => switchView("full"));
  $("view-tape").addEventListener("click", () => switchView("tape"));
  $("view-screen").addEventListener("click", () => switchView("screen"));
  $("view-index").addEventListener("click", () => switchView("index"));
  $("view-trend").addEventListener("click", () => switchView("trend"));
  $("view-tomorrow-rise").addEventListener("click", () => switchView("tomorrow-rise"));
  $("screen-btn").addEventListener("click", onScreen);
  $("index-btn").addEventListener("click", onIndex);
  $("trend-btn").addEventListener("click", onTrendPredict);
  $("tomorrow-rise-btn").addEventListener("click", onTomorrowRise);
  $("screen-open-full").addEventListener("click", () => {
    if (!selectedScreenTicker) return;
    $("ticker").value = selectedScreenTicker;
    syncAnalystAvailability();
    switchView("full");
  });
  $("tomorrow-rise-open-full").addEventListener("click", () => {
    if (!selectedTomorrowRiseTicker) return;
    $("ticker").value = selectedTomorrowRiseTicker;
    syncAnalystAvailability();
    switchView("full");
  });
  refreshModels();
  syncAnalystAvailability();
}

boot();
