document.addEventListener("DOMContentLoaded", function () {
  setupChatListeners();
  setupSessionSwitching(); 
  enhanceStructuredAgentMessagesHistoryChat(); // 🔥
});

/**
* ✅ Get the current session
*/
function getCurrentSessionId() {
  const urlParams = new URLSearchParams(window.location.search);
  console.log(urlParams.get("session_id"));
  return urlParams.get("session_id");
}

function setupSessionSwitching() {
    document.querySelectorAll(".chat-history-item").forEach(item => {
      item.addEventListener("click", function (e) {
        e.preventDefault();
  
        const sessionId = this.dataset.sessionId;
        if (!sessionId) return;
  
        const url = new URL(window.location.href);
        url.searchParams.set("view", "agents");
        url.searchParams.set("session_id", sessionId);
  
        // Redirect to the same page with updated session_id
        window.location.href = url.toString();
      });
    });
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

function toggleSidebar() {
    document.querySelector(".sidenav-fixed").classList.toggle("active");
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
        console.log("enhanceStructuredAgentMessages")
        div.innerHTML = `<div class="error-message">⚠️ Could not find valid JSON in message</div>`;
        return;
      }

      try {
        const data = JSON.parse(unescapeUnicode(jsonStr));
        // Procesa data
      } catch (e) {
        console.error("JSON parse failed:", e, jsonStr);
        div.innerHTML = `<div class="error-message">❌ JSON parsing error</div>`;
      }
    });
  }

/*
* ✅ enhanceStructuredAgentMessages in history chat, NOT in real time
*/
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

function unescapeUnicode(str) {
  return str.replace(/\\u[\dA-F]{4}/gi, function (match) {
    return String.fromCharCode(parseInt(match.replace(/\\u/g, ''), 16));
  });
}

