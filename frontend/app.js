// Bu yerga AWS serveringiz IP manzilini yozing, agar index.html faylini
// to‘g‘ridan-to‘g‘ri file:// orqali ochsangiz.
const CONFIGURED_API_BASE_URL = "http://<AWS_IP>:8000";
const API_BASE_URL =
  window.location.protocol === "file:" ? CONFIGURED_API_BASE_URL : window.location.origin;

const state = {
  sources: [],
  messages: [],
  socket: null,
  reconnectDelay: 1000,
  reconnectTimer: null,
  replyFiles: {}, // messageId -> [{name, mime, data_b64}]
  activeTab: "inbox", // "inbox" | "archive"
  archiveSearch: "",
  selectedIds: new Set(),
  counts: { telegram_unread: 0, email_unread: 0, archived: 0, opportunity_unread: 0 },
  archiveSettings: { archive_on_read: true, archive_on_reply: true, auto_archive_days: 0 },
  autoReplyEnabled: false,
  section: "telegram", // "telegram" | "email" | "opportunity"
  email: { accounts: [], messages: [], presets: [], tab: "inbox", expanded: new Set() },
  opp: {
    tab: "feed", // feed | channels | profile | settings | groups | test
    feedTab: "inbox", // inbox | archive
    feed: [],
    channels: [],
    groups: [],
    profile: null,
    settings: null,
    status: null,
    delivery: null,
  },
};

const OPP_INTERESTS = ["IT", "Til", "Fan", "Biznes", "Debat", "Liderlik", "Madaniyat", "San'at"];

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showError(message) {
  const box = $("#global-error");
  box.textContent = message;
  box.classList.remove("hidden");
}

function clearError() {
  $("#global-error").classList.add("hidden");
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = `Server xatosi (${response.status})`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

function formatTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("uz-UZ", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function sourceTypeLabel(type) {
  return { user: "Odam", group: "Guruh", channel: "Kanal" }[type] || type;
}

function renderSources() {
  $("#source-count").textContent = state.sources.length;
  const list = $("#source-list");
  if (!state.sources.length) {
    list.innerHTML = '<div class="empty-state small">Hali manba qo‘shilmagan.</div>';
    return;
  }
  list.innerHTML = state.sources
    .map(
      (source) => `
        <div class="source-item">
          <div class="source-row">
            <span class="source-name" title="${escapeHtml(source.display_name)}">${escapeHtml(source.display_name)}</span>
            <button class="toggle ${source.is_active ? "active" : ""}" data-action="toggle" data-id="${source.id}" aria-label="Faollikni o‘zgartirish"></button>
          </div>
          <div class="source-identifier">${escapeHtml(source.identifier)}</div>
          <div class="source-actions">
            <span class="source-type">${sourceTypeLabel(source.type)}</span>
            <button class="delete-button" data-action="delete" data-id="${source.id}">O‘chirish</button>
          </div>
        </div>
      `,
    )
    .join("");
}

function linkify(text) {
  const escaped = escapeHtml(text);
  return escaped.replace(/(https?:\/\/[^\s<]+)/g, (url) => {
    return `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`;
  });
}

function mediaMarkup(message) {
  if (!message.has_media_file) {
    return message.media_type ? `<span class="media-label">📎 ${escapeHtml(message.media_type)}</span>` : "";
  }
  const url = `${API_BASE_URL}/api/media/${message.id}`;
  const mime = message.media_mime || "";
  if (mime.startsWith("image/")) {
    return `<img class="message-media" src="${url}" alt="Rasm" loading="lazy" />`;
  }
  if (mime.startsWith("video/")) {
    return `<video class="message-media" src="${url}" controls preload="none"></video>`;
  }
  if (mime.startsWith("audio/")) {
    return `<audio src="${url}" controls></audio>`;
  }
  return `<a class="media-download" href="${url}" target="_blank" rel="noopener noreferrer">📎 ${escapeHtml(message.media_name || "Faylni yuklab olish")}</a>`;
}

// Stage 4: Xulosa/Holat/Tavsiya/Tahlil — bitta joyda, har yerda qayta ishlatiladi.
const HOLAT_CLASS = { Bepul: "holat-bepul", Pullik: "holat-pullik", Shubhali: "holat-shubhali", Muhim: "holat-muhim" };
const TAVSIYA_CLASS = {
  "E'tiborsiz qoldirish": "tavsiya-ignore",
  "Xabardor qilish": "tavsiya-notify",
  "Darhol javob berish": "tavsiya-urgent",
};

function dashboardCardMarkup(dashboard, title) {
  if (!dashboard || !dashboard.xulosa) return "";
  const holatClass = HOLAT_CLASS[dashboard.holat] || "holat-shubhali";
  const tavsiyaClass = TAVSIYA_CLASS[dashboard.tavsiya] || "tavsiya-notify";
  const tahlil = Array.isArray(dashboard.tahlil) ? dashboard.tahlil : [];
  return `
    <div class="dashboard-card">
      ${title ? `<div class="dashboard-card-title">${escapeHtml(title)}</div>` : ""}
      <div class="dashboard-row dashboard-xulosa">${escapeHtml(dashboard.xulosa)}</div>
      <div class="dashboard-row dashboard-badges">
        <span class="dashboard-badge ${holatClass}">Holat: ${escapeHtml(dashboard.holat)}</span>
        <span class="dashboard-badge ${tavsiyaClass}">Tavsiya: ${escapeHtml(dashboard.tavsiya)}</span>
      </div>
      ${tahlil.length ? `<ul class="dashboard-tahlil">${tahlil.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
    </div>`;
}

const TRIAGE_LABELS = { 0: "Spam", 1: "Info", 2: "🔔 Bildirishnoma", 3: "🚨 Muhim" };

function triageBadgeMarkup(message) {
  const level = message.triage_level;
  if (level === null || level === undefined) return "";
  const label = TRIAGE_LABELS[level] || `Daraja ${level}`;
  return `<span class="triage-badge level-${level}" title="${escapeHtml(message.triage_reason || "")}">${label}</span>`;
}

function renderMessages() {
  const list = $("#message-list");
  if (!state.messages.length) {
    list.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">✦</div>
        <strong>${state.activeTab === "archive" ? "Arxiv bo‘sh" : "Muhim xabarlar shu yerda ko‘rinadi"}</strong>
        <span>${state.activeTab === "archive" ? "Arxivlangan xabarlar shu yerda ko‘rinadi." : "Manba qo‘shing va Telegram'dan yangi xabar kuting."}</span>
      </div>`;
    updateBulkBar();
    return;
  }
  const isArchiveTab = state.activeTab === "archive";
  list.innerHTML = state.messages
    .map((message) => {
      const isOut = message.direction === "out";
      const checked = state.selectedIds.has(message.id) ? "checked" : "";
      return `
        <article class="message-card ${message.is_read ? "" : "unread"} ${isOut ? "outgoing" : ""}" data-message-id="${message.id}">
          <div class="message-meta">
            <label class="select-checkbox-label">
              <input type="checkbox" class="select-checkbox" data-action="select" data-id="${message.id}" ${checked} />
            </label>
            <span class="message-source">${isOut ? '<span class="direction-tag">Siz</span> ' : ""}${escapeHtml(message.source_display_name)}</span>
            ${triageBadgeMarkup(message)}
            <time>${escapeHtml(formatTime(message.received_at))}</time>
          </div>
          <div class="message-sender">${escapeHtml(message.sender_name)}</div>
          <div class="message-text">${message.text ? linkify(message.text) : "Media xabar"}</div>
          ${mediaMarkup(message)}
          ${dashboardCardMarkup(message.media_analysis, "Media tahlili")}
          <div class="message-footer">
            <span class="media-label">${!message.has_media_file && message.media_type ? `📎 ${escapeHtml(message.media_type)}` : ""}</span>
            <span class="footer-actions">
              ${!isOut ? `<button class="reply-toggle-button" data-action="reply-toggle" data-id="${message.id}">Javob</button>` : ""}
              ${message.is_read ? "" : `<button class="read-button" data-action="read" data-id="${message.id}">O‘qildi deb belgilash</button>`}
              ${isArchiveTab
                ? `<button class="archive-toggle-button" data-action="unarchive" data-id="${message.id}">Qaytarish</button>`
                : `<button class="archive-toggle-button" data-action="archive" data-id="${message.id}">Arxivga</button>`}
            </span>
          </div>
          <div class="reply-panel hidden" id="reply-panel-${message.id}">
            <textarea class="reply-textarea" placeholder="Javob yozing... (Ctrl/Cmd+Enter — yuborish)" rows="2"></textarea>
            <div class="reply-files"></div>
            <div class="reply-controls">
              <label class="file-picker-label">
                <input type="file" class="reply-file-input" multiple accept="image/*,video/*,.pdf,.zip,.txt" hidden />
                📎 Fayl
              </label>
              <label class="as-document-label">
                <input type="checkbox" class="as-document-checkbox" /> Hujjat sifatida
              </label>
              <button class="primary-button reply-send-button" data-action="reply-send" data-id="${message.id}">Yuborish</button>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
  updateBulkBar();
}

async function loadCounts() {
  try {
    state.counts = await api("/api/messages/counts");
  } catch (error) {
    // Non-fatal: counts are cosmetic.
  }
  try {
    const notifs = await api("/api/notifications?limit=100");
    state.counts.notifications_unread = notifs.filter((m) => !m.is_read).length;
  } catch (error) {
    // Non-fatal.
  }
  renderTabBadges();
  updateDocumentTitle();
}

function renderTabBadges() {
  $("#tab-inbox-count").textContent = state.counts.telegram_unread;
  $("#tab-archive-count").textContent = state.counts.archived;
  $("#section-telegram-count").textContent = state.counts.telegram_unread;
  $("#section-email-count").textContent = state.counts.email_unread;
  $("#email-tab-inbox-count").textContent = state.counts.email_unread;
  $("#section-opportunity-count").textContent = state.counts.opportunity_unread || 0;
  $("#opp-tab-feed-count").textContent = state.counts.opportunity_unread || 0;
  $("#section-notifications-count").textContent = state.counts.notifications_unread || 0;
}

function updateDocumentTitle() {
  const unread =
    (state.counts.telegram_unread || 0) +
    (state.counts.email_unread || 0) +
    (state.counts.opportunity_unread || 0);
  document.title = unread > 0 ? `(${unread}) Telegram Focus` : "Telegram Focus";
}

async function loadData() {
  clearError();
  try {
    const messagesQuery =
      state.activeTab === "archive"
        ? `/api/messages?limit=100&archived=true&channel=telegram${state.archiveSearch ? `&search=${encodeURIComponent(state.archiveSearch)}` : ""}`
        : "/api/messages?limit=100&archived=false&channel=telegram";
    const [sources, messages] = await Promise.all([api("/api/sources"), api(messagesQuery)]);
    state.sources = sources;
    state.messages = messages;
    renderSources();
    renderMessages();
    await loadCounts();
  } catch (error) {
    showError(error.message);
  }
}

async function addSource(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    await api("/api/sources", {
      method: "POST",
      body: JSON.stringify({
        identifier: $("#identifier").value,
        display_name: $("#display-name").value || null,
        type: $("#source-type").value,
      }),
    });
    form.reset();
    await loadData();
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
  }
}

async function handleSourceAction(event) {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const id = button.dataset.id;
  try {
    if (button.dataset.action === "toggle") {
      const source = state.sources.find((item) => String(item.id) === id);
      await api(`/api/sources/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !source.is_active }),
      });
    } else if (button.dataset.action === "delete") {
      if (!window.confirm("Bu manba va uning xabarlar tarixini o‘chirasizmi?")) return;
      await api(`/api/sources/${id}`, { method: "DELETE" });
    }
    await loadData();
  } catch (error) {
    showError(error.message);
  }
}

