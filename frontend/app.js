const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

const state = {
  apiBaseUrl: "",
  health: null,
  chatHistory: [],
  introShown: false,
};

const elements = {
  chatCard: document.getElementById("chat-card"),
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
  if (
    ["127.0.0.1", "localhost"].includes(window.location.hostname) &&
    window.location.port !== "8000"
  ) {
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

function kindLabel(kind) {
  return (
    {
      product: "Sản phẩm",
      policy: "Chính sách",
      contact: "Liên hệ",
    }[kind] || "Nguồn"
  );
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

function answerToHtml(answer) {
  const lines = String(answer ?? "")
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
    chunks.push(
      `<ul class="message-list">${bullets
        .map((item) => `<li>${escapeHtml(item)}</li>`)
        .join("")}</ul>`
    );
    bullets = [];
  };

  for (const line of lines) {
    if (line.startsWith("- ")) {
      bullets.push(line.slice(2).trim());
      continue;
    }

    flushBullets();
    chunks.push(`<p>${escapeHtml(line)}</p>`);
  }

  flushBullets();
  return chunks.join("");
}

function renderSources(sources) {
  const productSources = (sources || []).filter((source) => source.kind === "product");

  if (!productSources.length) {
    return "";
  }

  return `
    <div class="source-stack">
      ${productSources
        .slice(0, 3)
        .map(
          (source) => `
            <article class="source-card">
              <div class="source-card__top">
                <span class="badge">${escapeHtml(source.id || "S")}</span>
                <span class="source-kind">${escapeHtml(kindLabel(source.kind))}</span>
              </div>
              <strong>${escapeHtml(source.title || "Nguồn tham chiếu")}</strong>
              ${source.snippet ? `<p>${escapeHtml(source.snippet)}</p>` : ""}
              ${
                source.url
                  ? `<a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">Mở nguồn</a>`
                  : ""
              }
            </article>
          `
        )
        .join("")}
    </div>
  `;
}

function resolveDisplayAttachments(attachments, sources) {
  if (attachments?.length) {
    return attachments;
  }

  return (sources || [])
    .filter((source) => source.kind === "product" && source.imageUrl)
    .slice(0, 3)
    .map((source) => ({
      type: "image",
      title: source.title,
      imageUrl: source.imageUrl,
      linkUrl: source.url || "",
    }));
}

function renderMessageTitle(role) {
  if (role === "user") {
    return `<p class="message-title">Bạn</p>`;
  }
  return `<p class="message-title">Trợ lý</p>`;
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
                ${
                  attachment.linkUrl
                    ? `<a href="${escapeHtml(attachment.linkUrl)}" target="_blank" rel="noreferrer">Xem sản phẩm</a>`
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

function addMessage(role, options) {
  const node = document.createElement("article");
  const displayAttachments = resolveDisplayAttachments(options.attachments, options.sources);
  node.className = `message message--${role} ${options.pending ? "message--pending" : ""}`.trim();
  node.innerHTML = `
    ${renderMessageTitle(role)}
    ${options.html}
    ${renderAttachments(displayAttachments)}
    ${renderSources(options.sources)}
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
    ${renderSources(options.sources)}
    ${options.meta ? `<p class="message-footnote">${escapeHtml(options.meta)}</p>` : ""}
  `;
  elements.chatMessages.scrollTop = elements.chatMessages.scrollHeight;
}

function buildResponseMeta(payload) {
  const parts = [];
  if (payload?.scope) {
    parts.push(scopeLabel(payload.scope));
  }
  if (payload?.usedModel) {
    parts.push(payload.usedModel);
  }
  return parts.join(" • ");
}

function setChatLoading(isLoading) {
  elements.chatInput.disabled = isLoading;
  elements.chatSubmit.disabled = isLoading;
  elements.chatSubmit.textContent = isLoading ? "Đang gửi..." : "Gửi câu hỏi";
}

function setStatus(health) {
  const badge = elements.statusBadge;
  badge.className = "status-badge";

  if (!health) {
    badge.classList.add("status-badge--offline");
    badge.textContent = "Backend chưa kết nối";
    elements.statusDetail.textContent =
      "Hãy chạy python backend/server.py rồi mở lại trang để frontend gọi được API.";
    elements.modeText.textContent = "Offline";
    elements.scopeText.textContent = "Chưa có dữ liệu";
    elements.statsText.textContent = "0 sản phẩm • 0 chính sách";
    return;
  }

  if (health.chatMode === "local-grounded") {
    badge.classList.add("status-badge--fallback");
    badge.textContent = "Backend đang chạy • local grounded";
  } else if (health.apiConfigured) {
    badge.classList.add("status-badge--ok");
    badge.textContent = "Backend sẵn sàng • Gemini grounded";
  } else {
    badge.classList.add("status-badge--warn");
    badge.textContent = "Backend sẵn sàng";
  }

  const totalProducts = health.sourceStats?.products ?? 0;
  const totalPolicies = health.sourceStats?.policies ?? 0;

  elements.statusDetail.textContent = `Model: ${health.model} • Scope mode: ${health.scopeMode}`;
  elements.modeText.textContent = health.chatMode || "grounded";
  elements.scopeText.textContent = health.scopeMode || "strict_bakery";
  elements.statsText.textContent = `${totalProducts} sản phẩm • ${totalPolicies} chính sách`;
}

function updateShowcase(health) {
  const info = health?.storeInfo || {};

  elements.brandName.textContent = health?.brand || "Nguyễn Sơn Bakery Chatbot";
  elements.storePhone.textContent = info.phone || "Chưa có";
  elements.storeHours.textContent = info.openingHours || "Chưa có";
  elements.storeAddress.textContent = info.address || "Chưa có";
}

function renderPrompts(prompts) {
  const safePrompts = prompts?.length
    ? prompts
    : [
        "Có bánh nào dưới 50k không?",
        "Các món được yêu thích",
        "Cho mình xem vài loại cookies nhé",
      ];

  elements.promptList.innerHTML = safePrompts
    .slice(0, 6)
    .map(
      (prompt) =>
        `<button type="button" class="prompt-chip" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`
    )
    .join("");
}

function buildIntroMessage() {
  const health = state.health;
  if (!health?.storeInfo) {
    return `
      <p>Xin chào, mình là trợ lý tư vấn của cửa hàng bánh.</p>
      <p>Bạn có thể hỏi về sản phẩm, giá, chính sách hoặc yêu cầu xem ảnh sản phẩm.</p>
    `;
  }

  const info = health.storeInfo;
  return `
    <p>${escapeHtml(health.welcomeMessage || "Xin chào, mình là trợ lý tư vấn của cửa hàng.")}</p>
    <ul class="message-list">
      <li>Địa chỉ: ${escapeHtml(info.address || "Chưa có")}</li>
      <li>Giờ mở cửa: ${escapeHtml(info.openingHours || "Chưa có")}</li>
      <li>Hotline: ${escapeHtml(info.phone || "Chưa có")}</li>
    </ul>
  `;
}

function buildIntroHistoryText() {
  const health = state.health;
  if (!health?.storeInfo) {
    return "Xin chào, mình là trợ lý tư vấn của cửa hàng bánh. Bạn có thể hỏi về sản phẩm, giá, chính sách hoặc yêu cầu xem ảnh sản phẩm.";
  }

  const info = health.storeInfo;
  return [
    health.welcomeMessage || "Xin chào, mình là trợ lý tư vấn của cửa hàng.",
    `Địa chỉ: ${info.address || "Chưa có"}`,
    `Giờ mở cửa: ${info.openingHours || "Chưa có"}`,
    `Hotline: ${info.phone || "Chưa có"}`,
  ].join("\n");
}

function ensureIntro() {
  if (state.introShown) {
    return;
  }

  state.introShown = true;
  state.chatHistory.push({
    role: "assistant",
    content: buildIntroHistoryText(),
  });

  addMessage("assistant", {
    html: buildIntroMessage(),
    meta: state.health ? buildResponseMeta({ scope: "grounded", usedModel: state.health.chatMode }) : "",
  });
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

    const health = await response.json();
    state.health = health;
    ensureIntro();
  } catch (error) {
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
    replaceMessage(pending, {
      html: answerToHtml(payload.answer),
      attachments: payload.attachments,
      sources: payload.sources,
      meta: buildResponseMeta(payload),
    });

    state.chatHistory.push({ role: "assistant", content: payload.answer || "" });
  } catch (error) {
    replaceMessage(pending, {
      html: `
        <p>Hiện chưa gọi được backend chat.</p>
        <p>Hãy kiểm tra lại server local rồi thử lại nhé.</p>
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

  sendChat(query);
  elements.chatInput.value = "";
  autoResizeTextarea();
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
}

async function init() {
  state.apiBaseUrl = resolveApiBaseUrl();
  bindEvents();
  autoResizeTextarea();
  await loadHealth();
}

init();
