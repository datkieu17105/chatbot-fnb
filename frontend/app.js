const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

const state = {
  apiBaseUrl: "",
  health: null,
  chatHistory: [],
  introShown: false,
};

const elements = {
  brandName: document.getElementById("brand-name"),
  statusBadge: document.getElementById("status-badge"),
  statusDetail: document.getElementById("status-detail"),
  promptList: document.getElementById("prompt-list"),
  chatMessages: document.getElementById("chat-messages"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  chatSubmit: document.getElementById("chat-submit"),
  clearChat: document.getElementById("clear-chat"),
};

function resolveApiBaseUrl() {
  const configured = String(window.__CHATBOT_CONFIG__?.apiBaseUrl ?? "").trim();
  if (configured) {
    return configured.replace(/\/$/, "");
  }
  if (window.location.protocol === "file:") {
    return DEFAULT_API_BASE_URL;
  }
  if (["127.0.0.1", "localhost"].includes(window.location.hostname) && window.location.port.startsWith("55")) {
    return DEFAULT_API_BASE_URL;
  }
  return "";
}

function apiUrl(path) {
  return state.apiBaseUrl ? `${state.apiBaseUrl}${path}` : path;
}

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function scopeLabel(scope) {
  return (
    {
      grounded: "Grounded",
      partial: "Partial",
      out_of_scope: "Out of scope",
      general: "General",
    }[scope] || "Grounded"
  );
}

function kindLabel(kind) {
  return (
    {
      product: "Sản phẩm",
      policy: "Chính sách",
      contact: "Liên hệ",
    }[kind] || "Nguồn"
  );
}

function answerToHtml(answer) {
  const cleanedAnswer = String(answer ?? "").replace(/\s*\[S\d+\]/g, "");
  const lines = cleanedAnswer
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);

  if (!lines.length) {
    return "<p>Chưa có nội dung trả lời.</p>";
  }

  const chunks = [];
  let bullets = [];

  const flushBullets = () => {
    if (!bullets.length) {
      return;
    }
    chunks.push(`<ul class="message-list">${bullets.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`);
    bullets = [];
  };

  for (const line of lines) {
    const bulletMatch = line.match(/^[-*]\s+(.+)$/);
    if (bulletMatch) {
      bullets.push(bulletMatch[1].trim());
      continue;
    }
    flushBullets();
    chunks.push(`<p>${escapeHtml(line)}</p>`);
  }

  flushBullets();
  return chunks.join("");
}

function productCardIntroHtml(answer) {
  const firstLine = String(answer ?? "")
    .replace(/\s*\[S\d+\]/g, "")
    .split(/\n+/)
    .map((line) => line.trim())
    .find((line) => line && !/^[-*]\s+/.test(line));

  return `<p>${escapeHtml(firstLine || "Mình gợi ý vài lựa chọn phù hợp với nhu cầu của bạn:")}</p>`;
}

function renderSources(sources, options = {}) {
  const visibleSources = (sources || [])
    .filter((source) => !options.skipProductSources || source.kind !== "product")
    .filter((source) => source.kind !== "policy")
    .filter((source) => source.title || source.snippet)
    .slice(0, 4);
  if (!visibleSources.length) {
    return "";
  }

  return `
    <div class="source-stack" aria-label="Nguồn tham chiếu">
      ${visibleSources
        .map(
          (source) => `
            <article class="source-card">
              <div class="source-card__top">
                <span class="source-kind">${escapeHtml(kindLabel(source.kind))}</span>
                <span class="badge">${escapeHtml(source.id || "S")}</span>
              </div>
              <strong>${escapeHtml(source.title || "Nguồn tham chiếu")}</strong>
              ${source.snippet ? `<p>${escapeHtml(source.snippet)}</p>` : ""}
              ${source.url ? `<a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">Mở nguồn</a>` : ""}
            </article>
          `
        )
        .join("")}
    </div>
  `;
}

function resolveDisplayAttachments(attachments, sources) {
  if (attachments?.length) {
    return attachments.map((attachment) => ({ ...attachment, summary: "" }));
  }

  return (sources || [])
    .filter((source) => source.kind === "product" && source.imageUrl)
    .slice(0, 3)
    .map((source) => ({
      title: source.title,
      imageUrl: source.imageUrl,
      linkUrl: source.url || "",
      summary: "",
    }));
}