async function markRead(event) {
  const button = event.target.closest('[data-action="read"]');
  if (!button) return;
  try {
    const archive = state.archiveSettings.archive_on_read;
    await api(`/api/messages/${button.dataset.id}/read?archive=${archive}`, { method: "PATCH" });
    if (archive) {
      await fadeOutCard(button.dataset.id);
    }
    await loadData();
  } catch (error) {
    showError(error.message);
  }
}

async function handleNotificationsClick(event) {
  const readButton = event.target.closest('[data-action="read"]');
  const confirmButton = event.target.closest('[data-action="confirm-auto-reply"]');
  const cancelButton = event.target.closest('[data-action="cancel-auto-reply"]');
  try {
    if (readButton) {
      await api(`/api/messages/${readButton.dataset.id}/read?archive=false`, { method: "PATCH" });
      await loadNotifications();
    } else if (confirmButton) {
      const result = await api(`/api/messages/${confirmButton.dataset.id}/confirm-auto-reply`, { method: "POST" });
      if (!result.sent && result.reason === "rate_limited") {
        showError("Bu chatga so‘nggi 24 soatda allaqachon auto-javob yuborilgan.");
      }
      await loadNotifications();
    } else if (cancelButton) {
      await api(`/api/messages/${cancelButton.dataset.id}/cancel-auto-reply`, { method: "POST" });
      await fadeOutCard(cancelButton.dataset.id);
      await loadNotifications();
    }
  } catch (error) {
    showError(error.message);
  }
}

async function fadeOutCard(messageId) {
  const card = document.querySelector(`.message-card[data-message-id="${messageId}"]`);
  if (!card) return;
  card.classList.add("removing");
  await new Promise((resolve) => setTimeout(resolve, 220));
}

async function archiveMessage(messageId) {
  try {
    await api(`/api/messages/${messageId}/archive`, { method: "PATCH" });
    await fadeOutCard(messageId);
    state.selectedIds.delete(Number(messageId));
    await loadData();
  } catch (error) {
    showError(error.message);
  }
}

async function unarchiveMessage(messageId) {
  try {
    await api(`/api/messages/${messageId}/unarchive`, { method: "PATCH" });
    await fadeOutCard(messageId);
    state.selectedIds.delete(Number(messageId));
    await loadData();
  } catch (error) {
    showError(error.message);
  }
}

function toggleSelect(messageId, checked) {
  const id = Number(messageId);
  if (checked) state.selectedIds.add(id);
  else state.selectedIds.delete(id);
  updateBulkBar();
}

function updateBulkBar() {
  const bar = $("#bulk-bar");
  const count = state.selectedIds.size;
  if (count > 0) {
    bar.classList.remove("hidden");
    $("#bulk-selected-count").textContent = `${count} ta tanlandi`;
  } else {
    bar.classList.add("hidden");
  }
}