function enhanceStructuredAgentMessagesHistoryChat() {
  document.querySelectorAll(".agent-json").forEach(div => {
    const raw = div.dataset.raw;

    const keys = ['quote_details:', 'validation_rules_details:', 'rules:'];

    let jsonPart = null;
    for (const key of keys) {
      const idx = raw.indexOf(key);
      if (idx !== -1) {
        const afterKey = raw.slice(idx + key.length);
        jsonPart = extractJson(afterKey);
        if (jsonPart) break;
      }
    }

    if (!jsonPart) {
      console.log("enhanceStructuredAgentMessagesHistoryChat");
      div.innerHTML = `<div class="error-message">⚠️ Could not find valid JSON in message</div>`;
      return;
    }

    try {
      //console.log("JsonPart: ", jsonPart);
      const data = JSON.parse(unescapeUnicode(jsonPart));
      //console.log("Data: ", data);

      if (data.rules || (Array.isArray(data) && data[0]?.rule_type)) {
        const html = renderValidationRuleDetails(data.rules || data);
        div.innerHTML = html;
        return;
      }

      if (data.rules || (Array.isArray(data) && data[0]?.rules_request_description)) {
        //const html = renderValidationRuleDetails(data.rules || data);
        //console.log("Render Rules | Show rules")
        const html = renderRules(data);
        div.innerHTML = html;
        return;
      }

      const html = renderReadOnlyQuoteDetails(data);
      div.innerHTML = html;

    } catch (e) {
      console.error("❌ JSON parse failed:", e, jsonPart);
      div.innerHTML = `<div class="error-message">❌ Error trying to display the structured message. (JSON parsing error)</div>`;
    }
  });

  document.querySelectorAll(".agent-pdf").forEach(div => {
  const raw = unescapeUnicode(div.dataset.raw);

  if (!raw.includes("download_url")) return;

  // Get download_url
  const urlMatch = raw.match(/download_url:\s*["']?(.*?)["']?\s*(\n|$)/);
  const versionMatch = raw.match(/document_version:\s*([0-9]+)/);

  const downloadUrl = urlMatch ? urlMatch[1].trim() : null;
  const version = versionMatch ? versionMatch[1].trim() : null;
  //console.log("📄 Extracted PDF Info:", { version, downloadUrl });

  if (downloadUrl && version) {
    div.innerHTML = `
      📄 Quote PDF (v${version}) generated successfully! 
      <a href="${downloadUrl}" target="_blank">Download Here</a>
    `;
  } else {
    div.innerHTML = `<div class="error-message">⚠️ Could not extract PDF fields</div>`;
  }
});

  // Auto-scroll chat
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
    chatBox.scrollTop = chatBox.scrollHeight;

    try {

        const urlParams = new URLSearchParams(window.location.search);
        const sessionId = urlParams.get("session_id");  // 👈 Obtén el session_id desde la URL

        const response = await fetch("/agents/chat/", {   
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: userMessage, session_id: sessionId})
        });

        console.log("Full Response:", response);

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP error! Status: ${response.status} - ${errorText}`);
        }

        const data = await response.json();

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
            console.log(data.response);
            responseMessage += `📄 Quote PDF (v${data.response.document_version}) generated successfully! <a href="${data.response.download_url}" target="_blank">Download Here</a>`;
        } 
        // ✅ Handle Validation Rules Response
        else if (data.response && data.response.validation_rules_details) {
          console.log("Validation Rules Details");
          //console.log(data.response);
          //console.log(data.response.validation_rules_details)
          responseMessage += renderValidationRuleDetails(data.response.validation_rules_details);
        }
        // ✅ Show Rules
        else if (data.response && data.response.rules && data.response.read_only) {
          console.log("Show Rules");
          //console.log(data.response);
          //console.log(data.response.validation_rules_details)
          responseMessage += renderRules(data.response.rules);
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
        appendMessage("agent", `<div class="senderagent"><img width="95px" src="/media/img/agentcpq-5.png" alt="AgentCPQ Logo"> </div> <div class="message">${responseMessage}</div>`);

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

    // ✅ Detect stored notes as string
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
  
    messageBubble.innerHTML = message;
    chatBox.appendChild(messageBubble);

    // ✅ Re-initializes select from Materialize
    const selects = messageBubble.querySelectorAll('select');
    if (selects.length > 0) {
        M.FormSelect.init(selects);
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

      html += `<tr>`;

      quote.rendered_fields.forEach(field => {
        // Limpiar campos como Product.UOM
        const cleanedField = field.replace(/^Product\./, "");

        if (field === "Product And SKU") {
          html += `
            <td>
              <div class="centered-td">${item.sku}</div>
              <div class="centered-td" style="color: gray; font-size: 0.65em">${item.product}</div>
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

      html += `<tr>`;

      quote.rendered_fields.forEach(field => {
        // Limpiar campos como Product.UOM
        const cleanedField = field.replace(/^Product\./, "");

        if (field === "Product And SKU") {
          html += `
            <td>
              <div class="centered-td">${item.sku}</div>
              <div class="centered-td" style="color: gray; font-size: 0.65em">${item.product}</div>
            </td>`;
        } else if (field === "Quantity") {
          html += `
            <td>
              <input type="number" min="1" value="${item.quantity}" 
                data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" 
                class="editable-field" data-field="quantity" onchange="updateQuoteLine(this)">
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
      </p>
      <p class="total-amount">
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
      <p>💰 <b>Net Amount:</b> ${parseFloat(
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

      html += `<tr>`;

      quote.rendered_fields.forEach(field => {
        // Limpiar campos como Product.UOM
        const cleanedField = field.replace(/^Product\./, "");

        if (field === "Product And SKU") {
          html += `
            <td>
              <div class="centered-td">${item.sku}</div>
              <div class="centered-td" style="color: gray; font-size: 0.65em">${item.product}</div>
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

      html += `<tr>`;

      quote.rendered_fields.forEach(field => {
        // Limpiar campos como Product.UOM
        const cleanedField = field.replace(/^Product\./, "");

        if (field === "Product And SKU") {
          html += `
            <td>
              <div class="centered-td">${item.sku}</div>
              <div class="centered-td" style="color: gray; font-size: 0.65em">${item.product}</div>
            </td>`;
        } else if (field === "Quantity") {
          html += `
            <td>
              <input type="number" min="1" value="${item.quantity}" 
                data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" 
                class="editable-field" data-field="quantity" onchange="updateQuoteLine(this)"
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
      </p>
      <p class="total-amount">
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

      console.log(`🔄 Field Changed: ${event.target.name}, New Value: ${newValue}, Initial Value: ${initialValue}`);
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
    console.log("Entra a updateQuoteLine");
  
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

    console.log(`🔄 Field Changed: ${field}, SKU: ${sku}, New Value: ${newValue}, Quote: ${quoteId}, QuoteLine: ${quoteLineId}`);

    const updateData = { sku, field, value: newValue, quote_line_id: quoteLineId, hiddenMessage: true };
    const userMessage = `Update Quote Line: ${JSON.stringify(updateData)}`;

    try {
        const response = await fetch("/agents/chat/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: userMessage })
        });

        const data = await response.json();
        console.log("✅ Server Response:", data);

        if (data.response && data.response.quote_details) {
            const updatedQuote = data.response.quote_details;
            const quoteContainer = input.closest(".quote-container");

            //First we update every single quote line total price
            const row =input.closest("tr");

            updatedQuote.line_items.forEach(item => {
                const totalCell = row.querySelector(`.total-price[data-sku="${item.sku}"]`);
                if (totalCell) {
                    //1. Get the total price from quote line
                    const total = parseFloat(item.total_price);

                    //2. Formatted
                    const formattedTotal = `$${total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

                    //3. Upgrade the DOM immediately
                    totalCell.textContent = formattedTotal;
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

    console.log(`🔄 Field Changed: ${field}, Quote: ${quote}, New Value: ${newValue}`);

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
        console.log("✅ Server Response:", data);

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
            alert("⚠️ Failed to update quote.");
        }
    } catch (error) {
        console.error("❌ Error updating quote:", error);
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
  const creationDate = new Date(quote.expiration_date);

  // Add 0 in front if necessary
  const month = String(createdAt.getMonth() + 1).padStart(2, '0');
  const day = String(createdAt.getDate()).padStart(2, '0');
  const year = createdAt.getFullYear();

  const formattedDate = `${month}/${day}/${year}`;

  const month_e = String(creationDate.getMonth() + 1).padStart(2, '0');
  const day_e = String(creationDate.getDate()).padStart(2, '0');
  const year_e = creationDate.getFullYear();

  const formattedDate_e = `${month_e}/${day_e}/${year_e}`;

   var html = `
        <div>
          ⏳ Rendering temporary quote details...
        </div>
        <div class="quote-container">
              <div class="quote-header">
                  <h3>Quote: ${quote.quote_name}</h3>
                  <p><strong>Status:</strong> ${quote.status}</p>
              </div>
              <div class="quote-details">
                <div class="account">
                  <p><strong>Account:</strong> ${quote.account}</p>
                </div>
                <div class="opportunity">
                  <p><strong>Opportunity:</strong> ${quote.opportunity}</p>
                </div>
                <div class="created">
                  <p><strong>Created At:</strong> ${formattedDate}</p>
                </div>
                <div class="expiration">
                  <p><strong>Expiration Date:</strong> ${formattedDate_e}</p>
                </div>
                
                <div class="discount">
                  <p style="color: red;"><strong>Discount: </strong>
                    ${quote.discount_percentage}% ( - $${quote.discount_amount} )
                  </p>
                </div>
              </div>
              <h4>Line Items</h4>`;

  var is_subscription_cont = 0;

  quote.line_items.forEach(item => {
    if(item.is_subscription == true){
      if(is_subscription_cont == 0){
        html += `
              <table class="quote-table" data-quote-id="${quote.quote_name}">
                  <thead>
                      <tr>
                          <th>SKU/Product</th>
                          <th>Quantity</th>
                          <th>Unit Price</th>
                          <th>Discount (%)</th>
                          <th>Discount (USD)</th>
                          <th>Subscription</th>
                          <th>Term</th>
                          <th>Total Price</th>
                      </tr>
                  </thead>
                  <tbody>`;
            is_subscription_cont = 1;
      }

      html += `
          <tr>
              <td>
                <div class="centered-td">${item.sku}</div>
                <div class="centered-td" style="color: gray; font-size: 0.85em">${item.product}</div>
              </td>
              <td>
                ${item.quantity}
              </td>
              <td>
                ${parseFloat(item.unit_price.replace('$', '')).toLocaleString('en-US', {
                    style: 'currency',
                    currency: 'USD'
                })}
              </td>
              <td class="centered-td">
                ${item.discount_percentage.replace('%', '')}
              </td>
              <td class="centered-td">
                ${item.discount_amount.replace('$', '')}
              </td>
              <td class="centered-td">
                ${item.is_subscription ? '✅' : '❌'}
              </td>
              <td class="centered-td">
                ${item.term || '---'}
              </td>
              <td class="total-price" data-sku="${item.sku}">
                ${parseFloat(item.total_price.replace('$', '')).toLocaleString('en-US', {
                    style: 'currency',
                    currency: 'USD'
                })}
              </td>
          </tr>`;
    }
  });

  html += `</tbody></table><br>`
  let none_suscription_bool = 0;

  quote.line_items.forEach(item => {
    if(item.is_subscription == false){
      if(none_suscription_bool == 0){
        html += `
              <table class="quote-table" data-quote-id="${quote.quote_name}">
                  <thead>
                      <tr>
                          <th>SKU/Product</th>
                          <th>Quantity</th>
                          <th>Unit Price</th>
                          <th>Discount (%)</th>
                          <th>Discount (USD)</th>
                          <th>Total Price</th>
                      </tr>
                  </thead>
                  <tbody>`;
            none_suscription_bool = 1;
      }

      html += `
          <tr>
              <td>
                <div class="centered-td">${item.sku}</div>
                <div class="centered-td" style="color: gray; font-size: 0.85em">${item.product}</div>
              </td>
              <td>
                ${item.quantity}
              </td>
              <td>
                ${parseFloat(item.unit_price.replace('$', '')).toLocaleString('en-US', {
                    style: 'currency',
                    currency: 'USD'
                })}
              </td>
              <td class="centered-td">
                ${item.discount_percentage.replace('%', '')}
              </td>
              <td class="centered-td">
                ${item.discount_amount.replace('$', '')}
              </td>
              <td class="total-price" data-sku="${item.sku}">
                ${parseFloat(item.total_price.replace('$', '')).toLocaleString('en-US', {
                    style: 'currency',
                    currency: 'USD'
                })}
              </td>
          </tr>`;
    }
  });

  html += `</tbody></table>
    <p class="subtotal-amount">
      Subtotal: ${parseFloat(quote.subtotal.replace('$', '')).toLocaleString('en-US', {
          style: 'currency',
          currency: 'USD'
      })}
    </p>
    <p class="total-amount">
      Net Amount: ${parseFloat(quote.net_amount.replace('$', '')).toLocaleString('en-US', {
          style: 'currency',
          currency: 'USD'
      })}
    </p>
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

  const fieldLabelMap = {
    // Quote fields
    "quote.net_amount": "Net Amount",
    "quote.tax_amount": "Tax Amount",
    "quote.status": "Status",
    "quote.discount_percentage": "Quote Discount %",
    "quote.discount_amount": "Quote Discount Amount",
    "quote.discount_type": "Quote Discount Type",
    "quote.subtotal": "Quote Subtotal",

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

  return `<li class="depth-${depth}">⚠️ Unknown condition format</li>`;
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