function renderAttachments(attachments) {
  if (!attachments?.length) {
    return "";
  }
  return `
    <div class="attachment-grid">
      ${attachments
        .map(
          (attachment) => `
            <article class="attachment-card">
              <img src="${escapeHtml(attachment.imageUrl)}" alt="${escapeHtml(attachment.title)}" loading="lazy" />
              <div class="attachment-card__body">
                <strong>${escapeHtml(attachment.title)}</strong>
                ${attachment.summary ? `<p>${escapeHtml(attachment.summary)}</p>` : ""}
                ${
                  attachment.linkUrl
                    ? `<a href="${escapeHtml(attachment.linkUrl)}" target="_blank" rel="noreferrer">Chi tiết</a>`
                    : ""
                }
              </div>
            </article>
          `
        )
        .join("")}
    </div>
  `;
}

function buildResponseMeta(payload) {
  return "";
}

function renderMessageTitle(role) {
  return `<p class="message-title">${role === "user" ? "Bạn" : "Trợ lý"}</p>`;
}

function addMessage(role, options) {
  const node = document.createElement("article");
  const displayAttachments = resolveDisplayAttachments(options.attachments, options.sources);
  node.className = `message message--${role} ${options.pending ? "message--pending" : ""}`.trim();
  node.innerHTML = `
    ${renderMessageTitle(role)}
    ${options.html}
    ${renderAttachments(displayAttachments)}
    ${renderSources(options.sources, { skipProductSources: displayAttachments.length > 0 })}
    ${options.meta ? `<p class="message-footnote">${escapeHtml(options.meta)}</p>` : ""}
  `;
  elements.chatMessages.appendChild(node);
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
  return node;
}

