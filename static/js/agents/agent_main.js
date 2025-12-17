document.addEventListener("DOMContentLoaded", function () {
  setupChatListeners();
  setupSessionSwitching();
  setupUploadZone();
  loadPendingAttachments();
  enhanceStructuredAgentMessagesHistoryChat(); // 🔥
});

let pendingAttachments = [];
const UPLOAD_HINT_DEFAULT = "PNG, JPG, GIF, or WEBP up to 8 MB. Attachments are appended to the next PDF.";

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

function setupSessionSwitching() {
  document.querySelectorAll(".chat-history-item").forEach(item => {
    item.addEventListener("click", function (e) {
      e.preventDefault();

      const sessionId = this.dataset.sessionId;
      if (!sessionId) return;

      // Construir URL limpia sin parámetros previos
      const baseUrl = `${window.location.origin}/dashboard/`;
      window.location.href = `${baseUrl}?view=agents&session_id=${sessionId}`;
    });
  });
}

function showAgentFeedback() {
  const feedback = document.getElementById("agent-feedback");
  if (feedback) feedback.style.display = "block";
}

function hideAgentFeedback() {
  const feedback = document.getElementById("agent-feedback");
  if (feedback) feedback.style.display = "none";
}

function setupChatListeners() {
  console.log("Setting up chat listeners...");

  const inputField = document.getElementById("user-input");
  const button = document.getElementById("send-btn");

  if (!inputField || !button) {
      console.error("Chat input or button not found!");
      return;
  }

  button.addEventListener("click", sendMessage);
  inputField.addEventListener("keypress", function (event) {
      if (event.key === "Enter") sendMessage();
  });

  console.log("Chat listeners attached.");
}

