const messagesEl = document.querySelector("#messages");
const formEl = document.querySelector("#chatForm");
const inputEl = document.querySelector("#messageInput");
const sendBtn = document.querySelector("#sendBtn");
const clearBtn = document.querySelector("#clearBtn");
const offlineToggle = document.querySelector("#offlineToggle");
const thinkingToggle = document.querySelector("#thinkingToggle");
const modelName = document.querySelector("#modelName");
const thinkingModelName = document.querySelector("#thinkingModelName");
const keyStatus = document.querySelector("#keyStatus");
const amapStatus = document.querySelector("#amapStatus");
const qweatherStatus = document.querySelector("#qweatherStatus");
const trainStatus = document.querySelector("#trainStatus");
const aviationStatus = document.querySelector("#aviationStatus");
const locationStatus = document.querySelector("#locationStatus");
const conversationListEl = document.querySelector("#conversationList");
const newChatBtn = document.querySelector("#newChatBtn");
const locateBtn = document.querySelector("#locateBtn");
const inputSuggestToggle = document.querySelector("#inputSuggestToggle");
const inputTipsEl = document.querySelector("#inputTips");
const CURRENT_CONVERSATION_KEY = "travel_agent_current_conversation_id";
const LOCATION_CONTEXT_KEY = "travel_agent_location_context";
const INPUT_SUGGEST_KEY = "travel_agent_input_suggest_enabled";
let currentConversationId = localStorage.getItem(CURRENT_CONVERSATION_KEY) || "";
let currentLocationContext = loadLocationContext();
let activeController = null;
let inputTipTimer = null;
let traceInteractionUntil = 0;

if (inputSuggestToggle) {
  inputSuggestToggle.checked = localStorage.getItem(INPUT_SUGGEST_KEY) !== "false";
}

