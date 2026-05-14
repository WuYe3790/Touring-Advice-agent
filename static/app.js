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
const conversationListEl = document.querySelector("#conversationList");
const newChatBtn = document.querySelector("#newChatBtn");
const CURRENT_CONVERSATION_KEY = "travel_agent_current_conversation_id";
let currentConversationId = localStorage.getItem(CURRENT_CONVERSATION_KEY) || "";
let activeController = null;

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
    bubble.appendChild(renderTrace(trace, true));
  }
  bubble.dataset.rawText = text;
  messagesEl.scrollTop = messagesEl.scrollHeight;
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
  return trace.length ? `执行过程：${status}` : "执行过程：等待智能体行动";
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
    const titleText = item.type === "llm_response"
      ? `模型响应：${item.model || "unknown"}`
      : item.type === "tool_result"
        ? `工具返回：${item.tool || "unknown"}`
        : `调用工具：${item.tool || "unknown"}`;

    const args = JSON.stringify(item.args || {}, null, 2);
    const usage = summarizeUsage(item.usage);
    row.innerHTML = `
      <div class="trace-title">
        <span>${traceLabel(item)}</span>
        <strong>${escapeHtml(titleText)}</strong>
        <em class="trace-status">${traceStatusLabel(status)}</em>
        ${timeText ? `<em class="trace-time">${escapeHtml(timeText)}</em>` : ""}
      </div>
      ${item.type === "tool_call" ? `<pre>${escapeHtml(args)}</pre>` : ""}
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
  } catch {
    modelName.textContent = "读取失败";
    thinkingModelName.textContent = "读取失败";
    keyStatus.textContent = "未知";
    if (amapStatus) amapStatus.textContent = "未知";
    if (qweatherStatus) qweatherStatus.textContent = "未知";
  }
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
          if (data.message) {
            latestStatus = data.message;
          } else if (data.phase === "tool_call" || item.type === "tool_call") {
            latestStatus = `正在调用工具：${item.tool || "unknown"}`;
          } else if (data.phase === "tool_result" || item.type === "tool_result") {
            latestStatus = `工具结果已返回：${item.tool || "unknown"}`;
          } else if (data.phase === "llm_response" || item.type === "llm_response") {
            latestStatus = `模型阶段完成：${item.model || "unknown"}`;
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
loadStatus();
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

function renderTransportCards(transportList) {
  const cards = transportList.map(t => `
    <div class="transport-card">
      <span class="transport-mode-badge">${escapeHtml(t.mode || "")}</span>
      <div class="transport-route">${escapeHtml(t.from || "")} → ${escapeHtml(t.to || "")}</div>
      <div class="transport-details">
        <div class="transport-detail"><span>时长</span><span>${escapeHtml(t.duration || "--")}</span></div>
        <div class="transport-detail"><span>预估费用</span><span>${escapeHtml(t.cost_estimate || "--")}</span></div>
      </div>
      ${t.notes ? `<div class="transport-notes">${escapeHtml(t.notes)}</div>` : ""}
    </div>
  `).join("");
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