async function bulkArchiveSelected() {
  if (!state.selectedIds.size) return;
  try {
    const ids = Array.from(state.selectedIds);
    const result = await api("/api/messages/archive-bulk", {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
    state.selectedIds.clear();
    await loadData();
    return result;
  } catch (error) {
    showError(error.message);
  }
}

function switchTab(tab) {
  if (state.activeTab === tab) return;
  state.activeTab = tab;
  state.selectedIds.clear();
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  $("#archive-search-wrap").classList.toggle("hidden", tab !== "archive");
  loadData();
}

let searchDebounceTimer = null;
function handleArchiveSearchInput(event) {
  clearTimeout(searchDebounceTimer);
  const value = event.target.value;
  searchDebounceTimer = setTimeout(() => {
    state.archiveSearch = value;
    loadData();
  }, 300);
}

async function loadArchiveSettings() {
  try {
    state.archiveSettings = await api("/api/settings/archive");
  } catch (error) {
    // Keep defaults if this fails; non-fatal.
  }
}

async function loadAutoResponderSettings() {
  try {
    const result = await api("/api/settings/auto-responder");
    state.autoReplyEnabled = result.auto_reply_enabled;
  } catch (error) {
    // Keep default (false) if this fails; non-fatal.
  }
}

function openArchiveSettingsDialog() {
  $("#setting-archive-on-read").checked = state.archiveSettings.archive_on_read;
  $("#setting-archive-on-reply").checked = state.archiveSettings.archive_on_reply;
  $("#setting-auto-archive-days").value = state.archiveSettings.auto_archive_days;
  const autoReplyCheckbox = $("#setting-auto-reply-enabled");
  if (autoReplyCheckbox) autoReplyCheckbox.checked = state.autoReplyEnabled;
  $("#archive-settings-dialog").classList.remove("hidden");
}

function closeArchiveSettingsDialog() {
  $("#archive-settings-dialog").classList.add("hidden");
}

async function saveArchiveSettings() {
  const payload = {
    archive_on_read: $("#setting-archive-on-read").checked,
    archive_on_reply: $("#setting-archive-on-reply").checked,
    auto_archive_days: Number($("#setting-auto-archive-days").value) || 0,
  };
  try {
    state.archiveSettings = await api("/api/settings/archive", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    const autoReplyCheckbox = $("#setting-auto-reply-enabled");
    if (autoReplyCheckbox) {
      const result = await api("/api/settings/auto-responder", {
        method: "PUT",
        body: JSON.stringify({ auto_reply_enabled: autoReplyCheckbox.checked }),
      });
      state.autoReplyEnabled = result.auto_reply_enabled;
    }
    closeArchiveSettingsDialog();
    await loadNotifications();
  } catch (error) {
    showError(error.message);
  }
}

function handleGlobalKeydown(event) {
  const tag = (event.target.tagName || "").toLowerCase();
  const isEditable = tag === "input" || tag === "textarea" || event.target.isContentEditable;
  if (isEditable) return;
  if (state.section !== "telegram") return; // 'e' yorlig'i faqat Telegram bo'limida
  if (event.key === "e" && state.selectedIds.size > 0) {
    event.preventDefault();
    bulkArchiveSelected();
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function addReplyFiles(messageId, fileList) {
  const files = state.replyFiles[messageId] || (state.replyFiles[messageId] = []);
  for (const file of fileList) {
    try {
      const data_b64 = await fileToBase64(file);
      files.push({ name: file.name, mime: file.type || "application/octet-stream", data_b64 });
    } catch (error) {
      showError("Faylni o‘qishda xato: " + error.message);
    }
  }
  renderReplyFileChips(messageId);
}

function renderReplyFileChips(messageId) {
  const panel = document.getElementById(`reply-panel-${messageId}`);
  if (!panel) return;
  const container = panel.querySelector(".reply-files");
  const files = state.replyFiles[messageId] || [];
  container.innerHTML = files
    .map(
      (file, index) => `
        <span class="file-chip">
          ${escapeHtml(file.name)}
          <button type="button" class="file-chip-remove" data-action="reply-file-remove" data-id="${messageId}" data-index="${index}">✕</button>
        </span>
      `,
    )
    .join("");
}

function toggleReplyPanel(messageId) {
  const panel = document.getElementById(`reply-panel-${messageId}`);
  if (!panel) return;
  panel.classList.toggle("hidden");
  if (!panel.classList.contains("hidden")) {
    panel.querySelector(".reply-textarea").focus();
  }
}

async function sendReply(messageId) {
  const panel = document.getElementById(`reply-panel-${messageId}`);
  if (!panel) return;
  const textarea = panel.querySelector(".reply-textarea");
  const button = panel.querySelector(".reply-send-button");
  const asDocument = panel.querySelector(".as-document-checkbox").checked;
  const text = textarea.value.trim();
  const files = state.replyFiles[messageId] || [];

  if (!text && !files.length) {
    showError("Matn yoki fayl kiriting.");
    return;
  }

  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "Yuborilmoqda…";
  try {
    await api(`/api/messages/${messageId}/reply`, {
      method: "POST",
      body: JSON.stringify({ text, files, as_document: asDocument }),
    });
    textarea.value = "";
    delete state.replyFiles[messageId];
    panel.classList.add("hidden");
    await loadData();
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

async function handleMessageListClick(event) {
  const readButton = event.target.closest('[data-action="read"]');
  if (readButton) return markRead(event);

  const replyToggle = event.target.closest('[data-action="reply-toggle"]');
  if (replyToggle) {
    toggleReplyPanel(replyToggle.dataset.id);
    return;
  }

  const replySend = event.target.closest('[data-action="reply-send"]');
  if (replySend) {
    await sendReply(replySend.dataset.id);
    return;
  }

  const fileRemove = event.target.closest('[data-action="reply-file-remove"]');
  if (fileRemove) {
    const files = state.replyFiles[fileRemove.dataset.id] || [];
    files.splice(Number(fileRemove.dataset.index), 1);
    renderReplyFileChips(fileRemove.dataset.id);
    return;
  }

  const archiveButton = event.target.closest('[data-action="archive"]');
  if (archiveButton) {
    await archiveMessage(archiveButton.dataset.id);
    return;
  }

  const unarchiveButton = event.target.closest('[data-action="unarchive"]');
  if (unarchiveButton) {
    await unarchiveMessage(unarchiveButton.dataset.id);
    return;
  }
}

function handleMessageListChangeEvent(event) {
  const select = event.target.closest('[data-action="select"]');
  if (select) {
    toggleSelect(select.dataset.id, select.checked);
    return;
  }
  handleMessageListChange(event);
}

function handleMessageListChange(event) {
  const input = event.target.closest(".reply-file-input");
  if (!input) return;
  const card = input.closest(".message-card");
  const messageId = card?.dataset.messageId;
  if (messageId && input.files.length) {
    addReplyFiles(messageId, input.files);
    input.value = "";
  }
}

function handleMessageListKeydown(event) {
  const textarea = event.target.closest(".reply-textarea");
  if (!textarea) return;
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    const card = textarea.closest(".message-card");
    if (card?.dataset.messageId) sendReply(card.dataset.messageId);
  }
}

function handleMessageListPaste(event) {
  const textarea = event.target.closest(".reply-textarea");
  if (!textarea) return;
  const card = textarea.closest(".message-card");
  const messageId = card?.dataset.messageId;
  if (!messageId || !event.clipboardData) return;
  const imageItems = Array.from(event.clipboardData.items || []).filter((item) => item.type.startsWith("image/"));
  if (!imageItems.length) return;
  event.preventDefault();
  const files = imageItems.map((item) => item.getAsFile()).filter(Boolean);
  if (files.length) addReplyFiles(messageId, files);
}

function handleMessageListDragOver(event) {
  if (event.target.closest(".reply-panel")) event.preventDefault();
}

function handleMessageListDrop(event) {
  const panel = event.target.closest(".reply-panel");
  if (!panel) return;
  event.preventDefault();
  const card = panel.closest(".message-card");
  const messageId = card?.dataset.messageId;
  if (messageId && event.dataTransfer?.files?.length) {
    addReplyFiles(messageId, event.dataTransfer.files);
  }
}


// ================= Email bo'limi (Stage 4) =================
// XAVFSIZLIK: email tarkibi HECH QACHON xom HTML sifatida qo'yilmaydi.
// Barcha maydonlar escapeHtml orqali o'tadi; havolalar faqat http/https.
function safeLinkify(text) {
  const escaped = escapeHtml(text);
  return escaped.replace(/(https?:\/\/[^\s<&]+(?:&amp;[^\s<&]*)*)/g, (raw) => {
    const url = raw.replace(/&amp;/g, "&");
    let parsed;
    try {
      parsed = new URL(url);
    } catch (error) {
      return raw;
    }
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return raw;
    return `<a href="${escapeHtml(parsed.href)}" target="_blank" rel="noopener noreferrer nofollow">${raw}</a>`;
  });
}

function splitEmailText(text) {
  const value = String(text || "");
  const index = value.indexOf("\n\n");
  if (index === -1) return { subject: value || "(mavzusiz)", body: "" };
  return { subject: value.slice(0, index) || "(mavzusiz)", body: value.slice(index + 2) };
}

function splitAttachments(body) {
  const lines = body.split("\n");
  const attachments = [];
  while (lines.length && lines[lines.length - 1].startsWith("📎 ")) {
    attachments.unshift(lines.pop());
  }
  return { body: lines.join("\n").trim(), attachments };
}

function switchSection(section) {
  if (state.section === section) return;
  state.section = section;
  document.querySelectorAll(".section-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.section === section);
  });
  $("#telegram-section").classList.toggle("hidden", section !== "telegram");
  $("#email-section").classList.toggle("hidden", section !== "email");
  $("#opportunity-section").classList.toggle("hidden", section !== "opportunity");
  $("#notifications-section").classList.toggle("hidden", section !== "notifications");
  if (section === "email") loadEmailData();
  else if (section === "opportunity") loadOppData();
  else if (section === "notifications") loadNotifications();
  else loadData();
}

async function loadNotifications() {
  try {
    const items = await api("/api/notifications?limit=100");
    renderNotifications(items);
  } catch (error) {
    // Non-fatal.
  }
}

function renderNotifications(items) {
  const list = $("#notif-list");
  if (!list) return;
  if (!items.length) {
    list.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🔔</div>
        <strong>Bildirishnomalar yo‘q</strong>
        <span>Shoshilinch va e'tibor talab qiladigan xabarlar shu yerda ko‘rinadi.</span>
      </div>`;
    return;
  }
  list.innerHTML = items
    .map((message) => `
      <article class="message-card ${message.is_read ? "" : "unread"}" data-message-id="${message.id}">
        <div class="message-meta">
          <span class="message-source">${escapeHtml(message.source_display_name)}</span>
          ${triageBadgeMarkup(message)}
          <time>${escapeHtml(formatTime(message.received_at))}</time>
        </div>
        <div class="message-sender">${escapeHtml(message.sender_name)}</div>
        <div class="message-text">${message.text ? linkify(message.text) : "Media xabar"}</div>
        ${message.triage_level === 3 && message.triage_dashboard
          ? dashboardCardMarkup(message.triage_dashboard, "🚨 Shoshilinch tahlil")
          : (message.triage_reason ? `<div class="notif-reasoning">Tavsiya: ${escapeHtml(message.triage_reason)}</div>` : "")}
        ${message.triage_auto_reply ? `<div class="notif-auto-reply">Auto-javob: ${escapeHtml(message.triage_auto_reply)}</div>` : ""}
        <div class="message-footer">
          <span class="footer-actions">
            ${message.is_read ? "" : `<button class="read-button" data-action="read" data-id="${message.id}">O‘qildi</button>`}
            ${message.triage_level === 2 && !state.autoReplyEnabled ? `
              <button class="auto-reply-confirm-button" data-action="confirm-auto-reply" data-id="${message.id}">Yubordim</button>
              <button class="auto-reply-cancel-button" data-action="cancel-auto-reply" data-id="${message.id}">Bekor qilish</button>` : ""}
          </span>
        </div>
      </article>`)
    .join("");
}

async function loadEmailPresets() {
  try {
    state.email.presets = await api("/api/email/presets");
  } catch (error) {
    state.email.presets = [];
  }
  const select = $("#email-preset");
  select.innerHTML =
    '<option value="">Boshqa (qo‘lda)</option>' +
    state.email.presets
      .map((preset) => `<option value="${escapeHtml(preset.id)}">${escapeHtml(preset.name)}</option>`)
      .join("");
}

function handleEmailPresetChange() {
  const preset = state.email.presets.find((item) => item.id === $("#email-preset").value);
  const note = $("#email-preset-note");
  if (!preset) {
    note.classList.add("hidden");
    return;
  }
  $("#email-host").value = preset.imap_host;
  $("#email-port").value = preset.imap_port;
  note.textContent = preset.note;
  note.classList.remove("hidden");
}

function renderEmailAccounts() {
  $("#email-account-count").textContent = state.email.accounts.length;
  const list = $("#email-account-list");
  if (!state.email.accounts.length) {
    list.innerHTML = '<div class="empty-state small">Hali hisob ulanmagan.</div>';
    return;
  }
  list.innerHTML = state.email.accounts
    .map((account) => {
      const dotClass = account.last_error ? "error" : account.is_active ? "" : "paused";
      return `
        <div class="source-item">
          <div class="source-row">
            <span class="source-name" title="${escapeHtml(account.label)}"><span class="email-dot ${dotClass}"></span>${escapeHtml(account.label)}</span>
            <button class="toggle ${account.is_active ? "active" : ""}" data-email-action="toggle" data-id="${account.id}" aria-label="Faollikni o‘zgartirish"></button>
          </div>
          <div class="source-identifier">${escapeHtml(account.username)} · ${escapeHtml(account.imap_host)}</div>
          ${account.last_error ? `<div class="email-error">${escapeHtml(account.last_error)}</div>` : ""}
          <div class="email-account-actions">
            <button data-email-action="check" data-id="${account.id}">Hozir tekshirish</button>
            <button data-email-action="password" data-id="${account.id}">Parolni yangilash</button>
            <button class="delete-button" data-email-action="delete" data-id="${account.id}">O‘chirish</button>
          </div>
        </div>`;
    })
    .join("");
}

function renderEmailMessages() {
  const list = $("#email-list");
  if (!state.email.messages.length) {
    const archive = state.email.tab === "archive";
    list.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">✉</div>
        <strong>${archive ? "Arxiv bo‘sh" : "Xatlar shu yerda ko‘rinadi"}</strong>
        <span>${archive ? "Arxivlangan xatlar shu yerda ko‘rinadi." : state.email.accounts.length ? "Yangi xat kelishini kuting." : "Chapdan email hisob ulang."}</span>
      </div>`;
    return;
  }
  const isArchive = state.email.tab === "archive";
  list.innerHTML = state.email.messages
    .map((message) => {
      const { subject, body: rawBody } = splitEmailText(message.text);
      const { body, attachments } = splitAttachments(rawBody);
      const expanded = state.email.expanded.has(message.id);
      return `
        <article class="message-card email-card ${message.is_read ? "" : "unread"} ${expanded ? "expanded" : ""}" data-email-id="${message.id}">
          <div class="message-meta">
            <span class="message-source">${escapeHtml(message.source_display_name)}</span>
            <time>${escapeHtml(formatTime(message.received_at))}</time>
          </div>
          <div class="email-subject">${escapeHtml(subject)}</div>
          <div class="email-from">${escapeHtml(message.sender_name)}</div>
          <div class="email-snippet">${expanded ? safeLinkify(body || "(matn yo‘q)") : escapeHtml(body)}</div>
          ${attachments.length ? `<div class="email-attachments">${attachments.map((line) => escapeHtml(line)).join("<br>")}</div>` : ""}
          <div class="message-footer">
            <span class="media-label"></span>
            <span class="footer-actions">
              ${message.is_read ? "" : `<button class="read-button" data-email-action="read" data-id="${message.id}">O‘qildi</button>`}
              ${isArchive
                ? `<button class="archive-toggle-button" data-email-action="unarchive" data-id="${message.id}">Qaytarish</button>`
                : `<button class="archive-toggle-button" data-email-action="archive" data-id="${message.id}">Arxivga</button>`}
            </span>
          </div>
        </article>`;
    })
    .join("");
}

async function loadEmailData() {
  clearError();
  try {
    const archived = state.email.tab === "archive";
    const [accounts, messages] = await Promise.all([
      api("/api/email/accounts"),
      api(`/api/messages?limit=100&archived=${archived}&channel=email`),
    ]);
    state.email.accounts = accounts;
    state.email.messages = messages;
    renderEmailAccounts();
    renderEmailMessages();
    await loadCounts();
  } catch (error) {
    showError(error.message);
  }
}

async function addEmailAccount(event) {
  event.preventDefault();
  const button = $("#email-add-button");
  button.disabled = true;
  button.textContent = "Tekshirilmoqda...";
  try {
    await api("/api/email/accounts", {
      method: "POST",
      body: JSON.stringify({
        label: $("#email-label").value,
        imap_host: $("#email-host").value,
        imap_port: Number($("#email-port").value) || 993,
        username: $("#email-username").value,
        password: $("#email-password").value,
        folder: $("#email-folder").value || "INBOX",
      }),
    });
    $("#email-account-form").reset();
    $("#email-port").value = 993;
    $("#email-folder").value = "INBOX";
    $("#email-preset-note").classList.add("hidden");
    await loadEmailData();
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
    button.innerHTML = "<span>+</span> Hisob qo‘shish";
    $("#email-password").value = "";
  }
}

async function handleEmailAccountAction(event) {
  const button = event.target.closest("[data-email-action]");
  if (!button) return;
  const id = button.dataset.id;
  const action = button.dataset.emailAction;
  try {
    if (action === "toggle") {
      const account = state.email.accounts.find((item) => String(item.id) === String(id));
      await api(`/api/email/accounts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !account.is_active }),
      });
    } else if (action === "check") {
      button.disabled = true;
      const result = await api(`/api/email/accounts/${id}/check-now`, { method: "POST" });
      if (result.last_error) showError(result.last_error);
    } else if (action === "password") {
      const password = window.prompt("Yangi parol / App Password:");
      if (!password) return;
      await api(`/api/email/accounts/${id}`, { method: "PATCH", body: JSON.stringify({ password }) });
    } else if (action === "delete") {
      if (!window.confirm("Bu hisob va uning barcha xatlari o‘chiriladi. Davom etasizmi?")) return;
      await api(`/api/email/accounts/${id}`, { method: "DELETE" });
    }
    await loadEmailData();
  } catch (error) {
    showError(error.message);
  }
}

async function handleEmailListClick(event) {
  const actionButton = event.target.closest("[data-email-action]");
  if (actionButton) {
    const id = actionButton.dataset.id;
    const action = actionButton.dataset.emailAction;
    try {
      if (action === "read") await api(`/api/messages/${id}/read`, { method: "PATCH" });
      else if (action === "archive") await api(`/api/messages/${id}/archive`, { method: "PATCH" });
      else if (action === "unarchive") await api(`/api/messages/${id}/unarchive`, { method: "PATCH" });
      await loadEmailData();
    } catch (error) {
      showError(error.message);
    }
    return;
  }
  if (event.target.closest("a")) return; // havola bosildi — kengaytirmaymiz
  const card = event.target.closest(".email-card");
  if (!card) return;
  const id = Number(card.dataset.emailId);
  if (state.email.expanded.has(id)) state.email.expanded.delete(id);
  else state.email.expanded.add(id);
  renderEmailMessages();
}

function switchEmailTab(tab) {
  if (state.email.tab === tab) return;
  state.email.tab = tab;
  document.querySelectorAll(".email-tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.emailTab === tab);
  });
  loadEmailData();
}

// ── Imkoniyatlar (Stage 6) ───────────────────────────
// XAVFSIZLIK: barcha maydonlar escapeHtml orqali; havolalar faqat http/https.

function safeHttpUrl(value) {
  if (!value) return null;
  try {
    const parsed = new URL(String(value));
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch (_) {
    return null;
  }
}

function oppScoreClass(score) {
  if (score === null || score === undefined) return "low";
  if (score >= 80) return "high";
  if (score >= 50) return "mid";
  return "low";
}

function oppDeadlineMarkup(item) {
  if (!item.deadline) return "";
  const days = item.days_left;
  if (days === null || days === undefined) return `<div class="opp-deadline">📅 ${escapeHtml(item.deadline)}</div>`;
  if (days < 0) return `<div class="opp-deadline urgent">⌛ Muddat o‘tgan (${escapeHtml(item.deadline)})</div>`;
  const urgent = days <= 3;
  return `<div class="opp-deadline ${urgent ? "urgent" : ""}">${urgent ? "⏰" : "📅"} ${days} kun qoldi (${escapeHtml(item.deadline)})</div>`;
}

function renderOppFeed() {
  const list = $("#opp-feed-list");
  const archive = state.opp.feedTab === "archive";
  if (!state.opp.feed.length) {
    list.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🎯</div>
        <strong>${archive ? "Arxiv bo‘sh" : "Imkoniyatlar shu yerda ko‘rinadi"}</strong>
        <span>${archive ? "Arxivlangan imkoniyatlar shu yerda ko‘rinadi." : "Kanal qo‘shing va monitorni yoqing."}</span>
      </div>`;
    return;
  }
  list.innerHTML = state.opp.feed
    .map((item) => {
      const link = safeHttpUrl(item.link);
      const score = item.score === null || item.score === undefined ? "—" : item.score;
      return `
        <article class="message-card ${item.is_read ? "" : "unread"}" data-opp-id="${item.id}">
          <div class="message-meta">
            <span class="message-source">${escapeHtml(item.channel_name)}</span>
            <time>${escapeHtml(formatTime(item.received_at))}</time>
          </div>
          <div class="opp-card-head">
            <div class="opp-title">${escapeHtml(item.title)}</div>
            <span class="opp-score ${oppScoreClass(item.score)}" title="Moslik bali">${escapeHtml(score)}</span>
          </div>
          ${oppDeadlineMarkup(item)}
          <div class="opp-tags">
            ${item.is_free ? '<span class="opp-tag free">Bepul / Grant</span>' : ""}
            ${(item.fields || []).map((field) => `<span class="opp-tag">${escapeHtml(field)}</span>`).join("")}
          </div>
          ${item.reasons ? `<div class="opp-reasons">✅ ${escapeHtml(item.reasons)}</div>` : ""}
          <div class="message-footer">
            <span class="media-label">${
              link
                ? `<a class="opp-link-button" href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer nofollow">Havola ↗</a>`
                : ""
            }</span>
            <span class="footer-actions">
              ${item.is_read ? "" : `<button class="read-button" data-opp-action="read" data-id="${item.id}">O‘qildi</button>`}
              ${
                archive
                  ? `<button class="archive-toggle-button" data-opp-action="unarchive" data-id="${item.id}">Qaytarish</button>`
                  : `<button class="archive-toggle-button" data-opp-action="archive" data-id="${item.id}">Arxivga</button>`
              }
            </span>
          </div>
        </article>`;
    })
    .join("");
}

async function loadOppFeed() {
  const archived = state.opp.feedTab === "archive";
  state.opp.feed = await api(`/api/opp/feed?limit=100&archived=${archived}`);
  renderOppFeed();
}

function renderOppChannels() {
  const list = $("#opp-channel-list");
  if (!state.opp.channels.length) {
    list.innerHTML = '<div class="empty-state small">Hali kanal qo‘shilmagan.</div>';
    return;
  }
  list.innerHTML = state.opp.channels
    .map(
      (channel) => `
      <div class="source-item">
        <div class="source-row">
          <span class="source-name">${escapeHtml(channel.name)}</span>
          <button class="delete-button" data-opp-channel-delete="${channel.id}" type="button">O‘chirish</button>
        </div>
        <div class="source-identifier">ID: ${escapeHtml(channel.channel_id)} · oxirgi post: #${escapeHtml(channel.last_seen)}</div>
      </div>`,
    )
    .join("");
}

function renderOppProfile() {
  const profile = state.opp.profile;
  if (!profile) return;
  $("#opp-p-age").value = profile.age ?? "";
  $("#opp-p-grade").value = profile.grade ?? "";
  $("#opp-p-ielts").value = profile.ielts ?? "";
  $("#opp-p-knows-english").checked = !!profile.knows_english;
  $("#opp-p-is-pupil").checked = !!profile.is_pupil;
  $("#opp-p-is-student").checked = !!profile.is_student;
  $("#opp-p-only-free").checked = !!profile.only_free;
  const selected = new Set(profile.interests || []);
  $("#opp-p-interests").innerHTML = OPP_INTERESTS.map(
    (name) => `
      <label class="opp-check">
        <input type="checkbox" value="${escapeHtml(name)}" ${selected.has(name) ? "checked" : ""} />
        <span>${escapeHtml(name)}</span>
      </label>`,
  ).join("");
}

function renderOppSettings() {
  const settings = state.opp.settings;
  if (settings) {
    $("#opp-s-enabled").classList.toggle("active", !!settings.enabled);
    $("#opp-s-min-score").value = settings.min_score;
    $("#opp-s-min-score-label").textContent = settings.min_score;
  }
  const status = state.opp.status;
  $("#opp-status").innerHTML = status
    ? `<div>Holat: <b>${status.enabled ? "yoqilgan" : "o‘chirilgan"}</b></div>
       <div>Kanallar: <b>${escapeHtml(status.channels_count)}</b></div>
       <div>Tekshiruvlar: <b>${escapeHtml(status.total_checks)}</b> · Topilgan: <b>${escapeHtml(status.total_found)}</b></div>
       <div>Oxirgi tekshiruv: <b>${escapeHtml(status.last_check ? formatTime(status.last_check) : "—")}</b></div>`
    : "";
  renderOppDelivery();
}

function renderOppDelivery() {
  const delivery = state.opp.delivery;
  const box = $("#opp-delivery-mode");
  const warn = $("#opp-groups-warning");
  if (!delivery) {
    box.innerHTML = "";
    warn.classList.add("hidden");
    return;
  }
  const isBot = delivery.mode === "bot";
  box.innerHTML = `<div>Rejim: <b>${isBot ? "Bot (BOT_TOKEN)" : "Userbot (sizning akkauntingiz)"}</b></div>
    <div>BOT_TOKEN sozlangan: <b>${delivery.bot_configured ? "ha" : "yo‘q"}</b></div>
    ${delivery.warning ? `<div class="opp-note">⚠ ${escapeHtml(delivery.warning)}</div>` : ""}`;
  if (delivery.warning) {
    warn.textContent = `⚠ ${delivery.warning}`;
    warn.classList.remove("hidden");
  } else {
    warn.classList.add("hidden");
  }
}

function renderOppGroups() {
  const list = $("#opp-group-list");
  if (!state.opp.groups.length) {
    list.innerHTML = '<div class="empty-state small">Hali guruh qo‘shilmagan.</div>';
    return;
  }
  list.innerHTML = state.opp.groups
    .map((group) => {
      const confirmed = group.status === "confirmed";
      return `
      <div class="source-item">
        <div class="source-row">
          <span class="source-name">${escapeHtml(group.title)}</span>
          <span class="${confirmed ? "opp-badge-confirmed" : "opp-badge-pending"}">${confirmed ? "✓ tasdiqlangan" : "● kutilmoqda"}</span>
        </div>
        <div class="source-identifier">ID: ${escapeHtml(group.chat_id)}</div>
        <div class="source-actions">
          ${confirmed ? "<span></span>" : `<button class="quiet-button" data-opp-group-confirm="${group.id}" type="button">Tasdiqlash</button>`}
          <button class="delete-button" data-opp-group-delete="${group.id}" type="button">O‘chirish</button>
        </div>
      </div>`;
    })
    .join("");
}

async function loadOppData() {
  clearError();
  try {
    await loadOppTab(state.opp.tab);
    await loadCounts();
  } catch (error) {
    showError(error.message);
  }
}

async function loadOppTab(tab) {
  if (tab === "feed") {
    await loadOppFeed();
  } else if (tab === "channels") {
    state.opp.channels = await api("/api/opp/channels");
    renderOppChannels();
  } else if (tab === "profile") {
    state.opp.profile = await api("/api/opp/profile");
    renderOppProfile();
  } else if (tab === "settings") {
    const [settings, status, delivery] = await Promise.all([
      api("/api/opp/settings"),
      api("/api/opp/status"),
      api("/api/opp/delivery-mode"),
    ]);
    state.opp.settings = settings;
    state.opp.status = status;
    state.opp.delivery = delivery;
    renderOppSettings();
  } else if (tab === "groups") {
    const [groups, delivery] = await Promise.all([api("/api/opp/groups"), api("/api/opp/delivery-mode")]);
    state.opp.groups = groups;
    state.opp.delivery = delivery;
    renderOppGroups();
    renderOppDelivery();
  }
}

function switchOppTab(tab) {
  state.opp.tab = tab;
  document.querySelectorAll(".opp-tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.oppTab === tab);
  });
  ["feed", "channels", "profile", "settings", "groups", "test"].forEach((name) => {
    $(`#opp-pane-${name}`).classList.toggle("hidden", name !== tab);
  });
  loadOppData();
}

function switchOppFeedTab(tab) {
  if (state.opp.feedTab === tab) return;
  state.opp.feedTab = tab;
  document.querySelectorAll(".opp-feed-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.feedTab === tab);
  });
  loadOppData();
}

function handleOppSocketMessage(message) {
  if (state.section === "opportunity" && state.opp.tab === "feed" && state.opp.feedTab === "inbox") {
    loadOppFeed().catch(() => {});
  }
}

async function handleOppFeedClick(event) {
  const button = event.target.closest("[data-opp-action]");
  if (!button) return;
  const id = button.dataset.id;
  const action = button.dataset.oppAction;
  try {
    if (action === "read") await api(`/api/messages/${id}/read?archive=false`, { method: "PATCH" });
    else if (action === "archive") await api(`/api/messages/${id}/archive`, { method: "PATCH" });
    else if (action === "unarchive") await api(`/api/messages/${id}/unarchive`, { method: "PATCH" });
    await loadOppData();
  } catch (error) {
    showError(error.message);
  }
}

async function addOppChannel(event) {
  event.preventDefault();
  const input = $("#opp-channel-identifier");
  try {
    await api("/api/opp/channels", { method: "POST", body: JSON.stringify({ identifier: input.value }) });
    input.value = "";
    await loadOppData();
  } catch (error) {
    showError(error.message);
  }
}

async function handleOppChannelListClick(event) {
  const button = event.target.closest("[data-opp-channel-delete]");
  if (!button) return;
  if (!window.confirm("Kanalni kuzatuvdan o‘chirasizmi?")) return;
  try {
    await api(`/api/opp/channels/${button.dataset.oppChannelDelete}`, { method: "DELETE" });
    await loadOppData();
  } catch (error) {
    showError(error.message);
  }
}

async function oppRefreshDialogs() {
  const note = $("#opp-channels-note");
  note.textContent = "Yangilanmoqda...";
  try {
    const result = await api("/api/opp/refresh-dialogs", { method: "POST" });
    note.textContent = `Dialoglar yangilandi: ${result.count} ta.`;
  } catch (error) {
    note.textContent = "";
    showError(error.message);
  }
}

async function oppScanNow() {
  const note = $("#opp-channels-note");
  const button = $("#opp-scan-now");
  button.disabled = true;
  note.textContent = "Tekshirilmoqda (kanallar ko‘p bo‘lsa biroz vaqt olishi mumkin)...";
  try {
    const result = await api("/api/opp/scan-now", { method: "POST" });
    note.textContent = `Tekshiruv tugadi: ${result.found} ta yangi imkoniyat topildi.`;
    await loadCounts();
  } catch (error) {
    note.textContent = "";
    showError(error.message);
  } finally {
    button.disabled = false;
  }
}

async function saveOppProfile(event) {
  event.preventDefault();
  const numberOrNull = (selector) => {
    const raw = $(selector).value.trim();
    return raw === "" ? null : Number(raw);
  };
  const interests = Array.from(document.querySelectorAll("#opp-p-interests input:checked")).map((input) => input.value);
  try {
    state.opp.profile = await api("/api/opp/profile", {
      method: "PUT",
      body: JSON.stringify({
        age: Number($("#opp-p-age").value),
        grade: numberOrNull("#opp-p-grade"),
        ielts: numberOrNull("#opp-p-ielts"),
        knows_english: $("#opp-p-knows-english").checked,
        is_pupil: $("#opp-p-is-pupil").checked,
        is_student: $("#opp-p-is-student").checked,
        only_free: $("#opp-p-only-free").checked,
        interests,
      }),
    });
    renderOppProfile();
    clearError();
  } catch (error) {
    showError(error.message);
  }
}

async function saveOppSettings() {
  const current = state.opp.settings || { check_interval: 600 };
  try {
    state.opp.settings = await api("/api/opp/settings", {
      method: "PUT",
      body: JSON.stringify({
        enabled: $("#opp-s-enabled").classList.contains("active"),
        min_score: Number($("#opp-s-min-score").value),
        check_interval: current.check_interval,
      }),
    });
    state.opp.status = await api("/api/opp/status");
    renderOppSettings();
    clearError();
  } catch (error) {
    showError(error.message);
  }
}

async function addOppGroup(event) {
  event.preventDefault();
  const identifier = $("#opp-group-identifier");
  const title = $("#opp-group-title");
  try {
    await api("/api/opp/groups", {
      method: "POST",
      body: JSON.stringify({ identifier: identifier.value, title: title.value || null }),
    });
    identifier.value = "";
    title.value = "";
    await loadOppData();
  } catch (error) {
    showError(error.message);
  }
}

async function handleOppGroupListClick(event) {
  const confirmButton = event.target.closest("[data-opp-group-confirm]");
  const deleteButton = event.target.closest("[data-opp-group-delete]");
  try {
    if (confirmButton) {
      confirmButton.disabled = true;
      await api(`/api/opp/groups/${confirmButton.dataset.oppGroupConfirm}/confirm`, { method: "POST" });
      await loadOppData();
    } else if (deleteButton) {
      if (!window.confirm("Guruhni ro‘yxatdan o‘chirasizmi?")) return;
      await api(`/api/opp/groups/${deleteButton.dataset.oppGroupDelete}`, { method: "DELETE" });
      await loadOppData();
    }
  } catch (error) {
    showError(error.message);
    await loadOppData();
  }
}

async function runOppAnalyze() {
  const text = $("#opp-test-text").value.trim();
  const box = $("#opp-test-result");
  if (!text) {
    box.innerHTML = '<div class="bad">Matn kiriting.</div>';
    return;
  }
  box.innerHTML = "Tahlil qilinmoqda...";
  try {
    const r = await api("/api/opp/analyze", { method: "POST", body: JSON.stringify({ text }) });
    const li = (items, cls) => (items || []).map((x) => `<li class="${cls}">${escapeHtml(x)}</li>`).join("");
    const link = safeHttpUrl(r.link);
    box.innerHTML = `
      <div><b>${escapeHtml(r.title || "(sarlavhasiz)")}</b></div>
      <div>Ball: <span class="opp-score ${oppScoreClass(r.score)}">${escapeHtml(r.score)}</span>
        ${r.reject_reasons && r.reject_reasons.length ? '<span class="bad">— rad etiladi</span>' : ""}</div>
      ${r.deadline ? `<div>Muddat: <b>${escapeHtml(r.deadline)}</b></div>` : ""}
      ${(r.fields || []).length ? `<div>Yo‘nalish: ${r.fields.map((f) => `<span class="opp-tag">${escapeHtml(f)}</span>`).join(" ")}</div>` : ""}
      ${(r.match_reasons || []).length ? `<div>Mos kelish sabablari:<ul>${li(r.match_reasons, "ok")}</ul></div>` : ""}
      ${(r.reject_reasons || []).length ? `<div>Rad etish sabablari:<ul>${li(r.reject_reasons, "bad")}</ul></div>` : ""}
      ${link ? `<div><a class="opp-link-button" href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer nofollow">Havola ↗</a></div>` : ""}`;
  } catch (error) {
    box.innerHTML = `<div class="bad">${escapeHtml(error.message)}</div>`;
  }
}

function setConnection(online, label) {
  $("#connection-dot").className = `status-dot ${online ? "online" : "offline"}`;
  $("#connection-label").textContent = label;
}

function connectWebSocket() {
  const wsBase = API_BASE_URL.replace(/^http/, "ws");
  try {
    state.socket = new WebSocket(`${wsBase}/ws/messages`);
  } catch (error) {
    setConnection(false, "Ulanish xatosi");
    return;
  }
  state.socket.addEventListener("open", () => {
    state.reconnectDelay = 1000;
    setConnection(true, "Jonli ulangan");
  });
  state.socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.channel === "opportunity") {
      handleOppSocketMessage(message);
    } else if (message.channel === "email") {
      if (state.section === "email" && state.email.tab === "inbox" && !message.is_archived) {
        state.email.messages = [message, ...state.email.messages.filter((item) => item.id !== message.id)].slice(0, 100);
        renderEmailMessages();
      }
    } else if (state.activeTab === "inbox" && !message.is_archived) {
      state.messages = [message, ...state.messages.filter((item) => item.id !== message.id)].slice(0, 100);
      renderMessages();
    }
    loadCounts();
    if ("Notification" in window && Notification.permission === "granted") {
      const isEmail = message.channel === "email";
      const isOpp = message.channel === "opportunity";
      const firstLine = (message.text || "").split("\n")[0];
      new Notification(
        isOpp
          ? "🎯 Yangi imkoniyat"
          : isEmail
            ? `✉ ${message.source_display_name || "Email"}`
            : message.source_display_name || "Telegram Focus",
        {
          body: isOpp
            ? firstLine
            : isEmail
              ? `${message.sender_name}: ${firstLine}`
              : message.text || "Yangi media xabar",
        },
      );
    }
  });
  state.socket.addEventListener("close", () => {
    setConnection(false, "Qayta ulanmoqda...");
    clearTimeout(state.reconnectTimer);
    state.reconnectTimer = setTimeout(connectWebSocket, state.reconnectDelay);
    state.reconnectDelay = Math.min(state.reconnectDelay * 2, 15000);
  });
  state.socket.addEventListener("error", () => setConnection(false, "Ulanish xatosi"));
}

async function requestNotifications() {
  if (!("Notification" in window)) {
    showError("Bu brauzer tizim bildirishnomalarini qo‘llamaydi.");
    return;
  }
  const permission = await Notification.requestPermission();
  $("#notification-button").textContent =
    permission === "granted" ? "Bildirishnomalar yoqilgan" : "Bildirishnomalarni yoqish";
}

$("#source-form").addEventListener("submit", addSource);
$("#source-list").addEventListener("click", handleSourceAction);
$("#message-list").addEventListener("click", handleMessageListClick);
$("#message-list").addEventListener("change", handleMessageListChangeEvent);
$("#message-list").addEventListener("keydown", handleMessageListKeydown);
$("#message-list").addEventListener("paste", handleMessageListPaste);
$("#message-list").addEventListener("dragover", handleMessageListDragOver);
$("#message-list").addEventListener("drop", handleMessageListDrop);
$("#notification-button").addEventListener("click", requestNotifications);
document.querySelectorAll(".tab-button").forEach((button) => {
  button.addEventListener("click", () => switchTab(button.dataset.tab));
});
$("#archive-search").addEventListener("input", handleArchiveSearchInput);
$("#bulk-archive-button").addEventListener("click", bulkArchiveSelected);
$("#archive-settings-button").addEventListener("click", openArchiveSettingsDialog);
$("#archive-settings-cancel").addEventListener("click", closeArchiveSettingsDialog);
$("#archive-settings-save").addEventListener("click", saveArchiveSettings);
document.addEventListener("keydown", handleGlobalKeydown);
document.querySelectorAll(".section-tab").forEach((button) => {
  button.addEventListener("click", () => switchSection(button.dataset.section));
});
document.querySelectorAll(".email-tab-button").forEach((button) => {
  button.addEventListener("click", () => switchEmailTab(button.dataset.emailTab));
});
$("#email-preset").addEventListener("change", handleEmailPresetChange);
$("#email-account-form").addEventListener("submit", addEmailAccount);
$("#email-account-list").addEventListener("click", handleEmailAccountAction);
$("#email-list").addEventListener("click", handleEmailListClick);
document.querySelectorAll(".opp-tab-button").forEach((button) => {
  button.addEventListener("click", () => switchOppTab(button.dataset.oppTab));
});
document.querySelectorAll(".opp-feed-tab").forEach((button) => {
  button.addEventListener("click", () => switchOppFeedTab(button.dataset.feedTab));
});
$("#opp-feed-list").addEventListener("click", handleOppFeedClick);
$("#notif-list").addEventListener("click", handleNotificationsClick);
$("#opp-channel-form").addEventListener("submit", addOppChannel);
$("#opp-channel-list").addEventListener("click", handleOppChannelListClick);
$("#opp-refresh-dialogs").addEventListener("click", oppRefreshDialogs);
$("#opp-scan-now").addEventListener("click", oppScanNow);
$("#opp-profile-form").addEventListener("submit", saveOppProfile);
$("#opp-s-enabled").addEventListener("click", () => $("#opp-s-enabled").classList.toggle("active"));
$("#opp-s-min-score").addEventListener("input", (event) => {
  $("#opp-s-min-score-label").textContent = event.target.value;
});
$("#opp-s-save").addEventListener("click", saveOppSettings);
$("#opp-group-form").addEventListener("submit", addOppGroup);
$("#opp-group-list").addEventListener("click", handleOppGroupListClick);
$("#opp-test-run").addEventListener("click", runOppAnalyze);

loadArchiveSettings();
loadAutoResponderSettings();
loadEmailPresets();
loadData();
connectWebSocket();

// === AI SIDEBAR CONTROLLER (ROBUST & SCREEN-AWARE) ===
(function() {
  const aiHistory = [];

  function safeText(str) {
    return String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function getActiveScreenContext() {
    let tab = "Telegram";
    const sectionNames = {
      telegram: "Telegram",
      email: "Email",
      opportunity: "Imkoniyatlar",
      notifications: "Bildirishnomalar"
    };
    tab = sectionNames[state.section] || tab;

    let source = "Barcha xabarlar";
    const srcEl = document.querySelector(".source-item.active, [data-source-id].active, .channel-item.active");
    if (srcEl) {
      source = srcEl.textContent.trim().replace(/\s+/g, " ");
    }

    let items = [];
    document.querySelectorAll(".message-item, .message-card, tr, .opportunity-card").forEach((c, idx) => {
      if (idx < 8 && c.offsetParent !== null) {
        const t = c.textContent.trim().replace(/\s+/g, " ");
        const linkEl = c.querySelector("a[href^='http']");
        const href = linkEl ? linkEl.getAttribute("href") : "";
        if (t.length > 5) {
          items.push(href ? `${t.slice(0, 220)} [HAVOLA: ${href}]` : t.slice(0, 220));
        }
      }
    });

    return {
      active_tab: tab,
      active_source: source,
      visible_items: items.join("\n---\n")
    };
  }

  function updateLocationBadge() {
    const loc = document.getElementById("ai-current-location");
    if (!loc) return;
    const ctx = getActiveScreenContext();
    loc.textContent = `📍 ${ctx.active_tab} > ${ctx.active_source.slice(0, 16)}`;
  }

  function addMsg(sender, text) {
    const box = document.getElementById("ai-sidebar-chat");
    if (!box) return;
    const row = document.createElement("div");
    row.className = "ai-msg-row " + sender;
    const bubble = document.createElement("div");
    bubble.className = "ai-msg-bubble";
    let formatted = safeText(text).replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");
    bubble.innerHTML = formatted;
    row.appendChild(bubble);
    box.appendChild(row);
    box.scrollTop = box.scrollHeight;
    aiHistory.push({ sender, text });
  }

  async function loadWelcome() {
    const ruleEl = document.getElementById("ai-sidebar-rule");
    const modelEl = document.getElementById("ai-model-label");
    try {
      const res = await fetch("/api/ai/welcome");
      if (!res.ok) throw new Error("Status " + res.status);
      const d = await res.json();
      if (d.facts && d.facts.rule_of_one_focus && ruleEl) {
        ruleEl.textContent = d.facts.rule_of_one_focus;
      }
      if (d.used_model && modelEl) {
        modelEl.textContent = d.used_model.replace("gemini-", "");
      }
      addMsg("ai", d.greeting);
    } catch (e) {
      addMsg("ai", "Assalomu alaykum! Tizim faktlari yuklandi. Xabarlaringiz tahlilga tayyor.");
    }
  }

  async function sendMsg(overrideText) {
    const inp = document.getElementById("ai-side-input");
    const text = (overrideText || (inp ? inp.value : "")).trim();
    if (!text) return;
    if (inp) inp.value = "";

    addMsg("user", text);
    const ctx = getActiveScreenContext();

    try {
      const res = await fetch("/api/ai/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          history: aiHistory.slice(-6).map(h => ({ sender: h.sender, text: h.text })),
          current_context: ctx
        })
      });
      if (!res.ok) throw new Error("Status " + res.status);
      const d = await res.json();
      addMsg("ai", d.reply);
    } catch (e) {
      addMsg("ai", "Tarmoq bilan uzilish yuz berdi. Qayta urinib ko'ring.");
    }
  }

  function init() {
    const btn = document.getElementById("ai-side-send-btn");
    const inp = document.getElementById("ai-side-input");
    if (btn) btn.addEventListener("click", () => sendMsg());
    if (inp) {
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") sendMsg();
      });
    }
    document.querySelectorAll(".ai-chip").forEach(c => {
      c.addEventListener("click", () => sendMsg(c.getAttribute("data-q")));
    });
    setInterval(updateLocationBadge, 1500);
    loadWelcome();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