function replaceMessage(node, options) {
  const displayAttachments = resolveDisplayAttachments(options.attachments, options.sources);
  node.className = `message message--assistant ${options.pending ? "message--pending" : ""}`.trim();
  node.innerHTML = `
    ${renderMessageTitle("assistant")}
    ${options.html}
    ${renderAttachments(displayAttachments)}
    ${renderSources(options.sources, { skipProductSources: displayAttachments.length > 0 })}
    ${options.meta ? `<p class="message-footnote">${escapeHtml(options.meta)}</p>` : ""}
  `;
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

function setStatus(health) {
  elements.statusBadge.className = "status-badge";

  if (!health) {
    elements.statusBadge.classList.add("status-badge--offline");
    elements.statusBadge.textContent = "Chưa kết nối";
    elements.statusDetail.textContent = "";
    return;
  }

  if (health.chatMode === "local-grounded") {
    elements.statusBadge.classList.add("status-badge--fallback");
    elements.statusBadge.textContent = "Sẵn sàng";
  } else if (health.apiConfigured) {
    elements.statusBadge.classList.add("status-badge--ok");
    elements.statusBadge.textContent = "Sẵn sàng";
  } else {
    elements.statusBadge.classList.add("status-badge--warn");
    elements.statusBadge.textContent = "Sẵn sàng";
  }

  elements.statusDetail.textContent = "";
}

function updateStoreInfo(health) {
  elements.brandName.textContent = health?.brand || "Nguyễn Sơn Bakery";
}

function renderPrompts(prompts) {
  const safePrompts = prompts?.length
    ? prompts
    : [
        "Có bánh nào dưới 50k không?",
        "Các món được yêu thích?",
        "Cho mình xem ảnh bánh croissant",
        "Shop giao hàng như thế nào?",
      ];

  elements.promptList.innerHTML = safePrompts
    .slice(0, 4)
    .map((prompt) => `<button type="button" class="prompt-chip" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`)
    .join("");
}

function buildIntroMessage() {
  const health = state.health;
  if (!health?.storeInfo) {
    return `
      <p>Xin chào, mình là trợ lý tư vấn của cửa hàng bánh.</p>
      <p>Bạn cần tìm loại bánh nào hoặc muốn xem ảnh sản phẩm nào?</p>
    `;
  }

  return `
    <p>${escapeHtml(health.welcomeMessage || "Xin chào, mình là trợ lý tư vấn của cửa hàng.")}</p>
    <p>Bạn có thể hỏi về loại bánh, mức giá, giao hàng hoặc yêu cầu xem ảnh sản phẩm.</p>
  `;
}

function buildIntroHistoryText() {
  const health = state.health;
  if (!health?.storeInfo) {
    return "Xin chào, mình là trợ lý tư vấn của cửa hàng bánh. Bạn cần mình hỗ trợ gì?";
  }
  return health.welcomeMessage || "Xin chào, mình là trợ lý tư vấn của cửa hàng. Bạn cần mình hỗ trợ gì?";
}

function ensureIntro() {
  if (state.introShown) {
    return;
  }
  state.introShown = true;
  state.chatHistory.push({ role: "assistant", content: buildIntroHistoryText() });
  addMessage("assistant", {
    html: buildIntroMessage(),
    meta: state.health ? buildResponseMeta({ scope: "grounded", usedModel: state.health.chatMode }) : "",
  });
}

function setChatLoading(isLoading) {
  elements.chatInput.disabled = isLoading;
  elements.chatSubmit.disabled = isLoading;
  elements.chatSubmit.textContent = isLoading ? "Đang gửi..." : "Gửi";
}

function resetConversation() {
  elements.chatMessages.innerHTML = "";
  state.chatHistory = [];
  state.introShown = false;
  ensureIntro();
  elements.chatInput.value = "";
  autoResizeTextarea();
  elements.chatInput.focus();
}

async function loadHealth() {
  try {
    const response = await fetch(apiUrl(`/api/health?ts=${Date.now()}`), {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    state.health = await response.json();
    setStatus(state.health);
    updateStoreInfo(state.health);
    renderPrompts(state.health.prompts);
    ensureIntro();
  } catch (error) {
    setStatus(null);
    renderPrompts([]);
    addMessage("assistant", {
      html: `
        <p>Frontend chưa gọi được backend.</p>
        <p>Hãy chạy <strong>python backend/server.py</strong> rồi mở lại trang tại <strong>http://127.0.0.1:8000</strong>.</p>
      `,
      meta: String(error.message || error),
    });
  }
}

async function sendChat(query) {
  const trimmed = query.trim();
  if (!trimmed) {
    return;
  }

  ensureIntro();
  addMessage("user", { html: `<p>${escapeHtml(trimmed)}</p>` });
  state.chatHistory.push({ role: "user", content: trimmed });

  const pending = addMessage("assistant", {
    html: "<p>Đang xử lý câu hỏi...</p>",
    pending: true,
  });

  setChatLoading(true);

  try {
    const response = await fetch(apiUrl("/api/chat"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({
        message: trimmed,
        history: state.chatHistory.slice(-8),
      }),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const payload = await response.json();
    payload.answer = String(payload.answer || "").replace(/\s*\[S\d+\]/g, "");
    const hasProductCards =
      (payload.attachments || []).length > 0 ||
      (payload.sources || []).some((source) => source.kind === "product" && source.imageUrl);
    replaceMessage(pending, {
      html: hasProductCards ? productCardIntroHtml(payload.answer) : answerToHtml(payload.answer),
      attachments: payload.attachments,
      sources: payload.sources,
      meta: buildResponseMeta(payload),
    });
    state.chatHistory.push({ role: "assistant", content: payload.answer || "" });
  } catch (error) {
    replaceMessage(pending, {
      html: `
        <p>Hiện chưa gọi được backend chat.</p>
        <p>Hãy kiểm tra lại server local rồi thử lại.</p>
      `,
      meta: String(error.message || error),
    });
  } finally {
    setChatLoading(false);
    elements.chatInput.focus();
  }
}

function submitCurrentInput() {
  const query = elements.chatInput.value.trim();
  if (!query) {
    return;
  }
  elements.chatInput.value = "";
  autoResizeTextarea();
  sendChat(query);
}

function autoResizeTextarea() {
  elements.chatInput.style.height = "0px";
  elements.chatInput.style.height = `${Math.min(elements.chatInput.scrollHeight, 220)}px`;
}

function bindEvents() {
  elements.chatForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitCurrentInput();
  });

  elements.chatInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || event.shiftKey || event.isComposing) {
      return;
    }
    event.preventDefault();
    submitCurrentInput();
  });

  elements.chatInput.addEventListener("input", autoResizeTextarea);
  elements.clearChat.addEventListener("click", resetConversation);
  elements.promptList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-prompt]");
    if (!button) {
      return;
    }
    elements.chatInput.value = button.dataset.prompt || "";
    autoResizeTextarea();
    submitCurrentInput();
  });
}

async function init() {
  state.apiBaseUrl = resolveApiBaseUrl();
  bindEvents();
  autoResizeTextarea();
  await loadHealth();
}

init();

