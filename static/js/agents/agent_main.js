document.addEventListener("DOMContentLoaded", function () {
  setupChatListeners();
  setupSessionSwitching();
  setupSessionTitleEditing();
  setupSessionContextMenu();
  setupUploadZone();
  loadPendingAttachments();
  enhanceStructuredAgentMessagesHistoryChat(); // 🔥
  stripStructuredSuffixesInHistory();
  setupStructuredToggles();
  updateAttachmentPreview();
  initializeMaterializeSelects(document);
  initializeBundleStructureCards(document);
  initializeSingleRecordRelatedButtons(document);
  initializeSingleRecordDeleteButtons(document);
  initializeQuoteListViewButtons();
  initializeRecordListViewButtons();
  initializeQuoteDetailRecordLinks();
  initializeLeadRecordCards();
  initializeRecordCards();
  initializeAgentsEmptyState();
  setAgentFeedbackVisibility(false);
  initializeRecordListLayouts(document);
  initializeMetricCards(document);
  handleAutoPrompt();

  scrollToBottom("DOMContentLoaded", true);
});

function handleAutoPrompt() {
  const params = new URLSearchParams(window.location.search);
  const autoPrompt = params.get("auto_prompt");
  if (!autoPrompt) return;
  const inputField = document.getElementById("user-input");
  const chatBox = document.getElementById("chat-box");
  if (!inputField || !chatBox) return;
  const hasMessages = Boolean(chatBox.querySelector(".chat-message, .chat-text"));
  if (hasMessages) return;

  inputField.value = autoPrompt;
  params.delete("auto_prompt");
  const nextQuery = params.toString();
  const nextUrl = nextQuery ? `${window.location.pathname}?${nextQuery}` : window.location.pathname;
  window.history.replaceState({}, "", nextUrl);
  sendMessage();
}

function initializeMaterializeSelects(root) {
  if (!root) {
    return;
  }

  const selects = Array.from(root.querySelectorAll('select')).filter(
    sel => sel.dataset.skipMaterialize !== "true"
  );
  if (!selects.length) {
    return;
  }

  if (typeof M !== 'undefined' && M.FormSelect) {
    M.FormSelect.init(selects);
  } else {
    console.warn('Materialize M.FormSelect not available; select elements were not enhanced.');
  }
}

function mergeSingleRecordSections(root = document) {
  if (!root) return;
  const cards = root.querySelectorAll('.single-record-card');
  cards.forEach(card => {
    const sections = card.querySelectorAll('.single-record-section');
    if (sections.length <= 1) return;

    const primarySection = sections[0];
    const primaryGrid = primarySection.querySelector('.single-record-grid');
    if (!primaryGrid) return;

    for (let i = 1; i < sections.length; i++) {
      const grid = sections[i].querySelector('.single-record-grid');
      if (grid) {
        primaryGrid.innerHTML += grid.innerHTML;
      }
      sections[i].remove();
    }
  });
}

if (typeof window !== 'undefined') {
  window.initializeMaterializeSelects = initializeMaterializeSelects;
}

if (typeof window !== "undefined") {
  window.UPLOAD_HINT_DEFAULT = window.UPLOAD_HINT_DEFAULT || "PNG, JPG, GIF, or WEBP up to 8 MB. Attachments are appended to the next PDF.";
}
var UPLOAD_HINT_DEFAULT = (typeof window !== "undefined" && window.UPLOAD_HINT_DEFAULT)
  ? window.UPLOAD_HINT_DEFAULT
  : "PNG, JPG, GIF, or WEBP up to 8 MB. Attachments are appended to the next PDF.";

if (typeof window !== "undefined") {
  window.pendingAttachments = window.pendingAttachments || [];
}
var pendingAttachments = (typeof window !== "undefined" && window.pendingAttachments)
  ? window.pendingAttachments
  : [];
if (typeof window !== "undefined") {
  window.pendingBatchUpload = window.pendingBatchUpload || null;
}
var pendingBatchUpload = (typeof window !== "undefined" && window.pendingBatchUpload)
  ? window.pendingBatchUpload
  : null;
var pendingBatchLogs = (typeof window !== "undefined" && window.pendingBatchLogs)
  ? window.pendingBatchLogs
  : [];
var sessionContextMenu = (typeof window !== "undefined" && window.sessionContextMenu) ? window.sessionContextMenu : null;
var sessionContextTarget = (typeof window !== "undefined" && window.sessionContextTarget) ? window.sessionContextTarget : null;

function setPendingAttachments(next) {
  pendingAttachments = Array.isArray(next) ? next : [];
  if (typeof window !== "undefined") {
    window.pendingAttachments = pendingAttachments;
  }
}

function setPendingBatchUpload(next) {
  pendingBatchUpload = next || null;
  if (typeof window !== "undefined") {
    window.pendingBatchUpload = pendingBatchUpload;
  }
  updateBatchUploadStatus();
}

function getUploadHintElement(dropzone) {
  if (!dropzone) return null;
  const internal = dropzone.querySelector(".upload-hint");
  if (internal) return internal;
  const sibling = dropzone.nextElementSibling;
  if (sibling && sibling.classList && sibling.classList.contains("upload-hint")) {
    return sibling;
  }
  return null;
}

/**
* ✅ Get the current session
*/
function getCurrentSessionId() {
  const urlParams = new URLSearchParams(window.location.search);
  //console.log(urlParams.get("session_id"));
  return urlParams.get("session_id");
}

function updateSessionIdFromRedirect(redirectUrl) {
  if (!redirectUrl) return null;
  try {
    const nextUrl = new URL(redirectUrl, window.location.origin);
    const sessionId = nextUrl.searchParams.get("session_id");
    if (!sessionId) return null;
    const current = new URL(window.location.href);
    current.searchParams.set("session_id", sessionId);
    window.history.replaceState({}, "", current.toString());
    flushPendingBatchLogs(sessionId);
    return sessionId;
  } catch (error) {
    console.warn("Failed to update session id from redirect:", error);
    return null;
  }
}

function initializeAgentsEmptyState() {
  const chatContainer = document.querySelector(".chat-container");
  const chatBox = document.getElementById("chat-box");
  const inputField = document.getElementById("user-input");
  const emptyState = document.getElementById("chat-empty-state");
  if (!chatContainer || !chatBox || !inputField || !emptyState) return;

  const nameTarget = emptyState.querySelector("[data-user-name]");
  if (nameTarget) {
    nameTarget.textContent = window.USER_NAME || "there";
  }

  if (document.documentElement.dataset.agentsEmptyStateBound === "true") {
    updateAgentsEmptyState();
    return;
  }
  document.documentElement.dataset.agentsEmptyStateBound = "true";

  emptyState.querySelectorAll("[data-example]").forEach(button => {
    button.addEventListener("click", () => {
      const example = button.dataset.example || "";
      inputField.value = example;
      inputField.dispatchEvent(new Event("input", { bubbles: true }));
      inputField.focus();
      updateAgentsEmptyState();
    });
  });

  const observer = new MutationObserver(() => updateAgentsEmptyState());
  observer.observe(chatBox, { childList: true });

  inputField.addEventListener("input", updateAgentsEmptyState);
  inputField.addEventListener("focus", updateAgentsEmptyState);
  inputField.addEventListener("blur", updateAgentsEmptyState);
  updateAgentsEmptyState();
}

function updateAgentsEmptyState() {
  const chatContainer = document.querySelector(".chat-container");
  const chatBox = document.getElementById("chat-box");
  const inputField = document.getElementById("user-input");
  const emptyState = document.getElementById("chat-empty-state");
  const inputContainer = document.querySelector(".chat-input-container");
  if (!chatContainer || !chatBox || !inputField || !emptyState) return;

  const hasMessages = Boolean(chatBox.querySelector(".chat-message, .chat-text"));
  const hasInput = inputField.value.trim().length > 0;
  const dismissed = document.documentElement.dataset.agentsEmptyDismissed === "true";
  const shouldShow = !hasMessages && !dismissed;

  // Embed the input bar in the greeting container when empty; pin it to the bottom once messages exist.
  if (inputContainer) {
    const shell = emptyState.querySelector(".chat-empty-shell");
    const target = shouldShow && shell ? shell : chatContainer;
    if (inputContainer.parentNode !== target) {
      target.appendChild(inputContainer);
    }
  }

  chatContainer.classList.toggle("is-empty", shouldShow);
  document.body.classList.toggle("is-chat-empty", shouldShow);
  emptyState.setAttribute("aria-hidden", shouldShow ? "false" : "true");
}

function setupSessionSwitching() {
  document.querySelectorAll(".chat-history-item").forEach(item => {
    item.addEventListener("click", function (e) {
      if (this.dataset.editing === "true") {
        e.preventDefault();
        return;
      }

      e.preventDefault();

      const sessionId = this.dataset.sessionId;
      if (!sessionId) return;

      // Construir URL limpia sin parámetros previos
      const baseUrl = `${window.location.origin}/dashboard/`;
      window.location.href = `${baseUrl}?view=agents&session_id=${sessionId}`;
    });
  });
}

var SESSION_TITLE_MAX_LENGTH = (typeof window !== "undefined" && window.SESSION_TITLE_MAX_LENGTH) ? window.SESSION_TITLE_MAX_LENGTH : 255;
if (typeof window !== "undefined") {
  window.SESSION_TITLE_MAX_LENGTH = SESSION_TITLE_MAX_LENGTH;
}

function setupSessionTitleEditing() {
  const items = document.querySelectorAll(".chat-history-item");
  if (!items.length) {
    return;
  }

  items.forEach((item) => {
    const titleElement = item.querySelector(".chat-history-title");
    if (!titleElement) {
      return;
    }

    if (!item.dataset.sessionTitle) {
      const storedTitle = item.getAttribute("data-session-title") || titleElement.textContent.trim();
      if (storedTitle) {
        item.dataset.sessionTitle = storedTitle;
      }
    }

    if (!item.dataset.editing) {
      item.dataset.editing = "false";
    }

    const editTrigger = item.querySelector(".chat-edit-trigger");
    if (editTrigger) {
      editTrigger.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        startSessionTitleEdit(item);
      });

      editTrigger.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          event.stopPropagation();
          startSessionTitleEdit(item);
        }
      });
    }
  });
}

function startSessionTitleEdit(item) {
  closeSessionContextMenu();
  if (!item || item.dataset.editing === "true") {
    return;
  }

  const titleElement = item.querySelector(".chat-history-title");
  if (!titleElement) {
    return;
  }

  const currentTitle = item.dataset.sessionTitle || titleElement.textContent.trim() || "Untitled Session";
  item.dataset.editing = "true";
  item.dataset.originalTitle = currentTitle;

  const input = document.createElement("input");
  input.type = "text";
  input.className = "chat-title-input";
  input.value = currentTitle;
  input.maxLength = SESSION_TITLE_MAX_LENGTH;

  titleElement.textContent = "";
  titleElement.appendChild(input);

  requestAnimationFrame(() => {
    input.focus();
    input.select();
  });

  const finalize = (shouldSave) => {
    if (input.dataset.finalized === "true") {
      return;
    }
    input.dataset.finalized = "true";

    if (shouldSave) {
      commitSessionTitleEdit(item, input.value, currentTitle);
    } else {
      cancelSessionTitleEdit(item, currentTitle);
    }
  };

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      finalize(true);
    } else if (event.key === "Escape") {
      event.preventDefault();
      finalize(false);
    }
  });

  input.addEventListener("blur", () => finalize(true));
}

function commitSessionTitleEdit(item, rawValue, originalTitle) {
  const normalizedTitle = (rawValue || "").trim() || "Untitled Session";
  const sessionId = item.dataset.sessionId;

  setSessionTitleDisplay(item, normalizedTitle);
  delete item.dataset.originalTitle;

  if (!sessionId) {
    console.warn("Session id missing for title update.");
    return;
  }

  if (normalizedTitle === originalTitle) {
    return;
  }

  persistSessionTitle(sessionId, normalizedTitle)
    .then((savedTitle) => {
      if (typeof savedTitle === "string" && savedTitle.length) {
        setSessionTitleDisplay(item, savedTitle);
      }
    })
    .catch((error) => {
      console.error("Failed to update session title:", error);
      setSessionTitleDisplay(item, originalTitle);
    });
}

function cancelSessionTitleEdit(item, originalTitle) {
  setSessionTitleDisplay(item, originalTitle);
  delete item.dataset.originalTitle;
}

function setSessionTitleDisplay(item, title) {
  const titleElement = item.querySelector(".chat-history-title");
  if (!titleElement) {
    return;
  }

  const display = truncateTitle(title);
  titleElement.textContent = display;
  item.dataset.sessionTitle = title;
  item.setAttribute("data-session-title", title);
  item.dataset.editing = "false";
}

function truncateTitle(title, maxLength = 24) {
  if (!title) {
    return "Untitled Session";
  }

  if (title.length <= maxLength) {
    return title;
  }

  return `${title.slice(0, Math.max(0, maxLength - 3))}...`;
}

function persistSessionTitle(sessionId, title) {
  return fetch(`/dashboard/chat/session/${encodeURIComponent(sessionId)}/title/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCSRFToken(),
    },
    body: JSON.stringify({ title }),
  }).then(async (response) => {
    if (!response.ok) {
      let errorMessage = `Request failed with status ${response.status}`;
      try {
        const data = await response.json();
        if (data && data.error) {
          errorMessage = data.error;
        }
      } catch (parseError) {
        // Ignore JSON parse errors
      }
      throw new Error(errorMessage);
    }

    try {
      const data = await response.json();
      return data && typeof data.title === "string" ? data.title : title;
    } catch (parseError) {
      return title;
    }
  });
}

function getCSRFToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function setupSessionContextMenu() {
  sessionContextMenu = createSessionContextMenu();
  document.body.appendChild(sessionContextMenu);

  document.querySelectorAll(".chat-history-item").forEach((item) => {
    item.addEventListener("contextmenu", (event) => {
      if (!item.dataset.sessionId) {
        return;
      }

      if (item.dataset.editing === "true") {
        return;
      }

      event.preventDefault();
      sessionContextTarget = item;
      openSessionContextMenu(event);
    });
  });

  document.addEventListener("click", (event) => {
    if (!sessionContextMenu || sessionContextMenu.style.display !== "block") {
      return;
    }

    if (sessionContextMenu.contains(event.target)) {
      return;
    }

    closeSessionContextMenu();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeSessionContextMenu();
    }
  });

  window.addEventListener("resize", closeSessionContextMenu);
  document.addEventListener("scroll", closeSessionContextMenu, true);
}

function createSessionContextMenu() {
  const menu = document.createElement("div");
  menu.className = "chat-context-menu";
  menu.style.display = "none";

  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "chat-context-menu__item chat-context-menu__item--danger";
  deleteButton.textContent = "Delete Session";
  deleteButton.addEventListener("click", () => {
    if (!sessionContextTarget) {
      return;
    }

    const sessionId = sessionContextTarget.dataset.sessionId;
    if (!sessionId) {
      return;
    }

    const confirmed = window.confirm("Delete this chat session?");
    if (!confirmed) {
      closeSessionContextMenu();
      return;
    }

    deleteChatSession(sessionId)
      .then((result) => {
        if (result.was_active) {
          window.location.href = `${window.location.origin}/dashboard/?view=agents`;
          return;
        }

        if (sessionContextTarget && sessionContextTarget.parentElement) {
          sessionContextTarget.parentElement.removeChild(sessionContextTarget);
        }
      })
      .catch((error) => {
        console.error("Failed to delete session:", error);
      })
      .finally(() => {
        closeSessionContextMenu();
      });
  });

  menu.appendChild(deleteButton);
  return menu;
}

function openSessionContextMenu(event) {
  if (!sessionContextMenu) {
    return;
  }

  sessionContextMenu.style.display = "block";
  sessionContextMenu.style.visibility = "hidden";

  const { pageX, pageY } = event;
  const menuWidth = sessionContextMenu.offsetWidth;
  const menuHeight = sessionContextMenu.offsetHeight;
  const viewportWidth = window.innerWidth + window.scrollX;
  const viewportHeight = window.innerHeight + window.scrollY;

  const left = Math.min(pageX, viewportWidth - menuWidth - 8);
  const top = Math.min(pageY, viewportHeight - menuHeight - 8);

  sessionContextMenu.style.left = `${Math.max(left, 8)}px`;
  sessionContextMenu.style.top = `${Math.max(top, 8)}px`;
  sessionContextMenu.style.visibility = "visible";
}

function closeSessionContextMenu() {
  if (!sessionContextMenu) {
    return;
  }

  sessionContextMenu.style.display = "none";
  sessionContextMenu.style.visibility = "hidden";
  sessionContextTarget = null;
}

function deleteChatSession(sessionId) {
  return fetch(`/dashboard/chat/session/${encodeURIComponent(sessionId)}/delete/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCSRFToken(),
    },
  }).then(async (response) => {
    if (!response.ok) {
      let errorMessage = `Request failed with status ${response.status}`;
      try {
        const data = await response.json();
        if (data && data.error) {
          errorMessage = data.error;
        }
      } catch (parseError) {
        // swallow JSON parse errors
      }
      throw new Error(errorMessage);
    }

    try {
      return await response.json();
    } catch (parseError) {
      return { success: true, was_active: false };
    }
  });
}

function showAgentFeedback() {
  const feedback = document.getElementById("agent-feedback");
  if (document.documentElement.dataset.agentsEmptyDismissed !== "true") {
    document.documentElement.dataset.agentsEmptyDismissed = "true";
    if (typeof updateAgentsEmptyState === "function") {
      updateAgentsEmptyState();
    }
  }
  if (feedback) {
    setAgentFeedbackVisibility(true);
    startThinkingAnimation();
    scrollToBottom("showAgentFeedback");
  }
}

function hideAgentFeedback() {
  const feedback = document.getElementById("agent-feedback");
  stopThinkingAnimation();
  if (feedback) {
    setAgentFeedbackVisibility(false);
  }
}

function setAgentFeedbackVisibility(isVisible) {
  const feedback = document.getElementById("agent-feedback");
  if (!feedback) return;
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (isMobile) {
    feedback.style.display = "block";
    feedback.style.visibility = isVisible ? "visible" : "hidden";
    feedback.classList.toggle("is-visible", isVisible);
  } else {
    feedback.style.display = isVisible ? "block" : "none";
    feedback.style.visibility = "";
    feedback.classList.remove("is-visible");
  }
}

let thinkingInterval = null;
function startThinkingAnimation() {
  const el = document.querySelector("#agent-feedback .thinking-text");
  if (!el) return;
  stopThinkingAnimation();
  el.classList.add("thinking-text--dots");
  el.innerHTML = 'Thinking<span class="thinking-dot">.</span><span class="thinking-dot">.</span><span class="thinking-dot">.</span>';
}

function stopThinkingAnimation() {
  if (thinkingInterval) {
    clearInterval(thinkingInterval);
    thinkingInterval = null;
  }
}

function setupChatListeners() {
  console.log("Setting up chat listeners...");

  const inputField = document.getElementById("user-input");
  const button = document.getElementById("send-btn");
  const chatBox = document.getElementById("chat-box");

  if (!inputField || !button) {
      console.error("Chat input or button not found!");
      return;
  }

  button.addEventListener("click", sendMessage);
  inputField.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    if (event.shiftKey) return; // allow newline
    event.preventDefault();
    sendMessage();
  });

  const autosize = () => {
    if (inputField.tagName !== "TEXTAREA") return;
    inputField.style.height = "auto";
    const maxHeight = 160;
    const nextHeight = Math.min(inputField.scrollHeight, maxHeight);
    inputField.style.height = `${nextHeight}px`;
    inputField.style.overflowY = inputField.scrollHeight > maxHeight ? "auto" : "hidden";
  };

  inputField.addEventListener("input", autosize);
  autosize();

  if (chatBox && chatBox.dataset.quickReplyBound !== "true") {
    chatBox.dataset.quickReplyBound = "true";
    chatBox.addEventListener("click", (event) => {
      const trigger = event.target.closest("[data-chat-reply]");
      if (!trigger) return;
      event.preventDefault();

      const reply = String(trigger.dataset.chatReply || "").trim();
      if (!reply) return;

      inputField.value = reply;
      inputField.dispatchEvent(new Event("input", { bubbles: true }));

      const shouldSend = String(trigger.dataset.chatSend || "").toLowerCase() === "true";
      if (shouldSend) {
        sendMessage();
      } else {
        inputField.focus();
      }
    });
  }

  console.log("Chat listeners attached.");
}

const BATCH_FILE_TYPES = new Set([
  "text/csv",
  "text/tab-separated-values",
  "application/vnd.ms-excel",
  "text/plain",
]);
const BATCH_FILE_EXTENSIONS = [".csv", ".tsv"];

function isBatchFile(file) {
  if (!file) return false;
  const name = String(file.name || "").toLowerCase();
  if (BATCH_FILE_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return true;
  }
  return file.type ? BATCH_FILE_TYPES.has(file.type) : false;
}

function setupUploadZone() {
  const dropzone = document.getElementById("upload-dropzone");
  const fileInput = document.getElementById("upload-input");
  const browseBtn = document.getElementById("upload-browse-btn");
  const batchInput = document.getElementById("batch-upload-input");
  const batchBtn = document.getElementById("batch-upload-btn");

  if (!dropzone || !fileInput) {
    updateAttachmentPreview();
    return;
  }

  const activateDropzone = (event) => {
    event.preventDefault();
    dropzone.classList.add("is-dragover");
  };

  const deactivateDropzone = (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-dragover");
  };

  ["dragenter", "dragover"].forEach((evt) => {
    dropzone.addEventListener(evt, activateDropzone);
  });

  ["dragleave", "dragend"].forEach((evt) => {
    dropzone.addEventListener(evt, deactivateDropzone);
  });

  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-dragover");
    const files = Array.from(event.dataTransfer?.files || []);
    const batchFiles = files.filter((file) => isBatchFile(file));
    const attachmentFiles = files.filter((file) => !isBatchFile(file));
    handleBatchFiles(batchFiles);
    handleAttachmentFiles(attachmentFiles);
  });

  if (browseBtn) {
    browseBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      fileInput.click();
    });
  }

  fileInput.addEventListener("change", (event) => {
    const files = Array.from(event.target.files || []);
    handleAttachmentFiles(files);
    fileInput.value = "";
  });

  if (batchBtn && batchInput) {
    batchBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      batchInput.click();
    });
  }

  if (batchInput) {
    batchInput.addEventListener("change", (event) => {
      const files = Array.from(event.target.files || []);
      handleBatchFiles(files);
      batchInput.value = "";
    });
  }
}

async function loadPendingAttachments() {
  const dropzone = document.getElementById("upload-dropzone");
  if (!dropzone) {
    return;
  }

  try {
    const response = await fetch("/agents/upload-attachment/");
    if (!response.ok) {
      if (response.status === 400 || response.status === 503) {
        dropzone.classList.add("is-disabled");
        const hint = getUploadHintElement(dropzone);
        if (hint) {
          hint.textContent = response.status === 503
            ? "Attachment uploads need pending migrations. Contact your administrator."
            : "Open or create a quote to enable attachments.";
        }
      }
      setPendingAttachments([]);
      renderAttachmentList();
      updateAttachmentPreview();
      return;
    }

    const data = await response.json();
    setPendingAttachments(Array.isArray(data.attachments) ? data.attachments : []);
    dropzone.classList.remove("is-disabled");
    const hint = getUploadHintElement(dropzone);
    if (hint) {
      hint.textContent = UPLOAD_HINT_DEFAULT;
    }
    renderAttachmentList();
  } catch (error) {
    console.error("Failed to load pending attachments:", error);
    setPendingAttachments([]);
    renderAttachmentList();
  }
}

async function handleBatchFiles(files) {
  if (!files.length) {
    return;
  }

  if (document.documentElement.dataset.agentsEmptyDismissed !== "true") {
    document.documentElement.dataset.agentsEmptyDismissed = "true";
    if (typeof updateAgentsEmptyState === "function") {
      updateAgentsEmptyState();
    }
  }

  for (const file of files) {
    if (!file) continue;
    try {
      const content = await file.text();
      const cleaned = String(content || "").trim();
      if (!cleaned) {
        showQuoteToast(`⚠️ ${file.name} is empty.`, "error");
        continue;
      }

      const replaced = pendingBatchUpload && pendingBatchUpload.name;
      setPendingBatchUpload({
        name: file.name,
        content: cleaned,
        receivedAt: new Date().toISOString(),
      });
      const replaceNote = replaced ? ` (replaced ${escapeHtml(replaced)})` : "";
      appendBatchStatusMessage(
        `CSV ready: ${escapeHtml(file.name)}${replaceNote}. Tell me what to create (e.g. "Create Leads from upload").`,
        "info"
      );
      showQuoteToast(`CSV loaded: ${file.name}.`, "info");
    } catch (error) {
      console.error("Batch file processing failed:", error);
      showQuoteToast(`❌ Couldn't import ${file.name}: ${error.message}`, "error");
    } finally {
      hideAgentFeedback();
    }
  }
}

async function handleAttachmentFiles(files) {
  const dropzone = document.getElementById("upload-dropzone");
  if (!files.length) {
    return;
  }

  if (dropzone && dropzone.classList.contains("is-disabled")) {
    await loadPendingAttachments();
    if (dropzone.classList.contains("is-disabled")) {
      const hint = getUploadHintElement(dropzone);
      const fallbackMessage = hint ? hint.textContent : "⚠️ Open or create a quote before attaching files.";
      appendMessage(
        "agent",
        agentNoticeMarkup(fallbackMessage || "⚠️ Open or create a quote before attaching files.")
      );
      return;
    }
  }

  files.forEach((file) => uploadAttachment(file));
}

function renderAttachmentList() {
  const listEl = document.getElementById("upload-list");
  if (!listEl) {
    return;
  }

  listEl.innerHTML = "";

  listEl.style.display = "block";

  if (!pendingAttachments.length) {
    const emptyItem = document.createElement("li");
    emptyItem.classList.add("upload-empty");
    emptyItem.textContent = "No attachments";
    listEl.appendChild(emptyItem);
  } else {
    pendingAttachments.forEach((attachment) => {
      const item = document.createElement("li");
      const nameEl = document.createElement("span");
      nameEl.classList.add("upload-name");
      nameEl.textContent = attachment.original_name || "Attachment";

      const metaEl = document.createElement("span");
      metaEl.classList.add("upload-meta");
      if (attachment.uploaded_at) {
        const uploadedDate = new Date(attachment.uploaded_at);
        metaEl.textContent = uploadedDate.toLocaleString();
      }

      item.appendChild(nameEl);
      item.appendChild(metaEl);
      listEl.appendChild(item);
    });
  }

  updateAttachmentPreview();
}

function updateAttachmentPreview() {
  const previewEl = document.getElementById("attachment-preview");
  if (!previewEl) return;
  const detailEl = previewEl.querySelector("[data-attachment-details]");
  const supportsDetails = Boolean(detailEl);

  if (!pendingAttachments.length) {
    previewEl.classList.add("is-empty");
    if (supportsDetails) {
      detailEl.innerHTML = "";
    }
    return;
  }

  const latest = pendingAttachments[0];
  const name = latest.original_name || "Attachment";
  let meta = "";
  if (latest.uploaded_at) {
    meta = new Date(latest.uploaded_at).toLocaleString();
  }

  previewEl.classList.remove("is-empty");
  const content = `
    <span class="material-icons" aria-hidden="true">attach_file</span>
    <span class="attachment-name">${escapeHtml(name)}</span>
    ${meta ? `<span class="attachment-meta">${escapeHtml(meta)}</span>` : ""}
  `;
  if (supportsDetails) {
    detailEl.innerHTML = content;
  } else {
    previewEl.innerHTML = content;
  }
}

function updateBatchUploadStatus() {
  const statusEl = document.getElementById("batch-upload-status");
  if (!statusEl) return;
  if (!pendingBatchUpload || !pendingBatchUpload.name) {
    statusEl.textContent = "";
    statusEl.classList.remove("is-active");
    return;
  }
  statusEl.textContent = `CSV ready: ${pendingBatchUpload.name}`;
  statusEl.classList.add("is-active");
}

function agentNoticeMarkup(message) {
  return `
    <div class="senderagent">
      <img width="95px" src="/static/img/agentcpq-chat-icon.png" alt="AgentCPQ Logo">
    </div>
    <div class="message">${message}</div>
  `;
}

async function uploadAttachment(file) {
  const allowedTypes = [
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
  ];
  const maxSize = 8 * 1024 * 1024; // 8 MB

  if (!allowedTypes.includes(file.type)) {
    appendMessage(
      "agent",
      agentNoticeMarkup(`⚠️ <strong>${escapeHtml(file.name)}</strong> is not a supported format. Please upload PNG, JPG, GIF, or WEBP.`)
    );
    return;
  }

  if (file.size > maxSize) {
    appendMessage(
      "agent",
      agentNoticeMarkup(`⚠️ <strong>${escapeHtml(file.name)}</strong> is too large. Keep attachments under 8 MB.`)
    );
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  const sessionId = getCurrentSessionId();
  if (sessionId) {
    formData.append("session_id", sessionId);
  }

  try {
    const response = await fetch("/agents/upload-attachment/", {
      method: "POST",
      body: formData,
    });

    const payload = await response.json();

    if (!response.ok) {
      if (response.status === 503) {
        const dropzone = document.getElementById("upload-dropzone");
        if (dropzone) {
          dropzone.classList.add("is-disabled");
          const hint = getUploadHintElement(dropzone);
          if (hint) {
            hint.textContent = "Attachment uploads need pending migrations. Contact your administrator.";
          }
        }
      }
      throw new Error(payload.error || "Upload failed");
    }

    if (payload.attachment) {
      pendingAttachments.unshift(payload.attachment);
      renderAttachmentList();
    }

    appendMessage(
      "agent",
      agentNoticeMarkup(`📎 <strong>${escapeHtml(file.name)}</strong> uploaded. I'll merge it into the next quote PDF.`)
    );
  } catch (error) {
    console.error("Attachment upload failed:", error);
    appendMessage(
      "agent",
      agentNoticeMarkup(`❌ Couldn't upload <strong>${escapeHtml(file.name)}</strong>: ${escapeHtml(error.message)}`)
    );
  }
}

function renderGreeting() {
  if (document.getElementById("chat-empty-state")) {
    initializeAgentsEmptyState();
    return;
  }
  const chatBox = document.getElementById("chat-box");
  const userName = window.USER_NAME || "User";
  const greetingKey = `agentcpqGreetingShown:${encodeURIComponent(userName)}`;
  if (localStorage.getItem(greetingKey) === "true") return;
  // Check if chat box exists and is empty
  if (!chatBox || chatBox.children.length > 0) return;

  const greetingText = `
👋 <b>Hello ${userName} and welcome to AgentCPQ!</b><br><br>
I’m here to make quoting simpler than ever.<br><br>
You’ll notice there’s no traditional UI full of forms, buttons, or menus — that’s intentional. Everything happens right here, in one place. No clutter. No wiki. Just ask, and I’ll handle it for you.<br><br>
If you want to see this message in the future, just ask: "Show me the initial instructions in AgentCPQ".<br><br>
<b>Before you start:</b><br>
Like any quoting system, we’ll begin with your products.<br>
Try saying:<br>
<i>“Create a product called AgentCPQ-Solo, SKU ACPQ-SOLO, priced at $250, and mark it as a subscription.”</i><br><br>
That’s all you need to start using AgentCPQ.<br><br>

<span style="display:flex; align-items:center; gap:10px; margin-top:10px;">
  <img src="/static/img/agentcpq-6.png" width="70" style="vertical-align:middle;">
  <span style="font-weight:bold; color:#fc6a3d; font-size:1.2rem;">Quoting Agent</span>
</span><br>
Next, you can create a quote for a specific account.<br>
If the account or opportunity doesn’t exist, I’ll create them automatically.<br>
Once a quote exists, say:<br>
<i>“Add product ACPQ-SOLO, quantity 5.”</i><br><br>
You can also apply discounts, remove or edit line items, and add more products.<br>
Prefer visuals? Just say <b>“Show quote details.”</b><br>
You’ll get an inline editor where every change auto-saves — no buttons required.<br>
When you’re ready, simply ask <b>“Generate PDF.”</b><br><br>

<span style="display:flex; align-items:center; gap:10px; margin-top:10px;">
  <img src="/static/img/agentcpq-6.png" width="70" style="vertical-align:middle;">
  <span style="font-weight:bold; color:#fc6a3d; font-size:1.2rem;">Bundles (Admin Agent)</span>
</span><br>
To create a bundle:<br>
<i>“Create a new product called Enterprise Suite — it’s a bundle.”</i><br>
Then link products together:<br>
<i>“Add Product B as an option to Bundle Product A.”</i><br>
You can then add your new bundle to an existing or new quote.<br>
💡 <i>Tip: To reset your session anytime, say “Start fresh.”</i><br><br>

<span style="display:flex; align-items:center; gap:10px; margin-top:10px;">
  <img src="/static/img/agentcpq-6.png" width="70" style="vertical-align:middle;">
  <span style="font-weight:bold; color:#fc6a3d; font-size:1.2rem;">Analytics Agent</span>
</span><br>
You can also explore insights and reporting. Try:<br>
<i>“Show my quotes where net amount is greater than $30,000.”</i><br>
<i>“Show my last three opportunities.”</i><br>
<i>“List my bundle products.”</i><br><br>
You can view your products on the left panel — or, if you prefer fewer clicks, just ask me.<br><br>

<span style="display:flex; align-items:center; gap:10px; margin-top:10px;">
  <img src="/static/img/agentcpq-6.png" width="70" style="vertical-align:middle;">
  <span style="font-weight:bold; color:#fc6a3d; font-size:1.2rem;">Rules & Validations (Admin Agent)</span>
</span><br>
Want to enforce business logic? Just ask:<br>
<i>“Create a validation rule for product ACPQ-SOLO to prevent discounts greater than 70%.”</i><br>
Then test it by applying a 75% discount — I’ll show the error automatically.<br>
You can create similar rules for price, quantity, or other attributes.<br><br>

<b>Thank you for joining AgentCPQ!</b><br>
Keep things simple, ask naturally, and let me do the work.<br><br>
If you’ve already tried AgentCPQ, we’d love your feedback ❤️<br>
<a href="https://docs.google.com/forms/d/e/1FAIpQLSeNtxmgcXjyeOoraXgeLqtY05nC6a6prJcec_YXnkrS8zLydw/viewform" 
   target="_blank" 
   style="color:#fc6a3d; font-weight:bold; text-decoration:none;">
   👉 Click here to complete our quick survey
</a><br><br>
Your input helps us make AgentCPQ even better!
`;

  const greeting = document.createElement("div");
  greeting.classList.add("chat-text", "agent");
  greeting.innerHTML = `
    <div class="senderagent">
      <img width="95px" src="/static/img/agentcpq-chat-icon.png" alt="AgentCPQ Logo">
    </div>
    <div class="message">${greetingText}</div>
  `;

  chatBox.appendChild(greeting);
  chatBox.scrollTop = chatBox.scrollHeight;
  localStorage.setItem(greetingKey, "true");
}

function toggleSidebar() {
    document.querySelector(".sidenav-fixed").classList.toggle("active");
}

function colapseSidebar() {
    const sidenav = document.querySelector(".sidenav-fixed");
    const icon = document.getElementById("collapse-icon");
    const maincontent = document.querySelector(".main-content");

    const isCollapsed = sidenav.classList.toggle("collapse_sidebar");
    maincontent.classList.toggle("main-content-collapsed", isCollapsed);

    // Save collapsed state
    localStorage.setItem("sidebarCollapsed", isCollapsed ? "true" : "false");

    // Toggle icon direction
    icon.textContent = isCollapsed ? "chevron_right" : "chevron_left";
}

function unescapeUnicode(str) {
    return str.replace(/\\u[\dA-F]{4}/gi, function (match) {
      return String.fromCharCode(parseInt(match.replace(/\\u/g, ''), 16));
    });
  }

/*
* ✅ enhanceStructuredAgentMessages in real time, when user send a message
*/
function enhanceStructuredAgentMessages() {
    document.querySelectorAll(".agent-json").forEach(div => {
      const raw = div.dataset.raw;

      const jsonStr = extractJson(raw);
      if (!jsonStr) {
        div.innerHTML = `<div class="error-message">⚠️ Could not find valid JSON in message</div>`;
        return;
      }

      try {
        const data = JSON.parse(unescapeUnicode(jsonStr));
        // Process data
      } catch (e) {
        console.error("JSON parse failed:", e, jsonStr);
        div.innerHTML = `<div class="error-message">❌ JSON parsing error</div>`;
      }
    });
  }

/*
* ✅ enhanceStructuredAgentMessages in history chat, NOT in real time

function extractJson(text) {
  const startObj = text.indexOf('{');
  const startArr = text.indexOf('[');

  let start = -1;
  if (startObj === -1) start = startArr;
  else if (startArr === -1) start = startObj;
  else start = Math.min(startObj, startArr);

  if (start === -1) return null;

  return text.slice(start).trim();
}
 */

function unescapeUnicode(str) {
  return str.replace(/\\u[\dA-F]{4}/gi, function (match) {
    return String.fromCharCode(parseInt(match.replace(/\\u/g, ''), 16));
  });
}

/**
 * Strips a structured payload suffix (like `quote_details: { ... }`) from an agent message
 * only when there is a human-readable prefix before the key.
 *
 * This prevents the UI from dumping large JSON blobs after a normal confirmation message.
 */
function stripStructuredSuffixFromAgentMessage(message, keys) {
  if (typeof message !== "string" || !message) return { message, stripped: false };
  const keyList = Array.isArray(keys) ? keys : [keys];

  for (const key of keyList) {
    const idx = message.indexOf(key);
    if (idx === -1) continue;

    const before = message.slice(0, idx).trimEnd();
    if (!before) return { message, stripped: false };

    return { message: before, stripped: true };
  }

  return { message, stripped: false };
}

const WARNING_ICON_HTML =
  '<span class="material-icons" style="font-size:22px;vertical-align:middle;color:#ffd32e;margin-right:6px;">warning</span>';

function addWarningIconPrefix(message) {
  if (typeof message !== "string" || !message) return message;
  if (message.includes("{WARNING_ICON}")) {
    return message.replace(/{WARNING_ICON}/g, WARNING_ICON_HTML);
  }
  if (message.includes(WARNING_ICON_HTML)) return message;
  const textOnly = message.replace(/<[^>]*>/g, "").trim();
  if (!/^warning\b/i.test(textOnly)) return message;
  return `${WARNING_ICON_HTML} ${message}`;
}

function stripStructuredSuffixInElement(el, keys) {
  if (!el) return false;
  const cleaned = stripStructuredSuffixFromAgentMessage(el.innerHTML, keys);
  if (!cleaned.stripped) return false;
  el.innerHTML = cleaned.message;
  return true;
}

function stripStructuredSuffixesInHistory() {
  const keys = ["quote_details:", "update_details:", "intelligence_dashboard:"];
  const messages = document.querySelectorAll(".chat-message.agent .message");
  messages.forEach((el) => {
    if (!el || !el.innerHTML) return;
    const html = el.innerHTML;
    const containsKey = keys.some((key) => html.includes(key));
    if (!containsKey) return;

    const cleaned = stripStructuredSuffixFromAgentMessage(html, keys);
    if (cleaned.stripped) {
      el.innerHTML = cleaned.message;
      return;
    }

    // If the message is only structured JSON, hide the blob.
    const firstKeyIdx = keys
      .map((key) => html.indexOf(key))
      .filter((idx) => idx >= 0)
      .sort((a, b) => a - b)[0];
    if (firstKeyIdx === 0) {
      el.innerHTML = "";
    }
  });
}

function renderPdfSuccess(downloadUrl, version) {
  const safeUrl = escapeHtml(String(downloadUrl || ""));
  const safeVersion = escapeHtml(String(version || ""));
  return `
    <div class="pdf-success-card">
      <div class="pdf-success-icon">
        <span class="material-icons" aria-hidden="true">description</span>
      </div>
      <div class="pdf-success-body">
        <div class="pdf-success-title">PDF generated</div>
        <div class="pdf-success-subtitle">Version v${safeVersion}</div>
      </div>
      <a class="pdf-download-btn" href="${safeUrl}" target="_blank" rel="noopener" aria-label="Download PDF">
        <span class="material-icons" aria-hidden="true">download</span>
      </a>
    </div>
  `;
}

function extractEmbeddedJsonPayload(rawMessage, key) {
  if (typeof rawMessage !== "string" || !rawMessage) return null;
  const idx = rawMessage.indexOf(key);
  if (idx === -1) return null;
  const afterKey = rawMessage.slice(idx + key.length);
  const jsonPart = extractJson(afterKey);
  if (!jsonPart) return null;
  try {
    return JSON.parse(unescapeUnicode(jsonPart));
  } catch {
    return null;
  }
}

function shouldSkipDuplicateAgentMessage(messageHtml) {
  const chatBox = document.getElementById("chat-box");
  if (!chatBox) return false;
  const lastMessage = chatBox.querySelector(".chat-message.agent:last-of-type .message");
  if (!lastMessage) return false;

  const nextHtml = (messageHtml || "").trim();
  if (!nextHtml) return false;

  const lastHtml = (lastMessage.innerHTML || "").trim();
  const now = Date.now();
  const lastAt = window.lastAgentMessageAt || 0;

  if (lastHtml === nextHtml && (now - lastAt) < 2000) {
    return true;
  }
  return false;
}

function attachQuoteDetailsToggle(targetEl, quoteObj) {
  if (!targetEl || !quoteObj) return null;

  const wrapper = document.createElement("div");
  wrapper.className = "structured-toggle";
  wrapper.dataset.type = "quote_details";
  wrapper.dataset.payload = JSON.stringify(quoteObj);
  wrapper.dataset.rendered = "false";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "structured-toggle__btn";
  btn.innerHTML = `
    <span class="structured-toggle__label">Quote details</span>
    <i class="material-icons structured-toggle__chev" aria-hidden="true">chevron_right</i>
  `;
  btn.setAttribute("aria-expanded", "false");

  const body = document.createElement("div");
  body.className = "structured-toggle__body";
  body.style.display = "none";

  wrapper.appendChild(btn);
  wrapper.appendChild(body);
  targetEl.appendChild(wrapper);
  return wrapper;
}

function setStructuredToggleButtonState(btn, open) {
  if (!btn) return;
  const chevEl = btn.querySelector(".structured-toggle__chev");
  if (chevEl) chevEl.textContent = open ? "expand_more" : "chevron_right";
  btn.setAttribute("aria-expanded", open ? "true" : "false");
}

function setupStructuredToggles() {
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".structured-toggle__btn");
    if (!btn) return;

    const wrapper = btn.closest(".structured-toggle");
    if (!wrapper) return;

    const body = wrapper.querySelector(".structured-toggle__body");
    if (!body) return;

    const isOpen = body.style.display !== "none";
    if (isOpen) {
      body.style.display = "none";
      setStructuredToggleButtonState(btn, false);
      return;
    }

    // Lazy render on first open
    if (wrapper.dataset.type === "quote_details" && wrapper.dataset.rendered !== "true") {
      try {
        const payload = JSON.parse(wrapper.dataset.payload || "{}");
        ensureQuoteStatusValue(payload);
        body.innerHTML = renderQuoteDetails(payload);
        wrapper.dataset.rendered = "true";

        initializeQuoteDetailInteractions(body);
        initializeMaterializeSelects(body);
        initializeBundleStructureCards(body);
      } catch (err) {
        console.warn("Failed to render quote_details toggle payload:", err);
        body.innerHTML = `<div class="error-message">⚠️ Could not render quote details.</div>`;
      }
    }

    body.style.display = "block";
    setStructuredToggleButtonState(btn, true);
    requestAnimationFrame(() => {
      const chatBox = document.getElementById("chat-box");
      if (!chatBox) return;

      const chatRect = chatBox.getBoundingClientRect();
      const bodyRect = body.getBoundingClientRect();
      const padding = 18;

      const delta = bodyRect.bottom - (chatRect.bottom - padding);
      if (delta > 0) {
        chatBox.scrollTop += delta;
      }
    });
  }, { capture: false });
}

function enhanceStructuredAgentMessagesHistoryChat() {
  document.querySelectorAll(".agent-json").forEach(div => {
    const raw = div.dataset.raw;

    // Claves a buscar en el mensaje
    const keys = [
      'quote_details:',
      'update_details:',
      'intelligence_dashboard:',
      'single_record:',
      'validation_rules_details:',
      'rules:',
      'email_alerts_details:',
      'retrieved_records:',
      'inclusion_rules_details:',
      'action_triggers_details:',
      'exclusion_rules_details',
      'openGraphicBuilder'
    ];

    let jsonPart = null;
    let matchedKey = null;

    // Buscar la primera key que aparezca en el mensaje
    for (const key of keys) {
      const idx = raw.indexOf(key);
      if (idx !== -1) {
        matchedKey = key;
        const afterKey = raw.slice(idx + key.length);
        jsonPart = extractJson(afterKey);
        if (jsonPart) break;
      }
    }

    if (!jsonPart) {
      div.innerHTML = `<div class="error-message">⚠️ Could not find valid JSON in message</div>`;
      return;
    }

    try {
      const data = JSON.parse(unescapeUnicode(jsonPart));
      const hasPrefix = Boolean(matchedKey && raw.slice(0, raw.indexOf(matchedKey)).trim());

      //console.log("This is data: ", data);

      // === VALIDATION RULES ===
      if (data.rules || (Array.isArray(data) && data[0]?.rule_type == 'validation')) {
        const html = renderValidationRuleDetails(data.rules || data);
        div.innerHTML = html;
        return;
      }

      // === INCLUSION RULES ===
      if (data.rules || (Array.isArray(data) && data[0]?.rule_type == 'inclusion')) {
        let fullMessage = unescapeUnicode(raw);

        const html = renderInclusionRuleDetails(
          fullMessage,
          data.rules || data
        );
        div.innerHTML = html;
        return;
      }

      // === EXCLUSION RULES ===
      if (data.rules || (Array.isArray(data) && data[0]?.rule_type == 'exclusion')) {
        let fullMessage = unescapeUnicode(raw);

        const html = renderExclusionRuleDetails(
          fullMessage,
          data.rules || data
        );
        div.innerHTML = html;
        return;
      }

      if (matchedKey === 'single_record:') {
        let messageBeforeJson = raw.slice(0, raw.indexOf(matchedKey)).trim();
        messageBeforeJson = unescapeUnicode(messageBeforeJson);
        messageBeforeJson = messageBeforeJson.replace(/\\u003C/g, "<").replace(/\\u003E/g, ">");

        const recordHtml = renderSingleRecord(data);
        const prefix = messageBeforeJson ? `<div class="general-message">${messageBeforeJson}</div>` : '';
        div.innerHTML = `${prefix}${recordHtml}`;
        return;
      }

      // === ACTION TRIGGERS ===
      if (matchedKey === 'action_triggers_details:') {
        const fullMessage = unescapeUnicode(raw);
        // Normalizar a array: el LLM puede devolver directamente un array o un objeto con la key
        const triggers = Array.isArray(data)
          ? data
          : (data.action_triggers || data.action_triggers_details || data.triggers || data.rules || []);
        const html = renderActionTriggersDetails(fullMessage, triggers);
        div.innerHTML = html;
        return;
      }

      // === ACTION TRIGGERS ===
      if (matchedKey === 'openGraphicBuilder:') {
        console.log("Si es openGraphicBuilder")
        const html = renderGraphicBuilderForActionTrigger(data);
        div.innerHTML = html;
        return;
      }

      // === RULES ===
      if (data.rules || (Array.isArray(data) && data[0]?.rules_request_description)) {
        const html = renderRules(data);
        div.innerHTML = html;
        return;
      }

      // === RETRIEVED RECORDS ===
      if (matchedKey === 'retrieved_records:') {
        const html = renderRetrievedRecords("", data);
        div.innerHTML = html;
        initializeMetricCards(div);
        return;
      }

      // === INTELLIGENCE DASHBOARD ===
      if (matchedKey === 'intelligence_dashboard:') {
        const html = renderIntelligenceDashboard(data);
        div.innerHTML = html;
        return;
      }

      // === EMAIL ALERTS ===
      if (Array.isArray(data) && data[0]?.trigger) {
        const html = renderEmailAlerstDetails(data);
        div.innerHTML = html;
        return;
      }

      // === QUOTE DETAILS (editable) ===
      if (matchedKey === 'quote_details:' || matchedKey === 'update_details:') {
        ensureQuoteStatusValue(data);
        const quoteHtml = renderQuoteDetails(data);
        div.innerHTML = `${quoteHtml}`;

        // History-rendered quote cards still need JS bindings (flatpickr, selects, notes autosave).
        initializeQuoteDetailInteractions(div);
        initializeMaterializeSelects(div);
        initializeBundleStructureCards(div);
        return;
      }

      // === QUOTE DETAILS (por defecto si no entró en nada anterior) ===
      const html = renderReadOnlyQuoteDetails(data);
      div.innerHTML = html;

    } catch (e) {
      console.error("❌ JSON parse failed:", e, jsonPart);
      div.innerHTML = `<div class="error-message">❌ Error trying to display the structured message. (JSON parsing error)</div>`;
    }
  });

  // === PDFs ===
  document.querySelectorAll(".agent-pdf").forEach(div => {
    const raw = unescapeUnicode(div.dataset.raw);
    if (!raw.includes("download_url")) return;

    const urlMatch = raw.match(/download_url:\s*["']?(.*?)["']?\s*(\n|$)/);
    const versionMatch = raw.match(/document_version:\s*([0-9]+)/);

    const downloadUrl = urlMatch ? urlMatch[1].trim() : null;
    const version = versionMatch ? versionMatch[1].trim() : null;

    if (downloadUrl && version) {
      div.innerHTML = renderPdfSuccess(downloadUrl, version);
    } else {
      div.innerHTML = `<div class="error-message">⚠️ Could not extract PDF fields</div>`;
    }
  });

  // === Auto-scroll chat ===
  const chatBox = document.getElementById("chat-box");
  if (chatBox) {
    chatBox.scrollTop = chatBox.scrollHeight;
  }

  initializeBundleStructureCards(document);
}



function escapeHtml(text) {
  const map = {
    '&': "&amp;",
    '<': "&lt;",
    '>': "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  };
  return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}


const BATCH_ROW_SIZE = 5;
const BATCH_UPDATE_DATA_MARKER = "__BATCH_DATA_START__";
const batchSchemaCache = {
  loaded: false,
  data: null,
};

function normalizeBatchHeader(label) {
  return String(label || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

function normalizeBatchSearch(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function parseDelimitedLine(line, delimiter) {
  const result = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (char === delimiter && !inQuotes) {
      result.push(current.trim());
      current = "";
      continue;
    }
    current += char;
  }
  result.push(current.trim());
  return result;
}

function parseDelimitedBatch(cleaned) {
  const rawLines = cleaned.split(/\r?\n/);
  let headerIndex = -1;
  let delimiter = null;
  let headerColumns = [];

  for (let i = 0; i < rawLines.length; i += 1) {
    const line = rawLines[i].trim();
    if (!line) continue;
    if (line.includes("\t")) {
      const parsed = parseDelimitedLine(line, "\t");
      if (parsed.length > 1) {
        headerIndex = i;
        delimiter = "\t";
        headerColumns = parsed;
        break;
      }
    }
    if (line.includes(",")) {
      const parsed = parseDelimitedLine(line, ",");
      if (parsed.length > 1) {
        headerIndex = i;
        delimiter = ",";
        headerColumns = parsed;
        break;
      }
    }
  }

  if (headerIndex === -1) {
    return null;
  }

  const preambleLines = rawLines.slice(0, headerIndex).map((line) => line.trim()).filter(Boolean);
  const headerLines = headerColumns.map((col) => col.trim()).filter(Boolean);
  if (headerLines.length < 2) {
    return null;
  }

  const records = [];
  let rowMismatch = false;
  const headerLength = headerLines.length;
  for (let i = headerIndex + 1; i < rawLines.length; i += 1) {
    const line = rawLines[i];
    if (!line || !line.trim()) {
      continue;
    }
    const parsed = parseDelimitedLine(line, delimiter);
    if (parsed.length === 1 && !parsed[0]) {
      continue;
    }
    let row = parsed;
    if (row.length < headerLength) {
      rowMismatch = true;
      row = [...row, ...Array(headerLength - row.length).fill("")];
    } else if (row.length > headerLength) {
      rowMismatch = true;
      const head = row.slice(0, headerLength - 1);
      const tail = row.slice(headerLength - 1).join(" ");
      row = [...head, tail];
    }
    records.push(row);
  }

  if (!records.length) {
    return null;
  }

  return {
    headerLines,
    records,
    preambleLines,
    rowMismatch,
  };
}

async function fetchBatchSchema() {
  if (batchSchemaCache.loaded) return batchSchemaCache.data;
  try {
    const response = await fetch("/agents/batch-schema/");
    const data = await response.json();
    batchSchemaCache.loaded = true;
    batchSchemaCache.data = data;
    return data;
  } catch (err) {
    console.warn("Unable to load batch schema:", err);
    batchSchemaCache.loaded = true;
    batchSchemaCache.data = null;
    return null;
  }
}

async function mapBatchHeaders(objectName, headers) {
  if (!objectName || !Array.isArray(headers) || headers.length === 0) {
    return { headers, unmapped: [] };
  }
  try {
    const response = await fetch("/agents/batch-map/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ object: objectName, headers }),
    });
    const data = await response.json();
    if (!Array.isArray(data.mapped_headers) || data.mapped_headers.length !== headers.length) {
      return { headers, unmapped: [] };
    }
    const mapped = data.mapped_headers.map((value, idx) => value || headers[idx]);
    const unmapped = Array.isArray(data.unmapped_headers) ? data.unmapped_headers : [];
    return { headers: mapped, unmapped };
  } catch (err) {
    console.warn("Unable to map batch headers:", err);
    return { headers, unmapped: [] };
  }
}

function findHeaderRun(lines, allowedSet) {
  let best = { start: -1, length: 0 };
  let currentStart = -1;
  let currentLength = 0;

  lines.forEach((line, idx) => {
    const token = normalizeBatchHeader(line);
    if (!token || !allowedSet.has(token)) {
      if (currentLength > best.length) {
        best = { start: currentStart, length: currentLength };
      }
      currentStart = -1;
      currentLength = 0;
      return;
    }
    if (currentLength === 0) {
      currentStart = idx;
    }
    currentLength += 1;
  });

  if (currentLength > best.length) {
    best = { start: currentStart, length: currentLength };
  }

  return best;
}

function isHeaderCandidate(line, allowedSet) {
  const trimmed = String(line || "").trim();
  if (!trimmed) return false;
  if (/\bcreate\b/i.test(trimmed)) return false;
  const normalized = normalizeBatchHeader(trimmed);
  if (allowedSet && allowedSet.has(normalized)) return true;
  if (/@|https?:\/\/|www\./i.test(trimmed)) return false;
  const letters = (trimmed.match(/[a-z]/gi) || []).length;
  if (letters < 2) return false;
  const digits = (trimmed.match(/[0-9]/g) || []).length;
  if (digits > letters) return false;
  return true;
}

function findHeaderBlock(lines, allowedSet) {
  let start = -1;
  let length = 0;
  for (let i = 0; i < lines.length; i += 1) {
    if (isHeaderCandidate(lines[i], allowedSet)) {
      start = i;
      break;
    }
  }
  if (start === -1) return { start: -1, length: 0 };
  for (let i = start; i < lines.length; i += 1) {
    if (!isHeaderCandidate(lines[i], allowedSet)) {
      break;
    }
    length += 1;
  }
  return { start, length };
}
function detectBatchObject(cleaned, lines, schemaObjects, headerTokens = null) {
  const normalizedMessage = normalizeBatchSearch(cleaned);
  let match = null;

  schemaObjects.forEach((obj) => {
    if (!obj || !Array.isArray(obj.labels)) return;
    obj.labels.forEach((label) => {
      const normalizedLabel = normalizeBatchSearch(label);
      if (!normalizedLabel) return;
      const regex = new RegExp(`\\b${normalizedLabel.replace(/\s+/g, "\\s+")}\\b`, "i");
      if (regex.test(normalizedMessage)) {
        if (!match || normalizedLabel.length > match.labelLength) {
          match = { object: obj, labelLength: normalizedLabel.length };
        }
      }
    });
  });

  if (match) {
    return match.object;
  }

  let best = null;
  schemaObjects.forEach((obj) => {
    const allowedSet = new Set((obj.headers || []).map(normalizeBatchHeader));
    if (!allowedSet.size) return;
    if (Array.isArray(headerTokens) && headerTokens.length) {
      const score = headerTokens.reduce((count, token) => (
        allowedSet.has(normalizeBatchHeader(token)) ? count + 1 : count
      ), 0);
      if (score >= 2 && (!best || score > best.score)) {
        best = { object: obj, score };
      }
      return;
    }
    const run = findHeaderRun(lines, allowedSet);
    if (run.length >= 2 && (!best || run.length > best.run.length)) {
      best = { object: obj, run };
    }
  });

  return best ? best.object : null;
}

function detectBatchOperation(message) {
  const normalized = normalizeBatchSearch(message);
  if (!normalized) return "create";
  if (/\b(update|edit|change|modify|set)\b/i.test(normalized)) {
    return "update";
  }
  return "create";
}

function extractBatchIdentifierHint(message) {
  const text = String(message || "").toLowerCase();
  const match = text.match(/\bby\s+([a-z0-9_ ]+?)(?=\s+(?:for|with|using|where|from)\b|$)/i);
  if (!match || !match[1]) return "";
  const token = String(match[1]).trim().replace(/\s+/g, " ");
  if (!token) return "";
  const normalized = token.replace(/[^a-z0-9_ ]+/g, "").trim();
  const aliasMap = {
    "id": "id",
    "record id": "id",
    "recordid": "id",
    "identifier": "id",
    "name": "name",
    "email": "email",
    "e mail": "email",
    "external id": "external_id",
    "externalid": "external_id",
    "leadid": "leadId",
    "contactid": "contactId",
    "accid": "accid",
    "oppid": "oppid",
  };
  return aliasMap[normalized] || normalized.replace(/\s+/g, "_");
}

function buildBatchOperationLine(objectInfo, operation = "create", identifierField = "") {
  const label = (objectInfo && (objectInfo.label || objectInfo.name)) || "records";
  if (operation === "update") {
    const base = /record/i.test(label) ? `Update ${label}` : `Update ${label} records`;
    return identifierField ? `${base} by ${identifierField}` : base;
  }
  if (/record/i.test(label)) {
    return `Create ${label}`;
  }
  return `Create ${label} records`;
}

function buildBatchStatusMarkup(text, variant) {
  const safeText = escapeHtml(text || "");
  const variantClass = variant ? ` batch-result-status--${variant}` : "";
  return `<div class="batch-result-status${variantClass}">${safeText}</div>`;
}

async function persistAgentMessage(message, sessionId) {
  if (!message || !sessionId) return;
  try {
    await fetch("/agents/log-message/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      keepalive: true,
      body: JSON.stringify({ message, session_id: sessionId }),
    });
  } catch (error) {
    console.warn("Unable to persist agent message:", error);
  }
}

function logAgentMessage(message, sessionId) {
  if (!message) return;
  if (!sessionId) {
    pendingBatchLogs.push(message);
    if (typeof window !== "undefined") {
      window.pendingBatchLogs = pendingBatchLogs;
    }
    return;
  }
  persistAgentMessage(message, sessionId);
}

function flushPendingBatchLogs(sessionId) {
  if (!sessionId || !pendingBatchLogs.length) return;
  const messages = pendingBatchLogs.slice();
  pendingBatchLogs = [];
  if (typeof window !== "undefined") {
    window.pendingBatchLogs = pendingBatchLogs;
  }
  messages.forEach((message) => {
    persistAgentMessage(message, sessionId);
  });
}

function shouldDiscardBatchUpload(message) {
  const lowered = normalizeBatchSearch(message);
  if (!lowered) return false;
  if (!/(upload|csv|file|batch)/i.test(message)) return false;
  return /(discard|clear|remove|delete|cancel)/i.test(message);
}

function getBatchObjectFromMessage(message, schemaObjects) {
  const lines = String(message || "").split(/\r?\n/);
  return detectBatchObject(message || "", lines, schemaObjects, null);
}

function shouldUsePendingBatchUpload(message, schemaObjects) {
  if (!message || !schemaObjects) return false;
  if (/(upload|csv|spreadsheet|file)/i.test(message)) return true;
  if (/(create|import|load|ingest|update|edit|change|modify)/i.test(message)) {
    return Boolean(getBatchObjectFromMessage(message, schemaObjects));
  }
  return false;
}

function appendBatchStatusMessage(text, status = "info") {
  const icon = status === "success" ? "✅" : status === "error" ? "⚠️" : "ℹ️";
  appendMessage("agent", agentNoticeMarkup(`${icon} ${escapeHtml(text)}`));
  scrollToBottom("batchStatus", true);
}

function buildBatchMetricsMessage(batchPayload) {
  if (!batchPayload) return null;
  const objectLabel = batchPayload.objectName || batchPayload.objectLabel || "records";
  const totalRecords = Number(batchPayload.totalRecords || 0);
  const limit = Number.isFinite(totalRecords) && totalRecords > 0
    ? Math.min(Math.max(totalRecords, 5), 25)
    : 10;
  return `Show metrics: Show all ${objectLabel} records order by created_at DESC limit ${limit}`;
}

async function buildBatchPayload(message) {
  if (!/^batch\s*:/i.test(message || "")) return null;

  const cleaned = message.replace(/^batch\s*:/i, "").trim();
  if (!cleaned) return null;

  const rawLines = cleaned.split(/\r?\n/);
  while (rawLines.length && !rawLines[0].trim()) {
    rawLines.shift();
  }
  if (!rawLines.length) return null;

  const schema = await fetchBatchSchema();
  if (!schema || !Array.isArray(schema.objects) || schema.objects.length === 0) {
    return { fallbackMessage: cleaned, error: "schema_unavailable" };
  }

  const delimited = parseDelimitedBatch(cleaned);
  const headerTokens = delimited ? delimited.headerLines : null;
  const objectInfo = detectBatchObject(cleaned, rawLines, schema.objects, headerTokens);
  if (!objectInfo) {
    return { fallbackMessage: cleaned, error: "unknown_object" };
  }
  const operation = detectBatchOperation(cleaned);
  const identifierFieldHint = operation === "update" ? extractBatchIdentifierHint(cleaned) : "";

  let headerLines = [];
  let preambleLines = [];
  let records = [];
  let rowMismatch = false;

  if (delimited) {
    headerLines = delimited.headerLines;
    preambleLines = delimited.preambleLines || [];
    records = delimited.records || [];
    rowMismatch = delimited.rowMismatch || false;
  } else {
    const allowedSet = new Set((objectInfo.headers || []).map(normalizeBatchHeader));
    let headerRun = findHeaderRun(rawLines, allowedSet);
    if (headerRun.length < 2) {
      headerRun = findHeaderBlock(rawLines, allowedSet);
    }
    if (headerRun.length < 2) {
      return { fallbackMessage: cleaned, error: "missing_header" };
    }

    const headerStart = headerRun.start;
    const headerEnd = headerStart + headerRun.length;
    headerLines = rawLines.slice(headerStart, headerEnd).map((line) => line.trim());
    preambleLines = rawLines.slice(0, headerStart).map((line) => line.trim()).filter(Boolean);
    let dataLines = rawLines.slice(headerEnd).map((line) => line.trim());

    while (dataLines.length && !dataLines[dataLines.length - 1]) {
      dataLines.pop();
    }

    if (!dataLines.length) {
      return { fallbackMessage: cleaned, error: "row_mismatch" };
    }

    if (dataLines.length % headerLines.length !== 0) {
      rowMismatch = true;
      const remainder = dataLines.length % headerLines.length;
      const padCount = headerLines.length - remainder;
      for (let i = 0; i < padCount; i += 1) {
        dataLines.push("");
      }
    }

    for (let i = 0; i < dataLines.length; i += headerLines.length) {
      records.push(dataLines.slice(i, i + headerLines.length));
    }
  }

  if (!headerLines.length || !records.length) {
    return { fallbackMessage: cleaned, error: "row_mismatch" };
  }

  const mapped = operation === "update"
    ? { headers: headerLines, unmapped: [] }
    : await mapBatchHeaders(objectInfo.name, headerLines);
  const mappedHeaders = mapped.headers || headerLines;

  const batches = [];
  const objectLabel = objectInfo.label || objectInfo.name || "records";
  const operationLine = buildBatchOperationLine(objectInfo, operation, identifierFieldHint);
  for (let i = 0; i < records.length; i += BATCH_ROW_SIZE) {
    const batchLines = [];
    const hasOperationLine = preambleLines.some((line) => /^(create|update|edit|change|modify)\b/i.test(String(line || "").trim()));
    if (!hasOperationLine) {
      batchLines.push(operationLine);
    }
    if (preambleLines.length) {
      batchLines.push(...preambleLines);
    }
    batchLines.push(...mappedHeaders);
    if (operation === "update") {
      batchLines.push(BATCH_UPDATE_DATA_MARKER);
    }
    batchLines.push(...records.slice(i, i + BATCH_ROW_SIZE).flat());
    batches.push(batchLines.join("\n"));
  }

  return {
    batches,
    totalRecords: records.length,
    objectLabel,
    objectName: objectInfo.name,
    unmappedHeaders: mapped.unmapped || [],
    rowMismatch,
    operation,
  };
}

async function buildBatchPayloadFromUpload(message, upload) {
  if (!upload || !upload.content) return null;

  const schema = await fetchBatchSchema();
  if (!schema || !Array.isArray(schema.objects) || schema.objects.length === 0) {
    return { error: "schema_unavailable" };
  }
  const operation = detectBatchOperation(message);
  const identifierFieldHint = operation === "update" ? extractBatchIdentifierHint(message) : "";

  if (!shouldUsePendingBatchUpload(message, schema.objects)) {
    return null;
  }

  const objectInfo = getBatchObjectFromMessage(message, schema.objects);
  if (!objectInfo) {
    return { error: "missing_object", operation };
  }

  const delimited = parseDelimitedBatch(upload.content);
  if (!delimited) {
    return { error: "missing_header" };
  }

  const headerLines = delimited.headerLines || [];
  const records = delimited.records || [];
  const rowMismatch = delimited.rowMismatch || false;

  if (!headerLines.length || !records.length) {
    return { error: "row_mismatch" };
  }

  const mapped = operation === "update"
    ? { headers: headerLines, unmapped: [] }
    : await mapBatchHeaders(objectInfo.name, headerLines);
  const mappedHeaders = mapped.headers || headerLines;
  const allowedSet = new Set((objectInfo.headers || []).map(normalizeBatchHeader));
  const overlap = headerLines.filter((header) => allowedSet.has(normalizeBatchHeader(header))).length;
  const headerMismatch = overlap < 2;

  const batches = [];
  const objectLabel = objectInfo.label || objectInfo.name || "records";
  const operationLine = buildBatchOperationLine(objectInfo, operation, identifierFieldHint);
  for (let i = 0; i < records.length; i += BATCH_ROW_SIZE) {
    const batchLines = [];
    batchLines.push(operationLine);
    batchLines.push(...mappedHeaders);
    if (operation === "update") {
      batchLines.push(BATCH_UPDATE_DATA_MARKER);
    }
    batchLines.push(...records.slice(i, i + BATCH_ROW_SIZE).flat());
    batches.push(batchLines.join("\n"));
  }

  return {
    payload: {
      batches,
      totalRecords: records.length,
      objectLabel,
      objectName: objectInfo.name,
      unmappedHeaders: mapped.unmapped || [],
      rowMismatch,
      headerMismatch,
      operation,
    }
  };
}

async function handleBatchPayload(batchPayload, sessionId) {
  if (!batchPayload) {
    return false;
  }

  if (batchPayload.fallbackMessage) {
    let warning = "⚠️ Batch format not recognized. Fix the headers and try again.";
    if (batchPayload.error === "schema_unavailable") {
      warning = "⚠️ Batch schema unavailable. Try again later.";
    } else if (batchPayload.error === "unknown_object") {
      warning = "⚠️ Batch object not found. Add the object name in the message.";
    } else if (batchPayload.error === "missing_header") {
      warning = "⚠️ Batch headers not detected. Include a header row.";
    } else if (batchPayload.error === "row_mismatch") {
      warning = "⚠️ Batch rows don't match the header count. Ensure every record has the same number of lines.";
    }
    showQuoteToast(warning, "error");
    return true;
  }

  if (batchPayload.batches && batchPayload.batches.length > 0) {
    const totalBatches = batchPayload.batches.length;
    const totalRecords = batchPayload.totalRecords || (totalBatches * BATCH_ROW_SIZE);
    const label = batchPayload.objectLabel || "records";
    if (batchPayload.unmappedHeaders && batchPayload.unmappedHeaders.length) {
      showQuoteToast("⚠️ Some headers were not mapped; they were sent as-is.", "info");
    }
    if (batchPayload.rowMismatch) {
      showQuoteToast("⚠️ Batch rows were incomplete; missing values were left blank.", "info");
    }
    showQuoteToast(`Processing ${totalRecords} ${label} in ${totalBatches} batches...`, "info");
    for (let i = 0; i < totalBatches; i += 1) {
      if (!sessionId) {
        sessionId = getCurrentSessionId();
        flushPendingBatchLogs(sessionId);
      }
      showQuoteToast(`Batch ${i + 1}/${totalBatches} started`, "info");
      const startedText = `⏳ Batch ${i + 1}/${totalBatches} started.`;
      appendBatchStatusMessage(startedText, "info");
      await logAgentMessage(buildBatchStatusMarkup(startedText, "info"), sessionId);
      try {
        await sendMessageRequest(batchPayload.batches[i], sessionId, {
          keepFeedback: true,
          allowRedirect: false,
          batchInfo: { index: i + 1, total: totalBatches, label }
        });
        showQuoteToast(`Batch ${i + 1}/${totalBatches} completed`, "success");
      } catch (error) {
        console.error(`Batch ${i + 1} failed:`, error);
        showQuoteToast(`⚠️ Batch ${i + 1}/${totalBatches} failed. Continuing...`, "error");
        const failedText = `⚠️ Batch ${i + 1}/${totalBatches} failed. Continuing...`;
        appendBatchStatusMessage(failedText, "error");
        await logAgentMessage(buildBatchStatusMarkup(failedText, "error"), sessionId);
      }
      if (!sessionId) {
        sessionId = getCurrentSessionId();
      }
    }
    const metricsMessage = buildBatchMetricsMessage(batchPayload);
    if (metricsMessage) {
      const metricsText = `📊 Showing latest ${label} records.`;
      appendBatchStatusMessage(metricsText, "info");
      await logAgentMessage(buildBatchStatusMarkup(metricsText, "neutral"), sessionId);
      try {
        await sendMessageRequest(metricsMessage, sessionId, { keepFeedback: true, allowRedirect: false });
      } catch (error) {
        console.error("Batch metrics request failed:", error);
        showQuoteToast("⚠️ Could not load the latest records yet. Try again in a moment.", "error");
      }
    }
    return true;
  }

  return false;
}

async function sendMessageRequest(userMessage, sessionId, options = {}) {
  const payload = { message: userMessage };
  if (sessionId) {
    payload.session_id = sessionId;
  }
  if (options.batchInfo && typeof options.batchInfo === "object") {
    const { index, total, label } = options.batchInfo;
    if (Number.isInteger(index) && Number.isInteger(total)) {
      payload.batch_info = { index, total, label };
    }
  }

  const response = await fetch("/agents/chat/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`HTTP error! Status: ${response.status} - ${errorText}`);
  }

  const data = await response.json();
  handleAgentResponse(data, options);
  return data;
}

function handleAgentResponse(data, options = {}) {
  const keepFeedback = Boolean(options.keepFeedback);
  const batchInfo = options.batchInfo || null;
  const allowRedirect = options.allowRedirect !== false;
  let aiResponse = data.response;
  const chatBox = document.getElementById("chat-box");

  if (aiResponse && aiResponse.session_created && aiResponse.redirect_url) {
    if (allowRedirect) {
      window.location.href = aiResponse.redirect_url;
      return;
    }
    updateSessionIdFromRedirect(aiResponse.redirect_url);
    if (aiResponse.response) {
      aiResponse = aiResponse.response;
      data.response = aiResponse;
    }
  }

  let responseMessage = "";
  let embeddedQuoteDetails = null;
  let batchPrefix = "";
  if (batchInfo && batchInfo.total) {
    const labelText = batchInfo.label ? ` ${batchInfo.label}` : "";
    batchPrefix = `
      <div class="batch-result-header">
        <span class="batch-result-pill">Batch ${batchInfo.index}/${batchInfo.total}</span>
        <span class="batch-result-label">Results${labelText}</span>
      </div>
      <div class="batch-result-status">✅ Batch ${batchInfo.index}/${batchInfo.total} completed.</div>
    `;
  }

  if (data.response && data.response.warnings) {
    responseMessage += `<div class="warning-message"><strong>⚠️ Warnings:</strong><ul>`;
    data.response.warnings.forEach(warning => {
      responseMessage += `<li>${warning}</li>`;
    });
    responseMessage += `</ul></div>`;
  }

  if (data.response && data.response.history) {
    responseMessage += renderApprovalHistory(data.response);
  }
  else if (data.response && data.response.single_record) {
    responseMessage += renderSingleRecord(data.response.single_record);
  }
  else if (data.response && data.response.quote_details && !data.response.quote_notes) {
    ensureQuoteStatusValue(data.response.quote_details);
    if (data.response.message) {
      const cleaned = stripStructuredSuffixFromAgentMessage(
        data.response.message,
        ["quote_details:", "action_triggers_details:", "validation_rules_details:", "retrieved_records:", "intelligence_dashboard:"]
      );
      if (cleaned.message) {
        responseMessage += `<div class="general-message">${addWarningIconPrefix(cleaned.message)}</div>`;
      }
    }
    responseMessage += renderQuoteDetails(data.response.quote_details);
  }
  else if (data.response && data.response.quote_notes) {
    responseMessage += renderQuoteNotes(data.response.quote_details, data.response.quote_notes);
  }
  else if (data.response.download_url) {
    responseMessage += renderPdfSuccess(data.response.download_url, data.response.document_version);
  }
  else if (data.response && data.response.validation_rules_details) {
    responseMessage += renderValidationRuleDetails(data.response.validation_rules_details);
  }
  else if (data.response && data.response.hiddenMessage && data.response.temporaryMessage) {
    if (!keepFeedback) {
      hideAgentFeedback();
    }
    return;
  }
  else if (data.response && data.response.inclusion_rules_details) {
    responseMessage += renderInclusionRuleDetails(data.response.message, data.response.inclusion_rules_details);
  }
  else if (data.response && data.response.exclusion_rules_details) {
    responseMessage += renderExclusionRuleDetails(data.response.message, data.response.exclusion_rules_details);
  }
  else if (data.response && data.response.action_triggers_details) {
    responseMessage += renderActionTriggersDetails(data.response.message, data.response.action_triggers_details);
  }
  else if (data.response && data.response.rules && data.response.read_only) {
    responseMessage += renderRules(data.response.rules);
  }
  else if (data.response && data.response.email_alerts_details) {
    responseMessage += renderEmailAlerstDetails(data.response.email_alerts_details);
  }
  else if (data.response && data.response.retrieved_records) {
    const rendered = renderRetrievedRecords("", data.response.retrieved_records);
    if (rendered && rendered.trim()) {
      responseMessage += rendered;
    } else if (data.response.message) {
      const cleaned = stripStructuredSuffixFromAgentMessage(
        data.response.message,
        ["quote_details:", "action_triggers_details:", "validation_rules_details:", "retrieved_records:", "intelligence_dashboard:"]
      );
      responseMessage += `<div class="general-message">${cleaned.message}</div>`;
    }
  }
  else if (data.response && data.response.intelligence_dashboard) {
    const rendered = renderIntelligenceDashboard(data.response.intelligence_dashboard);
    if (data.response.message) {
      const cleaned = stripStructuredSuffixFromAgentMessage(
        data.response.message,
        ["intelligence_dashboard:"]
      );
      responseMessage += `<div class="general-message">${cleaned.message}</div>`;
    }
    responseMessage += rendered;
  }
  else if (data.response && data.response.openGraphicBuilder) {
    modelSchema = data.response.cpq_model_schema || {};
    console.log("📦 CPQ Model Schema loaded:", modelSchema);
    responseMessage += renderGraphicBuilderForActionTrigger(
      data.response.openGraphicBuilder
    );
  }
  else if (data.response && data.response.message) {
    const embeddedDashboard = extractEmbeddedJsonPayload(data.response.message, "intelligence_dashboard:");
    if (embeddedDashboard) {
      const rendered = renderIntelligenceDashboard(embeddedDashboard);
      if (rendered) {
        responseMessage += rendered;
      }
    }
    const cleaned = stripStructuredSuffixFromAgentMessage(
      data.response.message,
      ["quote_details:", "action_triggers_details:", "validation_rules_details:", "retrieved_records:", "intelligence_dashboard:"]
    );
    responseMessage += `<div class="general-message">${addWarningIconPrefix(cleaned.message)}</div>`;

    if (cleaned.stripped) {
      embeddedQuoteDetails = extractEmbeddedJsonPayload(data.response.message, "quote_details:");
    }
  }
  else {
    responseMessage += `<div class="error-message">🤖 No response received. Please try again.</div>`;
  }

  if (batchPrefix) {
    responseMessage = `${batchPrefix}${responseMessage}`;
  }

  if (!shouldSkipDuplicateAgentMessage(responseMessage)) {
    const agentBubble = appendMessage("agent", `<div class="senderagent"><img width="110px" src="/static/img/agentcpq-chat-icon.png" alt="AgentCPQ Logo"> </div> <div class="message">${responseMessage}</div>`);
    if (agentBubble) {
      const target = agentBubble.querySelector(".message .general-message") || agentBubble.querySelector(".message");
      if (embeddedQuoteDetails) {
        attachQuoteDetailsToggle(target, embeddedQuoteDetails);
      }
      initializeRecordListLayouts(agentBubble);
      initializeMetricCards(agentBubble);
      if (data.response && data.response.update_details) {
        attachQuoteDetailsToggle(target, data.response.update_details);
      }
    }
    window.lastAgentMessageAt = Date.now();
  }
  loadPendingAttachments();
  if (!keepFeedback) {
    hideAgentFeedback();
  }
  scrollToBottom("sendMessage:agentResponse", true);
  if (chatBox) {
    chatBox.scrollTop = chatBox.scrollHeight;
  }
}

/**
* ✅ Send user message to the agent and handle response
*/
async function sendMessage() {
    const inputField = document.getElementById("user-input");
    const chatBox = document.getElementById("chat-box");

    let userMessage = inputField.value.trim();
    if (!userMessage) return;

    if (document.documentElement.dataset.agentsEmptyDismissed !== "true") {
      document.documentElement.dataset.agentsEmptyDismissed = "true";
      updateAgentsEmptyState();
    }

    const safeUserMessage = escapeHtml(userMessage).replace(/\n/g, "<br>");
    appendMessage(
      "user",
      `<div class="chat-text user"><div class="sender">You: </div><div class="message">${safeUserMessage}</div></div>`
    )

    inputField.value = "";
    if (inputField && inputField.tagName === "TEXTAREA") {
      inputField.style.height = "auto";
      inputField.style.overflowY = "hidden";
    }

    scrollToBottom("sendMessage:user", true);

    const urlParams = new URLSearchParams(window.location.search);
    const sessionId = urlParams.get("session_id");
    try {
        showAgentFeedback();
        requestAnimationFrame(() => scrollToBottom("sendMessage:pending"));
        if (pendingBatchUpload) {
          if (shouldDiscardBatchUpload(userMessage)) {
            setPendingBatchUpload(null);
            appendBatchStatusMessage("CSV upload discarded.", "info");
            hideAgentFeedback();
            return;
          }
          const uploadResult = await buildBatchPayloadFromUpload(userMessage, pendingBatchUpload);
          if (uploadResult) {
            if (uploadResult.error) {
              let warning = "⚠️ Upload needs a header row. Please check the CSV.";
              if (uploadResult.error === "schema_unavailable") {
                warning = "⚠️ Batch schema unavailable. Try again later.";
              } else if (uploadResult.error === "missing_object") {
                warning = uploadResult.operation === "update"
                  ? "⚠️ Tell me which object to update (e.g. 'Update Contacts from upload by email')."
                  : "⚠️ Tell me which object to create (e.g. 'Create Leads from upload').";
              } else if (uploadResult.error === "row_mismatch") {
                warning = "⚠️ Upload rows don't match the header count. Ensure every record has the same number of columns.";
              }
              showQuoteToast(warning, "error");
              hideAgentFeedback();
              return;
            }
            if (uploadResult.payload && uploadResult.payload.headerMismatch) {
              showQuoteToast("⚠️ Upload headers do not closely match the selected object.", "info");
            }
            const handled = await handleBatchPayload(uploadResult.payload, sessionId);
            if (handled) {
              setPendingBatchUpload(null);
              hideAgentFeedback();
              return;
            }
          }
        }
        const batchPayload = await buildBatchPayload(userMessage);
        if (await handleBatchPayload(batchPayload, sessionId)) {
          hideAgentFeedback();
          return;
        }
        await sendMessageRequest(userMessage, sessionId);
    } catch (error) {
        console.error("Error:", error);
        appendMessage("agent-message", `<strong>Error:</strong> ${error.message}`);
        hideAgentFeedback();
    }
}

function scrollToBottom(arg, optionalForceWindow) {
  let reason = "";
  let forceWindow = false;

  if (typeof arg === "string" || typeof arg === "undefined") {
    reason = arg || "";
    forceWindow = Boolean(optionalForceWindow);
  } else if (arg && typeof arg === "object") {
    reason = arg.reason || "";
    forceWindow = Boolean(arg.forceWindow);
  }

  const label = reason ? `[scrollToBottom] ${reason}` : "[scrollToBottom]";
  const chatBox = document.getElementById("chat-box");
  if (!chatBox) {
    console.warn(`${label} chat-box not found`);
    return;
  }

  const performScroll = () => {
    if (typeof chatBox.scrollTo === "function") {
      const target = Math.max(0, chatBox.scrollHeight - chatBox.clientHeight);
      chatBox.scrollTo({ top: target, behavior: "smooth" });
    } else {
      chatBox.scrollTop = Math.max(0, chatBox.scrollHeight - chatBox.clientHeight);
    }

    setTimeout(() => {
      console.log(`${label} chatBox → scrollTop=${chatBox.scrollTop}, scrollHeight=${chatBox.scrollHeight}, clientHeight=${chatBox.clientHeight}`);
    }, 100);

    if (forceWindow) {
      const delta = chatBox.getBoundingClientRect().bottom - (window.innerHeight || document.documentElement.clientHeight);
      if (delta > 0) {
        window.scrollBy({ top: delta + 24, behavior: "smooth" });
        console.log(`${label} window scrollBy delta=${delta}`);
      }
    }
  };

  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(() => {
      requestAnimationFrame(performScroll);
    });
  } else {
    setTimeout(performScroll, 0);
  }
}


/**
* ✅ Append message to the chat box
*/
function appendMessage(className, message, options = {}) {
    const chatBox = document.getElementById("chat-box");
    let messageBubble = document.createElement("div");
    messageBubble.classList.add("chat-message", className);

    // ✅ Detect stored quote details (supports multiline JSON + optional human prefix).
    if (className === "agent" && message.includes("quote_details:")) {
      try {
        const key = "quote_details:";
        const idx = message.indexOf(key);
        const prefixRaw = idx > 0 ? message.slice(0, idx).trim() : "";
        const afterKey = message.slice(idx + key.length);
        const jsonStr = extractJson(afterKey);
        if (jsonStr) {
          const quote = JSON.parse(jsonStr);
          ensureQuoteStatusValue(quote);
          const rendered = message.includes("notes: {") ? renderQuoteNotes(quote) : renderQuoteDetails(quote);
          const prefix = prefixRaw ? `<div class="general-message">${prefixRaw}</div>` : "";
          message = `${prefix}${rendered}`;
        }
      } catch (e) {
        console.warn("Failed to parse quote_details JSON:", e);
      }
    }

    // ✅ Detect validation rules
    if (className === "agent" && message.includes("validation_rules_details: {")) {
      try {
        // Extract JSON from string
        const match = message.match(/validation_rules_details:\s({.+})/);
        if (match && match[1]) {
          const rules = JSON.parse(match[1]);
          message = renderValidationRuleDetails(rules);  // Use your nice formatter
        }
      } catch (e) {
        console.warn("Failed to parse validation_rules_details JSON:", e);
      }
    }

    // ✅ Detect inclusion rules
    if (className === "agent" && message.includes("inclusion_rules_details:")) {
      try {
        // Extraer el JSON, ya sea objeto {} o lista []
        const match = message.match(/inclusion_rules_details:\s([\s\S]+)/);
        if (match && match[1]) {
          const rules = JSON.parse(match[1].trim());
          message = renderInclusionRuleDetails(rules); // Usa tu formateador bonito
        }
      } catch (e) {
        console.warn("Failed to parse inclusion_rules_details JSON:", e);
      }
    }

    // ✅ Detect stored email alerts
    if (className === "agent" && message.includes("email_alerts_details:")) {
      try {
          // Extract JSON from string (object or array)
          const match = message.match(/email_alerts_details:\s(\[.+\]|\{.+\})/s);
          if (match && match[1]) {
              const alerts = JSON.parse(match[1]);
              message = renderEmailAlerstDetails(alerts);  // Use your nice formatter
          }
      } catch (e) {
          console.warn("Failed to parse email_alerts_details JSON:", e);
      }
    }

    // ✅ Detect stored single record cards
    if (className === "agent" && message.includes("single_record:")) {
      try {
        const match = message.match(/single_record:\s({[\s\S]+})/);
        if (match && match[1]) {
          const record = JSON.parse(match[1]);
          message = renderSingleRecord(record);
        }
      } catch (e) {
        console.warn("Failed to parse single_record JSON:", e);
      }
    }

    // ✅ Detect stored retrieved records (Analytics Agent)
    if (className === "agent" && message.includes("retrieved_records:")) {
      try {
        const key = "retrieved_records:";
        const idx = message.indexOf(key);
        const prefixRaw = idx > 0 ? message.slice(0, idx).trim() : "";
        const cleanedPrefix = prefixRaw.replace(/📦\s*$/u, "").trim();
        const afterKey = message.slice(idx + key.length);
        const jsonStr = extractJson(afterKey);
        if (jsonStr) {
          const records = JSON.parse(jsonStr);
          const rendered = renderRetrievedRecords("", records);
          const prefix = cleanedPrefix ? `<div class="general-message">${cleanedPrefix}</div>` : "";
          message = `${prefix}${rendered || ""}`;
        }
      } catch (e) {
        console.warn("Failed to parse retrieved_records JSON:", e);
      }
    }

    // ✅ Detect stored intelligence dashboards
    if (className === "agent" && message.includes("intelligence_dashboard:")) {
      try {
        const key = "intelligence_dashboard:";
        const idx = message.indexOf(key);
        const prefixRaw = idx > 0 ? message.slice(0, idx).trim() : "";
        const cleanedPrefix = prefixRaw.replace(/📦\s*$/u, "").trim();
        const afterKey = message.slice(idx + key.length);
        const jsonStr = extractJson(afterKey);
        if (jsonStr) {
          const payload = JSON.parse(jsonStr);
          const rendered = renderIntelligenceDashboard(payload);
          const prefix = cleanedPrefix ? `<div class="general-message">${cleanedPrefix}</div>` : "";
          message = `${prefix}${rendered || ""}`;
        }
      } catch (e) {
        console.warn("Failed to parse intelligence_dashboard JSON:", e);
      }
    }

    messageBubble.innerHTML = message;

    // If an agent message contains a human prefix + structured payload (e.g. quote_details: {...}),
    // keep only the human message by default.
    if (className === "agent") {
      const msgEl = messageBubble.querySelector(".message") || messageBubble;
      stripStructuredSuffixInElement(
        msgEl,
        ["quote_details:", "action_triggers_details:", "validation_rules_details:", "retrieved_records:", "intelligence_dashboard:"]
      );
    }
    if (options && options.anchor && options.anchor.parentNode) {
      options.anchor.parentNode.insertBefore(messageBubble, options.anchor.nextSibling);
    } else {
      chatBox.appendChild(messageBubble);
    }
    initializeMetricCards(messageBubble);

    // ✅ Re-initializes select from Materialize
  const selects = messageBubble.querySelectorAll('select');
  if (selects.length > 0) {
    if (typeof M !== 'undefined' && M.FormSelect) {
      const filtered = Array.from(selects).filter(sel => sel.dataset.skipMaterialize !== "true");
      if (filtered.length) {
        M.FormSelect.init(filtered);
      }
    } else {
      console.warn("Materialize M.FormSelect not available; select elements were not enhanced.");
    }
  }

    // ✅ Normalize single-record sections to a single section
    mergeSingleRecordSections(messageBubble);

    messageBubble.querySelectorAll('.single-record-card').forEach(card => {
      initializeSingleRecordCardLayout(card);
    });
    initializeSingleRecordRelatedButtons(messageBubble);
    initializeSingleRecordDeleteButtons(messageBubble);
    initializeQuoteListViewButtons();
    initializeRecordListViewButtons();
    initializeQuoteDetailRecordLinks();

    initializeBundleStructureCards(messageBubble);
    initializeQuoteNotesEditors(messageBubble);

    if (message.includes("agent-json")) {
        enhanceStructuredAgentMessages();
    }

    // ✅ Start Flatpickr if field exists
    const expirationInput = messageBubble.querySelector("#expiration_date");
    if (expirationInput) {
        flatpickr(expirationInput, {
            dateFormat: "m/d/Y",
            defaultDate: expirationInput.value,
            allowInput: false,
            onChange: function(selectedDates, dateStr, instance) {
              updateQuote(instance.input);
            }
        });
    }

    if (!options || !options.skipScroll) {
      scrollToBottom(`appendMessage:${className}`, true);
    }
    if (typeof updateAgentsEmptyState === "function") {
      updateAgentsEmptyState();
    }
    return messageBubble;
}

function renderQuoteDiscountControls(quote) {
  const type = quote && quote.discount_type;
  const percentageRaw = quote && quote.discount_percentage;
  const amountRaw = quote && quote.discount_amount;

  const hasValues = Boolean(type) && percentageRaw !== null && percentageRaw !== undefined && amountRaw !== null && amountRaw !== undefined;

  if (!hasValues) {
    return `
      <div class="quote-detail-inline-item">
        <div class="quote-detail-inline-label">Discount %</div>
        <div class="quote-detail-inline-field">
          <span class="quote-detail-value">—</span>
        </div>
      </div>
      <div class="quote-detail-inline-item">
        <div class="quote-detail-inline-label">Disc Amount</div>
        <div class="quote-detail-inline-field">
          <span class="quote-detail-value">—</span>
        </div>
      </div>
    `.trim();
  }

  const percentageValue = Number(percentageRaw);
  const amountValue = Number(amountRaw);

  const safePercentage = Number.isFinite(percentageValue) ? percentageValue : 0;
  const safeAmount = Number.isFinite(amountValue) ? amountValue : 0;
  const formattedAmount = safeAmount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const quoteName = quote && quote.quote_name ? quote.quote_name : '';

  return `
    <div class="quote-detail-inline-item">
      <div class="quote-detail-inline-label">Discount %</div>
      <div class="quote-detail-inline-field">
        <input type="number"
          value="${safePercentage}"
          data-field="discount_percentage"
          data-quote="${quoteName}"
          onchange="updateQuote(this)"
          class="quote-detail-inline-input">
      </div>
    </div>
    <div class="quote-detail-inline-item">
      <div class="quote-detail-inline-label">Disc Amount</div>
      <div class="quote-detail-inline-field">
        <input type="text"
          value="${formattedAmount}"
          data-field="discount_amount"
          data-quote="${quoteName}"
          onchange="updateQuote(this)"
          class="quote-detail-inline-input">
      </div>
    </div>
  `.trim();
}

function replaceQuoteDetailsElement(existingElement, quote) {
  if (!existingElement || !quote) {
    return null;
  }

  const previousSkus = new Set(
    Array.from(existingElement.querySelectorAll("[data-sku]")).map(el => el.dataset.sku)
  );

  const parent = existingElement.parentNode;
  if (!parent) {
    return null;
  }

  const template = document.createElement("div");
  template.innerHTML = renderQuoteDetails(quote);
  const nextElement = template.firstElementChild;
  if (!nextElement) {
    return null;
  }

  parent.replaceChild(nextElement, existingElement);
  initializeQuoteDetailInteractions(nextElement);

  // Highlight newly added line items (SKUs not present before)
  const newRows = nextElement.querySelectorAll(".quote-table tbody tr");
  newRows.forEach(row => {
    const skuEl = row.querySelector("[data-sku]");
    const sku = skuEl ? skuEl.dataset.sku : null;
    if (sku && !previousSkus.has(sku)) {
      row.classList.add("quote-line-flash");
      setTimeout(() => row.classList.remove("quote-line-flash"), 1800);
    }
  });

  flashQuoteTotals(nextElement);
  return nextElement;
}

function initializeQuoteDetailInteractions(container) {
  if (!container) {
    return;
  }

  const selects = container.querySelectorAll('select');
  if (selects.length > 0) {
    if (typeof M !== 'undefined' && M.FormSelect) {
      M.FormSelect.init(selects);
    }
  }

  const expirationInput = container.querySelector('#expiration_date[data-field="expiration_date"]');
  if (expirationInput && typeof flatpickr === "function") {
    flatpickr(expirationInput, {
      dateFormat: "m/d/Y",
      defaultDate: expirationInput.value,
      allowInput: false,
      onChange: function(selectedDates, dateStr, instance) {
        updateQuote(instance.input);
      }
    });
  }

  initializeQuoteNotesEditors(container);
}

function sanitizeQuoteNotesHtml(html) {
  if (!html) return "";

  const allowedTags = new Set(["B", "STRONG", "I", "EM", "U", "BR", "P", "UL", "OL", "LI"]);
  const parser = new DOMParser();
  const doc = parser.parseFromString(String(html), "text/html");

  const walk = (node) => {
    const children = Array.from(node.childNodes || []);
    for (const child of children) {
      if (child.nodeType === Node.ELEMENT_NODE) {
        const tag = child.tagName;
        if (tag === "DIV") {
          // Preserve line breaks from contenteditable by converting divs to paragraphs.
          const para = doc.createElement("p");
          while (child.firstChild) {
            para.appendChild(child.firstChild);
          }
          child.replaceWith(para);
          walk(para);
          continue;
        }
        if (!allowedTags.has(tag)) {
          const replacement = doc.createTextNode(child.textContent || "");
          child.replaceWith(replacement);
          continue;
        }

        // Strip all attributes (defensive)
        for (const attr of Array.from(child.attributes || [])) {
          child.removeAttribute(attr.name);
        }
        walk(child);
      }
    }
  };

  walk(doc.body);

  // Keep output tight; preserve <br> breaks
  return (doc.body.innerHTML || "").trim();
}

function initializeQuoteNotesEditors(container) {
  const editors = container.querySelectorAll(".quote-notes-editor[data-field='notes']");
  if (!editors.length) return;

  // Toolbar: apply formatting commands to the nearest editor.
  container.querySelectorAll(".quote-notes-tool").forEach((btn) => {
    if (btn.dataset.bound === "true") return;
    btn.dataset.bound = "true";
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      const cmd = btn.dataset.cmd;
      const editor = btn.closest(".quote-notes-block")?.querySelector(".quote-notes-editor");
      if (!editor || !cmd) return;
      editor.focus();
      try {
        document.execCommand(cmd, false, null);
      } catch (err) {
        console.warn("Quote notes command failed:", cmd, err);
      }
    });
  });

  editors.forEach((editor) => {
    if (editor.dataset.initialized === "true") return;
    editor.dataset.initialized = "true";

    let raw = "";
    try {
      raw = JSON.parse(editor.dataset.initialJson || "\"\"") || "";
    } catch {
      raw = editor.dataset.initialJson || "";
    }

    const isLikelyHtml = /<\s*\w+[^>]*>/.test(raw);
    const initialHtml = isLikelyHtml ? raw : escapeHtml(String(raw)).replace(/\n/g, "<br/>");
    const existingHtml = (editor.innerHTML || "").trim();
    editor.innerHTML = sanitizeQuoteNotesHtml(existingHtml || initialHtml);
    editor.dataset.initialValue = editor.innerHTML;

    editor.addEventListener("focus", () => {
      editor.dataset.initialValue = editor.innerHTML;
    });

    editor.addEventListener("paste", (event) => {
      // Prevent rich paste; keep it clean.
      event.preventDefault();
      const text = (event.clipboardData || window.clipboardData).getData("text/plain");
      document.execCommand("insertText", false, text);
    });

    editor.addEventListener("blur", () => {
      const sanitized = sanitizeQuoteNotesHtml(editor.innerHTML);
      editor.innerHTML = sanitized;
      updateQuote(editor);
    });
  });
}

function flashQuoteTotals(container) {
  // Flashing of totals disabled per request; keep function for callsites
}

function ensureQuoteStatusValue(quote) {
  if (!quote) return quote;
  const raw = quote.status_value || quote.status || "Draft";
  quote.status_value = raw;
  if (!quote.status) quote.status = raw;
  return quote;
}

function buildStatusOptions(quote) {
  ensureQuoteStatusValue(quote);
  const choices = Array.isArray(quote.status_choices) && quote.status_choices.length
    ? quote.status_choices
    : [
        { value: "Draft", label: "Draft" },
        { value: "Pending Approval", label: "Pending Approval" },
        { value: "Approved", label: "Approved" },
        { value: "Rejected", label: "Rejected" },
        { value: "Closed", label: "Closed" },
      ];
  const current = quote.status_value || quote.status || "";
  const normalizedStatus = (current || "").toString().toLowerCase();

  return choices
    .map(({ value, label }) => {
      const isSelected =
        value === current ||
        normalizedStatus === value.toString().toLowerCase();
      return `<option value="${value}" ${isSelected ? "selected" : ""}>${label}</option>`;
    })
    .join("");
}

function statusBadgeStyle(value) {
  const v = (value || "").toString().toLowerCase();
  const base = "display:inline-block;padding:4px 10px;border-radius:999px;font-weight:700;font-size:0.9rem;";
  if (v === "approved") return `${base}background:#e8f7ef;color:#0f9d58;`;
  if (v === "rejected") return `${base}background:#fde8ed;color:#e11d48;`;
  if (v === "pending approval") return `${base}background:#fff3d6;color:#d98200;`;
  return `${base}background:#f1f3f5;color:#555;`;
}

function prepareQuoteStatusFields(quote) {
  if (!quote) return { raw: "", normalized: "" };
  ensureQuoteStatusValue(quote);
  const raw = (quote.status_value || quote.status || "").toString().trim();
  const normalized = raw.replace(/_/g, " ").toLowerCase();
  // Hydrate back for downstream use to keep consistency
  quote.status_value = raw;
  return { raw, normalized };
}

function renderQuoteDetails(quote) {
  if (window.innerWidth < 1200) {
    return renderQuoteDetailsMobile(quote);   // ← new helper (see below)
  }
  if (console && typeof console.debug === "function") {
    console.debug("renderQuoteDetails status payload", {
      status_value: quote.status_value,
      status: quote.status
    });
  }
  const createdAt = new Date(quote.created_at);
  const expirationDate = new Date(quote.expiration_date);

  const month = String(createdAt.getUTCMonth() + 1).padStart(2, '0');
  const day = String(createdAt.getUTCDate()).padStart(2, '0');
  const year = createdAt.getUTCFullYear();

  const formattedDate = `${month}/${day}/${year}`;

  const monthFormatted = String(expirationDate.getUTCMonth() + 1).padStart(2, '0');
  const dayFormatted = String(expirationDate.getUTCDate()).padStart(2, '0');
  const yearFormatted = expirationDate.getUTCFullYear();

  const formattedDate_e = `${monthFormatted}/${dayFormatted}/${yearFormatted}`;

  const { raw: statusValue, normalized: normalizedStatus } = prepareQuoteStatusFields(quote);
  console.log('STATUS OPTIONS: '+buildStatusOptions(quote));
  const rawNotes = quote && Object.prototype.hasOwnProperty.call(quote, "notes") ? (quote.notes || "") : "";
  const notesLooksHtml = /<\s*\w+[^>]*>/.test(String(rawNotes));
  const notesInitialHtml = sanitizeQuoteNotesHtml(
    notesLooksHtml ? String(rawNotes) : escapeHtml(String(rawNotes)).replace(/\n/g, "<br/>")
  );
  const accountId = quote.account_id || quote.accountId;
  const opportunityId = quote.opportunity_id || quote.opportunityId;
  const accountText = quote.account ? escapeHtml(String(quote.account)) : "*****";
  const opportunityText = quote.opportunity ? escapeHtml(String(quote.opportunity)) : "*****";
  const accountValue = accountId
    ? `<button type="button" class="quote-detail-link quote-detail-value" data-record-id="${escapeHtml(String(accountId))}" data-object="Account" aria-label="View Account" title="View Account">${accountText}</button>`
    : `<span class="quote-detail-value">${accountText}</span>`;
  const opportunityValue = opportunityId
    ? `<button type="button" class="quote-detail-link quote-detail-value" data-record-id="${escapeHtml(String(opportunityId))}" data-object="Opportunity" aria-label="View Opportunity" title="View Opportunity">${opportunityText}</button>`
    : `<span class="quote-detail-value">${opportunityText}</span>`;
  var html = `<div class="quote-container" data-quote-name="${quote.quote_name}">
              <div class="quote-header">
                  <h3>Quote: ${quote.quote_name}</h3>
                  <div style="display: flex; align-items: center; gap: 8px;" class="status-select">
                    <span style="${statusBadgeStyle(statusValue)}">${statusValue || "—"}</span>
                  </div>
              </div>
              <div class="quote-details">
                <div class="quote-detail-item">
                  <div class="quote-detail-label-row">
                    <span class="material-icons quote-detail-icon" aria-hidden="true">apartment</span>
                    <span class="quote-detail-label">Account</span>
                  </div>
                  ${accountValue}
                </div>
                <div class="quote-detail-item">
                  <div class="quote-detail-label-row">
                    <span class="material-icons quote-detail-icon" aria-hidden="true">insights</span>
                    <span class="quote-detail-label">Opportunity</span>
                  </div>
                  ${opportunityValue}
                </div>
                <div class="quote-detail-item quote-detail-item--wide">
                  <div class="quote-detail-inline-row">
                    ${renderQuoteDiscountControls(quote)}
                    <div class="quote-detail-inline-item">
                      <div class="quote-detail-inline-label">Exp: Date</div>
                      <div class="quote-detail-date-field">
                        <span class="material-icons quote-detail-date-icon" aria-hidden="true">event</span>
                        ${quote.expiration_date ? `
                          <input type="text" id="expiration_date" name="expiration_date"
                            class="quote-detail-date-input"
                            data-field="expiration_date"
                            data-quote="${quote.quote_name}"
                            placeholder="MM/DD/YYYY"
                            value="${formattedDate_e}"/>
                        ` : `<span class="quote-detail-date-value">${escapeHtml("*****")}</span>`}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <h4>Line Items</h4>`;

  var has_printed_subscription_header = false;

  quote.line_items.forEach(item => {
    if(item.is_subscription == true){
      if(!has_printed_subscription_header){
        const headers = [];

        quote.rendered_fields.forEach(field => {
          const cleaned = field.replace(/^Product\./, "");

          if (cleaned.toLowerCase() === "discount") {
            headers.push(`<th>Discount (%)</th>`);
            headers.push(`<th>Discount (USD)</th>`);
          }
          else if (cleaned === "Total Price") {
            headers.push(`<th>Subscription</th>`);
            headers.push(`<th>Term</th>`);
            headers.push(`<th>Total Price</th>`);
          }
          else {
            const label = cleaned
              .replace("Product And SKU", "Product")
              .replace("Unit Price", "Unit Price")
              .replace("Quantity", "Quantity")
              .replace(/_/g, " ")
              .replace(/\b\w/g, l => l.toUpperCase());

            headers.push(`<th>${label}</th>`);
          }
        });

        html += `
                <table class="quote-table" data-quote-id="${quote.quote_name}">
                  <thead>
                    <tr>
                      ${headers.join("\n")}
                    </tr>
                  </thead>
                  <tbody>`;

        has_printed_subscription_header = true;
      }

      html += `<tr${item.is_bundle_child ? ' class="bundle-child"' : ''}>`;
      //console.log("Item: ", item);

      quote.rendered_fields.forEach(field => {
        // Limpiar campos como Product.UOM
        const cleanedField = field.replace(/^Product\./, "");

        if (field === "Product And SKU") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 16px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.product}</div>
                  <div class="centered-td" style="color: #888; font-size: 0.65em">SKU: ${item.sku}</div>
                  ${item.is_bundle_child ? ` <div class="centered-td" style="color: #888; font-size: 0.65em"> (Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "Product") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.product}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "SKU") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.sku}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "Quantity") {
          html += `
            <td>
              <input
                type="number"
                min="1"
                class="editable-field"
                value="${item.quantity}"
                data-quote="${quote.quote_name}"
                data-quoteline-id="${item.id}"
                data-sku="${item.sku}"
                data-field="quantity"
                onchange="updateQuoteLine(this)">
            </td>`;
        } else if (field === "Description") {
          //console.log("Field es description.");
          html += `
            <td class="quote-description-cell">
              <p>${item.description}</p>
            </td>`;
        }
        else if (field === "Unit Price") {
          html += `
            <td>
              ${parseFloat(item.unit_price.replace('$', '')).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })}
            </td>`;
        } else if (field === "Discount") {
          html += `
            <td class="centered-td">
              <input name="discountPercentage" type="number" min="0" max="100"
                value="${(() => {
                  const val = parseFloat(item.discount_percentage.replace('%', ''));
                  return Number.isInteger(val) ? val : val.toFixed(2);
                })()}"
                data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}"
                class="editable-field" data-field="discount_percentage" onchange="updateQuoteLine(this)">
            </td>`;
            html += `
            <td class="centered-td">
              <input name="discountAmount" type="number" min="0" max="100"
                value="${item.discount_amount.replace('$', '')}"
                data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}"
                class="editable-field" data-field="discount_amount" onchange="updateQuoteLine(this)">
            </td>`;
        } else if (field === "Total Price") {
          html += `
              <td class="centered-td">
                ${item.is_subscription ? '✅' : '❌'}
              </td>`;

          html += `
              <td class="centered-td">
                <input
                  name="term"
                  type="number"
                  value="${item.term || '---'}"
                  data-quote="${quote.quote_name}"
                  data-quoteline-id="${item.id}"
                  data-sku="${item.sku}"
                  class="editable-field"
                  data-field="term"
                  onchange="updateQuoteLine(this)"
                  style="text-align: center;">
              </td>`;

          html += `
            <td class="total-price" data-sku="${item.sku}">
              ${parseFloat(item.total_price.replace('$', '')).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })}
            </td>`;
        } else {
          // Custom Field: Just render the value
          html += `
            <td class="centered-td">${item[cleanedField] ?? "---"}</td>`;
        }
      });

      html += `</tr>`;
    }
  });

  html += `</tbody></table><br>`;
  let none_suscription_bool = 0;

  quote.line_items.forEach(item => {
    if(item.is_subscription == false){
      if(none_suscription_bool == 0){
        const headers = [];

        quote.rendered_fields.forEach(field => {
          const cleaned = field.replace(/^Product\./, "");

          if (cleaned.toLowerCase() === "discount") {
            headers.push(`<th>Discount (%)</th>`);
            headers.push(`<th>Discount (USD)</th>`);
          } else {
            const label = cleaned
              .replace("Product And SKU", "Product")
              .replace("Unit Price", "Unit Price")
              .replace("discount_percentage", "Discount (%)")
              .replace("discount_amount", "Discount (USD)")
              .replace("total_price", "Total Price")
              .replace("subscription", "Subscription")
              .replace("term", "Term")
              .replace("Quantity", "Quantity")
              .replace(/_/g, " ")
              .replace(/\b\w/g, l => l.toUpperCase());

            headers.push(`<th>${label}</th>`);
          }
        });

        html += `
                <table class="quote-table" data-quote-id="${quote.quote_name}">
                  <thead>
                    <tr>
                      ${headers.join("\n")}
                    </tr>
                  </thead>
                  <tbody>`;
        none_suscription_bool = 1;
      }

      html += `<tr${item.is_bundle_child ? ' class="bundle-child"' : ''}>`;
      //console.log("Item: ", item);

      if (item.is_bundle_child == true && item.is_bundle_component_selected == false) {
        quote.rendered_fields.forEach((field, index) => {
          if (index == 0 && field != "Discount"){
            html += `
                <td>
                  <div class="centered-td" style="color: gray; font-size: 0.65em">
                  Product available but not selected: ${item.sku}
                  </div>
                </td>
              `;
          }
          else if (field == "Discount"){
            html += `
                <td>
                  <div class="centered-td" style="color: gray; font-size: 0.65em">
                  </div>
                </td>
              `;
            html += `
              <td>
                <div class="centered-td" style="color: gray; font-size: 0.65em">
                </div>
              </td>
            `;
          }
          else {
            html += `
                <td>
                  <div class="centered-td" style="color: gray; font-size: 0.65em">
                  </div>
                </td>
              `;
          }
        });
      }
      else {

      quote.rendered_fields.forEach(field => {
        // Limpiar campos como Product.UOM
        const cleanedField = field.replace(/^Product\./, "");

        if (field === "Product And SKU") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.product}</div>
                  <div class="centered-td" style="color: #888; font-size: 0.65em">SKU: ${item.sku}</div>
                  ${item.is_bundle_child ? ` <div class="centered-td" style="color: #888; font-size: 0.65em"> (Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "Product") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.product}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "SKU") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.sku}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "Quantity") {
          html += `
            <td>
              <input type="number" min="1" value="${item.quantity}"
                data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}"
                class="editable-field" data-field="quantity" onchange="updateQuoteLine(this)">
            </td>`;
        } else if (field === "Description") {
          html += `
            <td class="quote-description-cell">
              <p>${item.description}</p>
            </td>`;
        } else if (field === "Unit Price") {
          html += `
            <td class="unit-price" data-sku="${item.sku}">
              ${parseFloat(item.unit_price.replace('$', '')).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })}
            </td>`;
        } else if (field === "Discount") {
          html += `
            <td class="centered-td">
              <input name="discountPercentage" type="number" min="0" max="100"
                value="${(() => {
                  const val = parseFloat(item.discount_percentage.replace('%', ''));
                  return Number.isInteger(val) ? val : val.toFixed(2);
                })()}"
                data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}"
                class="editable-field" data-field="discount_percentage" onchange="updateQuoteLine(this)">
            </td>`;
            html += `
            <td class="centered-td">
              <input name="discountAmount" type="number" min="0" max="100"
                value="${item.discount_amount.replace('$', '')}"
                data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}"
                class="editable-field" data-field="discount_amount" onchange="updateQuoteLine(this)">
            </td>`;
        } else if (field === "Total Price") {
          html += `
            <td class="total-price" data-sku="${item.sku}">
              ${parseFloat(item.total_price.replace('$', '')).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })}
            </td>`;
        } else {
          // Custom Field: Just render the value
          html += `
            <td class="centered-td">${item[cleanedField] ?? "---"}</td>`;
        }
      });

      }

      html += `</tr>`;
    }
  });

  html += `</tbody></table>
    <div class="total-container">
      <p class="subtotal-amount">
        Subtotal: ${parseFloat(quote.subtotal.replace('$', '')).toLocaleString('en-US', {
            style: 'currency',
            currency: 'USD'
        })}
      </p>`;

  if(quote.show_tax_information && (quote.show_quote_tax_percentage || quote.show_quote_tax_amount)){
    html += `
      <p class="subtotal-amount">
        Tax:
        ${
          quote.show_quote_tax_percentage && quote.show_quote_tax_amount
            ? `(${parseFloat(quote.tax_percentage)}%) `
            : quote.show_quote_tax_percentage
            ? `${parseFloat(quote.tax_percentage)}% `
            : ''
        }
        ${
          quote.show_quote_tax_amount
            ? parseFloat(quote.tax_amount).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })
            : ''
        }
      </p>
    `;
  }

  html += `    <p class="total-amount">
        Net Amount: ${parseFloat(quote.net_amount.replace('$', '')).toLocaleString('en-US', {
            style: 'currency',
            currency: 'USD'
        })}
      </p>
      <div class="quote-notes-block">
        <div class="quote-notes-label">Notes</div>
        <div class="quote-notes-toolbar" role="toolbar" aria-label="Notes formatting">
          <button type="button" class="quote-notes-tool" data-cmd="bold" title="Bold"><span class="material-icons">format_bold</span></button>
          <button type="button" class="quote-notes-tool" data-cmd="italic" title="Italic"><span class="material-icons">format_italic</span></button>
          <button type="button" class="quote-notes-tool" data-cmd="underline" title="Underline"><span class="material-icons">format_underlined</span></button>
          <span class="quote-notes-divider" aria-hidden="true"></span>
          <button type="button" class="quote-notes-tool" data-cmd="insertUnorderedList" title="Bullets"><span class="material-icons">format_list_bulleted</span></button>
          <button type="button" class="quote-notes-tool" data-cmd="insertOrderedList" title="Numbered list"><span class="material-icons">format_list_numbered</span></button>
        </div>
        <div
          class="quote-notes-editor"
          contenteditable="true"
          role="textbox"
          aria-multiline="true"
          data-field="notes"
          data-quote="${quote.quote_name}"
          data-initial-json="${escapeHtml(JSON.stringify(rawNotes))}"
          data-placeholder="Add notes for this quote…"
        >${notesInitialHtml}</div>
        <textarea class="quote-notes-textarea quote-notes-textarea--hidden" tabindex="-1" aria-hidden="true"></textarea>
      </div>
    </div>
  </div>`;

  return html;
}

/* ────────────────────────────── 2. MOBILE-ONLY HELPER ──────────────────────────────── */
/* Place this anywhere after renderQuoteDetails (same file or imported) */
function renderQuoteDetailsMobile(quote) {
  const format = (d) =>
    `${String(d.getUTCMonth() + 1).padStart(2, "0")}/${String(d.getUTCDate()).padStart(
      2,
      "0"
    )}/${d.getUTCFullYear()}`;

  const formatDateValue = (value) => {
    if (!value) return "—";
    const d = new Date(value);
    return isNaN(d.getTime()) ? "—" : format(d);
  };
  const formatCurrencyValue = (value) => {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "number" && Number.isFinite(value)) {
      return value.toLocaleString("en-US", { style: "currency", currency: "USD" });
    }
    const raw = String(value).replace(/[$,]/g, "");
    const num = parseFloat(raw);
    if (Number.isNaN(num)) return escapeHtml(String(value));
    return num.toLocaleString("en-US", { style: "currency", currency: "USD" });
  };
  const safeText = (value) => {
    if (value === null || value === undefined || value === "") return "—";
    return escapeHtml(String(value));
  };

  const discountPercentageValue = Number(quote.discount_percentage ?? 0);
  const discountAmountValue = Number(quote.discount_amount ?? 0);
  const safeDiscountPercentage = Number.isFinite(discountPercentageValue) ? discountPercentageValue : 0;
  const safeDiscountAmount = Number.isFinite(discountAmountValue) ? discountAmountValue : 0;
  const formattedDiscountAmount = formatCurrencyValue(safeDiscountAmount);
  const { raw: statusValue, normalized: normalizedStatus } = prepareQuoteStatusFields(quote);
  const rawNotes = quote && Object.prototype.hasOwnProperty.call(quote, "notes") ? (quote.notes || "") : "";
  const notesLooksHtml = /<\s*\w+[^>]*>/.test(String(rawNotes));
  const notesInitialHtml = sanitizeQuoteNotesHtml(
    notesLooksHtml ? String(rawNotes) : escapeHtml(String(rawNotes)).replace(/\n/g, "<br/>")
  );
  const statusStyle = `${statusBadgeStyle(statusValue)}font-size:0.75rem;padding:3px 8px;`;
  const discountDisplay = `${safeDiscountPercentage}%${formattedDiscountAmount !== "—" ? ` (${formattedDiscountAmount})` : ""}`;
  const lineItems = Array.isArray(quote.line_items) ? quote.line_items : [];
  const lineItemsHtml = lineItems.length
    ? lineItems.map((item) => {
        const itemName = escapeHtml(String(item.product || item.name || "Item"));
        const quantity = item.quantity ?? "—";
        const unitPrice = formatCurrencyValue(item.unit_price);
        const totalPrice = formatCurrencyValue(item.total_price);
        const subscriptionLabel = item.is_subscription ? `<span>Subscription</span>` : "";
        const totalMarkup = totalPrice !== "—"
          ? `<div class="quote-mobile-item-total">${totalPrice}</div>`
          : "";
        return `
          <div class="quote-mobile-item">
            <div class="quote-mobile-item-name">${itemName}</div>
            <div class="quote-mobile-item-meta">
              <span>Qty ${escapeHtml(String(quantity))}</span>
              <span>Unit ${unitPrice}</span>
              ${subscriptionLabel}
            </div>
            ${totalMarkup}
          </div>
        `;
      }).join("")
    : `<div class="quote-mobile-item quote-mobile-item--empty">No line items yet.</div>`;
  const taxMarkup = quote.show_tax_information && (quote.show_quote_tax_percentage || quote.show_quote_tax_amount)
    ? `<div class="quote-mobile-total-row">
        <span>Tax</span>
        <span>
          ${
            quote.show_quote_tax_percentage && quote.show_quote_tax_amount
              ? `(${parseFloat(quote.tax_percentage)}%) `
              : quote.show_quote_tax_percentage
              ? `${parseFloat(quote.tax_percentage)}% `
              : ''
          }
          ${
            quote.show_quote_tax_amount
              ? formatCurrencyValue(quote.tax_amount)
              : ''
          }
        </span>
      </div>`
    : "";
  const accountId = quote.account_id || quote.accountId;
  const opportunityId = quote.opportunity_id || quote.opportunityId;
  const accountCardClass = accountId ? "quote-mobile-card quote-mobile-card--link" : "quote-mobile-card";
  const opportunityCardClass = opportunityId ? "quote-mobile-card quote-mobile-card--link" : "quote-mobile-card";
  const accountAttrs = accountId
    ? ` data-record-id="${escapeHtml(String(accountId))}" data-object="Account" role="button" tabindex="0" aria-label="View Account record"`
    : "";
  const opportunityAttrs = opportunityId
    ? ` data-record-id="${escapeHtml(String(opportunityId))}" data-object="Opportunity" role="button" tabindex="0" aria-label="View Opportunity record"`
    : "";

  let html = `
    <div class="quote-mobile" data-quote-name="${quote.quote_name}">
      <div class="quote-mobile-header">
        <div class="quote-mobile-title-block">
          <div class="quote-mobile-kicker">Quote</div>
          <h3 class="quote-mobile-title">${escapeHtml(String(quote.quote_name || ""))}</h3>
          <div class="quote-mobile-meta">
            <div class="quote-mobile-meta-item">
              <span class="material-icons quote-mobile-meta-icon" aria-hidden="true">calendar_today</span>
              <span class="quote-mobile-meta-value">${formatDateValue(quote.created_at)}</span>
            </div>
            <div class="quote-mobile-meta-item quote-mobile-meta-item--expires">
              <span class="quote-mobile-meta-label">Exp.</span>
              <span class="quote-mobile-meta-value">${formatDateValue(quote.expiration_date)}</span>
            </div>
            <div class="quote-mobile-meta-item">
              <span class="material-icons quote-mobile-meta-icon" aria-hidden="true">local_offer</span>
              <span class="quote-mobile-meta-value">${discountDisplay}</span>
            </div>
          </div>
        </div>
        <div class="quote-mobile-status">
          <span class="quote-mobile-status-pill" style="${statusStyle}">${escapeHtml(String(statusValue || "—"))}</span>
        </div>
      </div>

      <div class="quote-mobile-section">
        <div class="quote-mobile-section-title">Details</div>
        <div class="quote-mobile-grid">
          <div class="${accountCardClass}"${accountAttrs}>
            <span class="quote-mobile-label">Account</span>
            <span class="quote-mobile-value">${safeText(quote.account)}</span>
          </div>
          <div class="${opportunityCardClass}"${opportunityAttrs}>
            <span class="quote-mobile-label">Opportunity</span>
            <span class="quote-mobile-value">${safeText(quote.opportunity)}</span>
          </div>
        </div>
      </div>

      <div class="quote-mobile-section">
        <div class="quote-mobile-section-title">Line Items</div>
        <div class="quote-mobile-items">${lineItemsHtml}</div>
      </div>

      <div class="quote-mobile-section">
        <div class="quote-mobile-section-title">Totals</div>
        <div class="quote-mobile-totals">
          <div class="quote-mobile-total-row">
            <span>Subtotal</span>
            <span>${formatCurrencyValue(quote.subtotal)}</span>
          </div>
          ${taxMarkup}
          <div class="quote-mobile-total-row is-grand">
            <span>Net Amount</span>
            <span>${formatCurrencyValue(quote.net_amount)}</span>
          </div>
        </div>
      </div>

      <div class="quote-mobile-section quote-notes-block">
        <div class="quote-mobile-section-title">Notes</div>
        <div class="quote-notes-toolbar" role="toolbar" aria-label="Notes formatting">
          <button type="button" class="quote-notes-tool" data-cmd="bold" title="Bold"><span class="material-icons">format_bold</span></button>
          <button type="button" class="quote-notes-tool" data-cmd="italic" title="Italic"><span class="material-icons">format_italic</span></button>
          <button type="button" class="quote-notes-tool" data-cmd="underline" title="Underline"><span class="material-icons">format_underlined</span></button>
          <span class="quote-notes-divider" aria-hidden="true"></span>
          <button type="button" class="quote-notes-tool" data-cmd="insertUnorderedList" title="Bullets"><span class="material-icons">format_list_bulleted</span></button>
        </div>
        <div
          class="quote-notes-editor"
          contenteditable="true"
          role="textbox"
          aria-multiline="true"
          data-field="notes"
          data-quote="${quote.quote_name}"
          data-initial-json="${escapeHtml(JSON.stringify(rawNotes))}"
          data-placeholder="Add notes for this quote…"
        >${notesInitialHtml}</div>
        <textarea class="quote-notes-textarea quote-notes-textarea--hidden" tabindex="-1" aria-hidden="true"></textarea>
      </div>
    </div>`;

  return html;
}

function renderReadOnlyQuoteDetails(quote) {
  if (window.innerWidth < 1200) {
    return renderQuoteDetailsMobile(quote);   // ← new helper (see below)
  }
  const { raw: statusValue } = prepareQuoteStatusFields(quote);
  const createdAt = new Date(quote.created_at);
  const expirationDate = new Date(quote.expiration_date);

  const month = String(createdAt.getUTCMonth() + 1).padStart(2, '0');
  const day = String(createdAt.getUTCDate()).padStart(2, '0');
  const year = createdAt.getUTCFullYear();

  const formattedDate = `${month}/${day}/${year}`;

  const monthFormatted = String(expirationDate.getUTCMonth() + 1).padStart(2, '0');
  const dayFormatted = String(expirationDate.getUTCDate()).padStart(2, '0');
  const yearFormatted = expirationDate.getUTCFullYear();

  const formattedDate_e = `${monthFormatted}/${dayFormatted}/${yearFormatted}`;
  const accountId = quote.account_id || quote.accountId;
  const opportunityId = quote.opportunity_id || quote.opportunityId;
  const accountText = quote.account ? escapeHtml(String(quote.account)) : "---";
  const opportunityText = quote.opportunity ? escapeHtml(String(quote.opportunity)) : "---";
  const accountValue = accountId
    ? `<button type="button" class="quote-detail-link quote-detail-value" data-record-id="${escapeHtml(String(accountId))}" data-object="Account" aria-label="View Account" title="View Account">${accountText}</button>`
    : `<span class="quote-detail-value">${accountText}</span>`;
  const opportunityValue = opportunityId
    ? `<button type="button" class="quote-detail-link quote-detail-value" data-record-id="${escapeHtml(String(opportunityId))}" data-object="Opportunity" aria-label="View Opportunity" title="View Opportunity">${opportunityText}</button>`
    : `<span class="quote-detail-value">${opportunityText}</span>`;
  const discountPercentDisplay = quote.discount_percentage !== null && quote.discount_percentage !== undefined
    ? escapeHtml(String(quote.discount_percentage))
    : "---";
  const discountAmountRaw = quote.discount_amount !== null && quote.discount_amount !== undefined
    ? quote.discount_amount
    : null;
  const discountAmountNumber = Number(discountAmountRaw);
  const discountAmountDisplay = Number.isFinite(discountAmountNumber)
    ? discountAmountNumber.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : (discountAmountRaw !== null ? escapeHtml(String(discountAmountRaw)) : "---");

  var html = `<div class="quote-container" data-quote-name="${quote.quote_name}">
              <div class="quote-header">
                  <h3>Quote: ${quote.quote_name}</h3>
                  <div style="display: flex; align-items: center; gap: 8px;" class="status-select">
                    <span style="${statusBadgeStyle(statusValue)}">${statusValue || "—"}</span>
                  </div>
              </div>
              <div class="quote-details">
                <div class="quote-detail-item">
                  <div class="quote-detail-label-row">
                    <span class="material-icons quote-detail-icon" aria-hidden="true">apartment</span>
                    <span class="quote-detail-label">Account</span>
                  </div>
                  ${accountValue}
                </div>
                <div class="quote-detail-item">
                  <div class="quote-detail-label-row">
                    <span class="material-icons quote-detail-icon" aria-hidden="true">insights</span>
                    <span class="quote-detail-label">Opportunity</span>
                  </div>
                  ${opportunityValue}
                </div>
                <div class="quote-detail-item quote-detail-item--wide">
                  <div class="quote-detail-inline-row">
                    <div class="quote-detail-inline-item">
                      <div class="quote-detail-inline-label">Discount %</div>
                      <div class="quote-detail-inline-field">
                        <input type="text"
                          class="quote-detail-inline-input"
                          value="${discountPercentDisplay}"
                          readonly />
                      </div>
                    </div>
                    <div class="quote-detail-inline-item">
                      <div class="quote-detail-inline-label">Disc Amount</div>
                      <div class="quote-detail-inline-field">
                        <input type="text"
                          class="quote-detail-inline-input"
                          value="${discountAmountDisplay}"
                          readonly />
                      </div>
                    </div>
                    <div class="quote-detail-inline-item">
                      <div class="quote-detail-inline-label">Exp: Date</div>
                      <div class="quote-detail-date-field">
                        <span class="material-icons quote-detail-date-icon" aria-hidden="true">event</span>
                        <input type="text"
                          class="quote-detail-date-input"
                          value="${quote.expiration_date ? formattedDate_e : "---"}"
                          readonly />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <h4>Line Items</h4>`;

  var has_printed_subscription_header = false;


  quote.line_items.forEach(item => {
    if(item.is_subscription == true){
      if(!has_printed_subscription_header){
        const headers = [];

        quote.rendered_fields.forEach(field => {
          const cleaned = field.replace(/^Product\./, "");

          if (cleaned.toLowerCase() === "discount") {
            headers.push(`<th>Discount (%)</th>`);
            headers.push(`<th>Discount (USD)</th>`);
          }
          else if (cleaned === "Total Price") {
            headers.push(`<th>Subscription</th>`);
            headers.push(`<th>Term</th>`);
            headers.push(`<th>Total Price</th>`);
          }
          else {
            const label = cleaned
              .replace("Product And SKU", "Product")
              .replace("Unit Price", "Unit Price")
              .replace("Quantity", "Quantity")
              .replace(/_/g, " ")
              .replace(/\b\w/g, l => l.toUpperCase());

            headers.push(`<th>${label}</th>`);
          }
        });

        html += `
                <table class="quote-table" data-quote-id="${quote.quote_name}">
                  <thead>
                    <tr>
                      ${headers.join("\n")}
                    </tr>
                  </thead>
                  <tbody>`;

        has_printed_subscription_header = true;
      }

      html += `<tr${item.is_bundle_child ? ' class="bundle-child"' : ''}>`;

      quote.rendered_fields.forEach(field => {
        // Limpiar campos como Product.UOM
        const cleanedField = field.replace(/^Product\./, "");

        if (field === "Product And SKU") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.product}</div>
                  <div class="centered-td" style="color: #888; font-size: 0.65em">SKU: ${item.sku}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "Product") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.product}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "SKU") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.sku}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                <div>
              </div>
            </td>`;
        } else if (field === "Quantity") {
          html += `
            <td>
              <input
                type="number"
                min="1"
                class="editable-field"
                value="${item.quantity}"
                data-quote="${quote.quote_name}"
                data-quoteline-id="${item.id}"
                data-sku="${item.sku}"
                data-field="quantity"
                onchange="updateQuoteLine(this)"
                disabled>
            </td>`;
        } else if (field === "Unit Price") {
          html += `
            <td>
              ${parseFloat(item.unit_price.replace('$', '')).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })}
            </td>`;
        } else if (field === "Description") {
          html += `
            <td class="quote-description-cell">
              <p>${item.description}</p>
            </td>`;
        } else if (field === "Discount") {
          html += `
            <td class="centered-td">
              <input name="discountPercentage" type="number" min="0" max="100"
                value="${(() => {
                  const val = parseFloat(item.discount_percentage.replace('%', ''));
                  return Number.isInteger(val) ? val : val.toFixed(2);
                })()}"
                data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}"
                class="editable-field" data-field="discount_percentage" onchange="updateQuoteLine(this)"
                disabled>
            </td>`;
            html += `
            <td class="centered-td">
              <input name="discountAmount" type="number" min="0" max="100"
                value="${item.discount_amount.replace('$', '')}"
                data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}"
                class="editable-field" data-field="discount_amount" onchange="updateQuoteLine(this)"
                disabled>
            </td>`;
        } else if (field === "Total Price") {
          html += `
              <td class="centered-td">
                ${item.is_subscription ? '✅' : '❌'}
              </td>`;

          html += `
              <td class="centered-td">
                <input
                  name="term"
                  type="number"
                  value="${item.term || '---'}"
                  data-quote="${quote.quote_name}"
                  data-quoteline-id="${item.id}"
                  data-sku="${item.sku}"
                  class="editable-field"
                  data-field="term"
                  onchange="updateQuoteLine(this)"
                  style="text-align: center;"
                  disabled>
              </td>`;

          html += `
            <td class="total-price" data-sku="${item.sku}">
              ${parseFloat(item.total_price.replace('$', '')).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })}
            </td>`;
        } else {
          // Custom Field: Just render the value
          html += `
            <td class="centered-td">${item[cleanedField] ?? "---"}</td>`;
        }
      });

      html += `</tr>`;
    }
  });

  html += `</tbody></table><br>`
  let none_suscription_bool = 0;

  quote.line_items.forEach(item => {
    if(item.is_subscription == false){
      if(none_suscription_bool == 0){
        const headers = [];

        quote.rendered_fields.forEach(field => {
          const cleaned = field.replace(/^Product\./, "");

          if (cleaned.toLowerCase() === "discount") {
            headers.push(`<th>Discount (%)</th>`);
            headers.push(`<th>Discount (USD)</th>`);
          } else {
            const label = cleaned
              .replace("Product And SKU", "Product")
              .replace("Unit Price", "Unit Price")
              .replace("discount_percentage", "Discount (%)")
              .replace("discount_amount", "Discount (USD)")
              .replace("total_price", "Total Price")
              .replace("subscription", "Subscription")
              .replace("term", "Term")
              .replace("Quantity", "Quantity")
              .replace(/_/g, " ")
              .replace(/\b\w/g, l => l.toUpperCase());

            headers.push(`<th>${label}</th>`);
          }
        });

        html += `
                <table class="quote-table" data-quote-id="${quote.quote_name}">
                  <thead>
                    <tr>
                      ${headers.join("\n")}
                    </tr>
                  </thead>
                  <tbody>`;
        none_suscription_bool = 1;
      }

      html += `<tr${item.is_bundle_child ? ' class="bundle-child"' : ''}>`;

      quote.rendered_fields.forEach(field => {
        // Limpiar campos como Product.UOM
        const cleanedField = field.replace(/^Product\./, "");

        if (field === "Product And SKU") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.product}</div>
                  <div class="centered-td" style="color: #888; font-size: 0.65em">SKU: ${item.sku}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "Product") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.product}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "SKU") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.sku}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                <div>
              </div>
            </td>`;
        } else if (field === "Quantity") {
          html += `
            <td>
              <input type="number" min="1" value="${item.quantity}"
                data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}"
                class="editable-field" data-field="quantity" onchange="updateQuoteLine(this)"
                disabled>
            </td>`;
        } else if (field === "Description") {
          html += `
            <td class="quote-description-cell">
              <p>${item.description}</p>
            </td>`;
        } else if (field === "Unit Price") {
          html += `
            <td>
              ${parseFloat(item.unit_price.replace('$', '')).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })}
            </td>`;
        } else if (field === "Discount") {
          html += `
            <td class="centered-td">
              <input name="discountPercentage" type="number" min="0" max="100"
                value="${(() => {
                  const val = parseFloat(item.discount_percentage.replace('%', ''));
                  return Number.isInteger(val) ? val : val.toFixed(2);
                })()}"
                data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}"
                class="editable-field" data-field="discount_percentage" onchange="updateQuoteLine(this)"
                disabled>
            </td>`;
            html += `
            <td class="centered-td">
              <input name="discountAmount" type="number" min="0" max="100"
                value="${item.discount_amount.replace('$', '')}"
                data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}"
                class="editable-field" data-field="discount_amount" onchange="updateQuoteLine(this)"
                disabled>
            </td>`;
        } else if (field === "Total Price") {
          html += `
            <td class="total-price" data-sku="${item.sku}">
              ${parseFloat(item.total_price.replace('$', '')).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })}
            </td>`;
        } else {
          // Custom Field: Just render the value
          html += `
            <td class="centered-td">${item[cleanedField] ?? "---"}</td>`;
        }
      });

      html += `</tr>`;
    }
  });

  html += `</tbody></table>
    <div class="total-container">
      <p class="subtotal-amount">
        Subtotal: ${parseFloat(quote.subtotal.replace('$', '')).toLocaleString('en-US', {
            style: 'currency',
            currency: 'USD'
        })}
      </p>`;

  if(quote.show_tax_information && (quote.show_quote_tax_percentage || quote.show_quote_tax_amount)){
    html += `
      <p class="subtotal-amount">
        Tax:
        ${
          quote.show_quote_tax_percentage && quote.show_quote_tax_amount
            ? `(${parseFloat(quote.tax_percentage)}%) `
            : quote.show_quote_tax_percentage
            ? `${parseFloat(quote.tax_percentage)}% `
            : ''
        }
        ${
          quote.show_quote_tax_amount
            ? parseFloat(quote.tax_amount).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })
            : ''
        }
      </p>
    `;
  }

  html += `    <p class="total-amount">
        Net Amount: ${parseFloat(quote.net_amount.replace('$', '')).toLocaleString('en-US', {
            style: 'currency',
            currency: 'USD'
        })}
      </p>
    </div>
  </div>`;

  return html;
}

const RELATED_BUTTON_CONFIG = {
  "related-opportunities": {
    label: "Related opportunities",
    icon: "work",
    endpoint: "/cpq/related-opportunities/",
    relationKey: "account_id",
    relatedAttr: "data-related-account-id",
    pluralLabel: "opportunities",
    parentLabel: "Account",
    objectName: "opportunity",
    listOnClick: true,
    listObjectLabel: "Opportunities",
    listFields: ["name", "account", "amount", "stage", "expected_close_date", "view_record"],
    viewObjectName: "Opportunity",
  },
  "related-contract-lines": {
    label: "Contract lines",
    icon: "receipt_long",
    endpoint: "/cpq/related-contract-lines/",
    relationKey: "account_id",
    relatedAttr: "data-related-account-id",
    pluralLabel: "contract lines",
    parentLabel: "Account",
    objectName: "contractline__c",
  },
  "related-quotes": {
    label: "Related quotes",
    icon: "request_quote",
    endpoint: "/cpq/related-quotes/",
    relationKey: "opportunity_id",
    relatedAttr: "data-related-opportunity-id",
    pluralLabel: "quotes",
    parentLabel: "Opportunity",
    objectName: "quote",
    listOnClick: true,
    listObjectLabel: "Quotes",
    listFields: ["name", "status", "net_amount", "expiration_date", "primary_quote", "view_quote"],
  },
  "related-activities": {
    label: "Related activities",
    icon: "event",
    endpoint: "/cpq/related-activities/",
    relationKey: "record_id",
    objectKey: "object",
    relatedAttr: "data-related-record-id",
    pluralLabel: "activities",
    parentLabel: "Record",
    objectName: "activity",
    listOnClick: true,
    listObjectLabel: "Activities",
    listFields: ["subject", "activity_type", "status", "due_date", "view_record"],
    viewObjectName: "Activity",
  },
};

const RELATED_BUTTONS_BY_OBJECT = {
  account: ["related-opportunities", "related-contract-lines"],
  opportunity: ["related-quotes"],
};

function getRelatedButtonConfig(role) {
  return RELATED_BUTTON_CONFIG[role];
}

function renderRelatedButton(role) {
  const config = getRelatedButtonConfig(role);
  if (!config) return "";
  const label = escapeHtml(config.label);
  return `<div class="single-record-related-wrap">
    <button type="button" class="single-record-related-btn" data-role="${role}" aria-label="${label}" title="${label}">
      <span class="material-icons" aria-hidden="true">${config.icon}</span>
      <span class="single-record-related-count" data-role="related-count">...</span>
    </button>
  </div>`;
}

function renderGenericRelatedButton(section, index) {
  if (!section || !Array.isArray(section.records) || section.records.length === 0) return "";
  const label = section.label || section.object || "Related records";
  const count = section.records.length;
  return `<div class="single-record-related-wrap">
    <button type="button" class="single-record-related-btn single-record-related-btn--generic" data-role="generic-related" data-section-index="${index}" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}">
      <span class="material-icons" aria-hidden="true">link</span>
      <span class="single-record-related-count" data-role="related-count">${count}</span>
    </button>
  </div>`;
}

function renderSingleRecord(record) {
  if (!record || !Array.isArray(record.fields)) {
    return `<div class="error-message">⚠️ Unable to display this record right now.</div>`;
  }

  const layout = record.layout || { order: [], hidden: [] };
  const orderedFields = orderSingleRecordFields(record.fields, layout);
  const normalizeKey = (value) => (value || "").toString().trim().replace(/\s+/g, " ").replace(/_/g, " ").toLowerCase();
  const findFieldValue = (keys) => {
    const wanted = keys.map(k => normalizeKey(k));
    const match = record.fields.find(f => {
      const nameKey = normalizeKey(f.name);
      const labelKey = normalizeKey(f.label);
      return wanted.includes(nameKey) || wanted.includes(labelKey);
    });
    return match ? escapeHtml(String(match.display_value ?? match.value ?? "")) : "";
  };

  const leadFullName = (() => {
    const first = findFieldValue(["first_name", "first name"]);
    const last = findFieldValue(["last_name", "last name"]);
    return `${first} ${last}`.trim();
  })();

  const title = record.object && record.object.toLowerCase() === "lead"
    ? (leadFullName || (record.record_value != null ? escapeHtml(String(record.record_value)) : "Record"))
    : (record.record_value != null ? escapeHtml(String(record.record_value)) : "Record");
  const objectLabel = record.display_label || record.object || '';
  const subtitle = objectLabel ? `<div class="single-record-subtitle">${escapeHtml(objectLabel)}</div>` : '';
  const headerLabel = '';
  const customBadge = record.is_custom_object ? `<span class="single-record-badge">Custom object</span>` : '';
  const partnerLabel = record.partner_label || record._partner_label;
  const partnerBadge = partnerLabel
    ? `<span class="single-record-badge single-record-badge--partner">${escapeHtml(String(partnerLabel))}</span>`
    : '';
  const layoutAttr = layout ? ` data-layout='${escapeHtml(JSON.stringify(layout))}'` : '';
  const showLayoutButton = typeof window !== "undefined" ? !!window.isAdmin : false;
  if (showLayoutButton) {
    ensureSingleRecordCustomizerStyles();
  }
  const objectName = (record.object || '').toLowerCase();
  const headerIconName = objectName === "product" ? "inventory_2" : "category";
  const headerIcon = `<span class="material-icons" aria-hidden="true">${headerIconName}</span>`;

  const leadHeaderMeta = (() => {
    if (objectName !== "lead") return "";
    const firstName = findFieldValue(["first_name", "first name"]);
    const lastName = findFieldValue(["last_name", "last name"]);
    const email = findFieldValue(["email"]);
    const company = findFieldValue(["company_name", "company name", "company"]);
    const phone = findFieldValue(["phone"]);

    const parts = [];
    const iconSpan = (icon, text) => `<span class="material-icons" aria-hidden="true" style="font-size:16px;vertical-align:middle;">${icon}</span> <span>${text}</span>`;
    if (firstName || lastName) {
      parts.push(iconSpan("person", `${firstName} ${lastName}`.trim()));
    }
    if (email) {
      parts.push(iconSpan("mail", email));
    }
    if (company) {
      parts.push(iconSpan("apartment", company));
    }
    if (phone) {
      parts.push(iconSpan("call", phone));
    }

    if (!parts.length) return "";
    return `
      <div class="single-record-lead-meta">
        ${parts.join('<span class="lead-meta-sep">|</span>')}
      </div>
    `;
  })();
  const relatedAccountId = record.related_account_id || (record.meta && record.meta.related_account_id) || '';
  const relatedAccountAttr = relatedAccountId ? ` data-related-account-id="${escapeHtml(String(relatedAccountId))}"` : '';
  const relatedOpportunityId = record.related_opportunity_id || (record.meta && record.meta.related_opportunity_id) || '';
  const relatedOpportunityAttr = relatedOpportunityId ? ` data-related-opportunity-id="${escapeHtml(String(relatedOpportunityId))}"` : '';
  const relatedRecordId = record.related_record_id || (record.meta && record.meta.related_record_id) || '';
  const relatedRecordAttr = relatedRecordId ? ` data-related-record-id="${escapeHtml(String(relatedRecordId))}"` : '';
  const layoutButton = showLayoutButton
    ? `<button type="button" class="single-record-layout-btn single-record-layout-btn--icon" onclick="openSingleRecordCustomizer(this)" aria-label="Edit layout" title="Edit layout">
         <span class="material-icons" aria-hidden="true">tune</span>
       </button>`
    : '';
  const deleteButton = record && record.can_delete
    ? `<button type="button" class="single-record-delete-btn" data-role="delete-record" aria-label="Delete record" title="Delete record">
         <span class="material-icons" aria-hidden="true">delete_forever</span>
       </button>`
    : '';
  const relatedRoles = [...(RELATED_BUTTONS_BY_OBJECT[objectName] || [])];
  if (objectName && objectName !== "activity" && !relatedRoles.includes("related-activities")) {
    relatedRoles.push("related-activities");
  }
  const relatedButtons = relatedRoles.map(renderRelatedButton).filter(Boolean).join('');

  // Generic related buttons: every related section the backend returned that is
  // not already covered by a hardcoded role gets a button next to Layout.
  // This makes related actions work for any standard or custom object.
  const hardcodedObjects = new Set(
    relatedRoles
      .map(role => ((RELATED_BUTTON_CONFIG[role] || {}).objectName || "").toLowerCase())
      .filter(Boolean)
  );
  const genericSections = (record.related || []).filter(
    (section) => section && Array.isArray(section.records) && section.records.length > 0
  );
  const genericRelatedButtons = genericSections
    .map((section, index) => {
      const sectionObject = String(section.object || "").toLowerCase();
      if (hardcodedObjects.has(sectionObject)) return "";
      return renderGenericRelatedButton(section, index);
    })
    .filter(Boolean)
    .join('');
  const allRelatedButtons = relatedButtons + genericRelatedButtons;
  const relatedButtonsRow = allRelatedButtons ? `<div class="single-record-related-actions">${allRelatedButtons}</div>` : '';
  const headerControls = (layoutButton || deleteButton)
    ? `<div class="single-record-header-controls">${layoutButton}${deleteButton}</div>`
    : '';
  const headerActions = (relatedButtonsRow || headerControls)
    ? `<div class="single-record-header-actions">${headerControls}${relatedButtonsRow}</div>`
    : '';

  const sectionsHtml = renderSingleRecordSection(
    "Details",
    orderedFields.map(entry => renderSingleRecordField(record, entry.field, entry.hidden))
  );

  const relatedSections = (record.related || [])
    .map((entry, index) => renderSingleRecordRelated(entry, index))
    .join('');

  const gridContent = sectionsHtml || '<div class="single-record-empty">No additional details were provided for this record.</div>';

  return `
    <div class="single-record-card" data-record-object="${escapeHtml(record.object || '')}" data-record-id="${record.record_id ?? ''}" data-record-name="${escapeHtml(String(record.record_value ?? ''))}"${relatedAccountAttr}${relatedOpportunityAttr}${relatedRecordAttr}${layoutAttr}>
      <div class="single-record-header">
        <div class="single-record-header-text">
          <div class="single-record-subtitle" style="display:flex;align-items:center;gap:6px;">
            ${headerIcon}
            ${subtitle || escapeHtml(record.object || '')}
          </div>
          <div class="single-record-title single-record-title--accent">${title}</div>
          ${leadHeaderMeta}
        </div>
        <div class="single-record-header-meta">
          ${headerLabel}
          ${partnerBadge}
          ${customBadge}
          ${headerActions}
        </div>
      </div>
      <div class="single-record-body">
        <div class="single-record-sections">
          ${gridContent}
        </div>
        ${relatedSections}
        <div class="single-record-feedback" data-role="card-feedback" aria-live="polite"></div>
      </div>
    </div>
  `;
}

function initializeSingleRecordRelatedButtons(root = document) {
  if (!root) return;
  const buttons = root.querySelectorAll('.single-record-related-btn[data-role]');
  buttons.forEach(button => {
    const role = button.dataset.role;
    if (button.dataset.bound === "true") return;
    button.dataset.bound = "true";

    const card = button.closest('.single-record-card');
    if (!card) return;

    // Generic related buttons (built from record.related sections) simply
    // scroll to the matching section already rendered in the card body.
    if (role === "generic-related") {
      const sectionIndex = button.dataset.sectionIndex;
      button.addEventListener('click', () => {
        const section = card.querySelector(`.single-record-related[data-related-section="${sectionIndex}"]`);
        if (section) {
          section.scrollIntoView({ behavior: "smooth", block: "start" });
          section.classList.add("single-record-related--flash");
          window.setTimeout(() => section.classList.remove("single-record-related--flash"), 1800);
        }
      });
      return;
    }

    const config = getRelatedButtonConfig(role);
    if (!config) return;
    const relationId = card.dataset.recordId;
    const objectName = card.dataset.recordObject || "";

    if (relationId) {
      loadRelatedRecordsCount(button, config, relationId, objectName);
    } else {
      const badge = button.querySelector('[data-role="related-count"]');
      if (badge) badge.textContent = "0";
    }

    button.addEventListener('click', () => {
      handleRelatedRecordsClick(card, button, config);
    });
    setupRelatedPopoverHandlers(button, card, config);
  });
}

function initializeSingleRecordDeleteButtons(root = document) {
  if (!root) return;
  const buttons = root.querySelectorAll('.single-record-delete-btn[data-role="delete-record"]');
  buttons.forEach(button => {
    if (button.dataset.bound === "true") return;
    button.dataset.bound = "true";
    button.addEventListener('click', () => handleSingleRecordDeleteClick(button));
  });
}

async function handleSingleRecordDeleteClick(button) {
  const card = button.closest('.single-record-card');
  if (!card) return;

  const feedback = card.querySelector('[data-role="card-feedback"]');
  const objectName = card.dataset.recordObject || '';
  const recordId = card.dataset.recordId;
  const recordName = card.dataset.recordName || '';

  if (!objectName || !recordId) {
    setSingleRecordCardFeedback(feedback, "Missing record details for deletion.", "error");
    return;
  }

  const labelText = recordName ? ` "${recordName}"` : '';
  const confirmMessage = `Delete this ${objectName}${labelText}? This will also delete related records.`;
  if (!window.confirm(confirmMessage)) {
    return;
  }

  setSingleRecordCardFeedback(feedback, `Deleting ${objectName}...`, "info");
  button.disabled = true;

  try {
    const response = await fetch("/cpq/single-record/delete/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCSRFToken(),
      },
      body: JSON.stringify({
        object: objectName,
        record_id: recordId,
      }),
    });

    let data = {};
    try {
      data = await response.json();
    } catch (error) {
      data = {};
    }

    if (!response.ok) {
      throw new Error(data.error || "Unable to delete the record.");
    }

    const deletedCount = typeof data.deleted_count === "number" ? data.deleted_count : null;
    const relatedCount = deletedCount && deletedCount > 1 ? deletedCount - 1 : 0;
    const successMessage = relatedCount
      ? `Deleted ${objectName} and ${relatedCount} related record${relatedCount === 1 ? "" : "s"}.`
      : `Deleted ${objectName}.`;

    setSingleRecordCardFeedback(feedback, successMessage, "success");
    card.classList.add("single-record-card--deleted");
    card.querySelectorAll('input, select, textarea, button').forEach(el => {
      if (el !== button) {
        el.disabled = true;
      }
    });

    const sessionId = getCurrentSessionId();
    purgeSingleRecordChatLog({
      sessionId,
      objectName,
      recordId,
    });

    setTimeout(() => {
      card.classList.add("single-record-card--removing");
      setTimeout(() => {
        card.remove();
      }, 220);
    }, 900);
  } catch (error) {
    setSingleRecordCardFeedback(feedback, error.message || "Unable to delete the record.", "error");
    button.disabled = false;
  }
}

async function purgeSingleRecordChatLog({ sessionId, objectName, recordId }) {
  if (!sessionId || !objectName || !recordId) return;
  try {
    await fetch("/cpq/single-record/delete-log/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCSRFToken(),
      },
      body: JSON.stringify({
        session_id: sessionId,
        object: objectName,
        record_id: recordId,
      }),
    });
  } catch (error) {
    console.warn("Unable to purge single record chat log:", error);
  }
}

function buildRelatedRecordsUrl(config, relationId, options = {}) {
  const params = new URLSearchParams();
  params.set(config.relationKey, relationId);
  if (config.objectKey && options.objectName) {
    params.set(config.objectKey, options.objectName);
  }
  if (options.summaryOnly) {
    params.set("summary", "1");
  }
  if (options.preview) {
    params.set("preview", "1");
  }
  if (options.persistList) {
    params.set("persist_list", "1");
  }
  if (options.sessionId) {
    params.set("session_id", options.sessionId);
  }
  if (options.persist) {
    params.set("persist", "1");
  }
  if (options.limit) {
    params.set("limit", String(options.limit));
  }
  if (options.recordId) {
    params.set("record_id", String(options.recordId));
  }
  return `${config.endpoint}?${params.toString()}`;
}

async function loadRelatedRecordsCount(button, config, relationId, objectName) {
  const badge = button.querySelector('[data-role="related-count"]');
  if (!badge) return;

  button.classList.add("is-loading");
  badge.textContent = "...";

  try {
    const response = await fetch(buildRelatedRecordsUrl(config, relationId, {
      summaryOnly: true,
      objectName,
    }));
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    const count = Number(data.count || 0);
    button.dataset.relatedCount = String(count);
    badge.textContent = String(count);
    button.classList.toggle("is-empty", count === 0);
  } catch (error) {
    console.warn("Failed to fetch related count", error);
    badge.textContent = "0";
    button.dataset.relatedCount = "0";
  } finally {
    button.classList.remove("is-loading");
  }
}

function setupRelatedPopoverHandlers(button, card, config) {
  if (button.dataset.popoverBound === "true") return;
  button.dataset.popoverBound = "true";

  const popover = ensureRelatedPopover(button, config);
  if (!popover) return;

  let hideTimer = null;
  const showPopover = () => {
    const count = Number(button.dataset.relatedCount || 0);
    if (count <= 1 && config.objectName !== "activity") return;
    clearTimeout(hideTimer);
    loadRelatedPreview(button, card, config, popover);
  };
  const hidePopover = () => {
    clearTimeout(hideTimer);
    hideTimer = window.setTimeout(() => {
      popover.classList.remove("is-visible");
    }, 120);
  };

  button.addEventListener("mouseenter", showPopover);
  button.addEventListener("mouseleave", hidePopover);
  popover.addEventListener("mouseenter", () => clearTimeout(hideTimer));
  popover.addEventListener("mouseleave", hidePopover);
}

function ensureRelatedPopover(button, config) {
  const container = button.closest(".single-record-related-wrap") || button.parentElement;
  if (!container) return null;
  const role = button.dataset.role || "";
  let popover = container.querySelector(`.single-record-related-popover[data-role="${role}"]`);
  if (!popover) {
    popover = document.createElement("div");
    popover.className = "single-record-related-popover";
    popover.dataset.role = role;
    popover.setAttribute("role", "menu");
    container.appendChild(popover);
  }
  if (popover.dataset.bound !== "true") {
    popover.dataset.bound = "true";
    popover.addEventListener("click", (event) => {
      const item = event.target.closest("[data-record-id], [data-action]");
      if (!item) return;
      event.preventDefault();
      if (item.dataset.action === "dismiss") {
        popover.classList.remove("is-visible");
        return;
      }
      if (item.dataset.action === "create-activity") {
        const card = popover._card;
        const cfg = popover._config;
        const sourceButton = popover._sourceButton;
        if (card && cfg) {
          const parentName = card.dataset.recordName || cfg.parentLabel || "Record";
          openActivityCreateModal({
            parentObject: card.dataset.recordObject,
            parentRecordId: card.dataset.recordId,
            parentName,
            listBubble: null,
            config: cfg,
            relatedButton: sourceButton,
          });
        }
        popover.classList.remove("is-visible");
        return;
      }
      if (item.dataset.recordId) {
        handleRelatedRecordSelection(popover, item.dataset.recordId);
      }
    });
  }
  popover._config = config;
  popover._sourceButton = button;
  return popover;
}

async function loadRelatedPreview(button, card, config, popover) {
  const relationId = card.dataset.recordId;
  if (!relationId) return;
  const objectName = card.dataset.recordObject || "";

  popover._card = card;
  popover.dataset.relationId = String(relationId);

  if (popover.dataset.loadedFor === String(relationId)) {
    popover.classList.add("is-visible");
    return;
  }

  popover.dataset.loadedFor = String(relationId);
  popover.innerHTML = `<div class="single-record-related-loading">Loading...</div>`;
  popover.classList.add("is-visible");

  try {
    const response = await fetch(buildRelatedRecordsUrl(config, relationId, {
      preview: true,
      limit: 8,
      objectName,
    }));
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    const records = Array.isArray(data.records) ? data.records : [];
    if (!records.length) {
      const action = config.objectName === "activity"
        ? `<button type="button" class="single-record-related-item" data-action="create-activity">+ Add activity</button>`
        : "";
      popover.innerHTML = `
        <div class="single-record-related-empty">No ${config.pluralLabel} found.</div>
        ${action}
      `;
      return;
    }

    const listItems = records.map((record) => {
      const label = record.record_value ? escapeHtml(String(record.record_value)) : "Record";
      return `<button type="button" class="single-record-related-item" data-record-id="${record.record_id}">${label}</button>`;
    }).join("");
    const note = data.truncated && data.count
      ? `<div class="single-record-related-note">Showing ${records.length} of ${data.count}</div>`
      : "";
    popover.innerHTML = `${listItems}${note}`;
  } catch (error) {
    console.warn("Failed to load related preview", error);
    popover.innerHTML = `<div class="single-record-related-empty">Unable to load ${config.pluralLabel}.</div>`;
  }
}

function handleRelatedRecordSelection(popover, recordId) {
  const config = popover._config;
  const card = popover._card;
  const button = popover._sourceButton;
  if (!config || !card || !button) return;

  const existing = findSingleRecordCardById(recordId, config.objectName);
  if (existing) {
    existing.scrollIntoView({ behavior: "smooth", block: "start" });
    popover.classList.remove("is-visible");
    return;
  }

  const chatMessage = card.closest(".chat-message");
  if (!chatMessage || !chatMessage.parentNode) return;

  const sessionId = getCurrentSessionId();
  const parentName = card.dataset.recordName || config.parentLabel || "Record";
  const objectName = card.dataset.recordObject || "";
  fetchRelatedRecordCards({
    relationId: card.dataset.recordId,
    sessionId,
    anchorMessage: chatMessage,
    parentName,
    config,
    recordId,
    countHint: Number(button.dataset.relatedCount || 0),
    objectName,
  });
  popover.classList.remove("is-visible");
}

function handleRelatedRecordsClick(card, button, config) {
  const relationId = card.dataset.recordId;
  if (!relationId) return;
  const objectName = card.dataset.recordObject || "";

  if (config.listOnClick) {
    const chatMessage = card.closest(".chat-message");
    if (!chatMessage || !chatMessage.parentNode) return;
    const parentName = card.dataset.recordName || config.parentLabel || "Record";
    const role = button.dataset.role || "";
    showRelatedRecordsList({
      relationId,
      anchorMessage: chatMessage,
      parentName,
      config,
      role,
      objectName,
    });
    return;
  }

  const existingCards = findRelatedCards(config, relationId);
  const relatedCount = Number(button.dataset.relatedCount || 0);
  if (existingCards.length && relatedCount > 0 && existingCards.length >= relatedCount) {
    existingCards[0].scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  const chatMessage = card.closest(".chat-message");
  if (!chatMessage || !chatMessage.parentNode) return;

  const sessionId = getCurrentSessionId();
  const parentName = card.dataset.recordName || config.parentLabel || "Record";
  fetchRelatedRecordCards({
    relationId,
    sessionId,
    anchorMessage: chatMessage,
    parentName,
    config,
    countHint: Number(button.dataset.relatedCount || 0),
    objectName,
  });
}

function findRelatedCards(config, relationId) {
  if (!config.relatedAttr) return [];
  const cards = Array.from(
    document.querySelectorAll(`.single-record-card[${config.relatedAttr}="${relationId}"]`)
  );
  if (!config.objectName) return cards;
  return cards.filter(card => (card.dataset.recordObject || "").toLowerCase() === config.objectName);
}

function findSingleRecordCardById(recordId, objectName) {
  if (!recordId) return null;
  const selector = `.single-record-card[data-record-id="${recordId}"]`;
  const cards = Array.from(document.querySelectorAll(selector));
  if (!objectName) return cards[0] || null;
  return cards.find(card => (card.dataset.recordObject || "").toLowerCase() === objectName) || null;
}

function findRelatedListMessage(config, relationId, role) {
  if (!relationId || !config || !role) return null;
  const attr = config.relatedAttr || "";
  const selector = `.chat-message[data-related-list-role="${role}"]${attr ? `[${attr}="${relationId}"]` : ""}`;
  return document.querySelector(selector);
}

function findQuoteDetailsMessage(quoteId) {
  if (!quoteId) return null;
  return document.querySelector(`.chat-message[data-quote-id="${quoteId}"]`);
}

function buildQuoteListViewButton(recordId) {
  if (!recordId) return "";
  const icon = `
    <svg class="record-view-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M2.458 12C3.732 7.943 7.523 5 12 5c4.477 0 8.268 2.943 9.542 7-1.274 4.057-5.065 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
      <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  `;
  return `<button type="button" class="quote-list-view-btn" data-quote-id="${recordId}" aria-label="View quote details" title="View quote details">
    ${icon}
  </button>`;
}

function buildRecordListViewButton(recordId, objectName) {
  if (!recordId) return "";
  const objectLabel = objectName ? `View ${objectName}` : "View record";
  const objectValue = objectName || "";
  const icon = `
    <svg class="record-view-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M2.458 12C3.732 7.943 7.523 5 12 5c4.477 0 8.268 2.943 9.542 7-1.274 4.057-5.065 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
      <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  `;
  return `<button type="button" class="record-list-view-btn" data-record-id="${recordId}" data-object="${objectValue}" aria-label="${objectLabel}" title="${objectLabel}">
    ${icon}
  </button>`;
}

function initializeQuoteListViewButtons() {
  if (document.documentElement.dataset.quoteListViewBound === "true") return;
  document.documentElement.dataset.quoteListViewBound = "true";

  document.addEventListener("click", (event) => {
    const button = event.target.closest(".quote-list-view-btn");
    if (!button) return;
    event.preventDefault();

    const quoteId = button.dataset.quoteId;
    if (!quoteId) return;
    const anchorMessage = button.closest(".chat-message");
    if (!anchorMessage) return;
    fetchQuoteDetailsFromList(quoteId, anchorMessage, button);
  });
}

function initializeRecordListViewButtons() {
  if (document.documentElement.dataset.recordListViewBound === "true") return;
  document.documentElement.dataset.recordListViewBound = "true";

  document.addEventListener("click", (event) => {
    const button = event.target.closest(".record-list-view-btn");
    if (!button) return;
    event.preventDefault();

    const recordId = button.dataset.recordId;
    const objectName = button.dataset.object;
    if (!recordId || !objectName) return;
    const anchorMessage = button.closest(".chat-message");
    if (!anchorMessage) return;
    fetchRecordDetailsFromList(recordId, objectName, anchorMessage, button);
  });
}

function initializeQuoteDetailRecordLinks() {
  if (document.documentElement.dataset.quoteDetailLinksBound === "true") return;
  document.documentElement.dataset.quoteDetailLinksBound = "true";

  const activateCard = (card) => {
    if (!card) return;
    const recordId = card.dataset.recordId;
    const objectName = card.dataset.object;
    if (!recordId || !objectName) return;
    const anchorMessage = card.closest(".chat-message");
    if (!anchorMessage) return;
    fetchRecordDetailsFromList(recordId, objectName, anchorMessage, null);
  };

  document.addEventListener("click", (event) => {
    const card = event.target.closest(".quote-mobile-card--link, .quote-detail-link");
    if (!card) return;
    event.preventDefault();
    activateCard(card);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".quote-mobile-card--link, .quote-detail-link");
    if (!card) return;
    event.preventDefault();
    activateCard(card);
  });
}

function initializeLeadRecordCards() {
  if (document.documentElement.dataset.leadRecordCardsBound === "true") return;
  document.documentElement.dataset.leadRecordCardsBound = "true";

  const isMobileViewport = () => window.matchMedia("(max-width: 768px)").matches;

  const handleActivate = (target) => {
    if (!isMobileViewport()) return;
    const card = target.closest(".records-lead-card");
    if (!card) return;
    if (target.closest(".record-list-view-btn")) return;
    const recordId = card.dataset.recordId;
    const objectName = card.dataset.object;
    if (!recordId || !objectName) return;
    const anchorMessage = card.closest(".chat-message");
    if (!anchorMessage) return;
    fetchRecordDetailsFromList(recordId, objectName, anchorMessage, null);
  };

  document.addEventListener("click", (event) => {
    handleActivate(event.target);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".records-lead-card");
    if (!card) return;
    event.preventDefault();
    handleActivate(event.target);
  });
}

function initializeRecordCards() {
  if (document.documentElement.dataset.recordCardsBound === "true") return;
  document.documentElement.dataset.recordCardsBound = "true";

  const isMobileViewport = () => window.matchMedia("(max-width: 768px)").matches;

  const handleActivate = (target) => {
    if (!isMobileViewport()) return;
    const card = target.closest(".records-card");
    if (!card) return;
    if (target.closest(".record-list-view-btn")) return;
    const recordId = card.dataset.recordId;
    const objectName = card.dataset.object;
    if (!recordId || !objectName) return;
    const anchorMessage = card.closest(".chat-message");
    if (!anchorMessage) return;
    fetchRecordDetailsFromList(recordId, objectName, anchorMessage, null);
  };

  document.addEventListener("click", (event) => {
    handleActivate(event.target);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".records-card");
    if (!card) return;
    event.preventDefault();
    handleActivate(event.target);
  });
}

async function fetchQuoteDetailsFromList(quoteId, anchorMessage, button) {
  const existing = findQuoteDetailsMessage(quoteId);
  if (existing) {
    existing.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  if (button) {
    button.disabled = true;
    button.classList.add("is-loading");
  }

  try {
    const sessionId = getCurrentSessionId();
    const urlParams = new URLSearchParams({ quote_id: quoteId });
    if (sessionId) {
      urlParams.set("session_id", sessionId);
      urlParams.set("persist", "1");
    }
    const url = `/cpq/quote-details/?${urlParams.toString()}`;
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    const quoteDetails = data.quote_details;
    if (!quoteDetails || quoteDetails.error) {
      const msg = quoteDetails && quoteDetails.message ? quoteDetails.message : "Unable to load quote details.";
      if (typeof showQuoteToast === "function") {
        showQuoteToast(msg, "error");
      } else {
        console.warn(msg);
      }
      return;
    }

    ensureQuoteStatusValue(quoteDetails);
    const html = `
      <div class="senderagent">
        <img width="115px" src="/static/img/agentcpq-chat-icon.png" alt="AgentCPQ Logo">
      </div>
      <div class="message">${renderQuoteDetails(quoteDetails)}</div>
    `;
    const bubble = appendMessage("agent", html, { anchor: anchorMessage, skipScroll: true });
    if (bubble) {
      bubble.dataset.quoteId = String(quoteId);
      const container = bubble.querySelector(".quote-container, .quote-mobile");
      if (container) {
        container.dataset.quoteId = String(quoteId);
      }
      bubble.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (error) {
    console.warn("Failed to load quote details", error);
    if (typeof showQuoteToast === "function") {
      showQuoteToast("Unable to load quote details.", "error");
    }
  } finally {
    if (button) {
      button.disabled = false;
      button.classList.remove("is-loading");
    }
  }
}

async function fetchRecordDetailsFromList(recordId, objectName, anchorMessage, button) {
  const objectKey = String(objectName || "").toLowerCase();
  const existing = findSingleRecordCardById(recordId, objectKey);
  if (existing) {
    existing.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  if (button) {
    button.disabled = true;
    button.classList.add("is-loading");
  }

  try {
    const sessionId = getCurrentSessionId();
    const urlParams = new URLSearchParams({ object: objectName, record_id: recordId });
    if (sessionId) {
      urlParams.set("session_id", sessionId);
      urlParams.set("persist", "1");
    }
    const response = await fetch(`/cpq/single-record/?${urlParams.toString()}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    const payload = data.single_record;
    if (!payload || payload.error) {
      const msg = payload && payload.message ? payload.message : "Unable to load record.";
      if (typeof showSingleRecordToast === "function") {
        showSingleRecordToast(msg, "error");
      } else {
        console.warn(msg);
      }
      return;
    }

    const html = `
      <div class="senderagent">
        <img width="115px" src="/static/img/agentcpq-chat-icon.png" alt="AgentCPQ Logo">
      </div>
      <div class="message">${renderSingleRecord(payload)}</div>
    `;
    const bubble = appendMessage("agent", html, { anchor: anchorMessage, skipScroll: true });
    if (bubble) {
      bubble.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (error) {
    console.warn("Failed to load record details", error);
    if (typeof showSingleRecordToast === "function") {
      showSingleRecordToast("Unable to load record.", "error");
    }
  } finally {
    if (button) {
      button.disabled = false;
      button.classList.remove("is-loading");
    }
  }
}

function buildRelatedListLabel(labelPrefix, parentName, parentLabel) {
  const trimmedPrefix = (labelPrefix || "records").trim();
  const prefix = trimmedPrefix ? trimmedPrefix.charAt(0).toUpperCase() + trimmedPrefix.slice(1) : "Records";
  const nameText = (parentName || "").toString().trim();
  const labelText = (parentLabel || "").toString().trim();
  if (!labelText) {
    return `${prefix} for ${nameText || "Record"}`;
  }
  const lowerName = nameText.toLowerCase();
  const lowerLabel = labelText.toLowerCase();
  const fullName = nameText
    ? (lowerName.endsWith(lowerLabel) ? nameText : `${nameText} ${labelText}`)
    : labelText;
  return `${prefix} for ${fullName}`;
}

const ACTIVITY_TYPE_OPTIONS = [
  { value: "call", label: "Call" },
  { value: "email", label: "Email" },
  { value: "meeting", label: "Meeting" },
  { value: "task", label: "Task" },
];

const ACTIVITY_STATUS_OPTIONS = [
  { value: "not_started", label: "Not Started" },
  { value: "in_progress", label: "In Progress" },
  { value: "completed", label: "Completed" },
  { value: "deferred", label: "Deferred" },
];

function buildRelatedListPayload(records, parentName, config) {
  const labelPrefix = config.listObjectLabel || config.pluralLabel || "records";
  const listLabel = buildRelatedListLabel(labelPrefix, parentName, config.parentLabel);
  const mapped = records.map(record => {
    if (Array.isArray(config.listFields) && config.listFields.length) {
      const row = {};
      config.listFields.forEach(field => {
        if (field === "name") {
          row[field] = record[field] || record.record_value || "Record";
        } else if (field === "view_quote") {
          row[field] = buildQuoteListViewButton(record.record_id);
        } else if (field === "view_record") {
          row[field] = buildRecordListViewButton(
            record.record_id,
            config.viewObjectName || config.objectName
          );
        } else {
          const rawValue = record[field];
          row[field] = typeof rawValue === "boolean" ? (rawValue ? "Yes" : "No") : rawValue;
        }
      });
      return row;
    }
    return {
      Name: record.record_value || "Record",
      Id: record.record_id,
    };
  });
  return { payload: { [listLabel]: mapped }, listLabel };
}

function injectActivityCreateAction(bubble, { relationId, parentName, config, objectName }) {
  if (!bubble || !config || config.objectName !== "activity") return;
  const headerActions = bubble.querySelector(".records-header-actions");
  if (!headerActions) return;
  if (headerActions.querySelector(".records-activity-create-btn")) return;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "records-activity-create-btn";
  button.setAttribute("aria-label", "Create activity");
  button.setAttribute("title", "Create activity");
  button.innerHTML = `<span class="material-icons" aria-hidden="true">add_task</span>`;
  button.dataset.parentObject = String(objectName || "");
  button.dataset.parentRecordId = String(relationId || "");
  button.dataset.parentName = String(parentName || "");
  button.dataset.relatedRole = "related-activities";

  button.addEventListener("click", () => {
    openActivityCreateModal({
      parentObject: objectName,
      parentRecordId: relationId,
      parentName,
      listBubble: bubble,
      config,
    });
  });

  headerActions.insertBefore(button, headerActions.firstChild);
}

function ensureActivityCreateModal() {
  let overlay = document.querySelector(".activity-modal-overlay");
  if (overlay) return overlay;

  overlay = document.createElement("div");
  overlay.className = "activity-modal-overlay";
  overlay.innerHTML = `
    <div class="activity-modal" role="dialog" aria-modal="true" aria-labelledby="activity-modal-title">
      <div class="activity-modal-header">
        <div>
          <div class="activity-modal-title" id="activity-modal-title">New Activity</div>
          <div class="activity-modal-subtitle"></div>
        </div>
        <button type="button" class="activity-modal-close" aria-label="Close">
          <span class="material-icons" aria-hidden="true">close</span>
        </button>
      </div>
      <form class="activity-modal-body">
        <div class="activity-modal-grid">
          <div class="activity-modal-field single-record-field">
            <div class="single-record-field-label">Subject</div>
            <div class="single-record-field-control">
              <input type="text" name="subject" required placeholder="Follow-up call" class="single-record-input" />
            </div>
          </div>
          <div class="activity-modal-field single-record-field">
            <div class="single-record-field-label">Type</div>
            <div class="single-record-field-control">
              <select name="activity_type" class="single-record-input"></select>
            </div>
          </div>
          <div class="activity-modal-field single-record-field">
            <div class="single-record-field-label">Status</div>
            <div class="single-record-field-control">
              <select name="status" class="single-record-input"></select>
            </div>
          </div>
          <div class="activity-modal-field single-record-field">
            <div class="single-record-field-label">Due Date</div>
            <div class="single-record-field-control">
              <input type="date" name="due_date" class="single-record-input" />
            </div>
          </div>
          <div class="activity-modal-field activity-modal-notes single-record-field">
            <div class="single-record-field-label">Notes</div>
            <div class="single-record-field-control">
              <textarea name="notes" rows="3" placeholder="Add any details..." class="single-record-input"></textarea>
            </div>
          </div>
        </div>
        <div class="activity-modal-related"></div>
        <div class="activity-modal-actions">
          <button type="button" class="activity-modal-cancel">Cancel</button>
          <button type="submit" class="activity-modal-submit">Create activity</button>
        </div>
      </form>
    </div>
  `;
  document.body.appendChild(overlay);

  const closeModal = () => {
    overlay.classList.remove("is-visible");
    overlay.dataset.busy = "false";
  };
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) closeModal();
  });
  overlay.querySelector(".activity-modal-close").addEventListener("click", closeModal);
  overlay.querySelector(".activity-modal-cancel").addEventListener("click", closeModal);

  return overlay;
}

async function refreshRelatedActivitiesList({ bubble, relationId, parentName, config, objectName }) {
  if (!bubble) return;
  const message = bubble.querySelector(".message");
  if (!message) return;

  try {
    const response = await fetch(buildRelatedRecordsUrl(config, relationId, {
      preview: true,
      objectName,
    }));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const records = Array.isArray(data.records) ? data.records : [];
    if (!records.length) return;

    const { payload } = buildRelatedListPayload(records, parentName, config);
    message.innerHTML = renderRetrievedRecords("", payload);
    initializeRecordListLayouts(bubble);
    initializeMetricCards(bubble);
    injectActivityCreateAction(bubble, { relationId, parentName, config, objectName });
  } catch (error) {
    console.warn("Failed to refresh related activities list", error);
  }
}

function openActivityCreateModal({ parentObject, parentRecordId, parentName, listBubble, config, relatedButton }) {
  const overlay = ensureActivityCreateModal();
  const modal = overlay.querySelector(".activity-modal");
  const form = overlay.querySelector(".activity-modal-body");
  const relatedContainer = overlay.querySelector(".activity-modal-related");
  const subtitle = overlay.querySelector(".activity-modal-subtitle");
  const submitBtn = overlay.querySelector(".activity-modal-submit");
  const typeSelect = overlay.querySelector("select[name=\"activity_type\"]");
  const statusSelect = overlay.querySelector("select[name=\"status\"]");

  const safeParent = (parentName || parentObject || "record").toString().trim();
  subtitle.textContent = safeParent ? `For ${safeParent}` : "";

  typeSelect.innerHTML = ACTIVITY_TYPE_OPTIONS.map((opt) => `<option value="${opt.value}">${opt.label}</option>`).join("");
  statusSelect.innerHTML = ACTIVITY_STATUS_OPTIONS.map((opt) => `<option value="${opt.value}">${opt.label}</option>`).join("");

  const normalizedObject = String(parentObject || "").toLowerCase();
  const directRelation = ["lead", "contact", "opportunity", "account"].includes(normalizedObject);
  const autoRelation = normalizedObject.includes("payment");
  const requiresRelationSelection = !directRelation && !autoRelation;
  const isAccount = normalizedObject === "account";
  const isQuote = normalizedObject === "quote";
  const isCustomObject = normalizedObject.endsWith("__c");
  
  if (requiresRelationSelection) {
    // Smart defaults based on object type
    let defaultRelationType = "contact";
    let relatedNote = "Select the record this activity should relate to.";
    
    if (isAccount) {
      defaultRelationType = "contact";
      relatedNote = `Select a contact or opportunity from ${safeParent} to link this activity.`;
    } else if (isQuote) {
      defaultRelationType = "opportunity";
      relatedNote = `Select the opportunity or contact to link this activity from ${safeParent}.`;
    } else if (isCustomObject) {
      defaultRelationType = "contact";
      relatedNote = `Select a Lead, Contact, or Opportunity to link this activity from ${safeParent}.`;
    }
    
    // Pre-fill with account name/ID immediately for accounts (before async lookup)
    const initialRelationValue = (isAccount && parentRecordId) ? (parentName || parentRecordId) : "";
    
    relatedContainer.innerHTML = `
      <div class="activity-modal-related-note">${relatedNote}</div>
      <div class="activity-modal-grid">
        <div class="activity-modal-field single-record-field">
          <div class="single-record-field-label">Related type</div>
          <div class="single-record-field-control">
            <select name="relation_object" class="single-record-input">
              <option value="lead" ${defaultRelationType === "lead" ? "selected" : ""}>Lead</option>
              <option value="contact" ${defaultRelationType === "contact" ? "selected" : ""}>Contact</option>
              <option value="opportunity" ${defaultRelationType === "opportunity" ? "selected" : ""}>Opportunity</option>
            </select>
          </div>
        </div>
        <div class="activity-modal-field single-record-field">
          <div class="single-record-field-label">Record name or ID</div>
          <div class="single-record-field-control">
            <input type="text" name="relation_identifier" value="${initialRelationValue}" placeholder="Search by name or id" class="single-record-input" />
          </div>
        </div>
      </div>
    `;
    
    // Pre-populate related records for all standard objects
    if (parentRecordId && requiresRelationSelection) {
      (async () => {
        try {
          let relationType = null;
          let relationValue = null;
          
          // For Quote: Use the quote's opportunity (direct relationship)
          if (isQuote) {
            const quoteResponse = await fetch(`/cpq/single-record/?object=quote&record_id=${parentRecordId}`, {
              headers: { "X-CSRFToken": getCSRFToken() },
            });
            if (quoteResponse.ok) {
              const quoteData = await quoteResponse.json();
              // Check for related opportunity ID in the record data
              const relatedOppId = quoteData.related_opportunity_id || 
                                   quoteData.meta?.related_opportunity_id ||
                                   quoteData.fields?.find(f => f.name === "opportunity")?.value;
              
              if (relatedOppId) {
                // Get opportunity name
                const oppResponse = await fetch(`/cpq/single-record/?object=opportunity&record_id=${relatedOppId}`, {
                  headers: { "X-CSRFToken": getCSRFToken() },
                });
                if (oppResponse.ok) {
                  const oppData = await oppResponse.json();
                  const oppName = oppData.record_value || oppData.fields?.find(f => f.name === "name")?.value || "";
                  const oppId = oppData.oppid || oppData.record_id || relatedOppId;
                  if (oppId || oppName) {
                    relationType = "opportunity";
                    relationValue = oppId || oppName;
                  }
                }
              }
              
              // Fallback: Try account's opportunities if no direct opportunity
              if (!relationValue) {
                const relatedAccountId = quoteData.related_account_id || 
                                         quoteData.meta?.related_account_id ||
                                         quoteData.fields?.find(f => f.name === "account")?.value;
                if (relatedAccountId) {
                  const oppsResponse = await fetch(`/cpq/related-opportunities/?account_id=${relatedAccountId}&limit=1&preview=1`, {
                    headers: { "X-CSRFToken": getCSRFToken() },
                  });
                  if (oppsResponse.ok) {
                    const oppsData = await oppsResponse.json();
                    if (oppsData.records && oppsData.records.length > 0) {
                      const opp = oppsData.records[0];
                      const oppName = opp.record_value || (opp.fields || []).find(f => f.name === "name")?.value || "";
                      const oppId = opp.oppid || opp.record_id || "";
                      if (oppId || oppName) {
                        relationType = "opportunity";
                        relationValue = oppId || oppName;
                      }
                    }
                  }
                }
              }
            }
          }
          // For Account: Try opportunities first, then fall back to account name
          else if (isAccount) {
            // First try to get opportunities from the account
            const oppsResponse = await fetch(`/cpq/related-opportunities/?account_id=${parentRecordId}&limit=1&preview=1`, {
              headers: { "X-CSRFToken": getCSRFToken() },
            });
            if (oppsResponse.ok) {
              const oppsData = await oppsResponse.json();
              if (oppsData.records && oppsData.records.length > 0) {
                const opp = oppsData.records[0];
                const oppName = opp.record_value || (opp.fields || []).find(f => f.name === "name")?.value || "";
                const oppId = opp.oppid || opp.record_id || "";
                if (oppId || oppName) {
                  relationType = "opportunity";
                  relationValue = oppId || oppName;
                }
              }
            }
            
            // If no opportunity, pre-fill with account name (default to contact, user can change type)
            // This helps users see the account name pre-filled
            if (!relationValue) {
              const accountResponse = await fetch(`/cpq/single-record/?object=account&record_id=${parentRecordId}`, {
                headers: { "X-CSRFToken": getCSRFToken() },
              });
              if (accountResponse.ok) {
                const accountData = await accountResponse.json();
                const accountName = accountData.record_value || accountData.fields?.find(f => f.name === "name")?.value || parentName || "";
                const accountId = accountData.accid || accountData.record_id || parentRecordId || "";
                if (accountName || accountId) {
                  relationType = "contact"; // Default to contact for accounts
                  // Use account ID or name - user can manually find contact if needed
                  // But at least the field is pre-filled so they know which account
                  relationValue = accountId || accountName;
                }
              } else {
                // Fallback: use parentName or account ID if API fails
                relationType = "contact";
                relationValue = parentName || parentRecordId;
              }
            }
          }
          // For Custom Objects: Try to get related records from lookup fields via single-record API
          else if (isCustomObject) {
            const recordResponse = await fetch(`/cpq/single-record/?object=${parentObject}&record_id=${parentRecordId}`, {
              headers: { "X-CSRFToken": getCSRFToken() },
            });
            if (recordResponse.ok) {
              const recordData = await recordResponse.json();
              // Check for related IDs in metadata or fields
              const relatedOppId = recordData.related_opportunity_id || recordData.meta?.related_opportunity_id;
              const relatedAccountId = recordData.related_account_id || recordData.meta?.related_account_id;
              const relatedContactId = recordData.related_contact_id || recordData.meta?.related_contact_id;
              
              // Priority: Opportunity > Contact > Account's contacts/opportunities
              if (relatedOppId) {
                const oppResponse = await fetch(`/cpq/single-record/?object=opportunity&record_id=${relatedOppId}`, {
                  headers: { "X-CSRFToken": getCSRFToken() },
                });
                if (oppResponse.ok) {
                  const oppData = await oppResponse.json();
                  const oppName = oppData.record_value || oppData.fields?.find(f => f.name === "name")?.value || "";
                  const oppId = oppData.oppid || oppData.record_id || relatedOppId;
                  if (oppId || oppName) {
                    relationType = "opportunity";
                    relationValue = oppId || oppName;
                  }
                }
              } else if (relatedContactId) {
                const contactResponse = await fetch(`/cpq/single-record/?object=contact&record_id=${relatedContactId}`, {
                  headers: { "X-CSRFToken": getCSRFToken() },
                });
                if (contactResponse.ok) {
                  const contactData = await contactResponse.json();
                  const contactName = contactData.record_value || contactData.fields?.find(f => f.name === "first_name" || f.name === "last_name")?.value || "";
                  const contactId = contactData.contactId || contactData.record_id || relatedContactId;
                  if (contactId || contactName) {
                    relationType = "contact";
                    relationValue = contactId || contactName;
                  }
                }
              } else if (relatedAccountId) {
                // Try account's opportunities
                const oppsResponse = await fetch(`/cpq/related-opportunities/?account_id=${relatedAccountId}&limit=1&preview=1`, {
                  headers: { "X-CSRFToken": getCSRFToken() },
                });
                if (oppsResponse.ok) {
                  const oppsData = await oppsResponse.json();
                  if (oppsData.records && oppsData.records.length > 0) {
                    const opp = oppsData.records[0];
                    const oppName = opp.record_value || (opp.fields || []).find(f => f.name === "name")?.value || "";
                    const oppId = opp.oppid || opp.record_id || "";
                    if (oppId || oppName) {
                      relationType = "opportunity";
                      relationValue = oppId || oppName;
                    }
                  }
                }
              }
            }
          }
          
          // Apply pre-populated values if found
          if (relationType && relationValue) {
            const relationSelect = relatedContainer.querySelector('select[name="relation_object"]');
            const relationInput = relatedContainer.querySelector('input[name="relation_identifier"]');
            if (relationSelect && relationInput) {
              relationSelect.value = relationType;
              relationInput.value = relationValue;
            }
          }
        } catch (error) {
          // Silently fail - user can still manually select
          console.debug("Could not pre-populate activity relation:", error);
        }
      })();
    }
  } else if (autoRelation) {
    relatedContainer.innerHTML = `
      <div class="activity-modal-related-note">This activity will be linked to the account on this payment.</div>
    `;
  } else if (isAccount) {
    relatedContainer.innerHTML = `
      <div class="activity-modal-related-note">This activity will be linked to this account.</div>
    `;
  } else {
    relatedContainer.innerHTML = "";
  }

  form.reset();
  overlay.classList.add("is-visible");

  if (form._activityHandler) {
    form.removeEventListener("submit", form._activityHandler);
  }

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (overlay.dataset.busy === "true") return;

    const formData = new FormData(form);
    const subject = String(formData.get("subject") || "").trim();
    if (!subject) {
      showSingleRecordToast("Subject is required.", "error");
      return;
    }

    const payload = {
      subject,
      activity_type: formData.get("activity_type"),
      status: formData.get("status"),
      due_date: formData.get("due_date"),
      notes: formData.get("notes"),
      object: parentObject,
      record_id: parentRecordId,
    };

    if (requiresRelationSelection) {
      payload.relation_object = formData.get("relation_object");
      payload.relation_identifier = String(formData.get("relation_identifier") || "").trim();
      if (!payload.relation_identifier) {
        showSingleRecordToast("Add a related record name or id.", "error");
        return;
      }
    }

    overlay.dataset.busy = "true";
    submitBtn.disabled = true;
    submitBtn.textContent = "Creating...";

    try {
      const response = await fetch("/cpq/activities/create/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCSRFToken(),
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Unable to create activity.");
      }

      overlay.classList.remove("is-visible");
      showSingleRecordToast("Activity created.", "success");

      if (listBubble && config) {
        refreshRelatedActivitiesList({
          bubble: listBubble,
          relationId: parentRecordId,
          parentName,
          config,
          objectName: parentObject,
        });
      } else if (relatedButton && config) {
        loadRelatedRecordsCount(relatedButton, config, parentRecordId, parentObject);
      }
    } catch (error) {
      showSingleRecordToast(error.message || "Unable to create activity.", "error");
    } finally {
      overlay.dataset.busy = "false";
      submitBtn.disabled = false;
      submitBtn.textContent = "Create activity";
    }
  };

  form._activityHandler = handleSubmit;
  form.addEventListener("submit", handleSubmit);
}

async function showRelatedRecordsList({ relationId, anchorMessage, parentName, config, role, objectName }) {
  const existing = findRelatedListMessage(config, relationId, role);
  if (existing) {
    existing.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }

  const sessionId = getCurrentSessionId();
  const url = buildRelatedRecordsUrl(config, relationId, {
    preview: true,
    sessionId,
    persistList: Boolean(sessionId),
    objectName,
  });
  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    const records = Array.isArray(data.records) ? data.records : [];
    if (!records.length && config.objectName !== "activity") {
      showSingleRecordToast(`No ${config.pluralLabel} found for ${parentName}.`, "info");
      return;
    }

    const { payload } = buildRelatedListPayload(records, parentName, config);
    const html = `
      <div class="senderagent">
        <img width="115px" src="/static/img/agentcpq-chat-icon.png" alt="AgentCPQ Logo">
      </div>
      <div class="message">${renderRetrievedRecords("", payload)}</div>
    `;
    const bubble = appendMessage("agent", html, { anchor: anchorMessage, skipScroll: true });
    if (bubble) {
      bubble.dataset.relatedListRole = role;
      if (config.relatedAttr) {
        bubble.setAttribute(config.relatedAttr, String(relationId));
      }
      bubble.dataset.relatedParentObject = String(objectName || "");
      bubble.dataset.relatedParentId = String(relationId || "");
      bubble.dataset.relatedParentName = String(parentName || "");
      initializeRecordListLayouts(bubble);
      initializeMetricCards(bubble);
      injectActivityCreateAction(bubble, { relationId, parentName, config, objectName });
      bubble.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (error) {
    console.warn("Failed to load related records list", error);
    showSingleRecordToast(`Could not load ${config.pluralLabel}.`, "error");
  }
}

async function fetchRelatedRecordCards({ relationId, sessionId, anchorMessage, parentName, config, countHint, recordId, objectName }) {
  const limit = 6;
  const url = buildRelatedRecordsUrl(config, relationId, {
    sessionId,
    persist: Boolean(sessionId),
    limit,
    recordId,
    objectName,
  });

  try {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    const records = Array.isArray(data.records) ? data.records : [];
    if (!records.length) {
      showSingleRecordToast(`No ${config.pluralLabel} found for ${parentName}.`, "info");
      return;
    }
    insertRelatedRecordCards(records, anchorMessage, relationId, config);
    if (data.truncated && data.count) {
      showSingleRecordToast(`Showing ${records.length} of ${data.count} ${config.pluralLabel}.`, "info");
    }
  } catch (error) {
    console.warn("Failed to load related records", error);
    const fallbackCount = typeof countHint === "number" ? countHint : 0;
    const parentLabel = (config.parentLabel || "record").toLowerCase();
    const message = fallbackCount
      ? `Could not load ${config.pluralLabel}.`
      : `No ${config.pluralLabel} found for this ${parentLabel}.`;
    showSingleRecordToast(message, fallbackCount ? "error" : "info");
  }
}

function insertRelatedRecordCards(records, anchorMessage, relationId, config) {
  let insertAfter = anchorMessage;
  let lastInserted = null;

  records.forEach(record => {
    const existingCard = findSingleRecordCardById(record.record_id, config.objectName);
    if (existingCard) {
      if (!lastInserted) {
        lastInserted = existingCard.closest(".chat-message") || existingCard;
      }
      return;
    }
    const html = `
      <div class="senderagent">
        <img width="115px" src="/static/img/agentcpq-chat-icon.png" alt="AgentCPQ Logo">
      </div>
      <div class="message">${renderSingleRecord(record)}</div>
    `;
    const bubble = appendMessage("agent", html, { anchor: insertAfter, skipScroll: true });
    if (config.relatedAttr) {
      bubble.setAttribute(config.relatedAttr, String(relationId));
    }
    insertAfter = bubble;
    lastInserted = bubble;
  });

  if (lastInserted) {
    lastInserted.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function normalizeBundleFieldValue(field, value) {
  const trimmed = value === null || value === undefined ? "" : String(value).trim();
  if (["quantity", "min", "max"].includes(field)) {
    const num = Number(trimmed);
    return Number.isNaN(num) ? "" : num;
  }
  if (field === "required" || field === "default") {
    if (trimmed === "" || trimmed === "null") return "";
    return trimmed === true || trimmed === "true" || trimmed === "yes" || trimmed === "1";
  }
  return trimmed;
}

function formatBundleFieldDisplay(field, value) {
  if (value === "" || value === null || value === undefined) return "—";
  if (field === "required" || field === "default") {
    return value === true || value === "true" ? "Yes" : "No";
  }
  return String(value);
}

function renderBundleRowToView(row) {
  row.querySelectorAll("[data-field]").forEach((cell) => {
    const field = cell.dataset.field;
    const raw = cell.dataset.value;
    const val = normalizeBundleFieldValue(field, raw);
    cell.textContent = formatBundleFieldDisplay(field, val);
  });
}

function startBundleEdit(card) {
  if (card.dataset.editing === "true") return;
  card.dataset.editing = "true";

  const rows = card.querySelectorAll(".bundle-option-row");
  rows.forEach((row) => {
    row.querySelectorAll("[data-field]").forEach((cell) => {
      const field = cell.dataset.field;
      const raw = cell.dataset.value;
      const val = normalizeBundleFieldValue(field, raw);

      if (["quantity", "min", "max"].includes(field)) {
        cell.innerHTML = `<input type="number" class="bundle-edit-input" data-edit-field="${field}" value="${val !== "" ? val : ""}" min="0">`;
      } else if (field === "required" || field === "default") {
        const truthy = val === true;
        cell.innerHTML = `
          <select class="bundle-edit-input browser-default" data-edit-field="${field}" data-skipMaterialize="true">
            <option value="true" ${truthy ? "selected" : ""}>Yes</option>
            <option value="false" ${!truthy ? "selected" : ""}>No</option>
          </select>
        `;
      } else {
        cell.innerHTML = `<input type="text" class="bundle-edit-input" data-edit-field="${field}" value="${val !== "" ? escapeHtml(String(val)) : ""}">`;
      }
    });
  });

  let actions = card.querySelector(".bundle-edit-actions");
  if (!actions) {
    actions = document.createElement("div");
    actions.className = "bundle-edit-actions";
    actions.innerHTML = `
      <div class="bundle-edit-feedback single-record-feedback" data-role="bundle-feedback"></div>
      <div class="bundle-edit-buttons">
        <button type="button" class="bundle-edit-save">Save</button>
        <button type="button" class="bundle-edit-cancel bundle-edit-cancel-btn">Cancel</button>
      </div>
    `;
    const body = card.querySelector(".single-record-body");
    body.appendChild(actions);
  }

  actions.style.display = "flex";

  const saveBtn = actions.querySelector(".bundle-edit-save");
  const cancelBtn = actions.querySelector(".bundle-edit-cancel-btn");

  if (saveBtn) {
    saveBtn.onclick = () => saveBundleEdits(card);
  }
  if (cancelBtn) {
    cancelBtn.onclick = () => cancelBundleEdit(card);
  }
}

function cancelBundleEdit(card) {
  card.dataset.editing = "false";
  card.querySelectorAll(".bundle-option-row").forEach(renderBundleRowToView);
  const actions = card.querySelector(".bundle-edit-actions");
  if (actions) actions.style.display = "none";
}

function readBundleRowValues(row, fromInputs = false) {
  const values = {};
  row.querySelectorAll("[data-field]").forEach((cell) => {
    const field = cell.dataset.field;
    let raw = cell.dataset.value;
    if (fromInputs) {
      const input = cell.querySelector("[data-edit-field]");
      if (input) {
        raw = input.value;
      }
    }
    values[field] = normalizeBundleFieldValue(field, raw);
  });
  return values;
}

function buildBundleUpdatePayload(card) {
  const parentSku = card.dataset.bundleSku || null;
  const parentName = card.dataset.bundleName || null;

  const updates = [];

  card.querySelectorAll(".bundle-option-row").forEach((row) => {
    const original = readBundleRowValues(row, false);
    const current = readBundleRowValues(row, true);

    const changed = {};
    ["quantity", "required", "default", "min", "max", "group"].forEach((field) => {
      const origVal = original[field];
      const newVal = current[field];
      if (field === "group") {
        if ((origVal || "") !== (newVal || "")) {
          changed["group_name"] = newVal === "" ? null : newVal;
        }
      } else if (field === "required") {
        if (origVal !== newVal) changed["is_required"] = newVal;
      } else if (field === "default") {
        if (origVal !== newVal) changed["default_selected"] = newVal;
      } else if (field === "quantity" && origVal !== newVal && newVal !== "") {
        changed["quantity"] = Number(newVal);
      } else if (field === "min" && origVal !== newVal && newVal !== "") {
        changed["min_quantity"] = Number(newVal);
      } else if (field === "max" && origVal !== newVal && newVal !== "") {
        changed["max_quantity"] = Number(newVal);
      }
    });

    if (Object.keys(changed).length === 0) return;

    updates.push({
      product_option_sku: row.dataset.productSku || null,
      product_option_name: row.dataset.productName || null,
      ...changed,
    });
  });

  if (!updates.length) return null;

  return {
    updates: [
      {
        parent_product_sku: parentSku,
        parent_product_name: parentName,
        updates,
      },
    ],
    hiddenMessage: true,
  };
}

function setBundleFeedback(card, message, intent = "info") {
  const feedback = card.querySelector('[data-role="bundle-feedback"]');
  setSingleRecordCardFeedback(feedback, message, intent);
}

async function saveBundleEdits(card) {
  const payload = buildBundleUpdatePayload(card);
  if (!payload) {
    setBundleFeedback(card, "No changes to save.", "info");
    cancelBundleEdit(card);
    return;
  }

  setBundleFeedback(card, "Saving…", "info");

  try {
    const response = await fetch("/agents/chat/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: `Update Bundle Option: ${JSON.stringify(payload)}` }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    const result = data.response || {};
    const message = result.message || "Bundle options updated.";
    const isError = typeof message === "string" && message.includes("⚠️");

    // Persist new values locally
    card.querySelectorAll(".bundle-option-row").forEach((row) => {
      const current = readBundleRowValues(row, true);
      Object.entries(current).forEach(([field, val]) => {
        const cell = row.querySelector(`[data-field="${field}"]`);
        if (!cell) return;
        cell.dataset.value = String(val);
      });
      renderBundleRowToView(row);
    });

    card.dataset.editing = "false";
    const actions = card.querySelector(".bundle-edit-actions");
    if (actions) actions.style.display = "none";
    setBundleFeedback(card, message, isError ? "error" : "success");
  } catch (err) {
    console.error("Failed to save bundle updates", err);
    setBundleFeedback(card, "❌ Could not save bundle updates. Please try again.", "error");
  }
}

function initializeBundleStructureCards(root) {
  root.querySelectorAll(".bundle-structure-card").forEach((card) => {
    if (card.dataset.bundleInit === "true") return;
    card.dataset.bundleInit = "true";

    const editable = card.dataset.editable === "true";
    card.querySelectorAll(".bundle-option-row").forEach(renderBundleRowToView);

    if (!editable) return;

    const editBtn = card.querySelector("[data-role=\"bundle-edit-toggle\"]");
    if (editBtn) {
      editBtn.addEventListener("click", () => startBundleEdit(card));
    }
  });
}

function renderSingleRecordSection(title, fieldsHtml) {
  if (!fieldsHtml || (Array.isArray(fieldsHtml) && !fieldsHtml.filter(Boolean).length)) {
    return '';
  }
  const content = Array.isArray(fieldsHtml) ? fieldsHtml.join('') : fieldsHtml;
  return `
    <div class="single-record-section">
      <div class="single-record-section-title" style="display:none;">${escapeHtml(title)}</div>
      <div class="single-record-grid" data-section="${escapeHtml(title.toLowerCase())}">
        ${content}
      </div>
    </div>
  `;
}

function orderSingleRecordFields(fields, layout) {
  if (!Array.isArray(fields)) return [];
  const order = (layout && Array.isArray(layout.order) && layout.order.length)
    ? layout.order
    : fields.map(field => buildFieldKey(field.name, field.is_custom, field.field_id));
  const hidden = new Set((layout && Array.isArray(layout.hidden)) ? layout.hidden : []);

  const isNotesField = (field) => {
    if (!field) return false;
    const parts = [field.name, field.label].filter(Boolean).join(" ").toLowerCase();
    const normalized = parts.replace(/_/g, " ");
    return /(^|[^a-z])notes?([^a-z]|$)/.test(normalized);
  };

  const byKey = new Map(
    fields.map(field => [buildFieldKey(field.name, field.is_custom, field.field_id), field])
  );

  const ordered = [];
  order.forEach(key => {
    const found = byKey.get(key);
    if (!found) return;
    const forceVisible = isNotesField(found);
    ordered.push({ field: found, hidden: !forceVisible && hidden.has(key) });
    byKey.delete(key);
  });

  // Append any new fields not in the stored layout
  byKey.forEach((field, key) => {
    const forceVisible = isNotesField(field);
    ordered.push({ field, hidden: !forceVisible && hidden.has(key) });
  });

  return ordered;
}

var singleRecordLayoutCache = (typeof window !== "undefined" && window.singleRecordLayoutCache) ? window.singleRecordLayoutCache : {};
if (typeof window !== "undefined") {
  window.singleRecordLayoutCache = singleRecordLayoutCache;
}

async function fetchSingleRecordLayout(objectName) {
  if (!objectName) return { order: [], hidden: [] };
  if (singleRecordLayoutCache[objectName]) {
    return singleRecordLayoutCache[objectName];
  }

  try {
    const response = await fetch(`/agents/single-record-layout/?object=${encodeURIComponent(objectName)}`, {
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const layout = {
      order: Array.isArray(data.order) ? data.order : [],
      hidden: Array.isArray(data.hidden) ? data.hidden : [],
    };
    singleRecordLayoutCache[objectName] = layout;
    return layout;
  } catch (err) {
    console.warn("Unable to fetch single record layout", err);
    return { order: [], hidden: [] };
  }
}

async function persistSingleRecordLayout(objectName, layout) {
  if (!objectName) return layout;
  const payload = {
    object: objectName,
    order: Array.isArray(layout.order) ? layout.order : [],
    hidden: Array.isArray(layout.hidden) ? layout.hidden : [],
  };

  try {
    const response = await fetch("/agents/single-record-layout/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCSRFToken(),
      },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const saved = {
      order: Array.isArray(data.order) ? data.order : payload.order,
      hidden: Array.isArray(data.hidden) ? data.hidden : payload.hidden,
    };
    singleRecordLayoutCache[objectName] = saved;
    return saved;
  } catch (err) {
    console.warn("Unable to save single record layout", err);
    return payload;
  }
}

function parseSingleRecordLayout(raw) {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    return {
      order: Array.isArray(parsed.order) ? parsed.order : [],
      hidden: Array.isArray(parsed.hidden) ? parsed.hidden : [],
    };
  } catch (_err) {
    return null;
  }
}

function openSingleRecordCustomizer(button) {
  (async () => {
  const card = button.closest('.single-record-card');
  if (!card) return;

  const existing = document.querySelector('.single-record-customizer-panel');
  if (existing) {
    existing.remove();
  }

  const objectName = card.dataset.recordObject || 'default';
  const layout = parseSingleRecordLayout(card.dataset.layout) || await fetchSingleRecordLayout(objectName);
  card.dataset.layout = JSON.stringify(layout);
  const fieldsEls = Array.from(card.querySelectorAll('.single-record-field'));
  if (!fieldsEls.length) return;

  ensureSingleRecordCustomizerStyles();

  const fields = fieldsEls.map(el => ({
    key: el.dataset.fieldKey,
    label: el.querySelector('.single-record-field-label')?.textContent.trim() || el.dataset.field || el.dataset.fieldKey,
    hidden: Array.isArray(layout.hidden) && layout.hidden.includes(el.dataset.fieldKey)
  }));

  const panel = document.createElement('div');
  panel.className = 'single-record-customizer-panel';
  panel.innerHTML = `
    <div class="single-record-customizer-header">
      <strong>Customize fields</strong>
      <button type="button" class="single-record-customizer-close" aria-label="Close" onclick="this.closest('.single-record-customizer-panel').remove()">✕</button>
    </div>
    <div class="single-record-customizer-body"></div>
    <div class="single-record-customizer-footer">
      <button type="button" class="single-record-customizer-save">Save</button>
    </div>
  `;

  const list = document.createElement('ul');
  list.className = 'single-record-customizer-list';

  const buildRow = (field) => {
    const li = document.createElement('li');
    li.className = 'single-record-customizer-item';
    li.dataset.fieldKey = field.key;
    li.dataset.visible = field.hidden ? "false" : "true";
    li.innerHTML = `
      <label>
        <span>${escapeHtml(field.label)}</span>
      </label>
      <div class="single-record-customizer-actions">
        <button type="button" class="single-record-move-up" aria-label="Move up">↑</button>
        <button type="button" class="single-record-move-down" aria-label="Move down">↓</button>
        <button type="button" class="single-record-toggle ${field.hidden ? 'is-off' : 'is-on'}" aria-label="Toggle visibility">
          ${field.hidden ? 'Hidden' : 'Visible'}
        </button>
      </div>
    `;
    return li;
  };

  fields.forEach(field => list.appendChild(buildRow(field)));
  panel.querySelector('.single-record-customizer-body').appendChild(list);

  panel.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const item = target.closest('.single-record-customizer-item');
    if (!item) return;

    if (target.classList.contains('single-record-toggle')) {
      event.preventDefault();
      const isVisible = item.dataset.visible !== "false";
      const nextVisible = !isVisible;
      item.dataset.visible = nextVisible ? "true" : "false";
      target.classList.toggle('is-on', nextVisible);
      target.classList.toggle('is-off', !nextVisible);
      target.textContent = nextVisible ? 'Visible' : 'Hidden';
      return;
    }

    if (target.classList.contains('single-record-move-up')) {
      event.preventDefault();
      const prev = item.previousElementSibling;
      if (prev) {
        item.parentNode.insertBefore(item, prev);
      }
    }

    if (target.classList.contains('single-record-move-down')) {
      event.preventDefault();
      const next = item.nextElementSibling;
      if (next) {
        next.parentNode.insertBefore(item, next.nextElementSibling);
      }
    }

    if (target.classList.contains('single-record-customizer-save')) {
      event.preventDefault();
      handleSave();
    }
  });

  const handleSave = () => {
    const rows = Array.from(panel.querySelectorAll('.single-record-customizer-item'));
    const newOrder = [];
    const hidden = [];
    rows.forEach(row => {
      const key = row.dataset.fieldKey;
      const isChecked = row.dataset.visible !== "false";
      if (!key) return;
      if (isChecked) {
        newOrder.push(key);
      } else {
        hidden.push(key);
      }
    });

    persistSingleRecordLayout(objectName, { order: newOrder, hidden })
      .then(saved => {
        card.dataset.layout = JSON.stringify(saved);
        applySingleRecordLayoutToCard(card, saved);
      })
      .catch(() => applySingleRecordLayoutToCard(card, { order: newOrder, hidden }))
      .finally(() => panel.remove());
  };

  const saveBtn = panel.querySelector('.single-record-customizer-save');
  if (saveBtn) {
    saveBtn.addEventListener('click', (e) => {
      e.preventDefault();
      handleSave();
    });
  }

  document.body.appendChild(panel);

  // Position panel near the card and enable dragging
  const rect = card.getBoundingClientRect();
  panel.style.position = 'fixed';
  panel.style.top = `${Math.max(12, rect.top + 8)}px`;
  panel.style.left = `${Math.min(window.innerWidth - 460, rect.right + 12)}px`;
  attachDragToPanel(panel, panel.querySelector('.single-record-customizer-header'));
  })();
}

function ensureSingleRecordCustomizerStyles() {
  if (document.getElementById('single-record-customizer-styles')) return;
  const style = document.createElement('style');
  style.id = 'single-record-customizer-styles';
  style.textContent = `
    .single-record-layout-btn { background: linear-gradient(135deg, #ff9f1c, #ff7a1a); color: #fff; border: none; padding: 6px 12px; border-radius: 20px; font-weight: 600; box-shadow: 0 4px 10px rgba(255,122,26,0.35); cursor: pointer; transition: transform 120ms ease, box-shadow 120ms ease, background 120ms ease; }
    .single-record-layout-btn:hover { transform: translateY(-1px); box-shadow: 0 6px 14px rgba(255,122,26,0.45); }
    .single-record-layout-btn--icon { width: 34px; height: 34px; padding: 0; display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; }
    .single-record-layout-btn--icon:hover { background: linear-gradient(135deg, #ffad3f, #ff8b2f); }
    .single-record-customizer-panel { border: 1px solid #f1f1f1; box-shadow: 0 10px 28px rgba(0,0,0,0.14); border-radius: 12px; background: #fff; padding: 12px; max-width: 440px; position: fixed; z-index: 2147483000; resize: both; overflow: auto; min-width: 320px; min-height: 240px; max-height: 85vh; max-width: 90vw; box-sizing: border-box; }
    .single-record-customizer-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; cursor: move; }
    .single-record-customizer-body { max-height: none; overflow: visible; padding: 4px 0; }
    .single-record-customizer-list { list-style: none; padding: 0; margin: 0; }
    .single-record-customizer-item { display: flex; justify-content: space-between; align-items: center; padding: 10px 6px; border-bottom: 1px solid #f3f3f3; }
    .single-record-customizer-item:last-child { border-bottom: none; }
    .single-record-customizer-actions { display: inline-flex; gap: 6px; align-items: center; }
    .single-record-customizer-actions button { border: 1px solid #ddd; background: #fafafa; padding: 4px 8px; cursor: pointer; border-radius: 8px; color: #444; }
    .single-record-customizer-actions button:hover { background: #f2f2f2; }
    .single-record-toggle { border: 1px solid #ff7a1a; color: #666; background: #fff; border-radius: 999px; padding: 4px 10px; font-weight: 600; }
    .single-record-toggle.is-on { background: #fff; color: #666; }
    .single-record-toggle.is-off { background: #ffede0; color: #444; }
    .single-record-customizer-footer { display: flex; justify-content: flex-end; padding-top: 8px; }
    .single-record-customizer-save { border: none; border-radius: 10px; padding: 8px 16px; background: linear-gradient(135deg, #ff9f1c, #ff7a1a); color: #fff; font-weight: 700; cursor: pointer; box-shadow: 0 6px 16px rgba(255,122,26,0.35); }
    .single-record-customizer-save:hover { transform: translateY(-1px); box-shadow: 0 8px 20px rgba(255,122,26,0.45); }
  `;
  document.head.appendChild(style);
}

function applySingleRecordLayoutToCard(card, layout) {
  if (!card) return;
  const container = card.querySelector('.single-record-sections');
  if (!container) return;

  const fields = Array.from(card.querySelectorAll('.single-record-field'));
  const byKey = new Map(fields.map(el => [el.dataset.fieldKey, el]));
  const hidden = new Set(Array.isArray(layout.hidden) ? layout.hidden : []);
  const order = (layout && Array.isArray(layout.order) && layout.order.length)
    ? layout.order
    : fields.map(el => el.dataset.fieldKey);

  const standardEls = [];
  const customEls = [];

  const pushEl = (el) => {
    const isCustom = el.dataset.isCustom === 'true';
    const key = el.dataset.fieldKey;
    const shouldHide = hidden.has(key);
    el.style.display = shouldHide ? 'none' : '';
    el.hidden = shouldHide;
    if (shouldHide) {
      el.setAttribute('aria-hidden', 'true');
    } else {
      el.removeAttribute('aria-hidden');
    }
    if (isCustom) {
      customEls.push(el);
    } else {
      standardEls.push(el);
    }
  };

  order.forEach(key => {
    const el = byKey.get(key);
    if (!el) return;
    pushEl(el);
    byKey.delete(key);
  });

  byKey.forEach(el => pushEl(el));

  const buildSectionNode = (title, els) => {
    if (!els.length) return null;
    const section = document.createElement('div');
    section.className = 'single-record-section';
    const header = document.createElement('div');
    header.className = 'single-record-section-title';
    header.textContent = title;
    const grid = document.createElement('div');
    grid.className = 'single-record-grid';
    els.forEach(node => grid.appendChild(node));
    section.appendChild(header);
    section.appendChild(grid);
    return section;
  };

  container.innerHTML = '';
  const merged = buildSectionNode('Details', [...standardEls, ...customEls]);
  if (merged) container.appendChild(merged);

  initializeMaterializeSelects(container);
}

function safeApplySingleRecordLayout(card, layout) {
  try {
    applySingleRecordLayoutToCard(card, layout);
  } catch (err) {
    console.error("Failed to apply single record layout", err, layout);
    showSingleRecordToast("Couldn't apply layout. Please try again.", "error");
  }
}

function attachDragToPanel(panel, handle) {
  if (!panel || !handle) return;
  let isDragging = false;
  let startX = 0;
  let startY = 0;
  let startLeft = 0;
  let startTop = 0;

  const onMouseMove = (event) => {
    if (!isDragging) return;
    const dx = event.clientX - startX;
    const dy = event.clientY - startY;
    panel.style.left = `${Math.max(8, startLeft + dx)}px`;
    panel.style.top = `${Math.max(8, startTop + dy)}px`;
  };

  const onMouseUp = () => {
    isDragging = false;
    document.removeEventListener('mousemove', onMouseMove);
    document.removeEventListener('mouseup', onMouseUp);
  };

  handle.addEventListener('mousedown', (event) => {
    isDragging = true;
    startX = event.clientX;
    startY = event.clientY;
    startLeft = panel.offsetLeft;
    startTop = panel.offsetTop;
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  });
}

async function initializeSingleRecordCardLayout(card) {
  if (!card) return;
  const objectName = card.dataset.recordObject;
  const initialLayout = parseSingleRecordLayout(card.dataset.layout);
  if (initialLayout) {
    applySingleRecordLayoutToCard(card, initialLayout);
  }
  const serverLayout = await fetchSingleRecordLayout(objectName);
  if (serverLayout) {
    card.dataset.layout = JSON.stringify(serverLayout);
    applySingleRecordLayoutToCard(card, serverLayout);
  }
}

function renderSingleRecordField(record, field, isHidden) {
  const label = escapeHtml(field.label || field.name || 'Field');
  const customPill = '';
  const fieldKey = `${field.name || ''}::${field.is_custom ? 'custom' : 'standard'}${field.is_custom ? '::' + (field.field_id || '') : ''}`;
  const inputId = `single-record-input-${fieldKey}`;
  const isEditable = field.is_editable !== false;
  const originalValue = encodeSingleRecordOriginal(field.raw_value ?? null);

  const fieldClasses = [
    "single-record-field",
    field.is_multiline ? "single-record-field--wide" : "",
  ].filter(Boolean).join(" ");
  const containerAttrs = [
    `class="${fieldClasses}"`,
    `data-field="${escapeHtml(field.name)}"`,
    `data-type="${escapeHtml(field.data_type || 'text')}"`,
    `data-is-custom="${field.is_custom ? 'true' : 'false'}"`,
    field.field_id ? `data-field-id="${field.field_id}"` : '',
    `data-field-key="${fieldKey}"`,
    `data-original-value="${originalValue}"`
  ].filter(Boolean).join(' ');

  return `
    <div ${containerAttrs} ${isHidden ? 'style="display:none;"' : ''}>
      <div class="single-record-field-label-row">
        <label class="single-record-field-label" for="${inputId}">${label}</label>
        ${customPill}
      </div>
      <div class="single-record-field-control">
        ${isEditable
          ? buildSingleRecordInput(field, inputId)
          : `<div class="single-record-field-value">${formatSingleRecordValue(field.display_value ?? field.value)}</div>`}
      </div>
    </div>
  `;
}

function buildSingleRecordInput(field, inputId) {
  const dataType = (field.data_type || 'text').toLowerCase();
  const rawValue = field.raw_value;
  const valueForInput = prepareSingleRecordInputValue(rawValue, dataType);
  const isChoice = dataType === 'choice' || Array.isArray(field.options);
  const baseAttrs = [
    `id="${inputId}"`,
    `class="single-record-input"`,
    `data-input="true"`,
    `data-type="${dataType}"`,
    `data-field="${field.name}"`,
    `data-is-custom="${field.is_custom ? 'true' : 'false'}"`,
    field.field_id ? `data-field-id="${field.field_id}"` : '',
    `data-skip-materialize="true"`,
    `onchange="handleSingleRecordAutoSave(this)"`,
  ];

  if (dataType === 'boolean') {
    return `
      <select ${baseAttrs.join(' ')}>
        <option value="" ${valueForInput === '' ? 'selected' : ''}>Unset</option>
        <option value="true" ${valueForInput === 'true' ? 'selected' : ''}>Yes</option>
        <option value="false" ${valueForInput === 'false' ? 'selected' : ''}>No</option>
      </select>
    `;
  }

  if (dataType === 'date') {
    return `<input type="date" ${baseAttrs.join(' ')} value="${escapeHtml(valueForInput)}">`;
  }

  if (dataType === 'datetime') {
    return `<input type="datetime-local" ${baseAttrs.join(' ')} value="${escapeHtml(valueForInput)}">`;
  }

  if (dataType === 'number') {
    return `<input type="number" step="any" ${baseAttrs.join(' ')} value="${escapeHtml(valueForInput)}">`;
  }

  if (dataType === 'choice') {
    const options = buildSingleRecordChoiceOptions(field.options, valueForInput);
    return `
      <select ${baseAttrs.join(' ')}>
        <option value="" ${valueForInput === '' ? 'selected' : ''}>Select…</option>
        ${options}
      </select>
    `;
  }

  if (dataType === 'lookup') {
    const options = buildSingleRecordChoiceOptions(field.options, valueForInput);
    return `
      <select ${baseAttrs.join(' ')}>
        <option value="" ${valueForInput === '' ? 'selected' : ''}>Select…</option>
        ${options}
      </select>
    `;
  }

  if (field.is_multiline) {
    return `<textarea ${baseAttrs.join(' ')} rows="3">${escapeHtml(valueForInput)}</textarea>`;
  }

  return `<input type="text" ${baseAttrs.join(' ')} value="${escapeHtml(valueForInput)}">`;
}

function prepareSingleRecordInputValue(rawValue, dataType) {
  if (rawValue === null || rawValue === undefined) {
    return '';
  }

  if (dataType === 'lookup') {
    return String(rawValue);
  }

  if (dataType === 'boolean') {
    if (rawValue === true || rawValue === 'true') return 'true';
    if (rawValue === false || rawValue === 'false') return 'false';
    return '';
  }

  if (dataType === 'date') {
    const dateObj = new Date(rawValue);
    if (Number.isNaN(dateObj.getTime())) {
      return '';
    }
    return dateObj.toISOString().slice(0, 10);
  }

  if (dataType === 'datetime') {
    const dateObj = new Date(rawValue);
    if (Number.isNaN(dateObj.getTime())) {
      return '';
    }
    return dateObj.toISOString().slice(0, 16);
  }

  if (dataType === 'number') {
    return typeof rawValue === 'number' ? String(rawValue) : String(rawValue ?? '');
  }

  return String(rawValue);
}

function buildSingleRecordChoiceOptions(options, currentValue) {
  if (!options || !Array.isArray(options)) {
    return '';
  }

  return options
    .map(option => {
      if (option === null || option === undefined) {
        return '';
      }
      const optValue = typeof option === 'object' ? option.value : option;
      const optLabel = typeof option === 'object' ? option.label : option;
      const valueStr = optValue === null || optValue === undefined ? '' : String(optValue);
      const labelStr = optLabel === null || optLabel === undefined ? '' : String(optLabel);
      const selected = valueStr === currentValue ? 'selected' : '';
      return `<option value="${escapeHtml(valueStr)}" ${selected}>${escapeHtml(labelStr)}</option>`;
    })
    .join('');
}

function readSingleRecordInputValue(input, dataType) {
  if (dataType === 'boolean') {
    const value = input.value;
    if (value === '') return '';
    return value === 'true';
  }

  if (dataType === 'number') {
    if (input.value === '') return '';
    const parsed = Number(input.value);
    return Number.isNaN(parsed) ? input.value : parsed;
  }

  return input.value;
}

function decodeSingleRecordOriginal(encoded) {
  if (!encoded) return '';
  try {
    return JSON.parse(decodeURIComponent(encoded));
  } catch (error) {
    return '';
  }
}

function encodeSingleRecordOriginal(value) {
  return encodeURIComponent(JSON.stringify(value));
}

function setSingleRecordCardFeedback(element, message, intent) {
  if (!element) return;
  element.textContent = message || '';
  element.classList.remove('single-record-feedback--success', 'single-record-feedback--error', 'single-record-feedback--info');
  if (intent === 'success') {
    element.classList.add('single-record-feedback--success');
  } else if (intent === 'error') {
    element.classList.add('single-record-feedback--error');
  } else {
    element.classList.add('single-record-feedback--info');
  }
}

function normalizeSingleRecordValue(value, dataType) {
  if (value === null || value === undefined || value === '') {
    return '';
  }

  if (dataType === 'boolean') {
    if (value === true || value === 'true') return true;
    if (value === false || value === 'false') return false;
    return '';
  }

  if (dataType === 'number') {
    const num = Number(value);
    return Number.isNaN(num) ? String(value) : num;
  }

  if (dataType === 'date' || dataType === 'datetime') {
    const dateObj = new Date(value);
    if (Number.isNaN(dateObj.getTime())) {
      return '';
    }
    return dateObj.toISOString();
  }

  if (Array.isArray(value)) {
    return value.map(item => normalizeSingleRecordValue(item, 'text'));
  }

  return String(value);
}

function singleRecordValuesEqual(a, b) {
  if (Array.isArray(a) || Array.isArray(b)) {
    return JSON.stringify(a) === JSON.stringify(b);
  }
  return a === b;
}

async function handleSingleRecordAutoSave(input) {
  const card = input.closest('.single-record-card');
  if (!card) return;

  const fieldContainer = input.closest('.single-record-field');
  if (!fieldContainer) return;

  const feedback = card.querySelector('[data-role="card-feedback"]');
  const dataType = (input.dataset.type || fieldContainer.dataset.type || 'text').toLowerCase();
  const original = decodeSingleRecordOriginal(fieldContainer.dataset.originalValue);
  const value = readSingleRecordInputValue(input, dataType);

  const normalizedOriginal = normalizeSingleRecordValue(original, dataType);
  const normalizedCurrent = normalizeSingleRecordValue(value, dataType);

  if (singleRecordValuesEqual(normalizedOriginal, normalizedCurrent)) {
    setSingleRecordCardFeedback(feedback, '', 'info');
    return;
  }

  if (handleSingleRecordAutoSave.timer) {
    clearTimeout(handleSingleRecordAutoSave.timer);
  }

  handleSingleRecordAutoSave.timer = setTimeout(() => {
    executeSingleRecordAutoSave(card);
  }, 800);
}

async function executeSingleRecordAutoSave(card) {
  const feedback = card.querySelector('[data-role="card-feedback"]');
  const fields = Array.from(card.querySelectorAll('.single-record-field'));
  const updates = [];

  fields.forEach(field => {
    const input = field.querySelector('[data-input="true"]');
    if (!input) return;

    const dataType = (input.dataset.type || field.dataset.type || 'text').toLowerCase();
    const original = decodeSingleRecordOriginal(field.dataset.originalValue);
    const value = readSingleRecordInputValue(input, dataType);

    const normalizedOriginal = normalizeSingleRecordValue(original, dataType);
    const normalizedCurrent = normalizeSingleRecordValue(value, dataType);

    if (!singleRecordValuesEqual(normalizedOriginal, normalizedCurrent)) {
      updates.push({
        field: input.dataset.field,
        value,
        data_type: dataType,
        is_custom: input.dataset.isCustom === 'true',
        field_id: input.dataset.fieldId ? Number(input.dataset.fieldId) : null,
        input,
        fieldContainer: field,
        normalizedCurrent,
      });
    }
  });

  if (updates.length === 0) {
    setSingleRecordCardFeedback(feedback, '', 'info');
    return;
  }

  const payload = {
    object: card.dataset.recordObject,
    record_id: card.dataset.recordId,
    updates: updates.map(update => ({
      field: update.field,
      value: update.value,
      data_type: update.data_type,
      is_custom: update.is_custom,
      field_id: update.field_id,
    })),
    hiddenMessage: true,
  };

  if (!payload.object || !payload.record_id) {
    setSingleRecordCardFeedback(feedback, '⚠️ Missing record information for this update.', 'error');
    return;
  }

  setSingleRecordCardFeedback(feedback, 'Saving…', 'info');

  try {
    const sessionId = getCurrentSessionId();
    const response = await fetch("/agents/chat/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: `Update Record: ${JSON.stringify(payload)}`,
        session_id: sessionId,
      })
    });

    const data = await response.json();
    const result = (data.response && data.response.response) ? data.response.response : (data.response || {});

    const messageText = String(result.message || '')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<[^>]*>/g, '')
      .trim();
    const updatedFields = Array.isArray(result.updated_fields) ? result.updated_fields : [];
    const failedFields = Array.isArray(result.failed_fields) ? result.failed_fields : [];

    if (result.single_record) {
      updateSingleRecordCard(card, result.single_record);
    }

    if (failedFields.length > 0 || (updatedFields.length === 0 && messageText)) {
      const intent = updatedFields.length > 0 ? 'info' : 'error';
      setSingleRecordCardFeedback(feedback, messageText || '⚠️ Not saved.', intent);
      if (messageText) showSingleRecordToast(messageText, intent);
      return;
    }

    if (updatedFields.length > 0) {
      setSingleRecordCardFeedback(feedback, '✅ Saved', 'success');
      return;
    }

    setSingleRecordCardFeedback(feedback, messageText || '⚠️ Unable to update the record.', 'error');
  } catch (error) {
    console.error('Error updating record:', error);
    setSingleRecordCardFeedback(feedback, '❌ Something went wrong while saving. Please try again.', 'error');
  }
}

function updateSingleRecordCard(card, recordData) {
  if (!recordData) return;

  card.dataset.recordObject = recordData.object || '';
  card.dataset.recordId = recordData.record_id ?? '';
  card.dataset.recordName = recordData.record_value != null ? String(recordData.record_value) : '';
  const relatedAccountId = recordData.related_account_id || (recordData.meta && recordData.meta.related_account_id);
  if (relatedAccountId) {
    card.dataset.relatedAccountId = String(relatedAccountId);
  }
  const relatedOpportunityId = recordData.related_opportunity_id || (recordData.meta && recordData.meta.related_opportunity_id);
  if (relatedOpportunityId) {
    card.dataset.relatedOpportunityId = String(relatedOpportunityId);
  }

  const fieldsByKey = {};
  recordData.fields.forEach(field => {
    const key = buildFieldKey(field.name, field.is_custom, field.field_id);
    fieldsByKey[key] = field;
  });

  Object.entries(fieldsByKey).forEach(([key, fieldData]) => {
    const selector = `.single-record-field[data-field-key="${key}"]`;
    const fieldEl = card.querySelector(selector);
    if (!fieldEl) return;

    fieldEl.dataset.originalValue = encodeSingleRecordOriginal(fieldData.raw_value ?? null);

    const control = fieldEl.querySelector('.single-record-field-control');
    if (!control) return;

    if (fieldData.is_editable === false) {
      control.innerHTML = `<div class="single-record-field-value">${formatSingleRecordValue(fieldData.display_value ?? fieldData.value)}</div>`;
      return;
    }

    const input = control.querySelector('[data-input="true"]');
    if (input) {
      setSingleRecordInputValue(input, fieldData.data_type, fieldData.raw_value);
    }
  });

  initializeMaterializeSelects(card);
  mergeSingleRecordSections(card);
}

function buildFieldKey(name, isCustom, fieldId) {
  const base = `${name || ''}::${isCustom ? 'custom' : 'standard'}`;
  return isCustom ? `${base}::${fieldId || ''}` : base;
}

function setSingleRecordInputValue(input, dataType, rawValue) {
  const prepared = prepareSingleRecordInputValue(rawValue, dataType);

  if (dataType === 'boolean') {
    input.value = prepared;
    return;
  }

  if (dataType === 'choice') {
    input.value = prepared;
    return;
  }

  if (dataType === 'lookup') {
    input.value = prepared;
    return;
  }

  if (dataType === 'number') {
    input.value = prepared;
    return;
  }

  if (dataType === 'date' || dataType === 'datetime') {
    input.value = prepared;
    return;
  }

  input.value = prepared;
}

function showSingleRecordToast(message, intent) {
  if (window.M && M.toast) {
    const classes = intent === 'error' ? 'toast-error' : intent === 'info' ? 'toast-info' : 'toast-success';
    M.toast({ html: escapeHtml(message), classes });
  } else {
    console.log(`[single-record:${intent}] ${message}`);
  }
}

function showQuoteToast(message, intent = "success") {
  const tone = intent === "error" ? "error" : intent === "info" ? "info" : "success";
  let container = document.querySelector(".quote-toast-container");
  if (!container) {
    container = document.createElement("div");
    container.className = "quote-toast-container";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = `quote-toast quote-toast--${tone}`;
  toast.textContent = message;
  container.appendChild(toast);

  requestAnimationFrame(() => toast.classList.add("is-visible"));

  const remove = () => {
    toast.classList.remove("is-visible");
    setTimeout(() => toast.remove(), 180);
  };

  setTimeout(remove, tone === "error" ? 4500 : 2400);
}

function renderSingleRecordRelated(entry, index) {
  if (!entry || !Array.isArray(entry.records) || entry.records.length === 0) {
    return '';
  }

  const sectionTitle = escapeHtml(entry.label || 'Related Records');
  const rows = entry.records
    .map(item => {
      if (typeof item === 'string') {
        return `<li>${escapeHtml(item)}</li>`;
      }
      const pairs = Object.entries(item || {})
        .map(([key, value]) => `<div class="single-related-row"><strong>${escapeHtml(key)}:</strong> <span>${formatSingleRecordValue(value)}</span></div>`)
        .join('');
      return `<li class="single-related-item">${pairs}</li>`;
    })
    .join('');

  const sectionAttr = index !== undefined ? ` data-related-section="${index}"` : '';
  return `
    <div class="single-record-related"${sectionAttr}>
      <h5>${sectionTitle}</h5>
      <ul>${rows}</ul>
    </div>
  `;
}

function formatSingleRecordValue(value) {
  if (value === null || value === undefined || value === '') {
    return '<span class="single-record-missing">—</span>';
  }

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return '<span class="single-record-missing">—</span>';
    }
    const allPrimitive = value.every(item => item === null || item === undefined || ['string', 'number', 'boolean'].includes(typeof item));
    if (allPrimitive) {
      return value
        .map(item => item === null || item === undefined ? '—' : escapeHtml(String(item)))
        .join(', ');
    }

    return value
      .map(item => `<div class="single-record-nested-item">${formatSingleRecordValue(item)}</div>`)
      .join('');
  }

  if (typeof value === 'object') {
    const objectRows = Object.entries(value)
      .map(([key, val]) => `<div class="single-related-row"><strong>${escapeHtml(key)}:</strong> <span>${formatSingleRecordValue(val)}</span></div>`)
      .join('');
    return `<div class="single-record-nested">${objectRows}</div>`;
  }

  const safe = escapeHtml(String(value));
  return safe.replace(/\n/g, '<br>');
}

/*
*
*/
function renderQuoteNotes(quote, notes) {

  var html = `<div class="">
              <div class="quote-header">
                  <h3>${quote.quote_name} Notes:</h3>
              </div>`;

  html += `
          <div class="row">
            <div class="input-field">
              <textarea id="quote-notes" class="materialize-textarea"
                        oninput="autoResize(this); updateQuoteNotes(this)">
                ${notes || ''}
              </textarea>
              <label for="quote-notes" class="active">Quote Notes</label>
            </div>
          </div>
        </div>
          `;

  return html;
}


/**
* ✅ Render Approval History as an HTML table
*/
function renderApprovalHistory(approvalData) {
    if (!approvalData.history || approvalData.history.length === 0) {
        return `<p>ℹ️ No approvals found for this quote.</p>`;
    }

    // ✅ Ensure quote_name is available
    let quoteTitle = approvalData.quote_name ? `<h4>Approval History for Quote: <strong>${approvalData.quote_name}</strong></h4>` : `<h4>Approval History</h4>`;

    let table = `<table style="width:100%; border-collapse: collapse; margin-top: 10px;">
        <thead>
            <tr style="background-color: #f4f4f4;">
                <th style="border: 1px solid #ddd; padding: 8px;">Workflow</th>
                <th style="border: 1px solid #ddd; padding: 8px;">Step</th>
                <th style="border: 1px solid #ddd; padding: 8px;">Status</th>
                <th style="border: 1px solid #ddd; padding: 8px;">Approved By</th>
                <th style="border: 1px solid #ddd; padding: 8px;">Approved At</th>
            </tr>
        </thead>
        <tbody>`;

    approvalData.history.forEach(approval => {
        table += `<tr>
            <td style="border: 1px solid #ddd; padding: 8px;">${approval.workflow}</td>
            <td style="border: 1px solid #ddd; padding: 8px;">${approval.step}</td>
            <td style="border: 1px solid #ddd; padding: 8px;">${approval.status}</td>
            <td style="border: 1px solid #ddd; padding: 8px;">${approval.approved_by}</td>
            <td style="border: 1px solid #ddd; padding: 8px;">${approval.approved_at}</td>
        </tr>`;
    });

    table += `</tbody></table>`;

    // ✅ Wrap with quote name at the top
    return `<div>${quoteTitle}${table}</div>`;
}

/**
* ✅ Handle input changes in quote lines
*/
document.addEventListener("focusin", (event) => {
  if (event.target.classList.contains("quote-line-input")) {
      event.target.dataset.initialValue = event.target.value.trim();
  }
});

document.addEventListener("change", (event) => {
  if (event.target.classList.contains("quote-line-input")) {
      const initialValue = event.target.dataset.initialValue || "";
      const newValue = event.target.value.trim();

      if (newValue !== initialValue) {
          event.target.setAttribute("data-changed", "true");
      } else {
          event.target.removeAttribute("data-changed");
      }

      //console.log(`🔄 Field Changed: ${event.target.name}, New Value: ${newValue}, Initial Value: ${initialValue}`);
  }
});

/**
* ✅ Update quote line and reflect changes in UI
*/

/**
* ✅ First we save the input focus
*/

/**
* ✅ Update quote line function
*/
async function updateQuoteLine(input) {
    const quoteId = input.dataset.quote;
    const sku = input.dataset.sku;
    const field = input.dataset.field;
    let newValue = input.value.trim();
    //console.log("Entra a updateQuoteLine");

    if (["quantity", "discount_amount", "discount_percentage", "term"].includes(field)) {
      newValue = parseFloat(newValue);
    }
    const quoteLineId = input.dataset.quotelineId;

    if (newValue < 0){
      alert("⚠️ Invalid quantity or unit price.");
    }

    if (!quoteId || !sku || !field) {
        console.warn("⚠️ Missing data attributes.");
        return;
    }

    //console.log(`🔄 Field Changed: ${field}, SKU: ${sku}, New Value: ${newValue}, Quote: ${quoteId}, QuoteLine: ${quoteLineId}`);

    const updateData = {
        sku,
        field,
        value: newValue,
        quote_line_id: quoteLineId,
        quote: quoteId,
        hiddenMessage: true
    };
    const userMessage = `Update Quote Line: ${JSON.stringify(updateData)}`;
    const sessionId = getCurrentSessionId();

    try {
        const response = await fetch("/agents/chat/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: userMessage, session_id: sessionId })
        });

        const data = await response.json();
        const result = (data.response && data.response.response) ? data.response.response : (data.response || {});

        if (result && result.quote_details) {
            const updatedQuote = result.quote_details;
            let quoteContainer = input.closest(".quote-container");
            if (!quoteContainer) {
              quoteContainer = document.querySelector(`.quote-container[data-quote-name="${updatedQuote.quote_name}"]`) ||
                document.querySelector(`.quote-mobile[data-quote-name="${updatedQuote.quote_name}"]`);
            }
            if (quoteContainer) {
              replaceQuoteDetailsElement(quoteContainer, updatedQuote);
              flashQuoteTotals(quoteContainer);
              showQuoteToast("✅ Quote line updated.", "success");
              return; // replaced card; no need for inline updates
            }

            //First we update every single quote line total price
            const row =input.closest("tr");

            updatedQuote.line_items.forEach(item => {
                const totalCell = quoteContainer.querySelector(`.total-price[data-sku="${item.sku}"]`); //Use quoteContainer to update every total price
                //console.log("Total Cell: ", totalCell); #For debugging
                if (totalCell) {
                    //1. Get the total price from quote line
                    const total = parseFloat(item.total_price);

                    //2. Formatted
                    const formattedTotal = `$${total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

                    //3. Upgrade the DOM immediately
                    totalCell.textContent = formattedTotal;
                }

                const unitCell = quoteContainer.querySelector(`.unit-price[data-sku="${item.sku}"]`)
                if (unitCell) {
                    //1. Get the total price from quote line
                    const unit_price = parseFloat(item.unit_price);

                    //2. Formatted
                    const formattedUnitPrice = `$${unit_price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

                    //3. Upgrade the DOM immediately
                    unitCell.textContent = formattedUnitPrice;
                }

                if (field == "discount_percentage" || field == "discount_amount"){
                  //Update discount fields
                  const discountPercentage = row.querySelector(`input[name="discountPercentage"][data-sku="${item.sku}"]`)
                  const discountAmount = row.querySelector(`input[name="discountAmount"][data-sku="${item.sku}"]`);
                  if (discountPercentage) {
                    let discountPct = parseFloat(item.discount_percentage.replace("%", ""));
                    discountPercentage.value = Number.isInteger(discountPct)
                      ? discountPct
                      : discountPct.toFixed(2);
                  }

                  if (discountAmount) {
                    const cleanAmount = parseFloat(item.discount_amount.replace(/[$,]/g, ""));
                    discountAmount.value = cleanAmount.toFixed(2);
                  }
                }
            });


            // ✅ Update subtotal
            const subtotalElement = quoteContainer.querySelector(".subtotal-amount");

            if (subtotalElement) {
                const subtotal = parseFloat(updatedQuote.subtotal);
                const formattedSubtotal = `$${subtotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                subtotalElement.textContent = `Subtotal: ${formattedSubtotal}`;
            }

            // ✅ Update discount amount in quote
            const discountAmountContainer = quoteContainer.querySelector(".discount-amount .discount-values");
            if (discountAmountContainer) {
                const discountPct = parseFloat(updatedQuote.discount_percentage);
                const discountAmt = parseFloat(updatedQuote.discount_amount);
                const formattedDiscountAmt = discountAmt.toLocaleString(undefined, { style: 'currency', currency: 'USD' });
                discountAmountContainer.textContent = `${discountPct}% (-${formattedDiscountAmt})`;
            }

            // ✅ Update net amount
            const netAmountParagraph = quoteContainer.querySelector(".total-amount");
            if (netAmountParagraph) {
                const totalNetAmount = parseFloat(updatedQuote.net_amount);
                const formattedTotalNetAmount = `$${totalNetAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                netAmountParagraph.textContent = `Net Amount: ${formattedTotalNetAmount}`;
            }

            showQuoteToast("✅ Quote line updated.", "success");
        } else {
            // ⬅️ Restart original value of the input field
            if (result && Object.prototype.hasOwnProperty.call(result, "original_value")) {
              input.value = result.original_value;
            }
            if (result && result.message) {
              const msg = String(result.message).replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]*>/g, '').trim();
              showQuoteToast(msg || "⚠️ Unable to update quote line.", "error");
            }
        }
    } catch (error) {
        console.error("❌ Error updating quote line:", error);
        // ⬅️ Restart original value of the input field
        if (input.dataset && Object.prototype.hasOwnProperty.call(input.dataset, "initialValue")) {
          input.value = input.dataset.initialValue;
        }
        showQuoteToast("❌ Failed to update quote line.", "error");
    }
}

/**
* ✅ Update expiration date
*/
async function updateQuote(input) {
    let newValue = (typeof input.value === "string") ? input.value : (input.innerHTML ?? "");
    const field = input.dataset.field;
    const quote = input.dataset.quote;

    if (!quote) {
        console.warn("⚠️ Missing quote ID.");
        return;
    }
    // Allow clearing Notes; keep existing behavior for other fields.
    if (!newValue && field !== "notes") {
        console.warn("⚠️ Missing value.");
        return;
    }

    if (field === "discount_amount") {
        newValue = newValue.replace(/,/g, '');
    }

    //console.log(`🔄 Field Changed: ${field}, Quote: ${quote}, New Value: ${newValue}`);

    const updateData = {
        field: field,
        value: newValue,
        quote: quote,
        hiddenMessage: true
    };

    const userMessage = `Update Quote: ${JSON.stringify(updateData)}`;

    try {
        const sessionId = getCurrentSessionId();
        const response = await fetch("/agents/chat/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: userMessage, session_id: sessionId })
        });

        const data = await response.json();
        const result = (data.response && data.response.response) ? data.response.response : (data.response || {});

        if (result && result.success === true && result.quote_details) {
            input.blur();

            const updatedQuote = result.quote_details;

            let existingDetails = input.closest('[data-quote-name]');
            if (!existingDetails) {
                existingDetails = document.querySelector(`.quote-container[data-quote-name="${updatedQuote.quote_name}"]`) ||
                    document.querySelector(`.quote-mobile[data-quote-name="${updatedQuote.quote_name}"]`);
            }

            if (existingDetails) {
                const newEl = replaceQuoteDetailsElement(existingDetails, updatedQuote);
                flashQuoteTotals(newEl || existingDetails);
            }

            if (field === "notes") {
              showQuoteToast("✅ Notes saved", "success");
              return;
            }
            showQuoteToast("✅ Quote updated.", "success");
        } else {
            // ⬅️ Restart original value of the input field
            if (result && Object.prototype.hasOwnProperty.call(result, 'original_value')) {
                if (typeof input.value === "string") {
                  input.value = result.original_value;
                } else {
                  input.innerHTML = result.original_value;
                }
            }
            if (field === "notes") {
              const raw = (result && result.message ? result.message : '⚠️ Unable to update notes.');
              const msg = String(raw).replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]*>/g, '').trim();
              showQuoteToast(msg || "⚠️ Unable to update notes.", "error");
              return;
            }
            const raw = result && result.message ? result.message : '⚠️ Unable to update quote.';
            const msg = String(raw).replace(/<br\s*\/?>/gi, '\n').replace(/<[^>]*>/g, '').trim();
            showQuoteToast(msg || "⚠️ Unable to update quote.", "error");
        }
    } catch (error) {
        console.error("❌ Error updating quote:", error);
        // ⬅️ Restart original value of the input field
        if (Object.prototype.hasOwnProperty.call(input.dataset, 'initialValue')) {
            if (typeof input.value === "string") {
              input.value = input.dataset.initialValue;
            } else {
              input.innerHTML = input.dataset.initialValue;
            }
        }
        if (field === "notes") {
          showQuoteToast("❌ Error saving notes.", "error");
          return;
        }
        showQuoteToast("❌ Error occurred while updating quote.", "error");
    }
}

/**
* ✅ Format agent response messages with structured JSON or lists
*/
function formatAgentResponse(response) {
  let formattedResponse = document.createElement("div");
  formattedResponse.classList.add("agent-message");

  if (response.includes("```json")) {
      let jsonContent = response.replace("```json", "").replace("```", "").trim();
      formattedResponse.innerHTML = `<strong>Agent:</strong> 📄 Here's the structured data:<br><pre class="json-preview"><code>${jsonContent}</code></pre>`;
      return formattedResponse;
  }

  if (response.includes("1.") && response.includes("2.")) {
      let listItems = response.split("\n").map(item => item.match(/^\d+\.\s/) ? `<li>🔹 ${item}</li>` : `<li>${item}</li>`).join("");
      formattedResponse.innerHTML = `<strong>Agent:</strong> 📖 Here's a detailed explanation:<br><ul class="formatted-list">${listItems}</ul>`;
      return formattedResponse;
  }

  formattedResponse.innerHTML = `<p>${response}</p>`;
  return formattedResponse;
}


/**
 * ✅ Show temporary HTML message and remove it after 8 seconds
 */
function renderTemporaryMessage(className, htmlContent, iterations) {
    const chatBox = document.getElementById("chat-box");

    const tempMessage = document.createElement("div");
    tempMessage.classList.add("chat-message", className, "temporary-message");
    tempMessage.innerHTML = htmlContent;

    chatBox.appendChild(tempMessage);

    chatBox.scrollTop = chatBox.scrollHeight;

    let time_to_set = 5000;
    if (iterations) {
        time_to_set = iterations * 5000;
    }

    setTimeout(() => {
        tempMessage.remove();
    }, time_to_set);
}

/**
* ✅ Show Temporary Quote Details Message
*/
function showTemporaryQuoteDetails(quote) {
  ensureQuoteStatusValue(quote);
   if (window.innerWidth < 1200) {
    return renderQuoteDetailsMobile(quote);   // ← new helper (see below)
  }
  const createdAt = new Date(quote.created_at);
  const expirationDate = new Date(quote.expiration_date);

  const month = String(createdAt.getUTCMonth() + 1).padStart(2, '0');
  const day = String(createdAt.getUTCDate()).padStart(2, '0');
  const year = createdAt.getUTCFullYear();

  const formattedDate = `${month}/${day}/${year}`;

  const monthFormatted = String(expirationDate.getUTCMonth() + 1).padStart(2, '0');
  const dayFormatted = String(expirationDate.getUTCDate()).padStart(2, '0');
  const yearFormatted = expirationDate.getUTCFullYear();

  const formattedDate_e = `${monthFormatted}/${dayFormatted}/${yearFormatted}`;

  const { raw: statusValue, normalized: normalizedStatus } = prepareQuoteStatusFields(quote);
  const accountId = quote.account_id || quote.accountId;
  const opportunityId = quote.opportunity_id || quote.opportunityId;
  const accountText = quote.account ? escapeHtml(String(quote.account)) : "---";
  const opportunityText = quote.opportunity ? escapeHtml(String(quote.opportunity)) : "---";
  const accountValue = accountId
    ? `<button type="button" class="quote-detail-link quote-detail-value" data-record-id="${escapeHtml(String(accountId))}" data-object="Account" aria-label="View Account" title="View Account">${accountText}</button>`
    : `<span class="quote-detail-value">${accountText}</span>`;
  const opportunityValue = opportunityId
    ? `<button type="button" class="quote-detail-link quote-detail-value" data-record-id="${escapeHtml(String(opportunityId))}" data-object="Opportunity" aria-label="View Opportunity" title="View Opportunity">${opportunityText}</button>`
    : `<span class="quote-detail-value">${opportunityText}</span>`;
  const discountPercentDisplay = quote.discount_percentage !== null && quote.discount_percentage !== undefined
    ? escapeHtml(String(quote.discount_percentage))
    : "---";
  const discountAmountRaw = quote.discount_amount !== null && quote.discount_amount !== undefined
    ? quote.discount_amount
    : null;
  const discountAmountNumber = Number(discountAmountRaw);
  const discountAmountDisplay = Number.isFinite(discountAmountNumber)
    ? discountAmountNumber.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : (discountAmountRaw !== null ? escapeHtml(String(discountAmountRaw)) : "---");

  var html = `
              <div>
                ⏳ Rendering temporary quote details...
              </div>
              <div class="quote-container">
              <div class="quote-header">
                  <h3>Quote: ${quote.quote_name}</h3>
                  <div style="display: flex; align-items: center; gap: 8px;" class="status-select">
                    <span style="${statusBadgeStyle(statusValue)}">${statusValue || "—"}</span>
                  </div>
              </div>
              <div class="quote-details">
                <div class="quote-detail-item">
                  <div class="quote-detail-label-row">
                    <span class="material-icons quote-detail-icon" aria-hidden="true">apartment</span>
                    <span class="quote-detail-label">Account</span>
                  </div>
                  ${accountValue}
                </div>
                <div class="quote-detail-item">
                  <div class="quote-detail-label-row">
                    <span class="material-icons quote-detail-icon" aria-hidden="true">insights</span>
                    <span class="quote-detail-label">Opportunity</span>
                  </div>
                  ${opportunityValue}
                </div>
                <div class="quote-detail-item quote-detail-item--wide">
                  <div class="quote-detail-inline-row">
                    <div class="quote-detail-inline-item">
                      <div class="quote-detail-inline-label">Discount %</div>
                      <div class="quote-detail-inline-field">
                        <input type="text"
                          class="quote-detail-inline-input"
                          value="${discountPercentDisplay}"
                          readonly />
                      </div>
                    </div>
                    <div class="quote-detail-inline-item">
                      <div class="quote-detail-inline-label">Disc Amount</div>
                      <div class="quote-detail-inline-field">
                        <input type="text"
                          class="quote-detail-inline-input"
                          value="${discountAmountDisplay}"
                          readonly />
                      </div>
                    </div>
                    <div class="quote-detail-inline-item">
                      <div class="quote-detail-inline-label">Exp: Date</div>
                      <div class="quote-detail-date-field">
                        <span class="material-icons quote-detail-date-icon" aria-hidden="true">event</span>
                        <input type="text"
                          class="quote-detail-date-input"
                          value="${quote.expiration_date ? formattedDate_e : "---"}"
                          readonly />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <h4>Line Items</h4>`;

  var has_printed_subscription_header = false;


  quote.line_items.forEach(item => {
    if(item.is_subscription == true){
      if(!has_printed_subscription_header){
        const headers = [];

        quote.rendered_fields.forEach(field => {
          const cleaned = field.replace(/^Product\./, "");

          if (cleaned.toLowerCase() === "discount") {
            headers.push(`<th>Discount (%)</th>`);
            headers.push(`<th>Discount (USD)</th>`);
          }
          else if (cleaned === "Total Price") {
            headers.push(`<th>Subscription</th>`);
            headers.push(`<th>Term</th>`);
            headers.push(`<th>Total Price</th>`);
          }
          else {
            const label = cleaned
              .replace("Product And SKU", "Product")
              .replace("Unit Price", "Unit Price")
              .replace("Quantity", "Quantity")
              .replace(/_/g, " ")
              .replace(/\b\w/g, l => l.toUpperCase());

            headers.push(`<th>${label}</th>`);
          }
        });

        html += `
                <table class="quote-table" data-quote-id="${quote.quote_name}">
                  <thead>
                    <tr>
                      ${headers.join("\n")}
                    </tr>
                  </thead>
                  <tbody>`;

        has_printed_subscription_header = true;
      }

      html += `<tr${item.is_bundle_child ? ' class="bundle-child"' : ''}>`;

      quote.rendered_fields.forEach(field => {
        // Limpiar campos como Product.UOM
        const cleanedField = field.replace(/^Product\./, "");

        if (field === "Product And SKU") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.product}</div>
                  <div class="centered-td" style="color: #888; font-size: 0.65em">SKU: ${item.sku}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "Product") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.product}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "SKU") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.sku}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                <div>
              </div>
            </td>`;
        } else if (field === "Quantity") {
          html += `
            <td>
              <div class="centered-td">${item.quantity}</div>
            </td>`;
        } else if (field === "Unit Price") {
          html += `
            <td>
              ${parseFloat(item.unit_price.replace('$', '')).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })}
            </td>`;
        } else if (field === "Description") {
          html += `
            <td class="quote-description-cell">
              <p>${item.description}</p>
            </td>`;
        } else if (field === "Discount") {
          html += `
            <td class="centered-td">
              <div class="centered-td">${item.discount_percentage}</div>
            </td>`;
            html += `
            <td class="centered-td">
              <div class="centered-td">${item.discount_amount}</div>
            </td>`;
        } else if (field === "Total Price") {
          html += `
              <td class="centered-td">
                ${item.is_subscription ? '✅' : '❌'}
              </td>`;

          html += `
              <td class="centered-td">
                  <div class="centered-td">${item.term}</div>
              </td>`;

          html += `
            <td class="total-price" data-sku="${item.sku}">
              ${parseFloat(item.total_price.replace('$', '')).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })}
            </td>`;
        } else {
          // Custom Field: Just render the value
          html += `
            <td class="centered-td">${item[cleanedField] ?? "---"}</td>`;
        }
      });

      html += `</tr>`;
    }
  });

  html += `</tbody></table><br>`
  let none_suscription_bool = 0;

  quote.line_items.forEach(item => {
    if(item.is_subscription == false){
      if(none_suscription_bool == 0){
        const headers = [];

        quote.rendered_fields.forEach(field => {
          const cleaned = field.replace(/^Product\./, "");

          if (cleaned.toLowerCase() === "discount") {
            headers.push(`<th>Discount (%)</th>`);
            headers.push(`<th>Discount (USD)</th>`);
          } else {
            const label = cleaned
              .replace("Product And SKU", "Product")
              .replace("Unit Price", "Unit Price")
              .replace("discount_percentage", "Discount (%)")
              .replace("discount_amount", "Discount (USD)")
              .replace("total_price", "Total Price")
              .replace("subscription", "Subscription")
              .replace("term", "Term")
              .replace("Quantity", "Quantity")
              .replace(/_/g, " ")
              .replace(/\b\w/g, l => l.toUpperCase());

            headers.push(`<th>${label}</th>`);
          }
        });

        html += `
                <table class="quote-table" data-quote-id="${quote.quote_name}">
                  <thead>
                    <tr>
                      ${headers.join("\n")}
                    </tr>
                  </thead>
                  <tbody>`;
        none_suscription_bool = 1;
      }

      html += `<tr${item.is_bundle_child ? ' class="bundle-child"' : ''}>`;

      quote.rendered_fields.forEach(field => {
        // Limpiar campos como Product.UOM
        const cleanedField = field.replace(/^Product\./, "");

        if (field === "Product And SKU") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.product}</div>
                  <div class="centered-td" style="color: #888; font-size: 0.65em">SKU: ${item.sku}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "Product") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.product}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                </div>
              </div>
            </td>`;
        } else if (field === "SKU") {
          html += `
            <td>
              <div style="display: flex; justify-content: center; align-items: center;">
                ${item.is_bundle_component_required === true || item.is_bundle_component_required === "true" ? `
                  <div style="margin-right: 6px;">📌</div>
                ` : ''}
                <div>
                  <div class="centered-td">${item.sku}</div>
                  ${item.is_bundle_child ? `<div class="centered-td" style="color: #888; font-size: 0.65em">(Bundle - ${item.bundle_name})</div>` : ''}
                <div>
              </div>
            </td>`;
        } else if (field === "Quantity") {
          html += `
            <td>
              <div class="centered-td">${item.quantity}</div>
            </td>`;
        } else if (field === "Description") {
          html += `
            <td class="quote-description-cell">
              <p>${item.description}</p>
            </td>`;
        } else if (field === "Unit Price") {
          html += `
            <td>
              ${parseFloat(item.unit_price.replace('$', '')).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })}
            </td>`;
        } else if (field === "Discount") {
          html += `
            <td class="centered-td">
              <div class="centered-td">${item.discount_percentage}</div>
            </td>`;
            html += `
            <td class="centered-td">
              <div class="centered-td">${item.discount_amount}</div>
            </td>`;
        } else if (field === "Total Price") {
          html += `
            <td class="total-price" data-sku="${item.sku}">
              ${parseFloat(item.total_price.replace('$', '')).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })}
            </td>`;
        } else {
          // Custom Field: Just render the value
          html += `
            <td class="centered-td">${item[cleanedField] ?? "---"}</td>`;
        }
      });

      html += `</tr>`;
    }
  });

  html += `</tbody></table>
    <div class="total-container">
      <p class="subtotal-amount">
        Subtotal: ${parseFloat(quote.subtotal.replace('$', '')).toLocaleString('en-US', {
            style: 'currency',
            currency: 'USD'
        })}
      </p>`;

  if(quote.show_tax_information && (quote.show_quote_tax_percentage || quote.show_quote_tax_amount)){
    html += `
      <p class="subtotal-amount">
        Tax:
        ${
          quote.show_quote_tax_percentage && quote.show_quote_tax_amount
            ? `(${parseFloat(quote.tax_percentage)}%) `
            : quote.show_quote_tax_percentage
            ? `${parseFloat(quote.tax_percentage)}% `
            : ''
        }
        ${
          quote.show_quote_tax_amount
            ? parseFloat(quote.tax_amount).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
              })
            : ''
        }
      </p>
    `;
  }

  html += `    <p class="total-amount">
        Net Amount: ${parseFloat(quote.net_amount.replace('$', '')).toLocaleString('en-US', {
            style: 'currency',
            currency: 'USD'
        })}
      </p>
    </div>
  </div>`;

  return html;
}

function renderValidationRuleDetails(rules, read_only=false) {
  let html = "";
  //console.log(rules);

  rules.forEach((rule) => {
    if (rule.success){
      var head_text = `✅ New validation rule created successfully | ${rule.name} ✅`;
      html +=
        `<div class="rule-container">
          <div class="rule-header">
              <h5>${head_text}</h3>
              <span style="margin-left: 10px; font-weight: bold; color: ${rule.active ? 'green' : 'red'};">
                ${rule.active ? '🟢 Active' : '🔴 Inactive'}
              </span>
          </div>
          <div class="rule-details">
              <div class="name">
                <label for="rule-name"><strong>Description:</strong></label>
                <input id="rule-name" type="text" value="${rule.description}" readonly/>
              </div>

              <div class="rule_type">
                <label for="rule-type"><strong>Rule Type:</strong></label>
                <input id="rule-type" type="text" value="${rule.rule_type}" readonly/>
              </div>

              <div class="target_type">
                <label for="target-type"><strong>Target Type:</strong></label>
                <input id="target-type" type="text" value="${rule.target_type}" readonly/>
              </div>

              <div class="priority">
                <label for="priority"><strong>Priority:</strong></label>
                <input id="priority" type="number" value="${rule.priority}" readonly/>
              </div>

              <div class="error_message">
                <label for="error-message"><strong>Error Message:</strong></label>
                <textarea id="error-message" class="materialize-textarea" rows="3" readonly>${rule.error_message}</textarea>
              </div>
          </div>

          <div class="conditions-details">
            <p><h6>Conditions:</h6></p>
            <ul class="conditions-list">
              ${renderConditions(rule.conditions)}
            </ul>
          </div>
        </div>`;
    }
    else if (rule.error){
      html +=
        `<div class="rule-container">
          <div class="rule-header">
              <h5>⚠️ Error creating validation rule ⚠️</h3>
          </div>
          <div class="rule-error">
              <div class="name">
                <label for="rule-name"><strong>Name:</strong></label>
                <input id="rule-name" type="text" value="${rule.name}" readonly/>
              </div>

              <div class="error">
                <label for="rule-error"><strong>Error:</strong></label>
                <h6>${(rule.error).replace("⚠️", "").trim()}</h6>
              </div>
          </div>
        </div>`;
    }

  });

  return html;
}

function renderInclusionRuleDetails(message, rules, read_only=false) {
  let html = "";
  //console.log(rules);

  // Agregar mensaje si viene
  if (message) {
    const idx = message.indexOf("inclusion_rules_details:");
    if (idx !== -1) {
      message = message.slice(0, idx).trim(); // cortar antes del JSON
    }

    if (message) {
      html += `<p style="margin-bottom:10px;">${message}</p><br>`;
    }
  }

  rules.forEach((rule) => {
    var head_text = `✅ New inclusion rule created successfully | ${rule.name} ✅`;
    html +=
      `<div class="rule-container">
        <div class="rule-header">
            <h5>${head_text}</h3>
            <span style="margin-left: 10px; font-weight: bold; color: ${rule.active ? 'green' : 'red'};">
              ${rule.active ? '🟢 Active' : '🔴 Inactive'}
            </span>
        </div>
        <div class="rule-details">
            <div class="name">
              <label for="rule-name"><strong>Description:</strong></label>
              <input id="rule-name" type="text" value="${rule.description}" readonly/>
            </div>

            <div class="rule_type">
              <label for="rule-type"><strong>Rule Type:</strong></label>
              <input id="rule-type" type="text" value="${rule.rule_type}" readonly/>
            </div>

            <div class="target_type">
              <label for="target-type"><strong>Target Type:</strong></label>
              <input id="target-type" type="text" value="${rule.target_type}" readonly/>
            </div>

            <div class="priority">
              <label for="priority"><strong>Priority:</strong></label>
              <input id="priority" type="number" value="${rule.priority}" readonly/>
            </div>

            <div class="error_message">
              <label for="error-message"><strong>Message:</strong></label>
              <textarea id="error-message" class="materialize-textarea" rows="3" readonly>${rule.error_message}</textarea>
            </div>
        </div>

        <div class="conditions-details">
          <p><h6>Trigger Product:</h6></p>
          <ul class="conditions-list">
            <li>${rule.conditions.trigger_product.name} (${rule.conditions.trigger_product.sku})</li>
          </ul>
        </div>

        <div class="conditions-details">
          <p><h6>Included Products:</h6></p>
          <ul class="conditions-list">
            ${rule.conditions.included_products
              .map(prod => {
                const label = prod.name || prod.sku || "Unknown Product";
                return `<li>${prod.quantity}x ${label}</li>`;
              })
              .join("")}
          </ul>
        </div>

      </div>`;

  });

  return html;
}

function renderExclusionRuleDetails(message, rules, read_only=false) {
  let html = "";
  //console.log(rules);

  // Agregar mensaje si viene
  if (message) {
    const idx = message.indexOf("exclusion_rules_details:");
    if (idx !== -1) {
      message = message.slice(0, idx).trim(); // cortar antes del JSON
    }

    if (message) {
      html += `<p style="margin-bottom:10px;">${message}</p><br>`;
    }
  }

  rules.forEach((rule) => {
    var head_text = `✅ New exclusion rule created successfully | ${rule.name} ✅`;
    html +=
      `<div class="rule-container">
        <div class="rule-header">
            <h5>${head_text}</h3>
            <span style="margin-left: 10px; font-weight: bold; color: ${rule.active ? 'green' : 'red'};">
              ${rule.active ? '🟢 Active' : '🔴 Inactive'}
            </span>
        </div>
        <div class="rule-details">
            <div class="name">
              <label for="rule-name"><strong>Description:</strong></label>
              <input id="rule-name" type="text" value="${rule.description}" readonly/>
            </div>

            <div class="rule_type">
              <label for="rule-type"><strong>Rule Type:</strong></label>
              <input id="rule-type" type="text" value="${rule.rule_type}" readonly/>
            </div>

            <div class="target_type">
              <label for="target-type"><strong>Target Type:</strong></label>
              <input id="target-type" type="text" value="${rule.target_type}" readonly/>
            </div>

            <div class="priority">
              <label for="priority"><strong>Priority:</strong></label>
              <input id="priority" type="number" value="${rule.priority}" readonly/>
            </div>

            <div class="error_message">
              <label for="error-message"><strong>Error Message:</strong></label>
              <textarea id="error-message" class="materialize-textarea" rows="3" readonly>${rule.error_message}</textarea>
            </div>
        </div>

        <div class="conditions-details">
          <p><h6>Excluded Products:</h6></p>
          <ul class="conditions-list">
            ${rule.conditions.excluded_products
              .map(prod => `<li>${prod}</li>`)
              .join("")}
          </ul>
        </div>

      </div>`;

  });

  return html;
}

function renderActionTriggersDetails(message, action_triggers, read_only=false) {
  let html = "";

  if (message) {
    const idx = message.indexOf("action_triggers_details:");
    if (idx !== -1) {
      message = message.slice(0, idx).trim();
    }
    if (message) {
      html += `<p style="margin-bottom:10px;">${message}</p><br>`;
    }
  }

  action_triggers.forEach((trigger) => {
    html += `
      <div class="rule-container">
        <div class="rule-header">
            <h5>✅ New action trigger ${trigger.name} created ✅</h5>
            <span style="margin-left: 10px; font-weight: bold; color: ${trigger.active ? 'green' : 'red'};">
              ${trigger.active ? '🟢 Active' : '🔴 Inactive'}
            </span>
        </div>

        <div class="action-trigger-details">

          <!-- ✅ DESCRIPTION -->
          <div class="description">
            <label><strong>Description:</strong></label>
            <input type="text" value="${trigger.description}" readonly/>
          </div>

          <!-- ✅ EVENT TYPE -->
          <div class="event_type">
            <label><strong>Event Type:</strong></label>
            ${renderEventTypeReadable(trigger.event_type)}
          </div>

          <!-- ✅ CONDITIONS -->
          <div class="conditions-details">
            <label><strong>Conditions:</strong></label>
            ${renderConditionsReadable(trigger.conditions)}
          </div>

          <!-- ✅ ACTIONS -->
          <div class="actions">
            <label><strong>Actions:</strong></label>
            ${renderActionsReadable(trigger.actions)}
          </div>

        </div>
      </div>`;
  });

  setTimeout(() => setupCollapsibles(), 50);

  return html;
  
}

function prettyName(str) {
  if (!str) return "";

  let clean = str
    .replace(/__/g, " ")
    .replace(/_/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase());

  // ✅ Campos personalizados (__c)
  if (str.endsWith("__c")) {
    return `<span style="color:#7b1fa2; font-style:italic;">${clean}</span>`;
  }

  // ✅ Objetos custom (terminan en "__c" también)
  if (str.includes("__c")) {
    return `<span style="color:#9c27b0; font-style:italic;">${clean}</span>`;
  }

  return clean;
}

function renderEventTypeReadable(ev) {
  if (!ev) return "<em>No event type defined</em>";

  const obj = prettyName(ev.object_name);
  const action = ev.action === "create" ? "created"
               : ev.action === "update" ? "updated"
               : "deleted";

  return `

    <li style="margin-bottom:14px;">

        <div style="
          display:flex;
          justify-content:space-between;
          align-items:center;
          width:100%;
        ">
          
          <!-- ✅ MAIN READABLE CONDITION -->
          <div style="
            padding:6px 10px;
            background:#f0f0f0;
            border-radius:6px;
            display:inline-block;
            ">
            Runs when <b>${obj}</b> is <strong>${action}</strong>
          </div>
      </li>
  `;
}

function renderConditionsReadable(conditions) {
  if (!conditions || !conditions.items || conditions.items.length === 0)
    return "<em>No conditions</em>";

  const logic = conditions.logic || "AND";
  let html = "<ul>";

  conditions.items.forEach((cond, idx) => {

    const source = buildReadableObjectPath(cond.source);
    const target = buildReadableObjectPath(cond.target);
    const op = operatorColored(cond.operator);

    html += `
      <li style="margin-bottom:14px;">

        <div style="
          display:flex;
          align-items:center;
          width:100%;
        ">
          
          <!-- ✅ MAIN READABLE CONDITION -->
          <div style="
            padding:6px 10px;
            background:#f0f0f0;
            border-radius:6px;
            display:inline-block;
            ">
            <strong>If</strong> ${source} ${op} ${target}
          </div>

        </div>

        <!-- ✅ SHOW TECHNICAL RIGHT ALIGNED -->
          <a href="#"
            style="font-size:0.85rem; margin-top:6px; display:inline-block;"
            onclick="this.nextElementSibling.style.display=
              this.nextElementSibling.style.display==='none'?'block':'none'; return false;">
            (Show technical)
          </a>

          <!-- ✅ TECHNICAL -->
        <pre class="tech-box" style="display:none; margin-left:5px;">
${buildTechnicalCondition(cond)}
        </pre>

        

      </li>
    `;

    // ✅ Insert AND / OR between conditions
    if (idx < conditions.items.length - 1) {
      html += `
        <div style="
          margin: 8px 0 14px 55px;
          display: inline-block;
          background: #e0e0e0;
          padding: 4px 14px;
          border-radius: 10px;
          font-weight: 600;
          color: #444;
          font-size: 0.85rem;
          letter-spacing: 1px;
        ">
          ${logic}
        </div>
      `;
    }
  });

  html += "</ul>";
  return html;
}

function buildReadableObjectPath(ref) {
  if (!ref) return "";

  if (ref.type === "static") return `"${ref.value}"`;

  // ✅ FIELD
  if (ref.type === "field" && ref.object && ref.field_name) {
    const obj = prettyName(ref.object);
    const path = ref.field_name.split(".").map(p => prettyName(p)).join(" → ");
    return `${obj} → ${path}`;
  }

  // ✅ LEFT SIDE
  if (!ref.type && ref.object && ref.field_name) {
    const obj = prettyName(ref.object);
    const path = ref.field_name.split(".").map(p => prettyName(p)).join(" → ");
    return `${obj} → ${path}`;
  }

  return `<em style="color:#b00;">Unsupported ref</em>`;
}

function operatorLabel(op) {
  const ops = {
    "==": "equals",
    "=": "equals",
    "!=": "does not equal",
    ">": "is greater than",
    "<": "is less than",
    ">=": "is greater or equal to",
    "<=": "is less or equal to",
    "contains": "contains"
  };
  return ops[op] || op;
}

function buildTechnicalCondition(cond) {
  const source = cond.source?.object && cond.source?.field_name
    ? `${cond.source.object}.${cond.source.field_name}`
    : cond.source?.field_name || cond.source?.alias || "<?>";
  
  const target = cond.target?.object && cond.target?.field_name
    ? `${cond.target.object}.${cond.target.field_name}`
    : cond.target?.data !== undefined
      ? JSON.stringify(cond.target.data)
      : cond.target?.alias || "<?>";

  return `${source} ${cond.operator} ${target}`;
}

function renderActionsReadable(actions) {
  if (!actions || actions.length === 0) {
    return "<em>No actions defined</em>";
  }

  let html = `<ul style="padding-left:0;">`;

  actions.forEach(a => {

    const obj = prettyName(a.target.object);

    let pathLabel = "";
    if (a.target) {
      pathLabel =
        " → " +
        a.target
          .split(".")
          .map(p => prettyName(p))
          .join(" → ");
    }

    const opColor =
      a.operation === "CREATE" ? "#2e7d32" :
      a.operation === "UPDATE" ? "#ef6c00" :
      a.operation === "CLONE"  ? "#1565c0" :
      "#c62828";

    let actionLabel = `
      <div style="
        display:inline-block;
        padding:8px 14px;
        background:#f4f6f8;
        border-radius:10px;
        border:1px solid #ddd;
        margin-bottom:10px;
      ">
        <span style="color:${opColor}; font-weight:700; margin-right:6px;">
          ${a.operation}
        </span>
        <span style="color:#333;">
          ${obj}${pathLabel}
        </span>
      </div>
    `;

    // =========================
    // ✅ PREFILTER
    // =========================
    let preFilterHtml = "";

    if (a.filters?.items?.length && a.filters.source_object) {
      preFilterHtml += `
        <div style="
          margin-bottom:16px;
          padding:12px;
          background:#fafafa;
          border:1px dashed #ccc;
          border-radius:10px;
        ">
          <div style="font-weight:700; margin-bottom:6px;">
            🔍 Searching records in <span style="color:#1976d2;">${prettyName(a.filters.source_object)}</span>
          </div>
          <ul style="margin-top:6px; padding-left:18px;">
      `;

      a.filters.items.forEach(f => {
        const left = prettyName(f.field);
        const op = operatorColored(f.operator);

        let right = "";
        if (f.value.type === "field") {
          right = `${prettyName(f.value.object)} → ${prettyName(f.value.field_name)}`;
        } 
        else if (f.value.type === "expression") {
          right = `<code>${f.value.formula}</code>`;
        }
        else {
          right = JSON.stringify(f.value.value);
        }

        preFilterHtml += `<li>If ${left} ${op} ${right}</li>`;
      });

      preFilterHtml += `</ul></div>`;
    }

    // =========================
    // ✅ NORMAL FIELDS
    // =========================
    let fieldsHtml = "";

    if (a.operation != "CLONE" && a.value?.fields) {
      for (const [fieldName, fv] of Object.entries(a.value.fields)) {
        const fieldPretty = prettyName(fieldName);

        if (fv.type === "static") {
          fieldsHtml += `<li>${fieldPretty} <span class="badge-static">static</span> = "${fv.value}"</li>`;
        }
        else if (fv.type === "field") {
          const field_name = fv.field_name ? prettyName(fv.field_name) : "(self)";
          fieldsHtml += `<li>${fieldPretty} <span class="badge-field">field</span> = ${prettyName(fv.object)} → ${field_name}</li>`;
        }
        else if (fv.type === "expression") {
          fieldsHtml += `<li>${fieldPretty} <span class="badge-expression">expression</span> <span class="formula-box">${fv.formula}</span></li>`;
        }
        else if (fv.type === "date") {
          fieldsHtml += `<li>${fieldPretty} <span class="badge-date">date</span> <span class="formula-box">${fv.formula}</span></li>`;
        }
        else if (fv.type === "sequence") {
          fieldsHtml += `<li>${fieldPretty} <span class="badge-sequence">sequence</span> = ${fv.prefix || ""}${"0".repeat(fv.padding || 0)}</li>`;
        }

        // ✅ LOOKUP CON DETALLE DEL WHERE ✅✅✅
        else if (fv.type === "lookup") {
          const whereLines = (fv.where?.items || []).map(w => {
            const left = prettyName(w.field_name);
            const op = operatorColored(w.operator);

            let right = "";
            if (w.value?.type === "expression") {
              right = `<code>${w.value.formula}</code>`;
            } else if (w.value?.type === "field") {
              right = `${prettyName(w.value.object)} → ${prettyName(w.value.field_name)}`;
            } else {
              right = JSON.stringify(w.value?.data);
            }

            return `<div style="margin-left:16px; font-size:0.85rem; color:#444;">• ${left} ${op} ${right}</div>`;
          }).join("");

          fieldsHtml += `
            <li>${fieldPretty}
              <span class="badge-lookup">lookup</span>
              → ${prettyName(fv.model)}
              ${whereLines}
            </li>`;
        }
      }
    }

    // =========================
    // ✅ CLONE MODIFIED FIELDS
    // =========================
    let cloneFieldsHtml = "";

    if (a.operation === "CLONE" && a.value?.fields && Object.keys(a.value.fields).length) {
      cloneFieldsHtml += `
        <div style="
          margin-top:12px;
          padding:12px;
          background:#f8fbff;
          border:1px solid #d0e2ff;
          border-radius:10px;
        ">
          <div style="font-weight:700; margin-bottom:6px;">
            ✏️ Modified fields
          </div>
          <ul style="padding-left:18px;">
      `;

      for (const [fname, fv] of Object.entries(a.value.fields)) {
        const fieldPretty = prettyName(fname);

        if (fv.type === "lookup") {
          const whereLines = (fv.where?.items || []).map(w => {
            const left = prettyName(w.field_name);
            const op = operatorColored(w.operator);

            let right = "";
            if (w.value?.type === "expression") {
              right = `<code>${w.value.formula}</code>`;
            } else if (w.value?.type === "field") {
              right = `${prettyName(w.value.object)} → ${prettyName(w.value.field_name)}`;
            } else {
              right = JSON.stringify(w.value?.value);
            }

            return `<div style="margin-left:16px; font-size:0.85rem; color:#444;">• ${left} ${op} ${right}</div>`;
          }).join("");

          cloneFieldsHtml += `
            <li>${fieldPretty}
              <span class="badge-lookup">lookup</span>
              → ${prettyName(fv.model)}
              ${whereLines}
            </li>`;
        }

        else if (fv.type === "field") {
          cloneFieldsHtml += `<li>${fieldPretty} <span class="badge-field">field</span> = ${prettyName(fv.object)} → ${prettyName(fv.field_name)}</li>`;
        }
        else if (fv.type === "static") {
          cloneFieldsHtml += `<li>${fieldPretty} <span class="badge-static">static</span> = "${fv.value}"</li>`;
        }
        else if (fv.type === "expression") {
          cloneFieldsHtml += `<li>${fieldPretty} <span class="badge-expression">expression</span> <span class="formula-box">${fv.formula}</span></li>`;
        }
      }

      cloneFieldsHtml += `</ul></div>`;
    }

    const techDetails = JSON.stringify(a, null, 2);

    html += `
      <li style="
        list-style:none;
        margin-bottom:26px;
        padding-bottom:18px;
        border-bottom:1px solid #eee;
      ">
        ${preFilterHtml}
        ${actionLabel}

        ${fieldsHtml ? `<ul style="margin-left:12px; margin-top:10px;">${fieldsHtml}</ul>` : ""}

        ${cloneFieldsHtml}

        <a href="#"
           onclick="this.nextElementSibling.style.display=
             this.nextElementSibling.style.display==='none'?'block':'none'; return false;"
           style="font-size:0.85rem; margin-top:10px; display:block;">
           (Show technical)
        </a>

        <pre class="tech-box" style="display:none;">${techDetails}</pre>
      </li>
    `;
  });

  html += "</ul>";
  return html;
}



function renderActionFields(valueDef) {
  if (!valueDef || !valueDef.fields) return "";

  let html = "";
  for (const [fieldName, fieldValue] of Object.entries(valueDef.fields)) {
    let prettyField = prettyName(fieldName);

    if (fieldValue.type === "static") {
      html += `<li>${prettyField} = "${fieldValue.data}"</li>`;
    } 
    else if (fieldValue.type === "field") {
      html += `<li>${prettyField} = ${prettyName(fieldValue.object)} → ${prettyName(fieldValue.path)}</li>`;
    } 
    else {
      html += `<li>${prettyField} = <em>Unsupported type</em></li>`;
    }
  }
  return html;
}

function setupCollapsibles() {
  document.querySelectorAll(".toggle-arrow").forEach(arrow => {
    arrow.onclick = () => {
      const content = arrow.parentElement.nextElementSibling;
      const open = content.style.display === "block";

      content.style.display = open ? "none" : "block";
      arrow.classList.toggle("open", !open);
    };
  });
}

function renderDescriptionBlock(description) {
  return `
    <div class="action-block">
      <div class="action-block-title">
        <span class="toggle-arrow">►</span> Description
      </div>
      <div class="collapsible-content">
        <input class="details-input" type="text" value="${description}" readonly />
      </div>
    </div>
  `;
}

function renderEventTypeBlock(event_type) {
  if (!event_type) return "";

  const objPretty = prettyName(event_type.object_type);
  const actionPretty = event_type.action === "create" ? "Created"
                      : event_type.action === "update" ? "Updated"
                      : "Deleted";

  const technical = `${event_type.object_type}.${event_type.action}`;

  return `
    <div class="action-block">
      <div class="action-block-title">
        <span class="toggle-arrow">►</span> Event Type
      </div>
      <div class="collapsible-content">
        <div>
          Runs when <strong>${objPretty}</strong> is <strong>${actionPretty}</strong>
        </div>

        <a href="#" onclick="this.nextElementSibling.style.display =
          this.nextElementSibling.style.display === 'none' ? 'block' : 'none'; return false;"
          style="margin-top:6px; display:block;">
          Show technical
        </a>

        <pre class="tech-box" style="display:none;">${technical}</pre>
      </div>
    </div>
  `;
}

function renderConditionsBlock(conditions) {
  if (!conditions || !conditions.items || conditions.items.length === 0)
    return `
      <div class="action-block">
        <div class="action-block-title">
          <span class="toggle-arrow">►</span> Conditions
        </div>
        <div class="collapsible-content"><em>No conditions</em></div>
      </div>`;

  let list = "<ul>";
  let technical = "";

  conditions.items.forEach((c) => {
    const left = buildReadableObjectPath(c.left);
    const right = buildReadableObjectPath(c.right);
    const op = operatorLabel(c.operator);

    list += `<li>${left} <strong>${op}</strong> ${right}</li>`;

    technical += buildTechnicalCondition(c) + "\n";
  });

  list += "</ul>";

  return `
    <div class="action-block">
      <div class="action-block-title">
        <span class="toggle-arrow">►</span> Conditions
      </div>
      <div class="collapsible-content readable-list">
        ${list}

        <a href="#" onclick="this.nextElementSibling.style.display =
          this.nextElementSibling.style.display === 'none' ? 'block' : 'none'; return false;">
          Show technical details
        </a>

        <pre class="tech-box" style="display:none;">${technical}</pre>
      </div>
    </div>`;
}

function renderActionsBlock(actions) {
  if (!actions || actions.length === 0)
    return `
      <div class="action-block">
        <div class="action-block-title">
          <span class="toggle-arrow">►</span> Actions
        </div>
        <div class="collapsible-content"><em>No actions found</em></div>
      </div>`;

  let html = "<ul>";

  actions.forEach((a) => {
    const objPretty = prettyName(a.target.object);
    const opPretty = a.operation;

    let fields = "";
    for (const [fieldName, fv] of Object.entries(a.value.fields || {})) {
      const prettyField = prettyName(fieldName);

      if (fv.type === "static") {
        fields += `<li>${prettyField} = "${fv.data}"</li>`;
      } else if (fv.type === "field") {
        fields += `<li>${prettyField} = ${prettyName(fv.object)} → ${prettyName(fv.path)}</li>`;
      }
    }

    html += `
      <li>
        <strong>${opPretty} ${objPretty}</strong>
        <ul>${fields}</ul>

        <a href="#" onclick="this.nextElementSibling.style.display =
          this.nextElementSibling.style.display === 'none' ? 'block' : 'none'; return false;">
          Show technical
        </a>
        <pre class="tech-box" style="display:none;">${JSON.stringify(a, null, 2)}</pre>
      </li>`;
  });

  html += "</ul>";

  return `
    <div class="action-block">
      <div class="action-block-title">
        <span class="toggle-arrow">►</span> Actions
      </div>
      <div class="collapsible-content readable-list">
        ${html}
      </div>
    </div>
  `;
}

function operatorColored(op) {
  const map = {
    "==": { label: "equals (==)", color: "#0073e6" },
    "!=": { label: "does not equal (!=)", color: "#e63946" },
    ">":  { label: "is greater than (>)", color: "#8d39e6" },
    "<":  { label: "is less than (<)", color: "#8d39e6" },
    ">=": { label: "is greater or equal (>=)", color: "#c77d1a" },
    "<=": { label: "is less or equal (<=)", color: "#c77d1a" },
    "contains": { label: "contains", color: "#009688" },
    "in": { label: "in", color: "#5c6bc0" },
    "not in": { label: "not in", color: "#5c6bc0" },
  };
  const info = map[op] || { label: op, color: "#222" };
  return `<span style="color:${info.color}; font-weight:600;">${info.label}</span>`;
}







function renderRules(group_rules) {
  let html = "";
  //console.log(rules);

  group_rules.forEach((group) => {
    html +=
        `<span>
            ${group.rules_request_description}
          </span>`;

    if (group.rules.length === 0){
      html +=
        `<br>
        <span>
            ⚠️ No rules found matching these specifications ⚠️
          </span>`;
    }

    group.rules.forEach((rule) => {

      var head_text = `📖 Rule | ${rule.name}`;
      html +=
        `<div class="rule-container">
          <div class="rule-header">
              <h5>${head_text}</h3>
              <span style="margin-left: 10px; font-weight: bold; color: ${rule.active ? 'green' : 'red'};">
                ${rule.active ? '🟢 Active' : '🔴 Inactive'}
              </span>
          </div>
          <div class="rule-details">
              <div class="name">
                <label for="rule-name"><strong>Description:</strong></label>
                <input id="rule-name" type="text" value="${rule.description}" readonly/>
              </div>

              <div class="rule_type">
                <label for="rule-type"><strong>Rule Type:</strong></label>
                <input id="rule-type" type="text" value="${rule.rule_type}" readonly/>
              </div>

              <div class="target_type">
                <label for="target-type"><strong>Target Type:</strong></label>
                <input id="target-type" type="text" value="${rule.target_type}" readonly/>
              </div>

              <div class="priority">
                <label for="priority"><strong>Priority:</strong></label>
                <input id="priority" type="number" value="${rule.priority}" readonly/>
              </div>

              <div class="error_message">
                <label for="error-message"><strong>Error Message:</strong></label>
                <textarea id="error-message" class="materialize-textarea" rows="3" readonly>${rule.error_message}</textarea>
              </div>
          </div>

          <div class="conditions-details">
            <p><h6>Conditions:</h6></p>
            <ul class="conditions-list">
              ${renderConditions(rule.conditions)}
            </ul>
          </div>
        </div>`;
    });
  });

  return html;
}


function renderConditions(condition, depth = 0) {
  if (!condition) return "<p>No conditions found.</p>";

  if (condition.excluded_products && Array.isArray(condition.excluded_products)) {
    return `
      <div class="conditions-details depth-${depth}">
        <h6>Excluded Products:</h6>
        <ul class="conditions-list">
          ${condition.excluded_products.map(prod => `<li>${prod}</li>`).join("")}
        </ul>
      </div>
    `;
  }

  if (condition.included_products && Array.isArray(condition.included_products)) {
    const triggerLabel = condition.trigger_product
      ? condition.trigger_product.name || condition.trigger_product.sku || "Unknown Trigger Product"
      : "Unknown Trigger Product";

    return `
      <div class="conditions-details depth-${depth}">
        <h6>Trigger Product:</h6>
        <ul class="conditions-list">
          <li>${triggerLabel}</li>
        </ul>

        <h6>Included Products:</h6>
        <ul class="conditions-list">
          ${condition.included_products
            .map(prod => {
              const label = prod.name || prod.sku || "Unknown Product";
              return `<li>${prod.quantity || 1}x ${label}</li>`;
            })
            .join("")}
        </ul>
      </div>
    `;
  }

  const fieldLabelMap = {
    // Quote fields
    "quote.net_amount": "Net Amount",
    "quote.tax_amount": "Tax Amount",
    "quote.status": "Status",
    "quote.discount_percentage": "Quote Discount Percentage",
    "quote.discount_amount": "Quote Discount Amount",
    "quote.discount_type": "Quote Discount Type",
    "quote.subtotal": "Quote Subtotal",

    // Account field
    "quote.account.name": "Account named",

    // Quote Line fields
    "quote_line.quantity": "Quantity",
    "quote_line.unit_price": "Unit Price",
    "quote_line.special_price": "Special Price",
    "quote_line.total_price": "Total Price",
    "quote_line.discount_percentage": "Discount %",
    "quote_line.discount_type": "Discount Type",
    "quote_line.discount_amount": "Discount Amount",
    "quote_line.billing_frequency": "Billing Frequency",
    "quote_line.billing_end_date": "Billing End Date",
    "quote_line.billing_start_date": "Billing Start Date",
    "quote_line.is_subscription": "Is Subscription",
    "quote_line.product_name": "Product Name",
    "quote_line.sku": "SKU",
    "quote_line.term": "Term",
    "quote_line.subtotal": "Line Subtotal"
  };

  function translateOperator(op) {
    switch (op) {
      case "==": return "is";
      case "!=": return "is not";
      case ">": return "is greater than";
      case ">=": return "is greater than or equal to";
      case "<": return "is less than";
      case "<=": return "is less than or equal to";
      default: return op;
    }
  }

  // Caso base: condición simple
  if (condition.fieldName && condition.operator && typeof condition.value !== "undefined") {
    const label = fieldLabelMap[condition.fieldName] || condition.fieldName;
    const operator = translateOperator(condition.operator);
    const value = condition.value;

    return `<li class="depth-${depth}">${label} ${operator} ${value}</li>`;
  }

  // Caso compuesto: lógica AND/OR
  if (condition.logic && Array.isArray(condition.items)) {
    const logicLabel = condition.logic.toUpperCase() === "AND"
      ? "All of the following:"
      : "One of the following:";

    const items = condition.items.map((item, index) => {
      const rendered = renderConditions(item, depth + 1);

      // Agregar el operador lógico entre condiciones (excepto después de la última)
      if (index < condition.items.length - 1) {
        return `${rendered}<li class="logic-operator depth-${depth + 1}">${condition.logic.toUpperCase()}</li>`;
      } else {
        return rendered;
      }
    });

    return `
      <li class="depth-${depth}">
        <strong>${logicLabel}</strong>
        <ul class="conditions-list">
          ${items.join("")}
        </ul>
      </li>
    `;
  }

  return `
    <li class="depth-${depth}">
      <label class="json-label">
        <pre>${escapeHtml(JSON.stringify(condition, null, 2))}</pre>
      </label>
    </li>
  `;
}

function extractJson(raw) {
  const firstBrace = raw.indexOf('{');
  const firstBracket = raw.indexOf('[');

  // Determinar si el JSON empieza con { o [
  let startIndex;
  let openChar, closeChar;

  if (firstBrace === -1 && firstBracket === -1) return null; // no JSON found
  if (firstBrace === -1) {
    startIndex = firstBracket;
    openChar = '['; closeChar = ']';
  } else if (firstBracket === -1) {
    startIndex = firstBrace;
    openChar = '{'; closeChar = '}';
  } else {
    // Escoger el que aparece primero
    if (firstBrace < firstBracket) {
      startIndex = firstBrace;
      openChar = '{'; closeChar = '}';
    } else {
      startIndex = firstBracket;
      openChar = '['; closeChar = ']';
    }
  }

  // Ahora encontrar el cierre balanceado
  let depth = 0;
  for (let i = startIndex; i < raw.length; i++) {
    if (raw[i] === openChar) depth++;
    else if (raw[i] === closeChar) depth--;

    if (depth === 0) {
      return raw.substring(startIndex, i + 1);
    }
  }

  // Si no se cerró el JSON, devolver null
  return null;
}

function renderEmailAlerstDetails(alerts) {
  let html = "";

  alerts.forEach((alert) => {
    if (alert.success){
      var head_text = `✅ New email alert created successfully ✅`;

      // Función interna para renderizar chips
      function renderChips(items, colorClass) {
        if(!items || items.length === 0) return `<span class="grey-text">None</span>`;
        return items.map(item => `<span class="chip ${colorClass} white-text">${item}</span>`).join(" ");
      }

      html +=
        `<div class="email-alert-container">
          <div class="email-alert-header" style="background: linear-gradient(135deg, #041530, #233049); color:#fff; padding:10px 14px; border-radius:12px 12px 0 0;">
              <h5>${head_text}</h3>
              <span style="margin-left: 10px; font-weight: bold; color: ${alert.active ? 'green' : 'red'};">
                ${alert.active ? '🟢 Active' : '🔴 Inactive'}
              </span>
          </div>
          <div class="email-alert-details" style="border-radius:0 0 12px 12px;">

              <div class="email-alert-name">
                <label><strong>Name:</strong></label>
                <input type="text" value="${alert.name}" readonly/>
              </div>

              <div class="email-alert-description">
                <label><strong>Description:</strong></label>
                <input type="text" value="${alert.description}" readonly/>
              </div>

              <div class="trigger">
                <label><strong>Trigger:</strong></label>
                <input type="text" value="${alert.trigger}" readonly/>
              </div>

              <div class="native_object">
                <label><strong>Native Object:</strong></label>
                <input type="text" value="${alert.native_object}" readonly/>
              </div>

              <div class="custom_object">
                <label><strong>Custom Object:</strong></label>
                <input type="text" value="${alert.custom_object ? alert.custom_object : '---'}" readonly/>
              </div>

              <div class="offset_days">
                <label><strong>Offset Days:</strong></label>
                <input type="text" value="${alert.offset_days ? alert.offset_days : '---'}" readonly/>
              </div>

              <div class="schedule_cron">
                <label><strong>Schedule Cron:</strong></label>
                <input type="text" value="${alert.schedule_cron ? alert.schedule_cron : '---'}" readonly/>
              </div>

              <div class="created_by">
                <label><strong>Created By:</strong></label>
                <input style="font-size: 1rem;" type="text" value="${alert.created_at} - ${alert.created_by}" readonly/>
              </div>

              <div class="recipients_users">
                <label><strong>Recipients Users:</strong></label>
                <div class="chips-container">
                  ${renderChips(alert.recipients_users, "blue")}
                </div>
              </div>

              <div class="recipients_roles">
                <label><strong>Recipients Roles:</strong></label>
                <div class="chips-container">
                  ${renderChips(alert.recipients_roles, "deep-purple")}
                </div>
              </div>

              <div class="recipients_externals">
                <label><strong>Recipients Externals:</strong></label>
                <div class="chips-container">
                  ${renderChips(alert.recipients_external, "green")}
                </div>
              </div>
          </div>
        </div>`;
    }
  });

  return html;
}

// Convierte snake_case a Title Case
function normalizeFieldName(fieldName) {
  return fieldName
    .replace(/_/g, " ")                    // reemplaza _ por espacio
    .replace(/\b\w/g, char => char.toUpperCase()); // primera letra de cada palabra en mayúscula
}

function resolveTemplateString(template, metrics) {
  if (typeof template !== "string") return template;
  return template.replace(/{{\s*([^}]+)\s*}}/g, (match, key) => {
    const value = metrics[key.trim()];
    if (value === null || value === undefined || value === "") return "—";
    return String(value);
  });
}

function extractTemplateTokens(template) {
  if (typeof template !== "string") return [];
  const matches = [...template.matchAll(/{{\s*([^}]+)\s*}}/g)];
  return matches.map((match) => match[1].trim());
}

function formatMetricValue(value, format) {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (Number.isNaN(num)) return String(value);
  if (!format) return num.toLocaleString("en-US");

  if (format.startsWith("percent")) {
    const decimals = format.endsWith("1dp") ? 1 : 0;
    const normalized = Math.abs(num) <= 1 ? num * 100 : num;
    return `${normalized.toFixed(decimals)}%`;
  }

  if (format.startsWith("ratio")) {
    const decimals = format.endsWith("2dp") ? 2 : 1;
    return num.toFixed(decimals);
  }

  if (format === "int") {
    return Math.round(num).toLocaleString("en-US");
  }

  return num.toLocaleString("en-US");
}

function formatTrendValue(value, format) {
  const formatted = formatMetricValue(value, format);
  const num = Number(value);
  if (!Number.isNaN(num) && num > 0) {
    return `+${formatted}`;
  }
  return formatted;
}

function evaluateEmphasisRule(condition, metrics) {
  if (!condition) return false;
  const match = condition.match(/{{\s*([^}]+)\s*}}\s*(<=|>=|==|!=|<|>)\s*(['"]?[^'"]+['"]?)/);
  if (!match) return false;
  const key = match[1].trim();
  const op = match[2];
  let right = match[3].trim();
  const left = metrics[key];

  if ((right.startsWith("'") && right.endsWith("'")) || (right.startsWith('"') && right.endsWith('"'))) {
    right = right.slice(1, -1);
    const leftStr = String(left);
    if (op === "==") return leftStr === right;
    if (op === "!=") return leftStr !== right;
    return false;
  }

  const leftNum = Number(left);
  const rightNum = Number(right);
  if (Number.isNaN(leftNum) || Number.isNaN(rightNum)) return false;

  if (op === "<") return leftNum < rightNum;
  if (op === "<=") return leftNum <= rightNum;
  if (op === ">") return leftNum > rightNum;
  if (op === ">=") return leftNum >= rightNum;
  if (op === "==") return leftNum === rightNum;
  if (op === "!=") return leftNum !== rightNum;
  return false;
}

function resolveEmphasisClass(rules, metrics) {
  if (!Array.isArray(rules)) return "";
  for (const rule of rules) {
    if (evaluateEmphasisRule(rule.when, metrics)) {
      return rule.emphasis || "";
    }
  }
  return "";
}

function normalizeBarList(source) {
  if (Array.isArray(source)) {
    return source.map((item) => {
      if (typeof item === "object") {
        return {
          label: item.label ?? item.status ?? item.key ?? "Unknown",
          value: item.value ?? item.count ?? 0,
        };
      }
      return { label: String(item), value: 0 };
    });
  }
  if (source && typeof source === "object") {
    return Object.entries(source).map(([label, value]) => ({ label, value }));
  }
  return [];
}

function renderIntelligenceDashboard(payload) {
  if (!payload || !payload.layout_key) return "";
  const data = payload.data || {};
  const layout = data.layout || {};
  const metrics = data.metrics || {};
  const changedFields = new Set(data.changed_fields || []);
  const highlightChanges = payload.render_hints && payload.render_hints.highlight_changed_fields;

  const formatValueFromTemplate = (template, formatSpec) => {
    const tokens = extractTemplateTokens(template);
    const key = tokens[0];
    const value = key ? metrics[key] : template;
    return formatMetricValue(value, formatSpec);
  };

  const buildCardClasses = (template, emphasisRules) => {
    const classes = ["intelligence-card"];
    const emphasis = resolveEmphasisClass(emphasisRules, metrics);
    if (emphasis === "alert") classes.push("is-alert");
    if (emphasis === "positive") classes.push("is-positive");
    if (highlightChanges) {
      const tokens = extractTemplateTokens(template);
      if (tokens.some((token) => changedFields.has(token))) {
        classes.push("is-changed");
      }
    }
    return classes.join(" ");
  };

  const renderKpiCard = (card) => {
    const value = formatValueFromTemplate(card.value, card.format?.value);
    const trend = card.trend ? formatTrendValue(metrics[extractTemplateTokens(card.trend)[0]], card.format?.trend) : null;
    const trendClass = Number(metrics[extractTemplateTokens(card.trend || "")[0]]) < 0 ? "is-negative" : "is-positive";
    return `
      <div class="${buildCardClasses(card.value, card.emphasis_rules)}">
        <div class="intelligence-card-title">${escapeHtml(card.title)}</div>
        <div class="intelligence-card-value">${escapeHtml(value)}</div>
        ${trend ? `<div class="intelligence-card-trend ${trendClass}">${escapeHtml(trend)}</div>` : ""}
      </div>
    `;
  };

  const renderProgressCard = (card) => {
    const value = Number(metrics[extractTemplateTokens(card.value)[0]] || 0);
    const target = Number(card.target || 1);
    const pct = target ? Math.min(Math.max((value / target) * 100, 0), 100) : 0;
    const formatted = formatMetricValue(value, card.format?.value);
    return `
      <div class="${buildCardClasses(card.value, card.emphasis_rules)} intelligence-card--progress">
        <div class="intelligence-card-title">${escapeHtml(card.title)}</div>
        <div class="intelligence-progress">
          <div class="intelligence-progress-bar" style="--progress:${pct.toFixed(1)}%;"></div>
        </div>
        <div class="intelligence-progress-meta">${escapeHtml(formatted)}x</div>
      </div>
    `;
  };

  const renderStatusBadge = (card) => {
    const value = resolveTemplateString(card.value, metrics);
    return `
      <div class="${buildCardClasses(card.value, card.emphasis_rules)} intelligence-card--badge">
        <div class="intelligence-card-title">${escapeHtml(card.title)}</div>
        <div class="intelligence-status-pill">${escapeHtml(String(value))}</div>
      </div>
    `;
  };

  const renderBarList = (section) => {
    const sourceKey = extractTemplateTokens(section.source)[0];
    const items = normalizeBarList(metrics[sourceKey]);
    const total = items.reduce((sum, item) => sum + Number(item.value || 0), 0);
    const palette = ["#2563eb", "#22c55e", "#f97316", "#a855f7", "#0ea5e9", "#f43f5e"];
    return `
      <div class="intelligence-section">
        <div class="intelligence-section-title">${escapeHtml(section.title)}</div>
        <div class="metric-segmented">
          <div class="metric-segmented-legend">
            ${items.map((item, idx) => `
              <div class="metric-legend-item">
                <span class="metric-legend-dot" style="--segment-color:${palette[idx % palette.length]};"></span>
                <span class="metric-legend-label">${escapeHtml(String(item.label))}</span>
                <span class="metric-legend-count">: ${formatMetricValue(item.value, "int")}</span>
              </div>
            `).join("")}
          </div>
          <div class="metric-segmented-bar">
            ${items.map((item, idx) => {
              const pct = total ? (Number(item.value || 0) / total) * 100 : 0;
              return `<span class="metric-segment" style="--segment-size:${pct.toFixed(2)}%;--segment-color:${palette[idx % palette.length]};"></span>`;
            }).join("")}
          </div>
        </div>
      </div>
    `;
  };

  const renderCallout = (section) => `
    <div class="intelligence-callout">
      <div class="intelligence-callout-title">${escapeHtml(section.title)}</div>
      <div class="intelligence-callout-body">${escapeHtml(resolveTemplateString(section.body, metrics))}</div>
    </div>
  `;

  let body = "";
  if (layout.type === "kpi_grid") {
    const cards = (layout.cards || []).slice(0, layout.max_cards || 99);
    body = `
      <div class="intelligence-kpi-grid">
        ${cards.map((card) => {
          if (card.type === "kpi") return renderKpiCard(card);
          if (card.type === "progress") return renderProgressCard(card);
          if (card.type === "status_badge") return renderStatusBadge(card);
          return "";
        }).join("")}
      </div>
    `;
  } else if (layout.type === "stacked_sections") {
    body = `
      <div class="intelligence-sections">
        ${(layout.sections || []).map((section) => {
          if (section.type === "kpi_row") {
            return `
              <div class="intelligence-kpi-row">
                ${(section.cards || []).map((card) => renderKpiCard(card)).join("")}
              </div>
            `;
          }
          if (section.type === "bar_list") return renderBarList(section);
          if (section.type === "callout") return renderCallout(section);
          return "";
        }).join("")}
      </div>
    `;
  } else if (layout.type === "action_panel") {
    body = `
      <div class="intelligence-sections">
        ${(layout.sections || []).map((section) => {
          if (section.type === "callout") return renderCallout(section);
          if (section.type === "kpi") return renderKpiCard(section);
          if (section.type === "bar_list") return renderBarList(section);
          return "";
        }).join("")}
      </div>
    `;
  }

  return `
    <div class="intelligence-dashboard" data-layout="${escapeHtml(layout.layout_key || payload.layout_key || "")}">
      ${body}
    </div>
  `;
}

// =====================================================
// ✅ renderRetrievedRecords (con estilos y scroll)
// ✅ openRecordsPopout (popout draggable con overlay)
// =====================================================

function renderRetrievedRecords(userMessage, recordsDetails) {
  try {
    let html = "";
    const formatNumber = (val) => {
      if (val === null || val === undefined) return "—";
      if (typeof val === "number") return val.toLocaleString("en-US", { maximumFractionDigits: 2 });
      return val;
    };
    const formatCurrency = (val) => {
      if (val === null || val === undefined) return "—";
      if (typeof val === "number") {
        return val.toLocaleString("en-US", {
          style: "currency",
          currency: "USD",
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        });
      }
      return val;
    };
    const isMoneyField = (field) => {
      const f = (field || "").toLowerCase();
      return [
        "amount",
        "net_amount",
        "subtotal",
        "total",
        "revenue",
        "price",
        "cost",
        "fee",
        "currency",
      ].some(k => f.includes(k));
    };
    const getISOWeek = (date) => {
      const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
      const dayNum = d.getUTCDay() || 7;
      d.setUTCDate(d.getUTCDate() + 4 - dayNum);
      const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
      return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
    };
    const formatPeriodLabel = (periodStr, groupBy) => {
      if (!periodStr) return "—";
      if ((groupBy || "").toLowerCase() === "quarter") return String(periodStr);
      const d = new Date(periodStr);
      if (isNaN(d.getTime())) return periodStr;
      switch ((groupBy || "").toLowerCase()) {
        case "week":
          return `Week ${getISOWeek(d)}`;
        case "day":
          return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
        case "year":
          return `${d.getFullYear()}`;
        case "month":
        default:
          return d.toLocaleString("en-US", { month: "long" });
      }
    };
    const formatRangeLabel = (rangeKey) => {
      if (!rangeKey || rangeKey === "null") return "";
      if (Array.isArray(rangeKey)) return "Custom range";
      const key = String(rangeKey).toLowerCase();
      const map = {
        last_3_months: "Last 3 months",
        last_month: "Last month",
        last_90_days: "Last 90 days",
        this_year: "This year",
        next_year: "Next year",
        this_month: "This month",
        this_quarter: "This quarter",
        current_quarter: "This quarter",
        last_quarter: "Last quarter",
        previous_quarter: "Last quarter",
        three_months: "Last 3 months",
        six_months: "Last 6 months",
        nine_months: "Last 9 months",
        twelve_months: "Last 12 months",
      };
      return map[key] || "Custom range";
    };
    const capitalizeWord = (value) => {
      if (!value) return "";
      const text = String(value).toLowerCase();
      return text.charAt(0).toUpperCase() + text.slice(1);
    };
    const isStatusGroupField = (value) => {
      const text = String(value || "").toLowerCase();
      return ["status", "stage", "type", "lifecycle"].some((token) => text.includes(token));
    };
    const buildInsightText = (series, totalVal, formatter, isTimeGroup, isFieldGroup, groupLabel) => {
      if (!Array.isArray(series) || series.length < 1) return "";
      if (isTimeGroup && series.length > 1) {
        const prev = Number(series[series.length - 2].value || 0);
        const curr = Number(series[series.length - 1].value || 0);
        if (prev === 0) return "";
        const delta = ((curr - prev) / prev) * 100;
        const arrow = delta >= 0 ? "↑" : "↓";
        return `${arrow} ${Math.abs(delta).toFixed(1)}% vs prior period`;
      }
      if (isFieldGroup) {
        const topItem = [...series]
          .sort((a, b) => Number(b.value || 0) - Number(a.value || 0))[0];
        if (!topItem || topItem.value == null) return "";
        const percent = totalVal ? (Number(topItem.value || 0) / Number(totalVal || 1)) * 100 : 0;
        const label = topItem.period ? String(topItem.period) : "Unknown";
        return `Top ${normalizeFieldName(groupLabel)}: ${label} (${formatter(topItem.value)}, ${percent.toFixed(1)}%)`;
      }
      return "";
    };

    const formatRecordValue = (field, value) => {
      if (value === null || value === undefined || value === "") return "—";
      if (typeof value === "boolean") return value ? "Yes" : "No";
      if (Array.isArray(value)) {
        const flat = value
          .map((item) => {
            if (item === null || item === undefined || item === "") return "";
            if (typeof item === "object") return JSON.stringify(item);
            return String(item);
          })
          .filter(Boolean);
        return flat.length ? flat.join(", ") : "—";
      }
      if (typeof value === "object") return "—";
      if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}(T.*)?$/.test(value)) {
        const d = new Date(value);
        if (!isNaN(d.getTime())) {
          return d.toLocaleDateString("en-US", {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
          });
        }
      }
      if (isMoneyField(field)) {
        const num = typeof value === "number" ? value : parseFloat(value);
        return isNaN(num) ? String(value) : formatCurrency(num);
      }
      return String(value);
    };
    const isBooleanValue = (value) => {
      if (typeof value === "boolean") return true;
      if (typeof value !== "string") return false;
      const normalized = value.trim().toLowerCase();
      return ["true", "false", "yes", "no"].includes(normalized);
    };
    const normalizeBooleanValue = (value) => {
      if (typeof value === "boolean") return value;
      if (typeof value !== "string") return null;
      const normalized = value.trim().toLowerCase();
      if (["true", "yes"].includes(normalized)) return true;
      if (["false", "no"].includes(normalized)) return false;
      return null;
    };
    const renderBooleanIcon = (value) => {
      const normalized = normalizeBooleanValue(value);
      if (normalized === null) return "—";
      const icon = normalized ? "check_circle" : "radio_button_unchecked";
      const className = normalized
        ? "records-boolean-icon records-boolean-icon--true"
        : "records-boolean-icon records-boolean-icon--false";
      return `<span class="${className}"><span class="material-icons" aria-hidden="true">${icon}</span></span>`;
    };
    const resolveRecordFieldValue = (record, candidates) => {
      const keys = Object.keys(record || {});
      if (!keys.length) return "";
      const lookup = new Map(keys.map((key) => [key.toLowerCase(), key]));
      for (const candidate of candidates) {
        const match = lookup.get(String(candidate).toLowerCase());
        if (!match) continue;
        const value = record[match];
        if (value !== null && value !== undefined && value !== "") {
          return value;
        }
      }
      return "";
    };
    const getPartnerLabel = (record) => resolveRecordFieldValue(record, ["_partner_label", "partner_label"]);
    const resolveRecordObjectName = (record, fallback) => {
      const objectValue = resolveRecordFieldValue(record, [
        "object",
        "record_object",
        "api_object",
        "object_name",
      ]);
      return objectValue || fallback;
    };
    const buildListViewValue = (record, viewField, fallbackObject, idCandidates) => {
      if (!record || !viewField) return "";
      const viewLower = String(viewField).toLowerCase();
      const existing = resolveRecordFieldValue(record, [viewLower]);
      if (existing) return existing;
      const recordId = resolveRecordFieldValue(record, idCandidates);
      if (!recordId) return "";
      if (viewLower === "view_quote") {
        return buildQuoteListViewButton(recordId);
      }
      const objectName = resolveRecordObjectName(record, fallbackObject);
      return buildRecordListViewButton(recordId, objectName);
    };
    const orderListFields = (fields) => {
      if (!Array.isArray(fields)) return [];
      const viewFields = [];
      const rest = [];
      fields.forEach((field) => {
        const lower = String(field).toLowerCase();
        if (lower === "view_record" || lower === "view_quote") {
          viewFields.push(field);
        } else {
          rest.push(field);
        }
      });
      return [...viewFields, ...rest];
    };

    // If payload arrives as string, try to parse it
    if (typeof recordsDetails === "string") {
      try {
        recordsDetails = JSON.parse(recordsDetails);
      } catch (e) {
        console.warn("retrieved_records parse error:", e);
        return `${html}<div class="error-message">Unable to display records.</div>`;
      }
    }
    if (!recordsDetails || typeof recordsDetails !== "object") {
      return `${html}<div class="error-message">No records to display.</div>`;
    }

    const showMobileActions = typeof window !== "undefined"
      && window.matchMedia
      && window.matchMedia("(max-width: 768px)").matches;

    // Add/update global styles (refresh on each render to avoid stale CSS).
    let style = document.getElementById("records-table-style");
    if (!style) {
      style = document.createElement("style");
      style.id = "records-table-style";
      document.head.appendChild(style);
    }
    style.textContent = `
      .records-container {
        font-family: 'Inter', sans-serif;
        color: #1f2937;
      }

      .records-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: linear-gradient(135deg, #041530, #233049);
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem 0.5rem 0 0;
      }

      .records-header-title {
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .records-header h5 {
        margin: 0;
        font-size: 1rem;
        letter-spacing: 0.5px;
      }

      .records-partner-pill {
        display: inline-flex;
        align-items: center;
        padding: 4px 10px;
        border-radius: 999px;
        background: rgba(16, 185, 129, 0.16);
        color: #047857;
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        white-space: nowrap;
      }

      .records-popout-btn {
        background: rgba(255, 255, 255, 0.2);
        border: 1px solid rgba(255,255,255,0.3);
        color: white;
        padding: 0.25rem 0.6rem;
        font-size: 0.8rem;
        border-radius: 0.4rem;
        cursor: pointer;
        transition: background 0.2s ease, transform 0.1s ease;
      }

      .records-popout-btn:focus {
        outline: none;
        box-shadow: none;
      }

      .records-popout-btn:hover {
        background: rgba(255, 255, 255, 0.35);
        transform: scale(1.05);
      }

      .records-table-wrapper {
        overflow-x: auto;
        overflow-y: auto;
        max-height: 500px;
        border: 1px solid #e5e7eb;
        border-radius: 0 0 0.5rem 0.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
      }

      .records-table {
        width: 100%;
        border-collapse: collapse;
        background: white;
        font-size: 1.12rem;
      }

      .records-table thead {
        background: #f9fafb;
        position: sticky;
        top: 0;
        z-index: 2;
      }

      .records-table th, .records-table td {
        padding: 0.75rem 1rem;
        white-space: nowrap;
        border-bottom: 1px solid #e5e7eb;
      }

      .records-table th {
        text-align: left;
        font-weight: 600;
        color: #374151;
        text-transform: uppercase;
        font-size: 1.1rem;
        background: #f8fafc;
        border-right: 1px solid #e5e7eb;
        box-shadow: inset 0 -1px 0 #e5e7eb;
      }

      .records-table th:last-child,
      .records-table td:last-child {
        border-right: none;
      }

      .records-table td {
        border-right: 1px solid #f1f5f9;
      }

      .records-table th.is-sortable {
        cursor: pointer;
        position: relative;
      }

      .records-table th.is-sortable::after {
        content: "";
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 18px;
        height: 18px;
        margin-left: 8px;
        vertical-align: middle;
        background: #9ca3af;
        mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M12 4l-4 4h3v6h2V8h3l-4-4zm0 16l4-4h-3V10h-2v6H8l4 4z'/%3E%3C/svg%3E") center / contain no-repeat;
        -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M12 4l-4 4h3v6h2V8h3l-4-4zm0 16l4-4h-3V10h-2v6H8l4 4z'/%3E%3C/svg%3E") center / contain no-repeat;
      }

      .records-table th.is-sorted::after {
        background: #2563eb;
      }

      .records-table th.is-sorted[data-sort-order="asc"]::after {
        mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M7 14l5-5 5 5H7z'/%3E%3C/svg%3E");
        -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M7 14l5-5 5 5H7z'/%3E%3C/svg%3E");
      }

      .records-table th.is-sorted[data-sort-order="desc"]::after {
        mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M7 10l5 5 5-5H7z'/%3E%3C/svg%3E");
        -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M7 10l5 5 5-5H7z'/%3E%3C/svg%3E");
      }

      .records-boolean-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: #0ea5e9;
        width: 100%;
      }

      .records-boolean-icon--false {
        color: #cbd5e1;
      }

      .records-boolean-icon .material-icons {
        font-size: 22px;
      }

      .records-boolean-cell {
        text-align: center;
      }

      .records-table td[data-field="description" i] {
        white-space: normal;
        word-break: break-word;
        max-width: 280px;
      }

      .records-table td[data-field="notes" i] {
        white-space: normal;
        word-break: break-word;
        max-width: 840px;
      }

      .records-table--lead th[data-field="notes" i],
      .records-table--lead td[data-field="notes" i],
      .records-table--leads th[data-field="notes" i],
      .records-table--leads td[data-field="notes" i] {
        min-width: 420px;
      }

      .records-table tbody tr:nth-child(even) {
        background-color: #f8fafc;
      }

      .records-table tbody tr:hover {
        background-color: #eff6ff;
      }

      .records-card-grid {
        display: none;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        padding: 12px;
        border: 1px solid #e5e7eb;
        border-top: 0;
        border-radius: 0 0 12px 12px;
        background: #fff;
      }

      .records-card {
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        padding: 16px;
        background: #f8fafc;
        box-shadow: 0 6px 14px rgba(15, 23, 42, 0.06);
        display: flex;
        flex-direction: column;
        gap: 14px;
        min-height: 135px;
      }

      .records-card.is-clickable {
        cursor: pointer;
        transition: transform 120ms ease, box-shadow 120ms ease, border 120ms ease;
      }

      .records-card.is-clickable:hover {
        transform: translateY(-1px);
        box-shadow: 0 10px 20px rgba(15, 23, 42, 0.12);
        border-color: rgba(148, 163, 184, 0.6);
      }

      .records-card.is-clickable:focus {
        outline: 2px solid rgba(37, 99, 235, 0.35);
        outline-offset: 2px;
      }

      .records-card-top {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 10px;
      }

      .records-card-pills {
        display: inline-flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 6px;
        justify-content: flex-end;
      }

      .records-card-title {
        font-weight: 700;
        font-size: 1.05rem;
        color: #111827;
      }

      .records-card-pill {
        display: inline-flex;
        align-items: center;
        padding: 4px 10px;
        border-radius: 999px;
        background: rgba(37, 99, 235, 0.12);
        color: #1d4ed8;
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        white-space: nowrap;
      }

      .records-card-meta {
        display: grid;
        gap: 6px;
        font-size: 0.88rem;
        color: #374151;
      }

      .records-card-row {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        align-items: center;
      }

      .records-card-label {
        font-size: 0.65rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #64748b;
      }

      .records-card-value {
        font-weight: 600;
        color: #0f172a;
        text-align: right;
        overflow-wrap: anywhere;
      }

      .records-card-view-row,
      .records-card-view-inline {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 10px;
        margin-top: 4px;
      }

      .records-card-empty {
        color: #94a3b8;
        font-size: 0.85rem;
      }

      .records-leads-grid {
        display: none;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        padding: 12px;
        border: 1px solid #e5e7eb;
        border-top: 0;
        border-radius: 0 0 12px 12px;
        background: #fff;
      }

      .records-lead-card {
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        padding: 16px;
        background: #f8fafc;
        box-shadow: 0 6px 14px rgba(15, 23, 42, 0.06);
        display: flex;
        flex-direction: column;
        gap: 14px;
        min-height: 135px;
      }

      .records-lead-card.is-clickable {
        cursor: pointer;
        transition: transform 120ms ease, box-shadow 120ms ease, border 120ms ease;
      }

      .records-lead-card.is-clickable:hover {
        transform: translateY(-1px);
        box-shadow: 0 10px 20px rgba(15, 23, 42, 0.12);
        border-color: rgba(148, 163, 184, 0.6);
      }

      .records-lead-card.is-clickable:focus {
        outline: 2px solid rgba(37, 99, 235, 0.35);
        outline-offset: 2px;
      }

      .records-lead-top {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 10px;
      }

      .records-lead-name {
        font-weight: 700;
        font-size: 1.05rem;
        color: #111827;
      }

      .records-lead-actions {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        flex-shrink: 0;
      }

      .records-lead-pill {
        display: inline-flex;
        align-items: center;
        padding: 4px 10px;
        border-radius: 999px;
        background: rgba(15, 118, 110, 0.12);
        color: #0f766e;
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        white-space: nowrap;
      }

      .records-lead-meta {
        display: grid;
        gap: 6px;
        font-size: 0.88rem;
        color: #374151;
      }

      .records-lead-view-row {
        display: flex;
        justify-content: flex-end;
        margin-top: 4px;
      }

      .records-lead-row {
        display: flex;
        justify-content: space-between;
        gap: 10px;
        align-items: center;
      }

      .records-lead-label {
        font-size: 0.65rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #64748b;
      }

      .records-lead-value {
        font-weight: 600;
        color: #0f172a;
        text-align: right;
        overflow-wrap: anywhere;
      }

      .records-lead-empty {
        color: #94a3b8;
        font-size: 0.85rem;
      }

      .records-leads-table {
        display: block;
      }

      .records-table-wrapper--list {
        display: block;
      }

      .records-card-view {
        display: inline-flex;
      }

      .records-lead-view {
        display: inline-flex;
      }

      .records-columns-row {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 4px 6px;
        border-radius: 6px;
        cursor: grab;
      }

      .records-columns-row.is-dragging {
        background: #f1f5f9;
        opacity: 0.6;
      }

      .records-columns-drag {
        cursor: grab;
        font-size: 18px;
        color: #94a3b8;
      }

      .records-columns-list {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .email-alert-container.popup .records-leads-grid {
        display: none;
      }

      .email-alert-container.popup .records-leads-table {
        display: block;
      }

      .email-alert-container.popup .records-card-grid {
        display: none;
      }

      .email-alert-container.popup .records-table-wrapper--list {
        display: block;
      }

      .email-alert-container.popup {
        display: flex;
        flex-direction: column;
        height: 100%;
      }

      .email-alert-container.popup .email-alert-header {
        flex: 0 0 auto;
      }

      .email-alert-container.popup .records-table-wrapper,
      .email-alert-container.popup .records-table-wrapper--list,
      .email-alert-container.popup .records-leads-table {
        flex: 1 1 auto;
        max-height: none;
        height: 100%;
      }

      /* Popup general */
      .records-overlay {
        position: fixed;
        inset: 0;
        background: rgba(15,23,42,0.45);
        z-index: 2147482999;
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .popup {
        background: #fff;
        border-radius: 0.9rem;
        box-shadow: 0 14px 40px rgba(2,6,23,0.36);
        width: 840px;
        max-width: 94vw;
        max-height: 84vh;
        overflow: hidden;
        z-index: 2147483000;
        display: flex;
        flex-direction: column;
      }

      .popup .popup-header {
        padding: 0.6rem 1rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        height: 52px;
        flex: 0 0 52px;
        border-radius: 0.9rem 0.9rem 0 0;
        background: linear-gradient(135deg, #041530, #233049);
        color: white;
      }

      .popup .popup-close {
        background: rgba(255,255,255,0.12);
        border: none;
        color: white;
        width: 34px;
        height: 34px;
        border-radius: 6px;
        font-size: 16px;
        cursor: pointer;
      }

      .popup .popup-body {
        padding: 0.5rem;
        overflow: auto;
        flex: 1 1 auto;
      }

      .records-popout-btn:focus {
        outline: none;
        box-shadow: none;
        background-color: rgba(255,255,255,0.12);
      }
      .records-popout-btn:active {
        background-color: rgba(255,255,255,0.12);
      }

      @media (max-width:640px) {
        .popup { width: 96vw; max-height: 90vh; }
        .records-table th, .records-table td { padding: 0.5rem 0.6rem; }
        .records-card-grid { grid-template-columns: 1fr; padding: 10px; }
        .records-card { padding: 10px 12px; }
        .records-leads-grid { grid-template-columns: 1fr; padding: 10px; }
        .records-lead-card { padding: 10px 12px; }
      }

      @media (max-width: 768px) {
        .records-card-grid {
          display: grid;
        }

        .records-table-wrapper--list {
          display: none;
        }

        .records-leads-grid {
          display: grid;
        }

        .records-leads-table {
          display: none;
        }

        .records-table--account th,
        .records-table--account td {
          display: none;
        }

        .records-table--account th[data-field="name" i],
        .records-table--account td[data-field="name" i],
        .records-table--account th[data-field="account_name" i],
        .records-table--account td[data-field="account_name" i],
        .records-table--account th[data-field="phone" i],
        .records-table--account td[data-field="phone" i],
        .records-table--account th[data-field="phone_number" i],
        .records-table--account td[data-field="phone_number" i] {
          display: table-cell;
        }

        .records-card--account .records-card-row {
          display: none;
        }

        .records-card--account .records-card-row[data-field="phone" i],
        .records-card--account .records-card-row[data-field="phone_number" i] {
          display: flex;
        }
      }
      `;

    // Renderizar objetos
    let entries = [];
    try {
      entries = Object.entries(recordsDetails);
    } catch (e) {
      console.warn("Failed to iterate recordsDetails:", e);
      return `${html}<div class="error-message">Unable to display records.</div>`;
    }

  for (const [objectName, records] of entries) {
    if (!records) continue;
    const listRecords = Array.isArray(records)
      ? records
      : (records && Array.isArray(records.records) ? records.records : []);
    const hasListRecords = Array.isArray(listRecords) && listRecords.length > 0;
    const lowerObjectName = String(objectName || "").toLowerCase();
    const isActivitiesList = lowerObjectName.includes("activities for");

    // Aggregates: render intent-driven metric card
    if (!Array.isArray(records) && records.aggregate) {
      const agg = records.aggregate;
      const series = Array.isArray(agg.series) ? agg.series : [];
      const totalVal = agg.total != null ? agg.total : agg.value;
      const money = isMoneyField(agg.field) || (agg.function || "").toLowerCase() === "sum";
      const formatter = money ? formatCurrency : formatNumber;
      const totalText = formatter(totalVal);
      const func = (agg.function || "").toLowerCase();
      const labelText = func === "count"
        ? "Count"
        : func === "avg" || func === "average"
          ? "Average"
          : func === "min"
            ? "Minimum"
            : func === "max"
              ? "Maximum"
              : money ? "Revenue" : "Total";
      const iconName = money
        ? "attach_money"
        : func === "count"
          ? "format_list_numbered"
          : func === "avg" || func === "average"
            ? "analytics"
            : func === "min"
              ? "south_west"
              : func === "max"
                ? "north_east"
                : "functions";
      const safeObjectName = escapeHtml(String(objectName || "Record"));
      const aggTitle = objectName === "Opportunity"
        ? `<span class="material-icons" aria-hidden="true">trending_up</span>${safeObjectName}`
        : safeObjectName;
      const aggId = `agg-${objectName}-${Math.random().toString(36).slice(2, 8)}`;
      const groupBy = String(agg.group_by || "").toLowerCase();
      const groupField = agg.group_field || "";
      const groupLabel = agg.group_label || agg.group_field || "Group";
      const isTimeGroup = ["month", "week", "day", "quarter", "year"].includes(groupBy);
      const isFieldGroup = groupBy === "field";
      const isStatusGroup = isFieldGroup && isStatusGroupField(groupField || groupLabel);
      const rangeText = formatRangeLabel(agg.range);
      const contextParts = [];
      if (rangeText) contextParts.push(rangeText);
      if (isTimeGroup) contextParts.push(`${capitalizeWord(groupBy)} trend`);
      if (isFieldGroup) contextParts.push(`By ${normalizeFieldName(groupLabel)}`);
      const contextText = contextParts.length ? contextParts.join(" | ") : "All time";
      const insightText = buildInsightText(series, totalVal, formatter, isTimeGroup, isFieldGroup, groupLabel);
      const targetValue = parseFloat(agg.target || agg.goal || agg.target_value);
      const hasTarget = Number.isFinite(targetValue) && targetValue > 0;
      const progressPct = hasTarget ? Math.min(100, (Number(totalVal || 0) / targetValue) * 100) : 0;
      const segmentTotal = Number(totalVal) || series.reduce((sum, item) => sum + Number(item.value || 0), 0);
      const palette = ["#2563eb", "#0ea5e9", "#7c3aed", "#f97316", "#22c55e", "#ef4444", "#14b8a6", "#eab308"];
      const seriesOrdered = isTimeGroup
        ? series
        : [...series].sort((a, b) => Number(b.value || 0) - Number(a.value || 0));
      const detailsTable = series.length ? `
        <div class="records-metric-table">
          <table class="records-table">
            <thead><tr><th>${isTimeGroup ? "Period" : normalizeFieldName(String(groupLabel))}</th><th>Value</th></tr></thead>
            <tbody>
              ${seriesOrdered.map(item => `
                <tr>
                  <td>${isTimeGroup ? formatPeriodLabel(item.period, agg.group_by) : escapeHtml(String(item.period || "Unknown"))}</td>
                  <td>${item.value != null ? formatter(item.value) : "—"}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      ` : "";
      const definitionRows = [
        { label: "Metric", value: `${labelText} (${func || "sum"})` },
        { label: "Field", value: normalizeFieldName(agg.field || "—") },
        { label: "Range", value: rangeText || "All time" },
        { label: "Group", value: isTimeGroup ? `${capitalizeWord(groupBy)} of ${normalizeFieldName(agg.date_field || "date")}` : (isFieldGroup ? normalizeFieldName(groupLabel) : "None") },
      ].filter(row => row.value);
      const definitionHtml = `
        <div class="records-metric-definition">
          ${definitionRows.map(row => `
            <div class="records-metric-definition-item">
              <span class="records-metric-definition-label">${row.label}</span>
              <span class="records-metric-definition-value">${escapeHtml(String(row.value))}</span>
            </div>
          `).join("")}
        </div>
      `;
      const segmentedHtml = isStatusGroup && series.length ? `
        <div class="metric-segmented">
          <div class="metric-segmented-legend">
            ${seriesOrdered.map((item, idx) => `
              <div class="metric-legend-item">
                <span class="metric-legend-dot" style="--segment-color:${palette[idx % palette.length]};"></span>
                <span class="metric-legend-label">${escapeHtml(String(item.period || "Unknown"))}</span>
                <span class="metric-legend-count">: ${formatter(item.value || 0)}</span>
              </div>
            `).join("")}
          </div>
          <div class="metric-segmented-bar">
            ${seriesOrdered.map((item, idx) => {
              const value = Number(item.value || 0);
              const pct = segmentTotal ? (value / segmentTotal) * 100 : 0;
              return `<span class="metric-segment" style="--segment-size:${pct.toFixed(2)}%;--segment-color:${palette[idx % palette.length]};"></span>`;
            }).join("")}
          </div>
        </div>
      ` : "";
      const progressHtml = hasTarget ? `
        <div class="metric-progress">
          <div class="metric-progress-bar" style="--progress:${progressPct.toFixed(1)}%;"></div>
        </div>
        <div class="metric-progress-meta">${formatter(totalVal)} of ${formatter(targetValue)} target</div>
      ` : "";
      const chartHtml = (!isStatusGroup && !hasTarget && series.length) ? `
        <div class="records-metric-chart ${isTimeGroup ? "records-metric-chart--spark" : ""}">
          <canvas id="${aggId}-chart-canvas"
            data-labels='${JSON.stringify(seriesOrdered.map(s => isTimeGroup ? formatPeriodLabel(s.period, agg.group_by) : String(s.period || "Unknown")))}'
            data-values='${JSON.stringify(seriesOrdered.map(s => s.value || 0))}'
            data-money='${money ? "1" : "0"}'
            data-intent='${isTimeGroup ? "trend" : "comparison"}'
            data-series-label='${escapeHtml(String(labelText || "Total"))}'
            style="width:100%; height:100%;"></canvas>
        </div>
      ` : "";
      html += `
        <div class="email-alert-container records-metric-card" style="margin-bottom:10px; position:relative;">
          <div class="records-metric-header">
            <div class="records-metric-title">${aggTitle}</div>
            <div class="records-metric-context">${escapeHtml(contextText)}</div>
          </div>
          <div class="records-metric-body">
            <div class="records-metric-kpi">
              <span class="material-icons records-metric-icon" aria-hidden="true">${iconName}</span>
              <div>
                <div class="records-metric-value">${totalText}</div>
                <div class="records-metric-label">${labelText}</div>
              </div>
            </div>
            ${segmentedHtml || progressHtml || chartHtml || ""}
            ${insightText ? `<div class="records-metric-insight">${escapeHtml(insightText)}</div>` : ""}
            <button type="button" class="records-metric-cta" onclick="toggleAggDetails('${aggId}', this)">View details</button>
            <div id="${aggId}-details" class="records-metric-details">
              ${definitionHtml}
              ${detailsTable}
            </div>
          </div>
        </div>
      `;
      if (!hasListRecords) {
        continue;
      }
    }

    if (!hasListRecords) {
      if (isActivitiesList) {
        const safeTitle = escapeHtml(String(objectName || "Activities"));
        html += `
          <div class="email-alert-container" style="margin-bottom:10px; position:relative;">
            <div class="email-alert-header" style="
              display:flex;
              justify-content:space-between;
              align-items:center;
              background: linear-gradient(135deg, #041530, #233049);
              color:#fff;
              padding:10px 14px;
              border-radius:12px 12px 0 0;
            ">
              <h4 style="margin:0;">${safeTitle} records (0).</h4>
              <div class="records-header-actions">
                <button onclick="makeDraggable(this)" class="record-popout-btn">
                  <span class="material-icons" aria-hidden="true">open_in_new</span>
                </button>
              </div>
            </div>
            <div style="padding:16px;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 12px 12px;background:#fff;">
              <div class="records-card-empty">No activities yet.</div>
            </div>
          </div>
        `;
      }
      continue;
    }
    const recordsList = listRecords;
    const normalizedObject = String(objectName || "").toLowerCase();
    const isLeadObject = normalizedObject === "lead" || normalizedObject === "leads";

    if (isLeadObject) {
      const recordCount = recordsList.length;
      const getRecordField = (record, candidates) => {
        const keys = Object.keys(record || {});
        const lookup = new Map(keys.map((key) => [key.toLowerCase(), key]));
        for (const candidate of candidates) {
          const match = lookup.get(candidate.toLowerCase());
          if (!match) continue;
          const value = record[match];
          if (value !== null && value !== undefined && value !== "") {
            return value;
          }
        }
        return "";
      };
      const safeText = (value) => {
        if (value === null || value === undefined || value === "") return "";
        return escapeHtml(String(value));
      };

      const headerPartnerLabel = recordsList.map(getPartnerLabel).find(Boolean);
      const headerPartnerPill = headerPartnerLabel
        ? `<span class="records-partner-pill">${safeText(headerPartnerLabel)}</span>`
        : "";

      const leadCards = recordsList.map((record) => {
        const firstName = getRecordField(record, ["first_name", "firstname", "first", "given_name"]);
        const lastName = getRecordField(record, ["last_name", "lastname", "last", "surname"]);
        const fullName = [firstName, lastName].filter(Boolean).join(" ").trim();
        const displayName = fullName
          || getRecordField(record, ["name", "full_name", "fullname"])
          || "Unnamed Lead";

        const email = getRecordField(record, ["email", "email_address"]);
        const phone = getRecordField(record, [
          "phone",
          "phone_number",
          "mobile",
          "mobile_phone",
          "mobilephone",
          "phone_number__c",
          "mobile_phone__c",
        ]);
        const company = getRecordField(record, ["company", "account", "account_name"]);
        const title = getRecordField(record, ["title", "job_title"]);
        const status = getRecordField(record, ["status", "lead_status"]);
        const source = getRecordField(record, ["lead_source", "source"]);
        const recordId = getRecordField(record, ["id", "record_id", "lead_id", "leadid", "sfid", "salesforce_id"]);

        const rows = [];
        if (email) rows.push(`<div class="records-lead-row"><span class="records-lead-label">Email</span><span class="records-lead-value">${safeText(email)}</span></div>`);
        rows.push(`<div class="records-lead-row"><span class="records-lead-label">Phone</span><span class="records-lead-value">${phone ? safeText(phone) : "—"}</span></div>`);
        if (company) rows.push(`<div class="records-lead-row"><span class="records-lead-label">Company</span><span class="records-lead-value">${safeText(company)}</span></div>`);
        if (title) rows.push(`<div class="records-lead-row"><span class="records-lead-label">Title</span><span class="records-lead-value">${safeText(title)}</span></div>`);
        if (source) rows.push(`<div class="records-lead-row"><span class="records-lead-label">Source</span><span class="records-lead-value">${safeText(source)}</span></div>`);

        const partnerTag = getRecordField(record, ["_partner_label", "partner_label"]);
        const partnerPill = partnerTag ? `<span class="records-partner-pill">${safeText(partnerTag)}</span>` : "";
        const statusPill = status ? `<span class="records-lead-pill">${safeText(status)}</span>` : "";
        const viewButton = recordId
          ? `<button type="button" class="record-list-view-btn records-lead-view" data-record-id="${escapeHtml(String(recordId))}" data-object="${escapeHtml(String(objectName))}" aria-label="View lead" title="View lead">
              <span class="material-icons" aria-hidden="true">visibility</span>
            </button>`
          : "";
        const actions = [partnerPill, statusPill].filter(Boolean).join("");

        const cardAttrs = recordId
          ? `data-record-id="${escapeHtml(String(recordId))}" data-object="${escapeHtml(String(objectName))}" role="button" tabindex="0"`
          : "";
        const cardClass = recordId ? "records-lead-card is-clickable" : "records-lead-card";

        return `
          <div class="${cardClass}" ${cardAttrs}>
            <div class="records-lead-top">
              <div class="records-lead-name">${safeText(displayName)}</div>
              ${actions ? `<div class="records-lead-actions">${actions}</div>` : ""}
            </div>
            <div class="records-lead-meta">
              ${rows.length ? rows.join("") : `<div class="records-lead-empty">No details available.</div>`}
              ${viewButton ? `<div class="records-lead-view-row">${viewButton}</div>` : ""}
            </div>
          </div>
        `;
      }).join("");

      const leadIdCandidates = ["id", "record_id", "lead_id", "leadid", "sfid", "salesforce_id"];
      const allFields = Object.keys(recordsList[0] || {}).filter((field) => !String(field).startsWith("_"));
      const lowerFields = allFields.map((field) => String(field).toLowerCase());
      const hasTable = allFields.length > 0;
      const hasViewField = lowerFields.includes("view_record") || lowerFields.includes("view_quote");
      const hasRecordIds = recordsList.some((record) => resolveRecordFieldValue(record, leadIdCandidates));
      const tableFields = orderListFields(
        hasViewField || !hasRecordIds ? allFields : [...allFields, "view_record"]
      );
      const tableClass = `records-table records-table--${String(objectName || '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')}`;
      const tableHtml = hasTable ? `
        <div class="records-table-wrapper records-leads-table" data-record-object="${escapeHtml(String(objectName))}" data-fields='${escapeHtml(JSON.stringify(tableFields))}'>
          <table class="${tableClass}">
            <thead>
              <tr>${tableFields.map(f => {
                const fieldLower = String(f).toLowerCase();
                const sortable = (fieldLower === "view_record" || fieldLower === "view_quote") ? "false" : "true";
                const sortClass = sortable === "true" ? "is-sortable" : "";
                return `<th data-field="${escapeHtml(String(f))}" data-sortable="${sortable}" class="${sortClass}">${normalizeFieldName(f)}</th>`;
              }).join('')}</tr>
            </thead>
            <tbody>
              ${recordsList.map(record => `
                <tr>
                  ${tableFields.map(field => {
                    const fieldLower = String(field).toLowerCase();
                    let value = fieldLower === "view_record" || fieldLower === "view_quote"
                      ? buildListViewValue(record, fieldLower, objectName, leadIdCandidates)
                      : record[field];
                    if (value === null || value === undefined || value === "") return `<td data-field="${escapeHtml(String(field))}">—</td>`;
                    if (isBooleanValue(value)) {
                      return `<td class="records-boolean-cell" data-field="${escapeHtml(String(field))}">${renderBooleanIcon(value)}</td>`;
                    }
                    if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}(T.*)?$/.test(value)) {
                      const d = new Date(value);
                      if (!isNaN(d.getTime())) {
                        value = d.toLocaleDateString('en-US', {
                          year:"numeric",month:"2-digit",day:"2-digit"
                        });
                      }
                    } else if (isMoneyField(field)) {
                      const num = typeof value === "number" ? value : parseFloat(value);
                      value = isNaN(num) ? value : formatCurrency(num);
                    }
                    return `<td data-field="${escapeHtml(String(field))}">${value}</td>`;
                  }).join('')}
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
      ` : "";

      html += `
        <div class="email-alert-container" style="margin-bottom:10px; position:relative;"${hasTable ? ` data-record-object="${escapeHtml(String(objectName))}"` : ""}>
          <div class="email-alert-header" style="
            display:flex;
            justify-content:space-between;
            align-items:center;
            background: linear-gradient(135deg, #041530, #233049);
            color:#fff;
            padding:10px 14px;
            border-radius:12px 12px 0 0;
          ">
            <div class="records-header-title">
              <h4 style="margin:0;">${objectName} records (${formatNumber(recordCount)}).</h4>
              ${headerPartnerPill}
            </div>
            <div class="records-header-actions">
              ${hasTable ? `
              <button type="button" class="records-columns-btn" data-object="${escapeHtml(String(objectName))}" aria-label="Choose columns" title="Choose columns">
                <span class="material-icons" aria-hidden="true">view_column</span>
              </button>` : ""}
              <button onclick="makeDraggable(this)" class="record-popout-btn">
                <span class="material-icons" aria-hidden="true">open_in_new</span>
              </button>
            </div>
          </div>
          ${hasTable ? `<div class="records-columns-panel" data-object="${escapeHtml(String(objectName))}"></div>` : ""}
          <div class="records-leads-grid">
            ${leadCards}
          </div>
          ${tableHtml}
        </div>
      `;
      continue;
    }

    const recordCount = recordsList.length;
    const recordIdCandidates = [
      "id",
      "record_id",
      "lead_id",
      "leadid",
      "accid",
      "contactid",
      "oppid",
      "prdid",
      "qteid",
      "activityid",
      "tenant_id",
      "external_id",
      "hs_deal_id",
      "sfid",
      "salesforce_id",
      "custom_identifier",
    ];
    const headerPartnerLabel = recordsList.map(getPartnerLabel).find(Boolean);
    const headerPartnerPill = headerPartnerLabel
      ? `<span class="records-partner-pill">${escapeHtml(String(headerPartnerLabel))}</span>`
      : "";
    const allFields = Object.keys(recordsList[0] || {}).filter((field) => !String(field).startsWith("_"));
    const lowerFields = allFields.map((field) => String(field).toLowerCase());
    const hasViewQuote = lowerFields.includes("view_quote");
    const hasViewRecord = lowerFields.includes("view_record");
    const hasRecordIds = recordsList.some((record) => resolveRecordFieldValue(record, recordIdCandidates));
    const hasQuoteIds = lowerFields.includes("qteid");
    const isQuoteObject = hasViewQuote || hasQuoteIds || normalizedObject === "quote" || normalizedObject === "quotes";
    const viewField = isQuoteObject ? "view_quote" : "view_record";
    const tableFields = orderListFields(
      (hasViewQuote || hasViewRecord || !hasRecordIds) ? allFields : [...allFields, viewField]
    );
    const normalizedSlug = String(objectName || "").toLowerCase().replace(/[^a-z0-9]+/g, '-');
    const tableClass = `records-table records-table--${normalizedSlug}`;
    const cardGridClass = `records-card-grid records-card-grid--${normalizedSlug}`;
    const requiredFields = normalizedSlug === "account"
      ? new Set(["phone", "phone_number"])
      : new Set();
    const isContractLine = normalizedSlug.includes("contractline");
    const contractLineFields = [
      "product",
      "product_name",
      "product_id",
      "productid",
      "product_c",
      "product__c",
      "line_type",
      "line_type_c",
      "line_type__c",
      "linetype",
      "line_typec",
    ];
    const preferredFields = [
      "phone",
      "email",
      "status",
      "stage",
      "source",
      "account",
      "account_name",
      "company",
      "title",
      "amount",
      "expected_close_date",
      "estimated_close_date",
      "website",
      "industry",
      "city",
      "state",
      "zip_code",
      "created_at",
    ];

    const recordCards = recordsList.map((record, index) => {
      const keys = Object.keys(record || {}).filter((key) => !String(key).startsWith("_"));
      const keyMap = new Map(keys.map((key) => [key.toLowerCase(), key]));

      const getFieldInfo = (candidates) => {
        for (const candidate of candidates) {
          const key = keyMap.get(candidate.toLowerCase());
          if (!key) continue;
          const value = record[key];
          if (value !== null && value !== undefined && value !== "") {
            return { key, value };
          }
        }
        return { key: null, value: "" };
      };

      const firstInfo = getFieldInfo(["first_name", "firstname", "first", "given_name"]);
      const lastInfo = getFieldInfo(["last_name", "lastname", "last", "surname"]);
      const nameInfo = getFieldInfo(["name", "title", "subject", "full_name", "fullname"]);
      const recordInfo = getFieldInfo(["custom_identifier", "record_id"]);
      const displayName = [firstInfo.value, lastInfo.value].filter(Boolean).join(" ").trim()
        || nameInfo.value
        || recordInfo.value
        || `Record ${index + 1}`;

      const statusInfo = getFieldInfo(["status", "stage"]);
      const partnerTag = getPartnerLabel(record);
      const partnerPill = partnerTag
        ? `<span class="records-partner-pill">${escapeHtml(String(partnerTag))}</span>`
        : "";
      const statusPill = statusInfo.value
        ? `<span class="records-card-pill">${escapeHtml(String(statusInfo.value))}</span>`
        : "";
      const pills = [partnerPill, statusPill].filter(Boolean).join("");

      const recordIdInfo = getFieldInfo([
        "id",
        "record_id",
        "lead_id",
        "leadid",
        "accid",
        "contactid",
        "oppid",
        "prdid",
        "qteid",
        "activityid",
        "tenant_id",
        "external_id",
        "hs_deal_id",
        "sfid",
        "salesforce_id",
        "custom_identifier",
      ]);
      const viewButton = recordIdInfo.value
        ? `<button type="button" class="record-list-view-btn records-card-view" data-record-id="${escapeHtml(String(recordIdInfo.value))}" data-object="${escapeHtml(String(objectName))}" aria-label="View record" title="View record">
            <span class="material-icons" aria-hidden="true">visibility</span>
          </button>`
        : "";

      const skipFields = new Set(["id", "record_id", "lead_id", "sfid", "salesforce_id", "custom_identifier"]);
      if (nameInfo.key) skipFields.add(nameInfo.key.toLowerCase());
      if (firstInfo.key) skipFields.add(firstInfo.key.toLowerCase());
      if (lastInfo.key) skipFields.add(lastInfo.key.toLowerCase());
      if (statusInfo.key) skipFields.add(statusInfo.key.toLowerCase());

      const fieldCandidates = [];
      if (isContractLine) {
        contractLineFields.forEach((candidate) => {
          const key = keyMap.get(candidate.toLowerCase());
          if (key && !fieldCandidates.includes(key)) {
            fieldCandidates.push(key);
          }
        });
      } else {
        preferredFields.forEach((candidate) => {
          const key = keyMap.get(candidate.toLowerCase());
          if (key && !fieldCandidates.includes(key)) {
            fieldCandidates.push(key);
          }
        });
        keys.forEach((key) => {
          if (!fieldCandidates.includes(key)) {
            fieldCandidates.push(key);
          }
        });
      }

      const rows = [];
      const maxFields = isContractLine ? 2 : 12;
      for (const fieldKey of fieldCandidates) {
        if (rows.length >= maxFields) break;
        if (skipFields.has(fieldKey.toLowerCase())) continue;
        const formatted = formatRecordValue(fieldKey, record[fieldKey]);
        const fieldLower = fieldKey.toLowerCase();
        if (formatted === "—" && !requiredFields.has(fieldLower)) continue;
        const valueHtml = (fieldLower === "view_record" || fieldLower === "view_quote")
          ? String(formatted)
          : escapeHtml(String(formatted));
        rows.push(
          `<div class="records-card-row" data-field="${escapeHtml(fieldLower)}"><span class="records-card-label">${normalizeFieldName(fieldKey)}</span><span class="records-card-value">${valueHtml}</span></div>`
        );
      }

      if (viewButton) {
        rows.push(`<div class="records-card-row records-card-view-inline" data-field="view_record">
          <span class="records-card-label">View record</span>
          <span class="records-card-value">${viewButton}</span>
        </div>`);
      }

      const cardAttrs = recordIdInfo.value
        ? `data-record-id="${escapeHtml(String(recordIdInfo.value))}" data-object="${escapeHtml(String(objectName))}" role="button" tabindex="0"`
        : "";
      const cardClass = recordIdInfo.value
        ? `records-card records-card--${escapeHtml(normalizedSlug)} is-clickable`
        : `records-card records-card--${escapeHtml(normalizedSlug)}`;

      return `
        <div class="${cardClass}" ${cardAttrs}>
          <div class="records-card-top">
            <div class="records-card-title">${escapeHtml(String(displayName))}</div>
            ${pills ? `<div class="records-card-pills">${pills}</div>` : ""}
          </div>
          <div class="records-card-meta">
            ${rows.length ? rows.join("") : `<div class="records-card-empty">No details available.</div>`}
          </div>
        </div>
      `;
    }).join("");

    const hasTable = allFields.length > 0;
    const tableHtml = hasTable ? `
      <div class="records-table-wrapper records-table-wrapper--list" data-record-object="${escapeHtml(String(objectName))}" data-fields='${escapeHtml(JSON.stringify(tableFields))}'>
        <table class="${tableClass}">
          <thead>
            <tr>${tableFields.map(f => {
              const fieldLower = String(f).toLowerCase();
              const sortable = (fieldLower === "view_record" || fieldLower === "view_quote") ? "false" : "true";
              const sortClass = sortable === "true" ? "is-sortable" : "";
              return `<th data-field="${escapeHtml(String(f))}" data-sortable="${sortable}" class="${sortClass}">${normalizeFieldName(f)}</th>`;
            }).join('')}</tr>
          </thead>
          <tbody>
            ${recordsList.map(record => `
              <tr>
                ${tableFields.map(field => {
                  const fieldLower = String(field).toLowerCase();
                  const rawValue = (fieldLower === "view_record" || fieldLower === "view_quote")
                    ? buildListViewValue(record, fieldLower, objectName, recordIdCandidates)
                    : record[field];
                  if (rawValue === null || rawValue === undefined || rawValue === "") {
                    return `<td data-field="${escapeHtml(String(field))}">—</td>`;
                  }
                  if (isBooleanValue(rawValue)) {
                    return `<td class="records-boolean-cell" data-field="${escapeHtml(String(field))}">${renderBooleanIcon(rawValue)}</td>`;
                  }
                  const formatted = formatRecordValue(field, rawValue);
                  const valueHtml = (fieldLower === "view_record" || fieldLower === "view_quote")
                    ? String(formatted)
                    : escapeHtml(String(formatted));
                  return `<td data-field="${escapeHtml(String(field))}">${valueHtml}</td>`;
                }).join('')}
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
    ` : "";

    html += `
      <div class="email-alert-container" style="margin-bottom:10px; position:relative;"${hasTable ? ` data-record-object="${escapeHtml(String(objectName))}"` : ""}>
        <div class="email-alert-header" style="
          display:flex;
          justify-content:space-between;
          align-items:center;
          background: linear-gradient(135deg, #041530, #233049);
          color:#fff;
          padding:10px 14px;
          border-radius:12px 12px 0 0;
        ">
          <h4 style="margin:0;">${objectName} records (${formatNumber(recordCount)}).</h4>
          <div class="records-header-actions">
            ${hasTable ? `
            <button type="button" class="records-columns-btn" data-object="${escapeHtml(String(objectName))}" aria-label="Choose columns" title="Choose columns">
              <span class="material-icons" aria-hidden="true">view_column</span>
            </button>` : ""}
            <button onclick="makeDraggable(this)" class="record-popout-btn">
              <span class="material-icons" aria-hidden="true">open_in_new</span>
            </button>
          </div>
        </div>
        ${hasTable ? `<div class="records-columns-panel" data-object="${escapeHtml(String(objectName))}"></div>` : ""}
        <div class="${cardGridClass}">
          ${recordCards || `<div class="records-card-empty">No details available.</div>`}
        </div>
        ${tableHtml}
      </div>
    `;
  }

  // Función global para hacer popup draggable
  if (!window.makeDraggableAdded) {
    const script = document.createElement('script');
    script.innerHTML = `
      function makeDraggable(button) {
        const container = button.closest('.email-alert-container');
        if (!container) return;

        if (!container.classList.contains('popup')) {
          container.style.position = 'fixed';
          container.style.top = '50px';
          container.style.left = '50px';
          container.style.width = '700px';
          container.style.height = '500px';
          container.style.background = 'white';
          container.style.border = '1px solid #ccc';
          container.style.borderRadius = '5px';
          container.style.boxShadow = '0 4px 12px rgba(0,0,0,0.2)';
          container.style.zIndex = '2147483000';
          container.style.overflow = 'auto';
          container.style.resize = 'both';
          container.classList.add('popup');

          const header = container.querySelector('.email-alert-header');
          let offsetX = 0, offsetY = 0, isDown = false;

          header.style.cursor = 'move';
          header.onmousedown = function(e) {
            isDown = true;
            offsetX = e.clientX - container.getBoundingClientRect().left;
            offsetY = e.clientY - container.getBoundingClientRect().top;
            document.onmousemove = function(e) {
              if (!isDown) return;
              container.style.left = e.clientX - offsetX + 'px';
              container.style.top = e.clientY - offsetY + 'px';
            }
            document.onmouseup = function() {
              isDown = false;
              document.onmousemove = null;
              document.onmouseup = null;
            }
          }

          button.innerHTML = '<span class="material-icons" aria-hidden="true">close</span>';
        } else {
          container.style.position = '';
          container.style.top = '';
          container.style.left = '';
          container.style.width = '';
          container.style.height = '';
          container.style.background = '';
          container.style.border = '';
          container.style.boxShadow = '';
          container.style.zIndex = '';
          container.style.overflow = '';
          container.style.resize = '';
          container.classList.remove('popup');
          button.innerHTML = '<span class="material-icons" aria-hidden="true">open_in_new</span>';
        }
      }

      if (!window.toggleAggDetails) {
        window.toggleAggDetails = function(id, btn) {
          const details = document.getElementById(id + "-details");
          if (!details) return;
          const isOpen = details.classList.toggle("is-open");
          if (btn) {
            btn.textContent = isOpen ? "Hide details" : "View details";
          }
        }
      }

      if (!window.renderAggChart) {
        window.renderAggChart = function(id) {
          const canvas = document.getElementById(id + "-chart-canvas");
          if (!canvas) return;
          const labels = JSON.parse(canvas.dataset.labels || "[]");
          const values = JSON.parse(canvas.dataset.values || "[]");
          const isMoney = canvas.dataset.money === "1";
          const intent = String(canvas.dataset.intent || "comparison").toLowerCase();
          const isTrend = intent === "trend";
          const chartType = isTrend ? "line" : "bar";
          const seriesLabel = canvas.dataset.seriesLabel || (isMoney ? "Revenue" : "Total");
          const ctx = canvas.getContext("2d");
          const barColor = "#2563eb";
          if (canvas._chartInstance) {
            canvas._chartInstance.destroy();
          }
          canvas._chartInstance = new Chart(ctx, {
            type: chartType,
            data: {
              labels,
              datasets: [
                {
                  label: seriesLabel,
                  data: values,
                  borderColor: isTrend ? "#2563eb" : "#1d4ed8",
                  tension: 0.35,
                  fill: isTrend,
                  pointRadius: isTrend ? 3 : 0,
                  pointHoverRadius: isTrend ? 5 : 0,
                  pointHitRadius: isTrend ? 8 : 0,
                  pointBorderWidth: isTrend ? 2 : 0,
                  pointBorderColor: "#1d4ed8",
                  pointBackgroundColor: isTrend ? "#ffffff" : "#1d4ed8",
                  borderWidth: 2,
                  backgroundColor: isTrend ? "rgba(37, 99, 235, 0.12)" : barColor,
                  borderRadius: isTrend ? 0 : 6,
                  barThickness: isTrend ? undefined : 20
                }
              ]
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              layout: {
                padding: isTrend
                  ? { top: 8, right: 8, bottom: 8, left: 8 }
                  : { top: 4, right: 4, bottom: 4, left: 4 }
              },
              plugins: {
                legend: {
                  display: false,
                  position: "top",
                  labels: {
                    font: { size: 12 },
                    color: "#111827"
                  }
                },
                tooltip: {
                  callbacks: {
                    label: (ctx) => {
                      const parsed = ctx.parsed;
                      const val = typeof parsed === "number"
                        ? parsed
                        : (parsed && typeof parsed.y !== "undefined" ? parsed.y : 0);
                      return isMoney ? "$" + val.toLocaleString("en-US") : val.toLocaleString("en-US");
                    }
                  }
                }
              },
              scales: isTrend ? {
                x: { display: false },
                y: { display: false }
              } : {
                x: {
                  ticks: { color: "#64748b" },
                  grid: { display: false }
                },
                y: {
                  beginAtZero: true,
                  ticks: {
                    color: "#64748b",
                    callback: (val) => isMoney ? "$" + Number(val).toLocaleString("en-US") : Number(val).toLocaleString("en-US")
                  },
                  grid: { color: "rgba(148, 163, 184, 0.18)" }
                }
              }
            }
          });
        };
      }

      if (!window.loadChartJs) {
        window.chartJsLoading = false;
        window.loadChartJs = function(cb) {
          if (window.Chart) return cb && cb();
          if (window.chartJsLoading) {
            document.addEventListener("chartjs-ready", function handler() {
              document.removeEventListener("chartjs-ready", handler);
              cb && cb();
            });
            return;
          }
          window.chartJsLoading = true;
          const script = document.createElement("script");
          script.src = "https://cdn.jsdelivr.net/npm/chart.js";
          script.onload = () => {
            window.chartJsLoading = false;
            document.dispatchEvent(new Event("chartjs-ready"));
            cb && cb();
          };
          document.head.appendChild(script);
        };
      }
    `;
    document.body.appendChild(script);
    window.makeDraggableAdded = true;
  }

    if (userMessage) {
      const cleanMessage = userMessage.split("retrieved_records:")[0];
      html += `<div style="margin-bottom:10px;"><p>${cleanMessage}</p></div>`;
    }

    return html;
  } catch (e) {
    console.warn("renderRetrievedRecords failed:", e);
    return `<div class="error-message">Unable to display records.</div>`;
  }
}

const listRecordLayoutCache = {};

async function fetchListRecordLayout(objectName) {
  const key = String(objectName || "");
  if (!key) return { order: [], hidden: [] };
  if (listRecordLayoutCache[key]) return listRecordLayoutCache[key];
  try {
    const response = await fetch(`/agents/list-record-layout/?object=${encodeURIComponent(key)}`);
    const data = await response.json();
    const layout = {
      order: Array.isArray(data.order) ? data.order : [],
      hidden: Array.isArray(data.hidden) ? data.hidden : []
    };
    listRecordLayoutCache[key] = layout;
    return layout;
  } catch (err) {
    console.warn("Failed to load list layout:", err);
    return { order: [], hidden: [] };
  }
}

async function saveListRecordLayout(objectName, layout) {
  const key = String(objectName || "");
  if (!key) return;
  listRecordLayoutCache[key] = layout;
  try {
    await fetch("/agents/list-record-layout/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        object: key,
        order: Array.isArray(layout.order) ? layout.order : [],
        hidden: Array.isArray(layout.hidden) ? layout.hidden : []
      })
    });
  } catch (err) {
    console.warn("Failed to save list layout:", err);
  }
}

function applyListColumnVisibility(table, hiddenFields) {
  if (!table) return;
  const hiddenSet = new Set((hiddenFields || []).map((f) => String(f).toLowerCase()));
  table.querySelectorAll("th[data-field], td[data-field]").forEach((cell) => {
    const key = String(cell.dataset.field || "").toLowerCase();
    if (!key) return;
    if (hiddenSet.has(key)) {
      cell.classList.add("records-col-hidden");
    } else {
      cell.classList.remove("records-col-hidden");
    }
  });
}

function reorderTableColumns(table, orderedFields) {
  if (!table || !Array.isArray(orderedFields) || orderedFields.length === 0) return;
  const orderKeys = orderedFields.map((field) => String(field).toLowerCase());

  const reorderCells = (row) => {
    const cells = Array.from(row.children).filter((cell) => cell.matches("th, td"));
    if (!cells.length) return;
    const cellMap = new Map();
    cells.forEach((cell, index) => {
      const key = String(cell.dataset.field || "").toLowerCase();
      if (!key) return;
      cellMap.set(key, { cell, index });
    });
    const ordered = [];
    const used = new Set();
    orderKeys.forEach((key) => {
      const entry = cellMap.get(key);
      if (!entry) return;
      if (used.has(entry.cell)) return;
      ordered.push(entry.cell);
      used.add(entry.cell);
    });
    cells.forEach((cell) => {
      if (used.has(cell)) return;
      ordered.push(cell);
    });
    ordered.forEach((cell) => row.appendChild(cell));
  };

  const headRow = table.tHead && table.tHead.rows.length ? table.tHead.rows[0] : null;
  if (headRow) {
    reorderCells(headRow);
  }
  const body = table.tBodies && table.tBodies.length ? table.tBodies[0] : null;
  if (body) {
    Array.from(body.rows).forEach(reorderCells);
  }
}

function parseSortValue(text) {
  if (text === null || text === undefined) return { type: "empty", value: "" };
  const raw = String(text).trim();
  if (!raw || raw === "—") return { type: "empty", value: "" };

  const lowered = raw.toLowerCase();
  if (lowered === "yes" || lowered === "no") {
    return { type: "boolean", value: lowered === "yes" ? 1 : 0 };
  }

  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) {
    const parsed = Date.parse(raw);
    if (!Number.isNaN(parsed)) {
      return { type: "date", value: parsed };
    }
  }
  if (/^\d{1,2}\/\d{1,2}\/\d{2,4}$/.test(raw)) {
    const parts = raw.split("/");
    const month = parseInt(parts[0], 10);
    const day = parseInt(parts[1], 10);
    let year = parseInt(parts[2], 10);
    if (year < 100) year += 2000;
    const parsed = new Date(year, month - 1, day).getTime();
    if (!Number.isNaN(parsed)) {
      return { type: "date", value: parsed };
    }
  }

  const numeric = raw.replace(/[^0-9.\-]/g, "");
  if (numeric && numeric !== "-" && numeric !== "." && numeric !== "-.") {
    const parsed = parseFloat(numeric);
    if (!Number.isNaN(parsed)) {
      return { type: "number", value: parsed };
    }
  }

  return { type: "string", value: lowered };
}

function detectColumnType(rows, field) {
  for (const row of rows) {
    const cell = getCellByField(row, field);
    if (!cell) continue;
    const parsed = parseSortValue(cell.textContent);
    if (parsed.type !== "empty") {
      return parsed.type;
    }
  }
  return "string";
}

function getCellByField(row, field) {
  const target = String(field || "").toLowerCase();
  if (!target) return null;
  const cells = Array.from(row.querySelectorAll("td[data-field]"));
  return cells.find((cell) => String(cell.dataset.field || "").toLowerCase() === target) || null;
}

function sortTableByField(table, field, order) {
  if (!table) return;
  const body = table.tBodies && table.tBodies.length ? table.tBodies[0] : null;
  if (!body) return;
  const rows = Array.from(body.rows);
  if (!rows.length) return;

  const columnType = detectColumnType(rows, field);
  const direction = order === "asc" ? 1 : -1;
  const rowsWithIndex = rows.map((row, index) => ({ row, index }));

  rowsWithIndex.sort((a, b) => {
    const aCell = getCellByField(a.row, field);
    const bCell = getCellByField(b.row, field);
    const aValue = parseSortValue(aCell ? aCell.textContent : "");
    const bValue = parseSortValue(bCell ? bCell.textContent : "");

    if (aValue.type === "empty" && bValue.type === "empty") {
      return a.index - b.index;
    }
    if (aValue.type === "empty") return 1;
    if (bValue.type === "empty") return -1;

    let comparison = 0;
    if (columnType === "number" || columnType === "date" || columnType === "boolean") {
      comparison = (aValue.value || 0) - (bValue.value || 0);
    } else {
      comparison = String(aValue.value).localeCompare(String(bValue.value));
    }

    if (comparison === 0) {
      return a.index - b.index;
    }
    return comparison * direction;
  });

  rowsWithIndex.forEach(({ row }) => {
    body.appendChild(row);
  });
}

function applyTableSortIndicator(table, field, order) {
  if (!table) return;
  const fieldKey = String(field || "").toLowerCase();
  const headers = table.querySelectorAll("th[data-field]");
  headers.forEach((header) => {
    const headerKey = String(header.dataset.field || "").toLowerCase();
    if (fieldKey && headerKey === fieldKey) {
      header.classList.add("is-sorted");
      header.dataset.sortOrder = order;
    } else {
      header.classList.remove("is-sorted");
      header.removeAttribute("data-sort-order");
    }
  });
}

function initializeRecordTableSorting(table) {
  if (!table || table.dataset.sortReady === "true") return;
  const headers = table.querySelectorAll("th[data-field]");
  headers.forEach((header) => {
    const sortable = header.dataset.sortable !== "false";
    if (!sortable) return;
    header.classList.add("is-sortable");
    header.addEventListener("click", () => {
      const field = header.dataset.field;
      if (!field) return;
      const current = header.dataset.sortOrder || "desc";
      const nextOrder = current === "asc" ? "desc" : "asc";
      sortTableByField(table, field, nextOrder);
      applyTableSortIndicator(table, field, nextOrder);
      table.dataset.sortField = field;
      table.dataset.sortOrder = nextOrder;
    });
  });

  if (table.dataset.sortField && table.dataset.sortOrder) {
    applyTableSortIndicator(table, table.dataset.sortField, table.dataset.sortOrder);
  }
  table.dataset.sortReady = "true";
}

function buildListColumnsPanel(panel, fields, hiddenFields, onToggle, onReorder) {
  const hiddenSet = new Set((hiddenFields || []).map((f) => String(f).toLowerCase()));
  const rows = fields.map((field) => {
    const key = String(field);
    const keyLower = key.toLowerCase();
    const checked = hiddenSet.has(keyLower) ? "" : "checked";
    return `
      <div class="records-columns-row" data-field="${escapeHtml(key)}" draggable="true">
        <span class="material-icons records-columns-drag" aria-hidden="true">drag_indicator</span>
        <label class="records-columns-item">
          <input type="checkbox" data-field="${escapeHtml(key)}" ${checked}>
          <span>${normalizeFieldName(key)}</span>
        </label>
      </div>
    `;
  }).join("");

  panel.innerHTML = `
    <div class="records-columns-title">
      <span>Columns</span>
      <button type="button" class="records-columns-close" aria-label="Close columns panel">
        <span class="material-icons" aria-hidden="true">close</span>
      </button>
    </div>
    <div class="records-columns-list">
      ${rows}
    </div>
  `;

  const closeBtn = panel.querySelector(".records-columns-close");
  if (closeBtn) {
    closeBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      panel.classList.remove("is-open");
    });
  }

  panel.querySelectorAll("input[type='checkbox']").forEach((input) => {
    input.addEventListener("change", () => {
      const key = String(input.dataset.field || "").toLowerCase();
      if (!key) return;
      if (input.checked) {
        hiddenSet.delete(key);
      } else {
        hiddenSet.add(key);
      }
      onToggle(Array.from(hiddenSet));
    });
  });

  const list = panel.querySelector(".records-columns-list");
  if (!list) return;

  let dragItem = null;
  list.addEventListener("dragstart", (event) => {
    if (event.target.closest("input[type='checkbox']")) {
      event.preventDefault();
      return;
    }
    dragItem = event.target.closest(".records-columns-row");
    if (!dragItem) return;
    dragItem.classList.add("is-dragging");
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", dragItem.dataset.field || "");
    }
  });

  list.addEventListener("dragover", (event) => {
    if (!dragItem) return;
    event.preventDefault();
    const targetRow = event.target.closest(".records-columns-row");
    if (!targetRow || targetRow === dragItem) return;
    const rect = targetRow.getBoundingClientRect();
    const shouldInsertBefore = event.clientY < rect.top + rect.height / 2;
    if (shouldInsertBefore) {
      list.insertBefore(dragItem, targetRow);
    } else {
      list.insertBefore(dragItem, targetRow.nextSibling);
    }
  });

  list.addEventListener("drop", () => {
    if (!dragItem) return;
    const newOrder = Array.from(list.querySelectorAll(".records-columns-row"))
      .map((row) => row.dataset.field)
      .filter(Boolean);
    if (typeof onReorder === "function") {
      onReorder(newOrder);
    }
  });

  list.addEventListener("dragend", () => {
    if (dragItem) {
      dragItem.classList.remove("is-dragging");
    }
    dragItem = null;
  });
}

async function initializeRecordListLayouts(root = document) {
  const containers = root.querySelectorAll(".email-alert-container[data-record-object]");
  containers.forEach(async (container) => {
    if (container.dataset.columnsReady === "true") return;
    const objectName = container.dataset.recordObject;
    const tableWrapper = container.querySelector(".records-table-wrapper[data-fields]");
    const panel = container.querySelector(".records-columns-panel");
    const columnsBtn = container.querySelector(".records-columns-btn");
    if (!objectName || !tableWrapper || !panel || !columnsBtn) return;

    let fields = [];
    try {
      fields = JSON.parse(tableWrapper.dataset.fields || "[]");
    } catch (err) {
      fields = [];
    }
    if (!Array.isArray(fields) || fields.length === 0) return;

    const table = tableWrapper.querySelector("table");
    const layout = await fetchListRecordLayout(objectName);
    const normalizedOrder = Array.isArray(layout.order) ? layout.order : [];
    let orderedFields = normalizedOrder.length
      ? [...normalizedOrder.filter((field) => fields.includes(field)), ...fields.filter((field) => !normalizedOrder.includes(field))]
      : fields;
    let hidden = Array.isArray(layout.hidden) ? layout.hidden : [];

    reorderTableColumns(table, orderedFields);
    applyListColumnVisibility(table, hidden);
    initializeRecordTableSorting(table);
    if (table && table.dataset.sortField && table.dataset.sortOrder) {
      applyTableSortIndicator(table, table.dataset.sortField, table.dataset.sortOrder);
    }

    buildListColumnsPanel(panel, orderedFields, hidden, (updatedHidden) => {
      hidden = updatedHidden;
      applyListColumnVisibility(table, updatedHidden);
      saveListRecordLayout(objectName, { order: orderedFields, hidden: updatedHidden });
    }, (newOrder) => {
      orderedFields = Array.isArray(newOrder) && newOrder.length ? newOrder : orderedFields;
      reorderTableColumns(table, orderedFields);
      if (tableWrapper) {
        tableWrapper.dataset.fields = JSON.stringify(orderedFields);
      }
      saveListRecordLayout(objectName, { order: orderedFields, hidden });
    });

    columnsBtn.addEventListener("click", () => {
      panel.classList.toggle("is-open");
    });

    container.dataset.columnsReady = "true";
  });
}

function initializeMetricCards(root = document) {
  const canvases = root.querySelectorAll(".records-metric-chart canvas");
  canvases.forEach((canvas) => {
    if (canvas.dataset.chartReady === "true") return;
    const aggId = canvas.id.replace(/-chart-canvas$/, "");
    const initChart = () => {
      if (window.renderAggChart && aggId) {
        window.renderAggChart(aggId);
      }
    };
    if (window.Chart) {
      initChart();
    } else if (window.loadChartJs) {
      window.loadChartJs(initChart);
    }
    canvas.dataset.chartReady = "true";
  });
}

// =====================================================
// ✅ POPUP con overlay + drag (de la primera versión)
// =====================================================

function openRecordsPopout(button) {
  const source = button.closest('.records-container');
  if (!source) return;

  // Crear popup
  const popup = document.createElement('div');
  popup.className = 'popup';
  popup.style.position = 'fixed';
  popup.style.top = '50%';
  popup.style.left = '50%';
  popup.style.transform = 'translate(-50%, -50%)';
  popup.style.width = '800px';
  popup.style.maxWidth = '90vw';
  popup.style.background = '#fff';
  popup.style.borderRadius = '1rem';
  popup.style.boxShadow = '0 12px 30px rgba(0,0,0,0.25)';
  popup.style.zIndex = '2147483000';
  popup.style.display = 'flex';
  popup.style.flexDirection = 'column';
  popup.style.overflow = 'hidden';

  // Header
  const popupHeader = document.createElement('div');
  popupHeader.className = 'popup-header';
  popupHeader.style.background = 'linear-gradient(135deg, #041530, #233049)';
  popupHeader.style.color = 'white';
  popupHeader.style.padding = '0 1rem';
  popupHeader.style.height = '48px';
  popupHeader.style.display = 'flex';
  popupHeader.style.alignItems = 'center';
  popupHeader.style.justifyContent = 'space-between';
  popupHeader.style.borderRadius = '1rem 1rem 0 0';
  popupHeader.style.cursor = 'grab';

  const titleText = source.querySelector('.records-header h5')?.innerText || 'Records';
  const titleDiv = document.createElement('div');
  titleDiv.style.fontWeight = '600';
  titleDiv.innerText = titleText;
  popupHeader.appendChild(titleDiv);

  // Botón cerrar
  const closeBtn = document.createElement('button');
  closeBtn.innerText = '✕';
  closeBtn.style.cssText = `
    background: rgba(255,255,255,0.2);
    color: white;
    border: none;
    font-size: 1.2rem;
    cursor: pointer;
    transition: 0.2s;
  `;
  closeBtn.onmouseenter = () => closeBtn.style.color = '#fc6a3d';
  closeBtn.onmouseleave = () => closeBtn.style.color = 'white';
  closeBtn.onclick = () => popup.remove();
  popupHeader.appendChild(closeBtn);

  // Body (tabla)
  const popupBody = document.createElement('div');
  popupBody.className = 'popup-body';
  popupBody.style.flex = '1';
  popupBody.style.overflowY = 'auto';
  popupBody.style.padding = '0.5rem';
  
  const clonedWrapper = source.querySelector('.records-table-wrapper').cloneNode(true);
  clonedWrapper.style.maxHeight = 'none';
  clonedWrapper.style.overflow = 'visible';
  popupBody.appendChild(clonedWrapper);

  popup.appendChild(popupHeader);
  popup.appendChild(popupBody);
  document.body.appendChild(popup);

  // Ajuste de altura dinámica según ventana
  requestAnimationFrame(() => {
    const maxBody = Math.round(window.innerHeight * 0.8) - popupHeader.getBoundingClientRect().height;
    popupBody.style.maxHeight = maxBody + 'px';
  });

  // Dragging
  let isDragging = false, offsetX = 0, offsetY = 0;
  popupHeader.addEventListener('mousedown', (e) => {
    isDragging = true;
    const rect = popup.getBoundingClientRect();
    offsetX = e.clientX - rect.left;
    offsetY = e.clientY - rect.top;
    popupHeader.style.cursor = 'grabbing';
    e.preventDefault();
  });

  window.addEventListener('mouseup', () => {
    isDragging = false;
    popupHeader.style.cursor = 'grab';
  });

  window.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    popup.style.left = `${e.clientX - offsetX}px`;
    popup.style.top = `${e.clientY - offsetY}px`;
    popup.style.transform = 'translate(0, 0)';
  });

  // Cerrar con ESC
  const onKey = (ev) => {
    if (ev.key === 'Escape') popup.remove();
  };
  window.addEventListener('keydown', onKey);

  // Limpieza al remover
  popup.addEventListener('remove', () => {
    window.removeEventListener('mouseup', () => {});
    window.removeEventListener('mousemove', () => {});
    window.removeEventListener('keydown', onKey);
  });
}

///////////////////////////////////////////////////////////
///           GRAPHIC BUILDER ACTION TRIGGER            ///
///////////////////////////////////////////////////////////

/**
 * JSON FINAL DEL ACTION TRIGGER
 * 👉 Todos los nodos escriben aquí
 */
let actionTriggerJSON = {
  description: "",
  event_type: null,
  conditions: {
    logical_operator: "AND",
    items: []
  },
  actions: []
};

/**
 * Schema de modelos CPQ
 * 👉 Viene del backend
 */
let modelSchema = {};   // { quote_line: { fields: {...} }, ... }

/**
 * Contexto disponible para drag & drop
 * 👉 Se va llenando dinámicamente
 */
let contextSources = {}; // { quote_line: schema, account: schema }

/**
 * Estado del nodo EVENT
 */
let eventNodeState = {
  configured: false,
  data: null
};

/**
 * Estado del nodo CONDITIONS
 */
let conditionsNodeState = {
  created: false
};

let conditionsDraft = {
  logical_operator: "AND",
  items: []
};

let eventDraft = null;
let eventSnapshot = null;

function renderGraphicBuilderForActionTrigger(openGraphicBuilder) {
  if (!openGraphicBuilder) return "";

  return `
    <div class="graphic-builder">

      <div class="flow-canvas">

        <!-- EVENT NODE -->
        <div id="event-node" class="flow-node event-node hidden" onclick="openEventNodeEditor()">
          <div class="node-title">Event</div>
          <div id="event-node-summary" class="node-summary">
            Not configured
          </div>
        </div>

        <!-- ADD EVENT NODE -->
        <div id="add-event-node" class="add-event-node" onclick="createEventNode()">
          <div class="plus-box">+</div>
          <div class="add-label">Add event node</div>
        </div>

        <!-- NODE EDITOR -->
        <div id="node-editor" class="node-editor hidden">

          <div class="editor-left">
            <h3>Event Type</h3>

            <div class="editor-section">
              <label>Description</label>
              <textarea id="event-description"
                        oninput="updateEventPreview()"
                        placeholder="Describe what this trigger does..."></textarea>
            </div>

            <div class="editor-section">
              <label>Object</label>
              <select id="event-object" onchange="updateEventPreview()">
                <option value="">Select object</option>
                ${renderCPQObjectOptions()}
              </select>
            </div>

            <div class="editor-section">
              <label>Action</label>
              <select id="event-action" onchange="updateEventPreview()">
                <option value="">Select action</option>
                <option value="create">Create</option>
                <option value="update">Update</option>
                <option value="delete">Delete</option>
              </select>
            </div>

            <div id="event-text-preview" class="preview-text">
              Select an object and action to describe this trigger.
            </div>

            <div class="editor-actions">
              <button class="btn-secondary" onclick="cancelEventEdit()">Cancel</button>
              <button class="btn-primary" onclick="saveEventNode()">Done</button>
            </div>
          </div>

          <div class="editor-right">
            <h4>Event JSON</h4>
            <pre id="event-json-preview">{}</pre>
          </div>

        </div>

        <!-- EVENT → NEXT CONNECTOR -->
        <div id="event-connector" class="event-connector hidden">
          <div class="connector-line"></div>

          <div class="connector-plus" onclick="toggleNextNodeMenu()">
            +
          </div>

          <div id="next-node-menu" class="next-node-menu hidden">
            <div class="next-node-option" onclick="createConditionsNode()">
              Conditions
            </div>
            <div class="next-node-option disabled">
              Actions (coming soon)
            </div>
          </div>
        </div>

      </div>
    </div>
  `;
}

function createEventNode() {
  document.getElementById("add-event-node").classList.add("hidden");
  document.getElementById("event-node").classList.remove("hidden");
  openEventNodeEditor();
}

function openEventNodeEditor() {
  // Snapshot del estado actual (lo guardado)
  const saved = eventNodeState?.data?.event_type
    ? {
        description: eventNodeState.data.description || "",
        object_name: eventNodeState.data.event_type.object_name || "",
        action: (eventNodeState.data.event_type.action || "").toLowerCase()
      }
    : { description: "", object_name: "", action: "" };

  eventSnapshot = JSON.parse(JSON.stringify(saved));
  eventDraft = JSON.parse(JSON.stringify(saved));

  // Cargar form con lo guardado
  setEventFormData(saved);

  // Mostrar editor
  document.getElementById("node-editor").classList.remove("hidden");

  // Pintar preview con lo cargado
  updateEventPreview(true);
}

function renderCPQObjectOptions() {
  const objects = [
    "Opportunity",
    "Quote",
    "QuoteLine",
    "Contract",
    "Account",
    "Subscription"
  ];

  return objects.map(o => {
    let value;

    if (o === "QuoteLine") {
      value = "quote_line";   // 👈 caso especial
    } else {
      value = o.toLowerCase();
    }

    return `<option value="${value}">${o}</option>`;
  }).join("");
}

function openEventTypePanel() {
  document.getElementById("event-type-panel").classList.remove("hidden");
}

function openEventTypeEditor() {
  document.getElementById("node-editor").classList.remove("hidden");
}

function updateEventPreview(fromSavedOrDraft = false) {
  // Siempre leemos del form y lo ponemos en draft
  const form = getEventFormData();

  if (!eventDraft) eventDraft = { description: "", object_name: "", action: "" };
  eventDraft.description = form.description;
  eventDraft.object_name = form.object_name;
  eventDraft.action = form.action;

  const description = eventDraft.description;
  const object = eventDraft.object_name;
  const action = eventDraft.action;

  let text = "Select an object and action to describe this trigger.";
  let nodeSummary = eventNodeState?.configured ? (document.getElementById("event-node-summary").innerText || "Configured") : "Not configured";

  if (object && action) {
    const label = object.charAt(0).toUpperCase() + object.slice(1);

    if (action === "create") text = `This trigger activates when a ${label} is created.`;
    if (action === "update") text = `This trigger activates when a ${label} is updated.`;
    if (action === "delete") text = `This trigger activates when a ${label} is deleted.`;

    // Solo actualiza el resumen del nodo visualmente mientras editas
    nodeSummary = `${label} · ${action.toUpperCase()}`;
  }

  document.getElementById("event-text-preview").innerText = text;

  // OJO: aquí sí puedes mostrar el summary mientras editas (como n8n),
  // pero si cancelas lo vamos a restaurar.
  document.getElementById("event-node-summary").innerText = nodeSummary;

  const json = {
    description: description || "",
    event_type: {
      object_name: object || null,
      action: action ? action.toUpperCase() : null
    }
  };

  document.getElementById("event-json-preview").innerText =
    JSON.stringify(json, null, 2);
}


function saveEventNode() {
  if (!eventDraft) eventDraft = getEventFormData();

  const description = eventDraft.description || "";
  const object = eventDraft.object_name || "";
  const action = eventDraft.action || "";

  if (!object || !action) {
    alert("Please select an object and an action.");
    return;
  }

  eventNodeState.configured = true;
  eventNodeState.data = {
    description: description,
    event_type: {
      object_name: object,
      action: action.toUpperCase()
    }
  };

  document.getElementById("event-node").classList.add("configured");

  // limpiar draft/snapshot
  eventSnapshot = null;
  eventDraft = null;

  closeEventEditor();

  // Mostrar conector hacia el siguiente nodo
  document.getElementById("event-connector")?.classList.remove("hidden");

  // Inicializar JSON global
  actionTriggerJSON.description = description;
  actionTriggerJSON.event_type = {
    object_name: object,
    action: action.toUpperCase()
  };

  // Inicializar Context Sources con el EVENT ROOT
  contextSources = {
    [object]: modelSchema[object]
  };

  console.log("✅ Event node saved:", eventNodeState.data);
}


function cancelEventEdit() {

  // CASO 1️⃣: Nodo NO configurado → volver a "Add first step"
  if (!eventNodeState.configured) {
    // Ocultar nodo
    document.getElementById("event-node").classList.add("hidden");

    // Mostrar botón inicial
    document.getElementById("add-event-node").classList.remove("hidden");

    // Resetear summary
    document.getElementById("event-node-summary").innerText = "Not configured";

    // Limpiar preview JSON
    document.getElementById("event-json-preview").innerText = "{}";

    // Limpiar texto descriptivo
    document.getElementById("event-text-preview").innerText =
      "Select an object and action to describe this trigger.";

  } 
  // CASO 2️⃣: Nodo ya configurado → restaurar snapshot
  else if (eventSnapshot) {

    setEventFormData(eventSnapshot);

    const obj = eventNodeState.data.event_type.object_name;
    const act = eventNodeState.data.event_type.action;
    const label = obj.charAt(0).toUpperCase() + obj.slice(1);

    document.getElementById("event-node-summary").innerText =
      `${label} · ${act}`;

    eventDraft = JSON.parse(JSON.stringify(eventSnapshot));
    updateEventPreview(true);
  }

  // Limpiar draft y snapshot
  eventDraft = null;
  eventSnapshot = null;

  closeEventEditor();
}

function closeEventEditor() {
  document.getElementById("node-editor").classList.add("hidden");
}


function getEventFormData() {
  return {
    description: document.getElementById("event-description")?.value || "",
    object_name: document.getElementById("event-object")?.value || "",
    action: document.getElementById("event-action")?.value || ""
  };
}

function setEventFormData(data) {
  document.getElementById("event-description").value = data?.description || "";
  document.getElementById("event-object").value = data?.object_name || "";
  document.getElementById("event-action").value = data?.action || "";

  // Si usas Materialize selects, refresca UI
  try {
    const selects = document.querySelectorAll(".graphic-builder select");
    M.FormSelect.init(selects);
  } catch (e) {}
}

function toggleNextNodeMenu() {
  document
    .getElementById("next-node-menu")
    .classList.toggle("hidden");
}

function createConditionsNode() {
  document.getElementById("next-node-menu").classList.add("hidden");

  if (conditionsNodeState.created) return;

  conditionsNodeState.created = true;

  const canvas = document.querySelector(".flow-canvas");
  canvas.insertAdjacentHTML("beforeend", renderConditionsNode());

  openConditionsEditor();

  // 🔑 RE-INICIALIZAR MATERIALIZE SELECTS
  try {
    const selects = document.querySelectorAll(
      ".graphic-builder .conditions-col-middle select"
    );
    M.FormSelect.init(selects);
  } catch (e) {
    console.warn("Materialize init failed", e);
  }
}

function renderConditionsNode() {
  return `
    <!-- CONDITIONS NODE -->
    <div id="conditions-node" class="flow-node conditions-node">
      <div class="node-title">Conditions</div>
      <div class="node-summary">Not configured</div>
    </div>

    <!-- CONDITIONS EDITOR -->
    <div id="conditions-editor" class="node-editor hidden">

      <!-- COLUMN 1 -->
      <div class="conditions-col conditions-col-left">
        ${renderConditionsColumnContext()}
      </div>

      <!-- COLUMN 2 (placeholder) -->
      <div class="conditions-col conditions-col-middle">
        <h3>Conditions</h3>
        
        <!-- LOGICAL OPERATOR -->
        <div class="conditions-section">
          <label class="section-label">Logical Operator</label>

          <select id="conditions-logical-operator"
                  onchange="updateConditionsLogicalOperator()">
            <option value="AND">
              All conditions must be true (AND)
            </option>
            <option value="OR">
              Any condition can be true (OR)
            </option>
          </select>

          <div class="section-divider"></div>
        </div>

        <!-- ITEMS -->
        <div class="conditions-section">
          <label class="section-label">Items</label>

          <button class="add-item-btn" onclick="addConditionRow()">
            +
          </button>

          <div id="conditions-items" class="conditions-items"></div>
        </div>
      </div>

      <!-- COLUMN 3 (placeholder) -->
      <div class="conditions-col conditions-col-right">
        <h4>Preview</h4>
        <pre>{}</pre>
      </div>

    </div>
  `;
}

function renderConditionsColumnContext() {
  const eventRoot = actionTriggerJSON.event_type?.object_name || "";

  return `
    <h3>When</h3>

    <div class="when-box">
      <strong>Event Root</strong>
      <div class="event-root-label">${eventRoot}</div>
    </div>

    <h4 class="section-title">Context Sources</h4>

    <div class="context-sources">
      ${renderContextSourceTree(eventRoot)}
    </div>
  `;
}

function renderContextSourceTree(objectName, path = objectName, visited = new Set()) {

  if (visited.has(objectName)) {
    return `
      <div class="context-cycle">
        ↺ ${objectName} (cycle)
      </div>
    `;
  }

  const schema = modelSchema[objectName];
  if (!schema) return "";

  visited.add(objectName);

  const fields = schema.fields || {};
  const nodeId = `${path.replace(/\./g, "_")}`;

  return `
    <div class="context-object" data-node="${nodeId}">
      <div class="context-object-header"
           onclick="toggleContextNode('${nodeId}')">
        <span class="arrow">▸</span> ${objectName}
      </div>

      <div class="context-fields hidden">
        ${Object.entries(fields).map(([fieldName, meta]) => {
          const fieldPath = `${path}.${fieldName}`;

          if (meta.type === "fk") {
            const fkNodeId = `${fieldPath.replace(/\./g, "_")}`;

            return `
              <div class="context-field fk">
                <div class="context-field-label"
                     onclick="toggleContextNode('${fkNodeId}')">
                  <span class="arrow">▸</span> ${fieldName}
                </div>

                <div class="context-nested hidden" data-node="${fkNodeId}">
                  ${renderObjectFields(
                    meta.target,
                    fieldPath,
                    new Set(visited)
                  )}
                </div>
              </div>
            `;
          }

          return `
            <div class="context-field"
                 draggable="true"
                 data-path="${fieldPath}">
              ${fieldName}
            </div>
          `;
        }).join("")}
      </div>
    </div>
  `;
}

function toggleContextNode(nodeId) {
  const container = document.querySelector(`[data-node="${nodeId}"]`);
  if (!container) return;

  let target;

  // Caso 1️⃣: object root → abrir fields
  if (container.classList.contains("context-object")) {
    target = container.querySelector(".context-fields");
  }
  // Caso 2️⃣: FK → el propio container es el nested
  else if (container.classList.contains("context-nested")) {
    target = container;
  }

  if (!target) return;

  // Flecha asociada
  const arrow = document.querySelector(
    `[onclick="toggleContextNode('${nodeId}')"] .arrow`
  );

  const isHidden = target.classList.contains("hidden");

  target.classList.toggle("hidden");

  if (arrow) {
    arrow.textContent = isHidden ? "▾" : "▸";
  }
}

function renderObjectFields(objectName, path, visited) {
  if (visited.has(objectName)) {
    return `<div class="context-cycle">↺ ${objectName} (cycle)</div>`;
  }

  const schema = modelSchema[objectName];
  if (!schema) return "";

  visited.add(objectName);

  return Object.entries(schema.fields || {}).map(([fieldName, meta]) => {
    const fieldPath = `${path}.${fieldName}`;

    if (meta.type === "fk") {
      const fkNodeId = fieldPath.replace(/\./g, "_");

      return `
        <div class="context-field fk">
          <div class="context-field-label"
               onclick="toggleContextNode('${fkNodeId}')">
            <span class="arrow">▸</span> ${fieldName}
          </div>

          <div class="context-nested hidden" data-node="${fkNodeId}">
            ${renderObjectFields(
              meta.target,
              fieldPath,
              new Set(visited)
            )}
          </div>
        </div>
      `;
    }

    return `
      <div class="context-field"
           draggable="true"
           data-path="${fieldPath}">
        ${fieldName}
      </div>
    `;
  }).join("");
}

function openConditionsEditor() {
  document.getElementById("conditions-editor").classList.remove("hidden");
}

function closeConditionsEditor() {
  document.getElementById("conditions-editor").classList.add("hidden");
}

// CONDITIONS NODE - COLUMN 2 FUNCTIONS

function addConditionRow() {
  const id = Date.now();

  conditionsDraft.items.push({
    id,
    left: null,
    operator: null,
    right: null
  });

  renderConditionsItems();
}

function renderConditionsItems() {
  const container = document.getElementById("conditions-items");
  if (!container) return;

  container.innerHTML = conditionsDraft.items.map(item => `
    <div class="condition-row" data-id="${item.id}">

      <!-- SOURCE -->
      <div class="condition-field">
        <label>Source</label>
        <div class="condition-cell empty"
             ondragover="allowDrop(event)"
             ondrop="dropConditionField(event, ${item.id})">
          ${item.left ? item.left.field_name : "Drop field here"}
        </div>
      </div>

      <!-- OPERATOR -->
      <div class="condition-field">
        <label>Operator</label>
        <select class="condition-operator"
                onchange="setConditionOperator(${item.id}, this.value)">
          <option value="">--</option>
          <option value="=" ${item.operator === "=" ? "selected" : ""}>=</option>
          <option value="!=" ${item.operator === "!=" ? "selected" : ""}>!=</option>
          <option value=">" ${item.operator === ">" ? "selected" : ""}>></option>
          <option value="<" ${item.operator === "<" ? "selected" : ""}><</option>
          <option value="contains" ${item.operator === "contains" ? "selected" : ""}>contains</option>
        </select>
      </div>

      <!-- TARGET -->
      <div class="condition-field">
        <label>Target</label>
        <input type="text"
               class="condition-cell"
               placeholder="Value"
               value="${item.right?.value ?? ""}"
               onchange="setConditionRight(${item.id}, this.value)" />
      </div>

    </div>
  `).join("");
}

function allowDrop(ev) {
  ev.preventDefault();
}

document.addEventListener("dragstart", e => {
  const path = e.target.dataset?.path;
  if (path) {
    e.dataTransfer.setData("text/plain", path);
  }
});

function dropConditionField(ev, conditionId) {
  ev.preventDefault();
  const path = ev.dataTransfer.getData("text/plain");

  const condition = conditionsDraft.items.find(c => c.id === conditionId);
  if (!condition) return;

  condition.left = {
    source: "field",
    field_name: path
  };

  renderConditionsItems();
  syncConditionsToJSON();
}

function setConditionOperator(id, operator) {
  const c = conditionsDraft.items.find(i => i.id === id);
  if (!c) return;

  c.operator = operator;
  syncConditionsToJSON();
}

function setConditionRight(id, value) {
  const c = conditionsDraft.items.find(i => i.id === id);
  if (!c) return;

  c.right = {
    source: "static",
    value: value
  };

  syncConditionsToJSON();
}

function updateConditionsLogicalOperator() {
  const value = document.getElementById("conditions-logical-operator").value;
  conditionsDraft.logical_operator = value;
  syncConditionsToJSON();
}

function syncConditionsToJSON() {
  actionTriggerJSON.conditions = {
    logical_operator: conditionsDraft.logical_operator,
    items: conditionsDraft.items
      .filter(c => c.left && c.operator && c.right)
      .map(({ left, operator, right }) => ({
        left,
        operator,
        right
      }))
  };

  // Preview (columna 3 luego)
  console.log("✅ Conditions JSON", actionTriggerJSON.conditions);
}