function setupUploadZone() {
  const dropzone = document.getElementById("upload-dropzone");
  const fileInput = document.getElementById("upload-input");
  const browseBtn = document.getElementById("upload-browse-btn");

  if (!dropzone || !fileInput) {
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
    handleAttachmentFiles(files);
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
      pendingAttachments = [];
      renderAttachmentList();
      return;
    }

    const data = await response.json();
    pendingAttachments = Array.isArray(data.attachments) ? data.attachments : [];
    dropzone.classList.remove("is-disabled");
    const hint = getUploadHintElement(dropzone);
    if (hint) {
      hint.textContent = UPLOAD_HINT_DEFAULT;
    }
    renderAttachmentList();
  } catch (error) {
    console.error("Failed to load pending attachments:", error);
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

  if (!pendingAttachments.length) {
    listEl.style.display = "none";
    return;
  }

  listEl.style.display = "block";
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

function enhanceStructuredAgentMessagesHistoryChat() {
  document.querySelectorAll(".agent-json").forEach(div => {
    const raw = div.dataset.raw;

    // Claves a buscar en el mensaje
    const keys = [
      'quote_details:',
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
        let messageBeforeJson = raw.slice(0, raw.indexOf(matchedKey)).trim();

        // 1️⃣ Desescapar Unicode
        messageBeforeJson = unescapeUnicode(messageBeforeJson);

        // 2️⃣ Reemplazar escapes de HTML (como \u003Cbr\u003E)
        messageBeforeJson = messageBeforeJson.replace(/\\u003C/g, "<").replace(/\\u003E/g, ">");

        const html = renderRetrievedRecords(messageBeforeJson, data);
        div.innerHTML = html;
        return;
      }

      // === EMAIL ALERTS ===
      if (Array.isArray(data) && data[0]?.trigger) {
        const html = renderEmailAlerstDetails(data);
        div.innerHTML = html;
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
      div.innerHTML = `
        📄 Quote PDF (v${version}) generated successfully!
        <a href="${downloadUrl}" target="_blank">Download Here</a>
      `;
    } else {
      div.innerHTML = `<div class="error-message">⚠️ Could not extract PDF fields</div>`;
    }
  });

  // === Auto-scroll chat ===
  const chatBox = document.getElementById("chat-box");
  if (chatBox) {
    chatBox.scrollTop = chatBox.scrollHeight;
  }
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


/**
* ✅ Send user message to the agent and handle response
*/
async function sendMessage() {
    const inputField = document.getElementById("user-input");
    const chatBox = document.getElementById("chat-box");

    let userMessage = inputField.value.trim();
    if (!userMessage) return;

    // Append user message to chat
    appendMessage("user", `<div class="sender">You: </div> <div class="message">${userMessage}</div>`)

    inputField.value = ""; // Clear input field

    // Auto-scroll chat
    scrollToBottom()

    try {

        const urlParams = new URLSearchParams(window.location.search);
        const sessionId = urlParams.get("session_id");  // 👈 Obtén el session_id desde la URL

        showAgentFeedback();

        requestAnimationFrame(scrollToBottom);

        const response = await fetch("/agents/chat/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: userMessage, session_id: sessionId})
        });

        //console.log("Full Response:", response);

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP error! Status: ${response.status} - ${errorText}`);
        }

        const data = await response.json();

        const aiResponse = data.response;

        // --- 1. Check if a new session was created ---
        if (aiResponse.session_created && aiResponse.redirect_url) {
            window.location.href = aiResponse.redirect_url; // Redirect to new session
            return;
        }

        let responseMessage = ""; // Initialize message variable

        // ✅ Handle Missing Product Warnings
        if (data.response && data.response.warnings) {
            responseMessage += `<div class="warning-message"><strong>⚠️ Warnings:</strong><ul>`;
            data.response.warnings.forEach(warning => {
                responseMessage += `<li>${warning}</li>`;
            });
            responseMessage += `</ul></div>`;
        }

        // ✅ Handle Approval History Response
        if (data.response && data.response.history) {
            responseMessage += renderApprovalHistory(data.response);
        }
        // ✅ Handle Quote Details Response
        else if (data.response && data.response.quote_details && !data.response.quote_notes) {
          //console.log("Quote Details");
          responseMessage += renderQuoteDetails(data.response.quote_details);
        }
        // ✅ Handle Quote Notes Response
        else if (data.response && data.response.quote_notes) {
          //console.log("Quote Notes");
          responseMessage += renderQuoteNotes(data.response.quote_details, data.response.quote_notes);
        }
        // ✅ Handle Quote PDF Response
        else if (data.response.download_url) {
            responseMessage += `📄 Quote PDF (v${data.response.document_version}) generated successfully! <a href="${data.response.download_url}" target="_blank">Download Here</a>`;
        }
        // ✅ Handle Validation Rules Response
        else if (data.response && data.response.validation_rules_details) {
          //console.log(data.response);
          //console.log(data.response.validation_rules_details)
          responseMessage += renderValidationRuleDetails(data.response.validation_rules_details);
        }
        // ✅ Handle Inclusion Rules Response
        else if (data.response && data.response.inclusion_rules_details) {
          responseMessage += renderInclusionRuleDetails(data.response.message, data.response.inclusion_rules_details);
        }
        // ✅ Handle Exclusion Rules Response
        else if (data.response && data.response.exclusion_rules_details) {
          responseMessage += renderExclusionRuleDetails(data.response.message, data.response.exclusion_rules_details);
        }
        // ✅ Handle Action Triggers Response
        else if (data.response && data.response.action_triggers_details) {
          responseMessage += renderActionTriggersDetails(data.response.message, data.response.action_triggers_details);
        }
        // ✅ Show Rules
        else if (data.response && data.response.rules && data.response.read_only) {
          //console.log(data.response);
          //console.log(data.response.validation_rules_details)
          responseMessage += renderRules(data.response.rules);
        }
        // ✅ Email Alerts
        else if (data.response && data.response.email_alerts_details) {
          //console.log(data.response);
          //console.log(data.response.email_alerts_details)
          responseMessage += renderEmailAlerstDetails(data.response.email_alerts_details);
        }
        // ✅ Analytics Records - retrieved_records
        else if (data.response && data.response.retrieved_records) {
          //console.log(data.response);
          //console.log(data.response.retrieved_records)
          responseMessage += renderRetrievedRecords(data.response.message, data.response.retrieved_records);
        }
        // ✅ openGraphicBuilder - for Action Triggers graphic mode
        else if (data.response && data.response.openGraphicBuilder) {

          // 🔑 PASO 1: guardar schema global
          modelSchema = data.response.cpq_model_schema || {};
          console.log("📦 CPQ Model Schema loaded:", modelSchema);

          // 🔑 PASO 2: renderizar builder
          responseMessage += renderGraphicBuilderForActionTrigger(
            data.response.openGraphicBuilder
          );
        }
        // ✅ Default Response (Handle General Messages)
        else if (data.response && data.response.message) {
            responseMessage += `<div class="general-message">${data.response.message}</div>`;
        }
        // ✅ Handle Unexpected Empty Response
        else {
            responseMessage += `<div class="error-message">🤖 No response received. Please try again.</div>`;
        }

        // ✅ Append the final response message to the chat
        appendMessage("agent", `<div class="senderagent"><img width="110px" src="/static/img/agentcpq-chat-icon.png" alt="AgentCPQ Logo"> </div> <div class="message">${responseMessage}</div>`);
        loadPendingAttachments();
        hideAgentFeedback();
        scrollToBottom();

        // ✅ Handle Temporary Quote Details After Update Quote Line, Add Product And Delete Quote Line Item
        if (data.response && data.response.update_details && data.response.temporaryMessage){
          const tempHtml = showTemporaryQuoteDetails(data.response.update_details);
          renderTemporaryMessage("agent", tempHtml, data.response.iterations);
        }

        // Auto-scroll chat
        chatBox.scrollTop = chatBox.scrollHeight;
    } catch (error) {
        console.error("Error:", error);
        appendMessage("agent-message", `<strong>Error:</strong> ${error.message}`);
        hideAgentFeedback();
    }
}

function scrollToBottom() {
    const chatBox = document.getElementById("chat-box");
    if (chatBox) {
        chatBox.scrollTop = chatBox.scrollHeight;
    }
}

/**
* ✅ Append message to the chat box
*/
function appendMessage(className, message) {
    const chatBox = document.getElementById("chat-box");
    let messageBubble = document.createElement("div");
    messageBubble.classList.add("chat-message", className);

    // ✅ Detect stored quote_details as string
    if (className === "agent" && message.includes("quote_details: {")) {
      try {
        // Extract JSON from string
        const match = message.match(/quote_details:\s({.+})/);
        if (match && match[1]) {
          const quote = JSON.parse(match[1]);
          message = renderQuoteDetails(quote);  // Use your nice formatter
        }
      } catch (e) {
        console.warn("Failed to parse quote_details JSON:", e);
      }
    }

    // ✅ Detect stored notes as string
    if (className === "agent" && message.includes("quote_details: {") && message.includes("notes: {")) {
      try {
        // Extract JSON from string
        const match = message.match(/quote_details:\s({.+})/);
        if (match && match[1]) {
          const quote = JSON.parse(match[1]);
          message = renderQuoteNotes(quote);  // Use your nice formatter
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

    // ✅ Detect stored retrieved records (Analytics Agent)
    if (className === "agent" && message.includes("retrieved_records:")) {
      try {
        // Extract JSON from string
        const match = message.match(/retrieved_records:\s({.+})/);
        if (match && match[1]) {
          const records = JSON.parse(match[1]);
          message = renderRetrievedRecords(records);  // Use your nice formatter
        }
      } catch (e) {
        console.warn("Failed to parse retrieved_records JSON:", e);
      }
    }

    messageBubble.innerHTML = message;
    chatBox.appendChild(messageBubble);

    // ✅ Re-initializes select from Materialize
   const selects = messageBubble.querySelectorAll('select');
    if (selects.length > 0 && typeof M !== 'undefined' && M.FormSelect) {
        M.FormSelect.init(selects);
    } else {
        console.warn("Materialize M.FormSelect not available or no selects found.");
    }

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
}

function renderQuoteDetails(quote) {
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

  var html = `<div class="quote-container">
              <div class="quote-header">
                  <h3>Quote: ${quote.quote_name}</h3>
                  <div style="display: flex; align-items: center; gap: 8px;" class="status-select">
                    <strong>Status:</strong>
                    <select
                      name="status"
                      data-field="status"
                      data-quote="${quote.quote_name}"
                      style="padding: 4px; border-radius: 4px; color: black;"
                      onchange="updateQuote(this)">
                      <option value="Draft" ${quote.status === "Draft" ? "selected" : ""}>Draft</option>
                      <option value="Pending Approval" ${quote.status === "Pending Approval" ? "selected" : ""}>Pending Approval</option>
                      <option value="Approved" ${quote.status === "Approved" ? "selected" : ""}>Approved</option>
                      <option value="Rejected" ${quote.status === "Rejected" ? "selected" : ""}>Rejected</option>
                      <option value="Closed" ${quote.status === "Closed" ? "selected" : ""}>Closed</option>
                    </select>
                  </div>
              </div>
              <div class="quote-details">
                <div class="account">
                  <p><strong>Account:</strong> ${quote.account ? quote.account : "*****"}</p>
                </div>
                <div class="opportunity">
                  <p><strong>Opportunity:</strong> ${quote.opportunity ? quote.opportunity : "*****"}</p>
                </div>
                <div class="created">
                  <p><strong>Created At:</strong> ${quote.created_at ? formattedDate : "*****"}</p>
                </div>
                <div class="expiration">
                  <p><strong>Expiration Date:</strong>
                  ${quote.expiration_date ? `
                  <input type="text" id="expiration_date" name="expiration_date"
                          data-field="expiration_date"
                          data-quote="${quote.quote_name}"
                          placeholder="MM/DD/YYYY"
                          style="display: inline-block; width: 7rem; margin-top: 0px; color: black;"
                          value="${formattedDate_e}"/>
                  ` : "*****"}
                  </p>
                </div>

                <div class="discount">
                  <p><strong>Discount: </strong>
                    ${(quote.discount_type && quote.discount_percentage && quote.discount_amount) ? `
                    <input type="number"
                          value="${Number(quote.discount_percentage)}"
                          data-field="discount_percentage"
                          data-quote="${quote.quote_name}"
                          onchange="updateQuote(this)"
                          style="width: 3rem; color: red;">
                    <span style="color: red;">%</span>
                    <span style="color: red;">( - $</span>
                    <input type="text"
                      value="${Number(quote.discount_amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}"
                      data-field="discount_amount"
                      data-quote="${quote.quote_name}"
                      onchange="updateQuote(this)"
                      style="width: 6rem; color: red;">
                    <span style="color: red;"> )</span>
                    ` : "*****"}
                  </p>
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
              .replace("Product And SKU", "SKU/Product")
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
                  <div class="centered-td">${item.sku}</div>
                  <div class="centered-td" style="color: gray; font-size: 0.65em">${item.product}</div>
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
            <td class="centered-td">
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
              .replace("Product And SKU", "SKU/Product")
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
                  <div class="centered-td">${item.sku}</div>
                  <div class="centered-td" style="color: gray; font-size: 0.65em">${item.product}</div>
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
            <td class="centered-td">
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

  const createdAt = new Date(quote.created_at);
  const expiration = new Date(quote.expiration_date);

  let html = `
    <div class="quote-mobile" style="font-family: Arial, sans-serif; line-height: 1.4">
      <h3 style="margin:0 0 8px 0; color:#ff7f00; font-size:1.2rem; font-weight:600; background-color:#f5f5f5; padding:0.5rem">${quote.quote_name}</h3>
      <p>🏢 <b>Account:</b> ${quote.account} 🔸 🗒️ <b>Status:</b> ${quote.status}</p>
      <p>📆 <b>Expires:</b> ${format(expiration)}</p>
      <p>🚀 <b>Opportunity:</b> ${quote.opportunity}</p>
      <p>🏷️ <b>Discount:</b> ${quote.discount_percentage}% (-$${Number(
        quote.discount_amount
      ).toLocaleString("en-US", { minimumFractionDigits: 2 })})</p>

      <h4 style="margin:16px 0 8px 0; font-size:1.3rem; color: #ff7f00; padding:0.5rem; border-bottom: 1px solid border-bottom: 1px solid #e7e7e7;) ">Line Items</h4>
      <ul style="padding-left:18px; margin:0">
        ${quote.line_items
          .map(
            (item) => `
          <li>
            ${item.quantity} × ${item.product} @ ${parseFloat(
              item.unit_price.replace("$", "")
            ).toLocaleString("en-US", { style: "currency", currency: "USD" })}
            ${item.is_subscription ? " /sub" : ""}
          </li>`
          )
          .join("")}
      </ul>

      <p style="margin-top:12px"><b>Subtotal:</b> ${parseFloat(
        quote.subtotal.replace("$", "")
      ).toLocaleString("en-US", { style: "currency", currency: "USD" })}</p>

      ${
        quote.show_tax_information && (quote.show_quote_tax_percentage || quote.show_quote_tax_amount)
          ? `<p>
              <b>Tax:</b>
              ${
                quote.show_quote_tax_percentage && quote.show_quote_tax_amount
                  ? `(${parseFloat(quote.tax_percentage)}%) `
                  : quote.show_quote_tax_percentage
                  ? `${parseFloat(quote.tax_percentage)}% `
                  : ''
              }
              ${
                quote.show_quote_tax_amount
                  ? parseFloat(quote.tax_amount).toLocaleString("en-US", {
                      style: "currency",
                      currency: "USD",
                    })
                  : ''
              }
            </p>`
          : ''
      }

      <p><span class="material-icons" style="font-size:20px;vertical-align:middle;color:#2e7d32;margin-right:4px;">attach_money</span><b>Net Amount:</b> ${parseFloat(
        quote.net_amount.replace("$", "")
      ).toLocaleString("en-US", { style: "currency", currency: "USD" })}</p>
    </div>`;

  return html;
}

function renderReadOnlyQuoteDetails(quote) {
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

  var html = `<div class="quote-container">
              <div class="quote-header">
                  <h3>Quote: ${quote.quote_name}</h3>
                  <div style="display: flex; align-items: center; gap: 8px;" class="status-select">
                    <p><strong>Status:</strong> ${quote.status}</p>
                  </div>
              </div>
              <div class="quote-details">
                <div class="account">
                  <p><strong>Account:</strong> ${quote.account ? quote.account : "---"}</p>
                </div>
                <div class="opportunity">
                  <p><strong>Opportunity:</strong> ${quote.opportunity ? quote.opportunity : "---"}</p>
                </div>
                <div class="created">
                  <p><strong>Created At:</strong> ${quote.created_at ? formattedDate : "---"}</p>
                </div>
                <div class="expiration">
                  <p><strong>Expiration Date:</strong> ${quote.expiration_date ? formattedDate : "---"}</p>
                </div>

                <div class="discount">
                  <p style="color: red;"><strong>Discount: </strong>
                    ${quote.discount_percentage}% ( - $${quote.discount_amount} )
                  </p>
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
              .replace("Product And SKU", "SKU/Product")
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
                  <div class="centered-td">${item.sku}</div>
                  <div class="centered-td" style="color: gray; font-size: 0.65em">${item.product}</div>
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
            <td class="centered-td">
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
              .replace("Product And SKU", "SKU/Product")
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
                  <div class="centered-td">${item.sku}</div>
                  <div class="centered-td" style="color: gray; font-size: 0.65em">${item.product}</div>
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
            <td class="centered-td">
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

    const updateData = { sku, field, value: newValue, quote_line_id: quoteLineId, hiddenMessage: true };
    const userMessage = `Update Quote Line: ${JSON.stringify(updateData)}`;

    try {
        const response = await fetch("/agents/chat/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: userMessage })
        });

        const data = await response.json();

        if (data.response && data.response.quote_details) {
            const updatedQuote = data.response.quote_details;
            const quoteContainer = input.closest(".quote-container");
            //console.log(updatedQuote); #For debugging

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

            alert("✅ Quote line updated successfully.");
        } else {
            // ⬅️ Restart original value of the input field
            input.value = data.response.original_value
            alert(data.response.message.replace(/<br\s*\/?>/gi, '\n'));
        }
    } catch (error) {
        console.error("❌ Error updating quote line:", error);
        // ⬅️ Restart original value of the input field
        input.value = data.response.original_value
        alert("❌ Failed to update quote.");
    }
}

/**
* ✅ Update expiration date
*/
async function updateQuote(input) {
    let newValue = input.value;
    const field = input.dataset.field;
    const quote = input.dataset.quote;

    if (!newValue || !quote) {
        console.warn("⚠️ Missing value or quote ID.");
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
        const response = await fetch("/agents/chat/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: userMessage })
        });

        const data = await response.json();

        if (data.response && data.response.message.includes("✅ Quote updated successfully.") && data.response.quote_details) {
            input.blur();

            const updatedQuote = data.response.quote_details;

            const quoteContainer = input.closest(".quote-details");

            if (field === "discount_percentage") {
                const discountAmountInput = quoteContainer.querySelector('input[data-field="discount_amount"]');
                if (discountAmountInput) {
                    const discountAmount = parseFloat(updatedQuote.discount_amount);
                    discountAmountInput.value = discountAmount.toLocaleString('en-US', {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2
                    });
                }
            }

            if (field === "discount_amount") {
                const discountPctInput = quoteContainer.querySelector('input[data-field="discount_percentage"]');
                if (discountPctInput) {
                    const discountPct = parseFloat(updatedQuote.discount_percentage);
                    discountPctInput.value = discountPct.toFixed(2);
                }
            }

            // 🧮 Update Net Amount (total amount)
            const totalContainer = input.closest(".quote-container");
            const netAmountEl = totalContainer.querySelector(".total-amount");
            if (netAmountEl && updatedQuote.net_amount) {
                const net = parseFloat(updatedQuote.net_amount.replace('$', ''));
                netAmountEl.innerHTML = `
                    Net Amount: ${net.toLocaleString('en-US', {
                        style: 'currency',
                        currency: 'USD'
                    })}
                `;
            }

            alert("✅ Quote updated successfully!");
        } else {
            // ⬅️ Restart original value of the input field
            input.value = data.response.original_value
            alert(data.response.message.replace(/<br\s*\/?>/gi, '\n'));
        }
    } catch (error) {
        console.error("❌ Error updating quote:", error);
        // ⬅️ Restart original value of the input field
        input.value = data.response.original_value
        alert("❌ Error occurred while updating quote.");
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

  var html = `
              <div>
                ⏳ Rendering temporary quote details...
              </div>
              <div class="quote-container">
              <div class="quote-header">
                  <h3>Quote: ${quote.quote_name}</h3>
                  <div style="display: flex; align-items: center; gap: 8px;" class="status-select">
                    <p><strong>Status:</strong> ${quote.status}</p>
                  </div>
              </div>
              <div class="quote-details">
                <div class="account">
                  <p><strong>Account:</strong> ${quote.account ? quote.account : "---"}</p>
                </div>
                <div class="opportunity">
                  <p><strong>Opportunity:</strong> ${quote.opportunity ? quote.opportunity : "---"}</p>
                </div>
                <div class="created">
                  <p><strong>Created At:</strong> ${quote.created_at ? formattedDate : "---"}</p>
                </div>
                <div class="expiration">
                  <p><strong>Expiration Date:</strong> ${quote.expiration_date ? formattedDate : "---"}</p>
                </div>

                <div class="discount">
                  <p style="color: red;"><strong>Discount: </strong>
                    ${quote.discount_percentage}% ( - $${quote.discount_amount} )
                  </p>
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
              .replace("Product And SKU", "SKU/Product")
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
                  <div class="centered-td">${item.sku}</div>
                  <div class="centered-td" style="color: gray; font-size: 0.65em">${item.product}</div>
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
            <td class="centered-td">
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
              .replace("Product And SKU", "SKU/Product")
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
                  <div class="centered-td">${item.sku}</div>
                  <div class="centered-td" style="color: gray; font-size: 0.65em">${item.product}</div>
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
            <td class="centered-td">
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
          <div class="email-alert-header">
              <h5>${head_text}</h3>
              <span style="margin-left: 10px; font-weight: bold; color: ${alert.active ? 'green' : 'red'};">
                ${alert.active ? '🟢 Active' : '🔴 Inactive'}
              </span>
          </div>
          <div class="email-alert-details">

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

// =====================================================
// ✅ renderRetrievedRecords (con estilos y scroll)
// ✅ openRecordsPopout (popout draggable con overlay)
// =====================================================

function renderRetrievedRecords(userMessage, recordsDetails) {
  let html = "";

  // Añadir estilos globales una sola vez
  if (!document.getElementById("records-table-style")) {
    const style = document.createElement("style");
    style.id = "records-table-style";
    style.innerHTML = `
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

      .records-header h5 {
        margin: 0;
        font-size: 1rem;
        letter-spacing: 0.5px;
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
        max-height: 320px;
        border: 1px solid #e5e7eb;
        border-radius: 0 0 0.5rem 0.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
      }

      .records-table {
        width: 100%;
        border-collapse: collapse;
        background: white;
        font-size: 0.9rem;
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
        font-size: 0.8rem;
      }

      .records-table tbody tr:nth-child(even) {
        background-color: #f8fafc;
      }

      .records-table tbody tr:hover {
        background-color: #eff6ff;
      }

      /* Popup general */
      .records-overlay {
        position: fixed;
        inset: 0;
        background: rgba(15,23,42,0.45);
        z-index: 9998;
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
        z-index: 9999;
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
      }
    `;
    document.head.appendChild(style);
  }

  // Renderizar objetos
  for (const [objectName, records] of Object.entries(recordsDetails)) {
    if (!records || records.length === 0) continue;
    const allFields = Object.keys(records[0]);

    html += `
      <div class="records-container" style="margin-bottom:1.5rem;">
        <div class="records-header">
          <h5>${objectName} Records</h5>
          <button class="records-popout-btn" onclick="openRecordsPopout(this)">Pop Out</button>
        </div>

        <div class="records-table-wrapper">
          <table class="records-table">
            <thead>
              <tr>${allFields.map(f => `<th>${normalizeFieldName(f)}</th>`).join('')}</tr>
            </thead>
            <tbody>
              ${records.map(record => `
                <tr>
                  ${allFields.map(field => {
                    let value = record[field];
                    if (value === null || value === undefined || value === "") return `<td>—</td>`;
                    if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
                      const d = new Date(value);
                      value = d.toLocaleString('en-US', {
                        year:"numeric",month:"2-digit",day:"2-digit",
                        hour:"2-digit",minute:"2-digit",second:"2-digit",
                        hour12:false
                      });
                    }
                    return `<td>${value}</td>`;
                  }).join('')}
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  if (userMessage) {
    const cleanMessage = userMessage.split("retrieved_records:")[0];
    html += `<div style="margin-bottom:10px;"><p>${cleanMessage}</p></div>`;
  }

  return html;
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
  popup.style.zIndex = '10000';
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