function loadLocationContext() {
  try {
    return JSON.parse(localStorage.getItem(LOCATION_CONTEXT_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveLocationContext(context) {
  currentLocationContext = context || {};
  localStorage.setItem(LOCATION_CONTEXT_KEY, JSON.stringify(currentLocationContext));
  updateLocationStatus();
}

function locationLabel(context = currentLocationContext) {
  return context.city || context.district || context.province || "";
}

function updateLocationStatus(text = "") {
  if (!locationStatus) return;
  const label = text || locationLabel();
  locationStatus.textContent = label || "未定位";
}

function getConversationHistory() {
  return [...messagesEl.querySelectorAll(".message:not(.loading)")].slice(0, -1).slice(-8).map((message) => {
    const role = message.classList.contains("user") ? "user" : "assistant";
    const bubble = message.querySelector(".bubble");
    return { role, text: bubble?.dataset.rawText || bubble?.textContent || "" };
  });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

const POI_MARKER_LABELS = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

function markerLabel(index) {
  return POI_MARKER_LABELS[index] || String(index + 1);
}

function parseLngLat(location) {
  const [lng, lat] = String(location || "").split(",").map(Number);
  if (!Number.isFinite(lng) || !Number.isFinite(lat)) return null;
  return { lng, lat };
}

function mapViewport(locations) {
  const points = locations.map(parseLngLat).filter(Boolean);
  if (!points.length) return { center: locations[0] || "", zoom: "12" };
  const lngs = points.map((point) => point.lng);
  const lats = points.map((point) => point.lat);
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const lngSpan = maxLng - minLng;
  const latSpan = maxLat - minLat;
  const span = Math.max(lngSpan, latSpan * 1.8);
  const center = `${((minLng + maxLng) / 2).toFixed(6)},${((minLat + maxLat) / 2).toFixed(6)}`;
  let zoom = 12;
  if (span > 2.2) zoom = 7;
  else if (span > 1.1) zoom = 8;
  else if (span > 0.55) zoom = 9;
  else if (span > 0.28) zoom = 10;
  else if (span > 0.14) zoom = 11;
  else if (span <= 0.035) zoom = 13;
  return { center, zoom: String(zoom) };
}

function buildMapImageUrl(locations, options = {}) {
  const cleanLocations = (locations || [])
    .map((location) => String(location || "").trim())
    .filter((location) => /^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$/.test(location))
    .slice(0, POI_MARKER_LABELS.length);
  if (!cleanLocations.length) return "";
  const viewport = mapViewport(cleanLocations);
  const params = new URLSearchParams({
    location: options.center || viewport.center,
    zoom: options.zoom || viewport.zoom,
    size: options.size || "1024*520",
    markers: cleanLocations
      .map((loc, index) => `mid,0x1677ff,${markerLabel(index)}:${loc}`)
      .join("|"),
  });
  return `/api/amap/static-map?${params.toString()}`;
}

function markTraceInteraction() {
  traceInteractionUntil = Date.now() + 700;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function updateDraggableMap(viewport) {
  const image = viewport.querySelector(".poi-map-preview");
  if (!image) return;
  const x = Number(viewport.dataset.offsetX || 0);
  const y = Number(viewport.dataset.offsetY || 0);
  image.style.transform = `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`;
}

function clampMapOffset(viewport) {
  const image = viewport.querySelector(".poi-map-preview");
  if (!image || !image.complete) return;
  const maxX = Math.max(0, (image.clientWidth - viewport.clientWidth) / 2);
  const maxY = Math.max(0, (image.clientHeight - viewport.clientHeight) / 2);
  viewport.dataset.offsetX = String(clamp(Number(viewport.dataset.offsetX || 0), -maxX, maxX));
  viewport.dataset.offsetY = String(clamp(Number(viewport.dataset.offsetY || 0), -maxY, maxY));
  updateDraggableMap(viewport);
}

function initDraggableMaps(root = document) {
  root.querySelectorAll("[data-draggable-map]").forEach((viewport) => {
    if (viewport.dataset.dragReady === "true") return;
    viewport.dataset.dragReady = "true";
    viewport.dataset.offsetX = viewport.dataset.offsetX || "0";
    viewport.dataset.offsetY = viewport.dataset.offsetY || "0";
    const image = viewport.querySelector(".poi-map-preview");
    if (image) {
      image.addEventListener("load", () => clampMapOffset(viewport), { once: true });
    }

    let dragging = false;
    let startX = 0;
    let startY = 0;
    let baseX = 0;
    let baseY = 0;
    viewport.addEventListener("pointerdown", (event) => {
      dragging = true;
      startX = event.clientX;
      startY = event.clientY;
      baseX = Number(viewport.dataset.offsetX || 0);
      baseY = Number(viewport.dataset.offsetY || 0);
      viewport.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    viewport.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      viewport.dataset.offsetX = String(baseX + event.clientX - startX);
      viewport.dataset.offsetY = String(baseY + event.clientY - startY);
      clampMapOffset(viewport);
    });
    const stopDrag = (event) => {
      if (!dragging) return;
      dragging = false;
      if (viewport.hasPointerCapture(event.pointerId)) {
        viewport.releasePointerCapture(event.pointerId);
      }
      clampMapOffset(viewport);
    };
    viewport.addEventListener("pointerup", stopDrag);
    viewport.addEventListener("pointercancel", stopDrag);
  });
}

function renderMarkdown(text) {
  if (window.marked) {
    marked.setOptions({
      gfm: true,
      breaks: true,
    });
    return marked.parse(text);
  }
  return renderSimpleMarkdown(text);
}

function renderSimpleMarkdown(text) {
  const lines = text.split("\n");
  const html = [];
  let inList = false;
  let inTable = false;

  function closeList() {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  }

  function closeTable() {
    if (inTable) {
      html.push("</tbody></table>");
      inTable = false;
    }
  }

  function inline(value) {
    return escapeHtml(value).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trim();
    const next = lines[i + 1]?.trim() || "";
    if (!line) {
      closeList();
      closeTable();
      continue;
    }

    const tableCells = line.split("|").map((cell) => cell.trim()).filter(Boolean);
    const nextIsDivider = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(next);
    const isDivider = /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line);
    if (tableCells.length > 1 && nextIsDivider) {
      closeList();
      closeTable();
      html.push("<table><thead><tr>");
      tableCells.forEach((cell) => html.push(`<th>${inline(cell)}</th>`));
      html.push("</tr></thead><tbody>");
      inTable = true;
      i += 1;
      continue;
    }
    if (inTable && tableCells.length > 1 && !isDivider) {
      html.push("<tr>");
      tableCells.forEach((cell) => html.push(`<td>${inline(cell)}</td>`));
      html.push("</tr>");
      continue;
    }

    closeTable();
    if (line.startsWith("### ")) {
      closeList();
      html.push(`<h3>${inline(line.slice(4))}</h3>`);
    } else if (line.startsWith("## ")) {
      closeList();
      html.push(`<h2>${inline(line.slice(3))}</h2>`);
    } else if (line.startsWith("# ")) {
      closeList();
      html.push(`<h2>${inline(line.slice(2))}</h2>`);
    } else if (/^[-*]\s+/.test(line)) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inline(line.replace(/^[-*]\s+/, ""))}</li>`);
    } else {
      closeList();
      html.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  closeTable();
  return html.join("");
}

function appendMessage(role, text, extraClass = "") {
  const article = document.createElement("article");
  article.className = `message ${role} ${extraClass}`.trim();
  if (role === "assistant") {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = "AI";
    article.appendChild(avatar);
  }
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (role === "assistant") {
    bubble.innerHTML = renderMarkdown(text);
  } else {
    bubble.textContent = text;
  }
  bubble.dataset.rawText = text;
  article.appendChild(bubble);
  messagesEl.appendChild(article);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return article;
}

function renderWelcome() {
  messagesEl.innerHTML = "";
  appendMessage(
    "assistant",
    "你好，我可以帮你规划旅行。试试输入：“我明天从郑州去杭州，玩3天，2个人，酒店300，餐饮120，门票300”。",
  );
}

function setMessageText(article, text) {
  const bubble = article.querySelector(".bubble");
  if (!bubble) return;
  bubble.textContent = text;
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendMeta(article, data) {
  const bubble = article.querySelector(".bubble");
  if (!bubble || !data) return;
  const meta = document.createElement("div");
  meta.className = "message-meta";
  const parts = [];
  if (data.mode) parts.push(data.mode);
  if (data.model) parts.push(data.model);
  if (typeof data.elapsed_seconds === "number") parts.push(`耗时 ${data.elapsed_seconds}s`);
  meta.textContent = parts.join(" · ");
  if (meta.textContent) {
    bubble.dataset.meta = meta.textContent;
    bubble.appendChild(meta);
  }
  if (Array.isArray(data.trace) && data.trace.length) {
    bubble.dataset.trace = JSON.stringify(data.trace);
    bubble.appendChild(renderTrace(data.trace));
  }
}

function summarizeUsage(usage) {
  if (!usage || typeof usage !== "object") return "";
  const total = usage.total_tokens ?? usage.total ?? "";
  return total ? `tokens ${total}` : "";
}

function compactResult(text) {
  if (!text) return "";
  const compact = String(text).replace(/\s+/g, " ").trim();
  return compact.length > 140 ? `${compact.slice(0, 140)}...` : compact;
}

function traceLabel(item) {
  if (item.type === "tool_call") return "工具";
  if (item.type === "tool_result") return "返回";
  if (item.type === "llm_response") return "模型";
  return "阶段";
}

function renderTrace(trace, expanded = false) {
  const details = document.createElement("details");
  details.className = "trace-panel";
  if (expanded) {
    details.open = true;
  }
  const summary = document.createElement("summary");
  const toolCount = trace.filter((item) => item.type === "tool_call").length;
  const llmCount = trace.filter((item) => item.type === "llm_response").length;
  summary.textContent = trace.length
    ? `执行过程：${toolCount} 次工具调用，${llmCount} 次模型响应`
    : "执行过程：等待智能体行动";
  details.appendChild(summary);

  const list = document.createElement("div");
  list.className = "trace-list";
  trace.forEach((item) => {
    const row = document.createElement("div");
    row.className = `trace-item ${item.type}`;
    if (item.type === "tool_call") {
      const args = JSON.stringify(item.args || {}, null, 2);
      row.innerHTML = `
        <div class="trace-title"><span>${traceLabel(item)}</span>调用工具：${escapeHtml(item.tool || "unknown")}</div>
        <pre>${escapeHtml(args)}</pre>
        ${item.result ? `<p><strong>返回：</strong>${escapeHtml(compactResult(item.result))}</p>` : '<p class="trace-pending">等待工具返回</p>'}
      `;
    } else if (item.type === "llm_response") {
      row.innerHTML = `
        <div class="trace-title"><span>${traceLabel(item)}</span>模型响应：${escapeHtml(item.model || "unknown")}</div>
        <p>${escapeHtml(summarizeUsage(item.usage))}</p>
      `;
    } else {
      row.innerHTML = `
        <div class="trace-title"><span>${traceLabel(item)}</span>工具返回：${escapeHtml(item.tool || "unknown")}</div>
        <p>${escapeHtml(compactResult(item.result))}</p>
      `;
    }
    list.appendChild(row);
  });
  details.appendChild(list);
  return details;
}

function renderLoadingStatus(article, text, trace = [], stats = {}) {
  const bubble = article.querySelector(".bubble");
  if (!bubble) return;
  const existingTrace = bubble.querySelector(".trace-panel");
  const existingTraceList = bubble.querySelector(".trace-list");
  const isTraceInteracting = Date.now() < traceInteractionUntil;
  const traceWasOpen = existingTrace ? existingTrace.open : true;
  const traceWasAtBottom = existingTraceList
    ? existingTraceList.scrollHeight - existingTraceList.scrollTop - existingTraceList.clientHeight < 12
    : true;
  const traceScrollTop = existingTraceList ? existingTraceList.scrollTop : 0;
  const messagesWereAtBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 32;

  if (isTraceInteracting && existingTrace) {
    const status = bubble.querySelector(".loading-status");
    if (status) status.textContent = text;
    const streamStats = bubble.querySelector(".stream-stats");
    if (streamStats) {
      const parts = [];
      if (stats.eventCount > 0) parts.push(`已收到 ${stats.eventCount} 个阶段事件`);
      if (typeof stats.silentSeconds === "number") parts.push(`距离上次更新 ${stats.silentSeconds}s`);
      if (stats.model) parts.push(stats.model);
      streamStats.textContent = parts.length ? parts.join(" · ") : "正在建立流式连接";
    }
    bubble.dataset.rawText = text;
    return;
  }

  bubble.innerHTML = "";
  const status = document.createElement("div");
  status.className = "loading-status";
  status.textContent = text;
  bubble.appendChild(status);

  const streamStats = document.createElement("div");
  streamStats.className = "stream-stats";
  const parts = [];
  if (stats.eventCount > 0) parts.push(`已收到 ${stats.eventCount} 个阶段事件`);
  if (typeof stats.silentSeconds === "number") parts.push(`距离上次更新 ${stats.silentSeconds}s`);
  if (stats.model) parts.push(stats.model);
  streamStats.textContent = parts.length ? parts.join(" · ") : "正在建立流式连接";
  bubble.appendChild(streamStats);

  if (trace.length) {
    const traceEl = renderTrace(trace, traceWasOpen);
    bubble.appendChild(traceEl);
    const traceList = traceEl.querySelector(".trace-list");
    if (traceList && traceEl.open) {
      if (traceWasAtBottom) {
        traceList.scrollTop = traceList.scrollHeight;
      } else {
        traceList.scrollTop = traceScrollTop;
      }
    }
  }
  bubble.dataset.rawText = text;
  if (messagesWereAtBottom) {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
}

function parseSseBuffer(buffer) {
  const events = [];
  const frames = buffer.split("\n\n");
  const rest = frames.pop() || "";
  frames.forEach((frame) => {
    const dataLines = frame
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart());
    if (!dataLines.length) return;
    try {
      events.push(JSON.parse(dataLines.join("\n")));
    } catch {
      // Ignore malformed stream frames and keep reading the next event.
    }
  });
  return { events, rest };
}

async function requestChatStream(payload, onEvent) {
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${response.status}`);
  }

  if (!response.body) {
    throw new Error("当前浏览器不支持流式读取。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseBuffer(buffer);
    buffer = parsed.rest;
    parsed.events.forEach(onEvent);
  }

  buffer += decoder.decode();
  const parsed = parseSseBuffer(buffer + "\n\n");
  parsed.events.forEach(onEvent);
}

async function loadConversations() {
  try {
    const response = await fetch("/api/conversations");
    const data = await response.json();
    const conversations = data.conversations || [];
    conversationListEl.innerHTML = "";
    conversations.forEach((conversation) => {
      const item = document.createElement("div");
      item.className = `conversation-item ${conversation.id === currentConversationId ? "active" : ""}`;
      item.dataset.id = conversation.id;
      item.innerHTML = `
        <div>
          <div class="conversation-title"></div>
          <div class="conversation-meta">${conversation.message_count || 0} 条消息</div>
        </div>
        <button class="delete-chat-btn" type="button" title="删除">×</button>
      `;
      item.querySelector(".conversation-title").textContent = conversation.title || "新会话";
      item.addEventListener("click", () => loadConversation(conversation.id));
      item.querySelector(".delete-chat-btn").addEventListener("click", async (event) => {
        event.stopPropagation();
        await deleteConversation(conversation.id);
      });
      conversationListEl.appendChild(item);
    });
  } catch {
    conversationListEl.innerHTML = '<div class="conversation-meta">历史会话加载失败</div>';
  }
}

async function loadConversation(conversationId) {
  if (!conversationId) {
    currentConversationId = "";
    localStorage.removeItem(CURRENT_CONVERSATION_KEY);
    renderWelcome();
    await loadConversations();
    return;
  }

  const response = await fetch(`/api/conversations/${conversationId}/messages`);
  const data = await response.json();
  currentConversationId = conversationId;
  localStorage.setItem(CURRENT_CONVERSATION_KEY, conversationId);
  messagesEl.innerHTML = "";
  const messages = data.messages || [];
  if (!messages.length) {
    renderWelcome();
  } else {
    messages.forEach((message) => {
      const article = appendMessage(message.role, message.text || "");
      if (message.meta?.structured_data) {
        renderStructuredCardsInto(article, message.meta.structured_data);
      }
      if (message.meta && Object.keys(message.meta).length) {
        appendMeta(article, message.meta);
      }
    });
  }
  await loadConversations();
}

async function deleteConversation(conversationId) {
  await fetch(`/api/conversations/${conversationId}`, { method: "DELETE" });
  if (conversationId === currentConversationId) {
    currentConversationId = "";
    localStorage.removeItem(CURRENT_CONVERSATION_KEY);
    renderWelcome();
  }
  await loadConversations();
}

function setBusy(isBusy) {
  inputEl.disabled = isBusy;
  sendBtn.disabled = isBusy;
  sendBtn.querySelector("span").textContent = isBusy ? "生成中" : "发送";
}

function traceStatusLabel(status) {
  if (status === "running") return "运行中";
  if (status === "error") return "异常";
  if (status === "success") return "成功";
  return "待处理";
}

function traceStatusClass(status) {
  if (status === "running") return "running";
  if (status === "error") return "error";
  if (status === "success") return "success";
  return "pending";
}

function formatTraceTime(item) {
  if (typeof item.duration_ms === "number") {
    return `耗时 ${(item.duration_ms / 1000).toFixed(2)}s`;
  }
  if (typeof item.started_ms === "number") {
    return `开始 +${(item.started_ms / 1000).toFixed(2)}s`;
  }
  return "";
}

const TRACE_TOOL_INFO = {
  get_weather_info: { label: "天气", title: "查询天气", desc: "获取实时天气和未来预报，判断出行舒适度。" },
  get_air_quality_info: { label: "空气", title: "查询空气质量", desc: "判断户外活动、骑行和老人儿童出行风险。" },
  get_weather_alerts: { label: "预警", title: "查询天气预警", desc: "检查暴雨、大风、高温等灾害预警。" },
  calculate_trip_budget: { label: "预算", title: "计算预算", desc: "按人数、天数、住宿、餐饮和门票估算费用。" },
  get_transport_advice: { label: "驾车", title: "规划驾车路线", desc: "查询驾车距离、耗时和过路费参考。" },
  search_flight_options: { label: "航班", title: "查询航班", desc: "查询航班时刻、机场、航站楼和状态。" },
  get_public_transit_plan: { label: "公交", title: "规划公交/地铁", desc: "查询市内公共交通换乘方案。" },
  get_walking_route: { label: "步行", title: "规划步行路线", desc: "判断短距离步行可达性。" },
  get_bicycling_route: { label: "骑行", title: "规划骑行路线", desc: "判断共享单车或骑行路线是否合适。" },
  get_route_distance_matrix: { label: "距离", title: "比较距离耗时", desc: "比较多个地点到同一目的地的距离和耗时。" },
  get_traffic_status: { label: "路况", title: "查询实时路况", desc: "检查指定地点周边道路拥堵情况和通行风险。" },
  search_travel_pois: { label: "POI", title: "搜索目的地地点", desc: "查询景点、餐饮、商圈、酒店等 POI。" },
  search_nearby_pois: { label: "周边", title: "搜索周边地点", desc: "围绕指定地点按半径查询餐饮、住宿或地铁站。" },
  get_place_location: { label: "定位", title: "解析地点位置", desc: "核验地点地址和经纬度。" },
  get_map_marker_link: { label: "地图", title: "生成地图链接", desc: "生成可打开的高德地图标记链接。" },
  search_train_tickets: { label: "火车", title: "查询火车余票", desc: "查询真实车次、时刻、余票和票价。" },
  search_interline_train_tickets: { label: "中转", title: "查询中转火车", desc: "查询需要换乘的火车/高铁中转方案。" },
  get_train_route: { label: "经停", title: "查询列车经停", desc: "查询指定车次的经停站和时刻表。" },
};

function traceToolInfo(tool) {
  return TRACE_TOOL_INFO[tool] || { label: "工具", title: `调用工具：${tool || "unknown"}`, desc: "调用外部工具补充真实数据。" };
}

function traceArgsSummary(args) {
  if (!args || typeof args !== "object") return "";
  const preferred = [
    "city", "date", "origin", "destination", "origin_city", "destination_city",
    "departure", "arrival", "from_city", "to_city", "place", "keyword",
    "origins", "train_code", "train_filter_flags", "limit",
  ];
  const chips = preferred
    .filter(key => args[key] !== undefined && args[key] !== "" && args[key] !== null)
    .slice(0, 5)
    .map(key => `${key}: ${args[key]}`);
  return chips.map(chip => `<span>${escapeHtml(String(chip))}</span>`).join("");
}

function summarizeTrace(trace) {
  const toolCount = trace.filter((item) => item.type === "tool_call").length;
  const llmCount = trace.filter((item) => item.type === "llm_response").length;
  const runningCount = trace.filter((item) => item.status === "running").length;
  const errorCount = trace.filter((item) => item.status === "error").length;
  const status = [
    `${toolCount} 次工具`,
    `${llmCount} 次模型`,
    runningCount ? `${runningCount} 进行中` : "",
    errorCount ? `${errorCount} 异常` : "",
  ].filter(Boolean).join("，");
  const toolNames = trace
    .filter((item) => item.type === "tool_call")
    .map((item) => traceToolInfo(item.tool).title)
    .filter(Boolean);
  const mainFlow = [...new Set(toolNames)].slice(0, 3).join(" → ");
  return trace.length
    ? `执行过程：${status}${mainFlow ? `｜${mainFlow}` : ""}`
    : "执行过程：等待智能体行动";
}

function renderTrace(trace, expanded = false) {
  const details = document.createElement("details");
  details.className = "trace-panel";
  if (expanded) {
    details.open = true;
  }
  const summary = document.createElement("summary");
  summary.textContent = summarizeTrace(trace);
  details.appendChild(summary);

  const list = document.createElement("div");
  list.className = "trace-list";
  trace.forEach((item) => {
    const row = document.createElement("div");
    const status = item.status || (item.result ? "success" : "pending");
    row.className = `trace-item ${item.type} ${traceStatusClass(status)}`;
    const timeText = formatTraceTime(item);
    const info = traceToolInfo(item.tool);
    const titleText = item.type === "llm_response"
      ? `模型整合结果：${item.model || "unknown"}`
      : item.type === "tool_result"
        ? `${info.title}完成`
        : info.title;

    const args = JSON.stringify(item.args || {}, null, 2);
    const usage = summarizeUsage(item.usage);
    row.innerHTML = `
      <div class="trace-title">
        <span>${item.type === "llm_response" ? "模型" : escapeHtml(info.label)}</span>
        <strong>${escapeHtml(titleText)}</strong>
        <em class="trace-status">${traceStatusLabel(status)}</em>
        ${timeText ? `<em class="trace-time">${escapeHtml(timeText)}</em>` : ""}
      </div>
      ${item.type === "tool_call" ? `<p class="trace-desc">${escapeHtml(info.desc)}</p>` : ""}
      ${item.type === "tool_call" && traceArgsSummary(item.args) ? `<div class="trace-arg-chips">${traceArgsSummary(item.args)}</div>` : ""}
      ${item.type === "tool_call" ? `<details class="trace-raw"><summary>查看原始参数</summary><pre>${escapeHtml(args)}</pre></details>` : ""}
      ${item.type === "llm_response" && usage ? `<p>${escapeHtml(usage)}</p>` : ""}
      ${item.result ? `<p><strong>返回：</strong>${escapeHtml(compactResult(item.result))}</p>` : ""}
      ${item.type === "tool_call" && !item.result ? '<p class="trace-pending">工具运行中，等待返回结果</p>' : ""}
    `;
    list.appendChild(row);
  });
  details.appendChild(list);
  return details;
}

function downloadTraceReport(data) {
  const report = {
    exported_at: new Date().toISOString(),
    mode: data.mode || "",
    model: data.model || "",
    elapsed_seconds: data.elapsed_seconds ?? null,
    trace: data.trace || [],
    structured_data: data.structured_data || null,
  };
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `agent-trace-${Date.now()}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function renderTraceActions(data) {
  const actions = document.createElement("div");
  actions.className = "trace-actions";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "trace-export-btn";
  button.textContent = "导出执行报告";
  button.addEventListener("click", () => downloadTraceReport(data));
  actions.appendChild(button);
  return actions;
}

function appendMeta(article, data) {
  const bubble = article.querySelector(".bubble");
  if (!bubble || !data) return;
  const meta = document.createElement("div");
  meta.className = "message-meta";
  const parts = [];
  if (data.mode) parts.push(data.mode);
  if (data.model) parts.push(data.model);
  if (typeof data.elapsed_seconds === "number") parts.push(`耗时 ${data.elapsed_seconds}s`);
  meta.textContent = parts.join(" · ");
  if (meta.textContent) {
    bubble.dataset.meta = meta.textContent;
    bubble.appendChild(meta);
  }
  if (Array.isArray(data.trace) && data.trace.length) {
    bubble.dataset.trace = JSON.stringify(data.trace);
    bubble.appendChild(renderTrace(data.trace));
    bubble.appendChild(renderTraceActions(data));
  }
}

async function requestChatStream(payload, onEvent) {
  activeController = new AbortController();
  const response = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: activeController.signal,
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${response.status}`);
  }

  if (!response.body) {
    throw new Error("当前浏览器不支持流式读取。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseBuffer(buffer);
    buffer = parsed.rest;
    parsed.events.forEach(onEvent);
  }

  buffer += decoder.decode();
  const parsed = parseSseBuffer(buffer + "\n\n");
  parsed.events.forEach(onEvent);
}

function setBusy(isBusy) {
  inputEl.disabled = isBusy;
  sendBtn.disabled = false;
  sendBtn.classList.toggle("is-stopping", isBusy);
  sendBtn.querySelector("span").textContent = isBusy ? "停止" : "发送";
}

formEl.addEventListener("submit", (event) => {
  if (!activeController) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  activeController.abort();
  activeController = null;
  setBusy(false);
}, true);

async function loadStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();
    modelName.textContent = data.model || "未知";
    thinkingModelName.textContent = data.thinking_model || "未知";
    keyStatus.textContent = data.api_key_loaded ? "已配置" : "未配置";
    if (amapStatus) amapStatus.textContent = data.amap_key_loaded ? "已配置" : "未配置";
    if (qweatherStatus) {
      qweatherStatus.textContent = data.qweather_key_loaded
        ? (data.qweather_host_loaded ? "已配置" : "缺少 Host")
        : "未配置";
    }
    if (trainStatus) trainStatus.textContent = data.train_tools_available ? "可用" : "未检测到";
    if (aviationStatus) aviationStatus.textContent = data.aviationstack_key_loaded ? "已配置" : "未配置";
  } catch {
    modelName.textContent = "读取失败";
    thinkingModelName.textContent = "读取失败";
    keyStatus.textContent = "未知";
    if (amapStatus) amapStatus.textContent = "未知";
    if (qweatherStatus) qweatherStatus.textContent = "未知";
    if (trainStatus) trainStatus.textContent = "未知";
    if (aviationStatus) aviationStatus.textContent = "未知";
  }
}

async function detectIpLocation() {
  if (locationLabel()) {
    updateLocationStatus();
    return;
  }
  updateLocationStatus("定位中...");
  try {
    const response = await fetch("/api/amap/ip-location");
    const data = await response.json();
    if (response.ok && (data.city || data.province)) {
      saveLocationContext({
        source: "高德IP定位",
        province: data.province || "",
        city: data.city || data.province || "",
        district: "",
        adcode: data.adcode || "",
        address: data.city || data.province || "",
        location: "",
      });
    } else {
      updateLocationStatus("未定位");
    }
  } catch {
    updateLocationStatus("未定位");
  }
}

function requestBrowserLocation() {
  if (!navigator.geolocation) {
    updateLocationStatus("浏览器不支持定位");
    return;
  }
  updateLocationStatus("等待授权...");
  navigator.geolocation.getCurrentPosition(
    async (position) => {
      const { longitude, latitude } = position.coords;
      const location = `${longitude.toFixed(6)},${latitude.toFixed(6)}`;
      try {
        const response = await fetch(`/api/amap/reverse-geocode?location=${encodeURIComponent(location)}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "逆地理编码失败");
        saveLocationContext({
          source: "浏览器定位+高德逆地理编码",
          province: data.province || "",
          city: data.city || data.province || "",
          district: data.district || "",
          adcode: data.adcode || "",
          address: data.address || "",
          location,
        });
      } catch {
        saveLocationContext({ source: "浏览器定位", location });
      }
    },
    () => updateLocationStatus(locationLabel() || "定位被拒绝"),
    { enableHighAccuracy: true, timeout: 8000, maximumAge: 10 * 60 * 1000 },
  );
}

function extractTipKeyword(text) {
  const beforeCursor = text.slice(0, inputEl.selectionStart || text.length);
  const token = beforeCursor.split(/[\s，。,.、；;！？!?：:\n]/).pop() || "";
  return token.replace(/^(从|到|去|前往|查|查询|附近|明天|今天|后天)/, "").trim();
}

const tipSeparatorPattern = /[\s,.;:!?，。；：！？、（）()【】[\]{}<>《》"'“”‘’\n\r\t]/;
const tipTriggerChars = "从到去往在";
const tipTriggerWords = ["出发地", "目的地", "起点", "终点", "附近", "前往", "出发", "查询", "搜索", "查", "搜"];
const tipIgnorePrefixPattern = /^(帮我|我想|我打算|想要|计划|明天|今天|后天|查|查询|搜索|看看|一下)$/;

function getTipQuery(text) {
  const cursor = inputEl.selectionStart ?? text.length;
  const beforeCursor = text.slice(0, cursor);
  let start = cursor;
  while (start > 0 && !tipSeparatorPattern.test(text[start - 1])) {
    start -= 1;
  }

  let triggerStart = -1;
  for (const char of tipTriggerChars) {
    const index = beforeCursor.lastIndexOf(char);
    if (index > triggerStart) triggerStart = index;
  }
  for (const word of tipTriggerWords) {
    const index = beforeCursor.lastIndexOf(word);
    if (index >= 0 && index + word.length > triggerStart) {
      triggerStart = index + word.length - 1;
    }
  }
  if (triggerStart >= start) {
    start = triggerStart + 1;
  }

  let raw = text.slice(start, cursor);
  const leadingSpaces = raw.match(/^\s*/)?.[0].length || 0;
  start += leadingSpaces;
  raw = raw.trimStart();

  let keyword = raw.trim();
  if (keyword.startsWith("一下")) {
    start += 2;
    keyword = keyword.slice(2).trim();
  }
  if (!keyword || tipIgnorePrefixPattern.test(keyword)) {
    return { keyword: "", start, end: cursor };
  }

  return { keyword, start, end: cursor };
}

function hideInputTips() {
  if (!inputTipsEl) return;
  inputTipsEl.hidden = true;
  inputTipsEl.innerHTML = "";
}

async function loadInputTips() {
  if (!inputTipsEl || activeController || (inputSuggestToggle && !inputSuggestToggle.checked)) {
    hideInputTips();
    return;
  }
  const keyword = getTipQuery(inputEl.value).keyword;
  if (keyword.length < 2 || keyword.length > 16) {
    hideInputTips();
    return;
  }
  try {
    const params = new URLSearchParams({ keywords: keyword });
    const city = locationLabel();
    if (city) params.set("city", city);
    const response = await fetch(`/api/amap/input-tips?${params.toString()}`);
    const data = await response.json();
    const tips = Array.isArray(data.tips) ? data.tips.filter((tip) => tip.name) : [];
    if (!tips.length) {
      hideInputTips();
      return;
    }
    inputTipsEl.innerHTML = tips.map((tip) => `
      <button type="button" class="input-tip" data-name="${escapeHtml(tip.name)}">
        <strong>${escapeHtml(tip.name)}</strong>
        <span>${escapeHtml(tip.district || tip.address || "")}</span>
      </button>
    `).join("");
    inputTipsEl.hidden = false;
  } catch {
    hideInputTips();
  }
}

function applyInputTip(name) {
  const { keyword, start, end } = getTipQuery(inputEl.value);
  const prefix = inputEl.value.slice(0, start);
  const suffix = inputEl.value.slice(end);
  inputEl.value = keyword ? `${prefix}${name}${suffix}` : `${inputEl.value}${name}`;
  const nextCursor = (keyword ? prefix.length : inputEl.value.length - name.length) + name.length;
  hideInputTips();
  inputEl.focus();
  inputEl.setSelectionRange(nextCursor, nextCursor);
}

formEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = inputEl.value.trim();
  if (!message) return;

  appendMessage("user", message);
  inputEl.value = "";
  const loadingEl = appendMessage("assistant", "请求已发送，等待模型响应 0s", "loading");
  const startedAt = Date.now();
  let latestStatus = "请求已发送，等待智能体响应";
  let liveTrace = [];
  let finalData = null;
  let eventCount = 0;
  let lastEventAt = Date.now();
  let activeModel = "";
  const streamStats = () => ({
    eventCount,
    model: activeModel,
    silentSeconds: Math.max(0, Math.floor((Date.now() - lastEventAt) / 1000)),
  });
  const timer = setInterval(() => {
    const elapsed = Math.floor((Date.now() - startedAt) / 1000);
    const mode = offlineToggle.checked ? "离线演示" : (thinkingToggle.checked ? "深度思考" : "普通模式");
    renderLoadingStatus(loadingEl, `${mode} · ${latestStatus}，已等待 ${elapsed}s`, liveTrace, streamStats());
  }, 1000);
  renderLoadingStatus(loadingEl, latestStatus, liveTrace, streamStats());
  setBusy(true);

  try {
    await requestChatStream(
      {
        message,
        conversation_id: currentConversationId,
        history: getConversationHistory(),
        offline_demo: offlineToggle.checked,
        thinking_mode: thinkingToggle.checked,
        client_context: currentLocationContext,
      },
      (data) => {
        eventCount += 1;
        lastEventAt = Date.now();
        if (data.conversation_id) {
          currentConversationId = data.conversation_id;
          localStorage.setItem(CURRENT_CONVERSATION_KEY, currentConversationId);
        }
        if (data.model) {
          activeModel = data.model;
        }

        if (data.event === "status") {
          latestStatus = data.message || latestStatus;
          renderLoadingStatus(loadingEl, latestStatus, liveTrace, streamStats());
        } else if (data.event === "trace") {
          liveTrace = Array.isArray(data.trace) ? data.trace : liveTrace;
          const item = data.item || {};
          if (data.phase === "tool_call" || item.type === "tool_call") {
            latestStatus = `正在${traceToolInfo(item.tool).title}`;
          } else if (data.phase === "tool_result" || item.type === "tool_result") {
            latestStatus = `${traceToolInfo(item.tool).title}已完成`;
          } else if (data.phase === "llm_response" || item.type === "llm_response") {
            latestStatus = `模型阶段完成：${item.model || "unknown"}`;
          } else if (data.message) {
            latestStatus = data.message;
          } else {
            latestStatus = "智能体继续整合信息";
          }
          renderLoadingStatus(loadingEl, latestStatus, liveTrace, streamStats());
        } else if (data.event === "done") {
          finalData = data;
        } else if (data.event === "error") {
          finalData = data;
        }
      },
    );
    clearInterval(timer);
    loadingEl.remove();

    if (finalData?.conversation_id) {
      currentConversationId = finalData.conversation_id;
      localStorage.setItem(CURRENT_CONVERSATION_KEY, currentConversationId);
    }
    const responseEl = appendMessage("assistant", finalData?.answer || finalData?.error || "没有返回内容。");
    if (finalData?.structured_data) {
      renderStructuredCardsInto(responseEl, finalData.structured_data);
    }
    appendMeta(responseEl, finalData || {});
    await loadConversations();
  } catch (error) {
    clearInterval(timer);
    loadingEl.remove();
    if (error.name === "AbortError") {
      appendMessage("assistant", "已停止本次生成。");
      return;
    }
    appendMessage("assistant", `请求失败：${error.message}`);
  } finally {
    activeController = null;
    setBusy(false);
    inputEl.focus();
  }
});

if (locateBtn) {
  locateBtn.addEventListener("click", requestBrowserLocation);
}

if (inputSuggestToggle) {
  inputSuggestToggle.addEventListener("change", () => {
    localStorage.setItem(INPUT_SUGGEST_KEY, inputSuggestToggle.checked ? "true" : "false");
    if (!inputSuggestToggle.checked) {
      hideInputTips();
      return;
    }
    clearTimeout(inputTipTimer);
    inputTipTimer = setTimeout(loadInputTips, 120);
  });
}

inputEl.addEventListener("input", () => {
  clearTimeout(inputTipTimer);
  inputTipTimer = setTimeout(loadInputTips, 260);
});

inputEl.addEventListener("blur", () => {
  setTimeout(hideInputTips, 160);
});

if (inputTipsEl) {
  inputTipsEl.addEventListener("mousedown", (event) => {
    const button = event.target.closest(".input-tip");
    if (!button) return;
    event.preventDefault();
    applyInputTip(button.dataset.name || "");
  });
}

messagesEl.addEventListener("pointerdown", (event) => {
  if (event.target.closest(".trace-panel")) markTraceInteraction();
});

messagesEl.addEventListener("wheel", (event) => {
  if (event.target.closest(".trace-panel")) markTraceInteraction();
}, { passive: true });

messagesEl.addEventListener("scroll", () => {
  if (messagesEl.querySelector(".message.loading .trace-panel:hover")) markTraceInteraction();
}, { passive: true });

clearBtn.addEventListener("click", () => {
  if (currentConversationId) {
    deleteConversation(currentConversationId);
  } else {
    renderWelcome();
  }
  inputEl.focus();
});

newChatBtn.addEventListener("click", async () => {
  currentConversationId = "";
  localStorage.removeItem(CURRENT_CONVERSATION_KEY);
  renderWelcome();
  await loadConversations();
  inputEl.focus();
});

inputEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    formEl.requestSubmit();
  }
});

renderWelcome();
updateLocationStatus();
loadStatus();
detectIpLocation();
loadConversations().then(() => {
  if (currentConversationId) {
    loadConversation(currentConversationId).catch(() => {
      currentConversationId = "";
      localStorage.removeItem(CURRENT_CONVERSATION_KEY);
      renderWelcome();
    });
  }
});

// ====== Structured Card Rendering ======

function renderStructuredCardsInto(article, data) {
  const bubble = article.querySelector(".bubble");
  if (!bubble || !data) return;
  const html = buildStructuredCards(data);
  if (!html) return;
  const container = document.createElement("div");
  container.className = "structured-container";
  container.innerHTML = html;
  bubble.appendChild(container);
  initDraggableMaps(container);
}

function buildStructuredCards(data) {
  if (!data || typeof data !== "object") return "";
  let html = "";
  if (data.summary) {
    html += `<div class="card-section summary-card"><div class="summary-text">${escapeHtml(data.summary)}</div></div>`;
  }
  if (data.weather && data.weather.length) {
    html += renderWeatherCards(data.weather);
  }
  if (data.weather_alerts && data.weather_alerts.length) {
    html += renderWeatherAlertCards(data.weather_alerts);
  }
  if (data.daily_itinerary && data.daily_itinerary.length) {
    html += renderItineraryTimeline(data.daily_itinerary);
  }
  if (data.transport_options && data.transport_options.length) {
    html += renderTransportCards(data.transport_options);
  }
  if (data.budget && typeof data.budget.total === "number") {
    html += renderBudgetCard(data.budget);
  }
  if (data.tips && data.tips.length) {
    html += renderTipsList(data.tips);
  }
  if (data.poi_recommendations && data.poi_recommendations.length) {
    html += renderPoiCards(data.poi_recommendations);
  }
  return html;
}

function renderWeatherCards(weatherList) {
  const cards = weatherList.map(w => `
    <div class="weather-card">
      <div class="weather-card-header">
        <span class="weather-card-city">${escapeHtml(w.city || "")}</span>
        <span class="weather-card-date">${escapeHtml(w.date || "")}</span>
      </div>
      <div class="weather-card-body">
        <span class="weather-card-temp">${escapeHtml(w.temperature || "--")}</span>
        <span class="weather-card-condition">${escapeHtml(w.condition || "")}</span>
      </div>
      <div class="weather-card-details">
        <span>湿度 ${escapeHtml(w.humidity || "--")}</span>
        <span>风速 ${escapeHtml(w.wind || "--")}</span>
      </div>
    </div>
  `).join("");
  return `<div class="card-section"><h3 class="card-section-title">天气信息</h3><div class="weather-card-grid">${cards}</div></div>`;
}

function weatherAlertClass(alert) {
  const text = `${alert.severity || ""} ${alert.level || ""} ${alert.title || ""} ${alert.status || ""}`.toLowerCase();
  if (text.includes("red") || text.includes("红") || text.includes("严重")) return "danger";
  if (text.includes("orange") || text.includes("橙") || text.includes("较重")) return "orange";
  if (text.includes("yellow") || text.includes("黄") || text.includes("一般")) return "yellow";
  if (text.includes("blue") || text.includes("蓝")) return "blue";
  if (text.includes("no_active") || text.includes("无预警")) return "clear";
  if (text.includes("unavailable") || text.includes("不可用")) return "muted";
  return "default";
}

function renderWeatherAlertCards(alerts) {
  const cards = alerts.map(alert => {
    const kind = weatherAlertClass(alert);
    const title = alert.title || (alert.status === "no_active" ? "当前无天气灾害预警" : "天气预警");
    return `
      <div class="weather-alert-card alert-${kind}">
        <div class="weather-alert-head">
          <span class="weather-alert-badge">${escapeHtml(alert.severity || alert.level || alert.type || "预警")}</span>
          <span class="weather-alert-city">${escapeHtml(alert.city || "")}</span>
        </div>
        <h4>${escapeHtml(title)}</h4>
        <div class="weather-alert-meta">
          ${alert.type ? `<span>${escapeHtml(alert.type)}</span>` : ""}
          ${alert.pub_time ? `<span>${escapeHtml(alert.pub_time)}</span>` : ""}
          ${alert.data_source ? `<span>${escapeHtml(alert.data_source)}</span>` : ""}
        </div>
        ${alert.text ? `<p>${escapeHtml(alert.text)}</p>` : ""}
      </div>
    `;
  }).join("");
  return `<div class="card-section"><h3 class="card-section-title">天气预警</h3><div class="weather-alert-grid">${cards}</div></div>`;
}

function renderItineraryTimeline(itinerary) {
  const items = itinerary.map(d => `
    <div class="timeline-item">
      <div class="timeline-marker">D${escapeHtml(String(d.day))}</div>
      <div class="timeline-content">
        <h4 class="timeline-title">${escapeHtml(d.title || "")}</h4>
        ${d.activities && d.activities.length ? `<p class="timeline-activities"><strong>活动</strong> ${d.activities.map(a => escapeHtml(a)).join(" → ")}</p>` : ""}
        ${d.meals && d.meals.length ? `<p class="timeline-meals"><strong>餐饮</strong> ${d.meals.map(m => escapeHtml(m)).join("、")}</p>` : ""}
        ${d.accommodation ? `<p class="timeline-accommodation"><strong>住宿</strong> ${escapeHtml(d.accommodation)}</p>` : ""}
      </div>
    </div>
  `).join("");
  return `<div class="card-section"><h3 class="card-section-title">每日行程</h3><div class="timeline">${items}</div></div>`;
}

function transportCategory(option) {
  const raw = `${option.category || ""} ${option.mode || ""} ${option.notes || ""}`.toLowerCase();
  const text = `${option.category || ""} ${option.mode || ""} ${option.notes || ""}`;
  if (raw.includes("driving") || text.includes("驾车") || text.includes("自驾")) return "driving";
  if (raw.includes("interline") || text.includes("中转") || (Array.isArray(option.legs) && option.legs.length > 1)) return "interline";
  if (raw.includes("flight") || text.includes("航班") || /^[A-Z]{2}\s?\d+/.test(option.mode || "")) return "flight";
  if (raw.includes("train") || text.includes("高铁") || text.includes("动车") || /^[GDCZTK]\d+/.test(option.mode || "")) return "train";
  if (raw.includes("transit") || text.includes("地铁") || text.includes("公交")) return "transit";
  if (raw.includes("walking") || text.includes("步行")) return "walking";
  if (raw.includes("bicycling") || text.includes("骑行")) return "bicycling";
  if (raw.includes("traffic") || text.includes("路况") || text.includes("拥堵")) return "traffic";
  return "generic";
}

function transportIcon(category) {
  return {
    flight: "航",
    train: "铁",
    interline: "转",
    transit: "乘",
    walking: "步",
    bicycling: "骑",
    traffic: "堵",
    driving: "驾",
    generic: "行",
  }[category] || "行";
}

function transportLabel(category) {
  return {
    flight: "航班",
    train: "火车",
    interline: "中转火车",
    transit: "公交地铁",
    walking: "步行",
    bicycling: "骑行",
    traffic: "实时路况",
    driving: "驾车",
    generic: "交通",
  }[category] || "交通";
}

function isUsefulTransportValue(value) {
  const text = String(value || "").trim();
  if (!text) return false;
  if (["--", "-", "未知", "可用", "available", "null", "undefined"].includes(text.toLowerCase())) return false;
  return true;
}

function cleanTransportNote(note) {
  const text = String(note || "").trim();
  if (!text) return "";
  if (/Aviationstack/i.test(text) && /不提供票价|票价/.test(text)) {
    return "航班票价需以航司或购票平台为准";
  }
  if (/不支持按指定日期查询/.test(text)) {
    return "当前航班数据仅作近期班次参考";
  }
  return text;
}

function transportMetaChips(option) {
  const chips = [];
  if (isUsefulTransportValue(option.status) && !["success", "ok"].includes(String(option.status).toLowerCase())) {
    chips.push(option.status);
  }
  if (isUsefulTransportValue(option.departure_time) || isUsefulTransportValue(option.arrival_time)) {
    chips.push(`${isUsefulTransportValue(option.departure_time) ? option.departure_time : "--"} → ${isUsefulTransportValue(option.arrival_time) ? option.arrival_time : "--"}`);
  }
  return chips.map(chip => `<span>${escapeHtml(String(chip))}</span>`).join("");
}

function renderTransportLegs(legs) {
  if (!Array.isArray(legs) || !legs.length) return "";
  const items = legs.map((leg, index) => `
    <div class="transport-leg">
      <div class="transport-leg-index">${index + 1}</div>
      <div class="transport-leg-body">
        <div class="transport-leg-title">
          <strong>${escapeHtml(leg.mode || `第 ${index + 1} 段`)}</strong>
          ${leg.status ? `<span>${escapeHtml(leg.status)}</span>` : ""}
        </div>
        <div class="transport-leg-route">${escapeHtml(leg.from || "")} → ${escapeHtml(leg.to || "")}</div>
        <div class="transport-leg-meta">
          ${leg.departure_time || leg.arrival_time ? `<span>${escapeHtml(leg.departure_time || "--")} → ${escapeHtml(leg.arrival_time || "--")}</span>` : ""}
          ${leg.duration ? `<span>${escapeHtml(leg.duration)}</span>` : ""}
          ${leg.cost_estimate ? `<span>${escapeHtml(leg.cost_estimate)}</span>` : ""}
        </div>
        ${leg.notes ? `<div class="transport-leg-notes">${escapeHtml(leg.notes)}</div>` : ""}
      </div>
    </div>
  `).join("");
  return `<div class="transport-legs">${items}</div>`;
}

function renderTransportCards(transportList) {
  const cards = transportList.map(t => {
    const category = transportCategory(t);
    const note = cleanTransportNote(t.notes);
    return `
    <div class="transport-card transport-${category}">
      <div class="transport-card-head">
        <span class="transport-icon">${transportIcon(category)}</span>
        <div>
          <span class="transport-mode-badge">${escapeHtml(t.mode || transportLabel(category))}</span>
          <div class="transport-type-label">${transportLabel(category)}</div>
        </div>
      </div>
      <div class="transport-route">${escapeHtml(t.from || "")} → ${escapeHtml(t.to || "")}</div>
      ${transportMetaChips(t) ? `<div class="transport-meta-chips">${transportMetaChips(t)}</div>` : ""}
      <div class="transport-details">
        <div class="transport-detail"><span>时长</span><span>${escapeHtml(isUsefulTransportValue(t.duration) ? t.duration : "--")}</span></div>
        <div class="transport-detail"><span>费用/票价</span><span>${escapeHtml(isUsefulTransportValue(t.cost_estimate) ? t.cost_estimate : "--")}</span></div>
      </div>
      ${renderTransportLegs(t.legs)}
      ${note ? `<div class="transport-notes">${escapeHtml(note)}</div>` : ""}
    </div>
  `}).join("");
  return `<div class="card-section"><h3 class="card-section-title">交通方案</h3><div class="transport-grid">${cards}</div></div>`;
}

function renderBudgetCard(budget) {
  let rows = "";
  if (budget.breakdown && typeof budget.breakdown === "object") {
    rows = Object.entries(budget.breakdown).map(([key, val]) => `
      <div class="budget-row">
        <span class="budget-label">${escapeHtml(key)}</span>
        <span class="budget-value">${escapeHtml(String(val))} 元</span>
      </div>
    `).join("");
  }
  return `
    <div class="card-section"><h3 class="card-section-title">预算明细</h3>
      <div class="budget-card">
        ${rows}
        <div class="budget-row budget-total">
          <span class="budget-label">总计</span>
          <span class="budget-value">${escapeHtml(String(budget.total))} ${escapeHtml(budget.currency || "元")}</span>
        </div>
        ${budget.notes ? `<p class="budget-notes">${escapeHtml(budget.notes)}</p>` : ""}
      </div>
    </div>`;
}

function renderTipsList(tips) {
  const items = tips.map((t, i) => `
    <li class="tips-item">
      <span class="tips-num">${i + 1}</span>
      <span>${escapeHtml(t)}</span>
    </li>
  `).join("");
  return `<div class="card-section"><h3 class="card-section-title">出行提示</h3><ul class="tips-list">${items}</ul></div>`;
}

function renderPoiCards(categories) {
  if (!categories || !categories.length) return "";
  const sections = categories.map(cat => {
    const mapItems = (cat.items || []).filter((item) => item.location).slice(0, POI_MARKER_LABELS.length);
    const locations = mapItems.map((item) => item.location);
    const mapUrl = buildMapImageUrl(locations);
    const mapLegend = mapItems.length ? `
      <div class="poi-map-legend">
        ${mapItems.map((item, index) => `
          <span><b>${markerLabel(index)}</b>${escapeHtml(item.name || `地点${index + 1}`)}</span>
        `).join("")}
      </div>
    ` : "";
    const items = (cat.items || []).map((item, index) => `
      <div class="poi-card">
        ${index < POI_MARKER_LABELS.length && item.location ? `<span class="poi-card-index">${markerLabel(index)}</span>` : ""}
        <span class="poi-card-type">${escapeHtml(item.type || "")}</span>
        <h4 class="poi-card-name">${escapeHtml(item.name || "")}</h4>
        ${item.address ? `<p class="poi-card-address">${escapeHtml(item.address)}</p>` : ""}
        ${renderPoiMeta(item)}
      </div>
    `).join("");
    return `
      <div class="poi-category">
        <h4 class="poi-category-title">${escapeHtml(cat.category || "POI推荐")}</h4>
        ${mapUrl ? `
          <div class="poi-map-viewport" data-draggable-map>
            <img class="poi-map-preview" src="${escapeHtml(mapUrl)}" alt="${escapeHtml(cat.category || "地点")}地图预览" loading="lazy" referrerpolicy="no-referrer" draggable="false" onerror="this.closest('.poi-map-viewport').hidden=true">
          </div>
        ` : ""}
        ${mapLegend}
        <div class="poi-card-grid">${items}</div>
      </div>
    `;
  }).join("");
  return `<div class="card-section"><h3 class="card-section-title">地点推荐</h3><div class="poi-categories">${sections}</div></div>`;
}

function renderPoiMeta(item) {
  const chips = [];
  if (item.rating) chips.push(`评分 ${item.rating}`);
  if (item.cost) chips.push(`人均 ${item.cost}`);
  if (item.tel) chips.push(item.tel);
  if (item.location) chips.push(item.location);
  if (!chips.length && !item.photo_url && !item.map_url) return "";
  return `
    <div class="poi-card-meta">
      ${chips.map(chip => `<span>${escapeHtml(String(chip))}</span>`).join("")}
      ${item.map_url ? `<a href="${escapeHtml(item.map_url)}" target="_blank" rel="noreferrer">地图</a>` : ""}
      ${item.photo_url ? `<a href="${escapeHtml(item.photo_url)}" target="_blank" rel="noreferrer">图片</a>` : ""}
    </div>
  `;
}
