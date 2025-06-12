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
  
      const startIndex = raw.indexOf('{');
      if (startIndex !== -1) {
        const jsonStr = raw.slice(startIndex);
  
        try {
          const quote = JSON.parse(unescapeUnicode(jsonStr));
          const html = renderQuoteDetails(quote);
          div.innerHTML = html;
        } catch (e) {
          console.error("❌ JSON parse failed:", e, jsonStr);
          div.innerHTML = `<div class="error-message">❌ Error trying to display the structured message. (JSON parsing error)</div>`;
        }
      } else {
        div.innerHTML = `<div class="error-message">⚠️ Could not find quote details JSON</div>`;
      }
    });
  }

/*
* ✅ enhanceStructuredAgentMessages in history chat, NOT in real time
*/
function enhanceStructuredAgentMessagesHistoryChat() {

    document.querySelectorAll(".agent-json").forEach(div => {
      const raw = div.dataset.raw;
  
      const startIndex = raw.indexOf('{');
      if (startIndex !== -1) {
        const jsonStr = raw.slice(startIndex);
  
        try {
          const quote = JSON.parse(unescapeUnicode(jsonStr));
          const html = renderReadOnlyQuoteDetails(quote);
          div.innerHTML = html;
          return;
        } catch (e) {
          console.error("❌ JSON parse failed:", e, jsonStr);
          div.innerHTML = `<div class="error-message">❌ Error trying to display the structured message. (JSON parsing error)</div>`;
        }
      }

      // Desescapamos unicode para manejar caracteres especiales y saltos de línea
      let unescapedRaw = unescapeUnicode(raw);

      // Ejemplo patrón para mensaje PDF (puedes añadir más patrones similares)
      const pdfPatternUrl = /download_url:\s*"?([^"\s]+)"?/i;
      const pdfPatternVersion = /document_version:\s*(\d+)/i;

      const downloadUrlMatch = unescapedRaw.match(pdfPatternUrl);
      const versionMatch = unescapedRaw.match(pdfPatternVersion);

      if (downloadUrlMatch && versionMatch) {
        const url = downloadUrlMatch[1].trim();
        const version = versionMatch[1].trim();
        const message = unescapedRaw.split("download_url:")[0].trim();

        div.innerHTML = `
          <div class="general-message">
            <p>${message}<a href="${url}" target="_blank" class="download-link"> Download Here</a></p>
          </div>
        `;
        return;
      }

      div.innerHTML = `<pre class="plain-text-message">${escapeHtml(unescapedRaw)}</pre>`;

    });

    const chatBox = document.getElementById("chat-box");

    // Auto-scroll chat
    chatBox.scrollTop = chatBox.scrollHeight;
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
        else if (data.response && data.response.quote_details) {
            responseMessage += renderQuoteDetails(data.response.quote_details);
        } 
        // ✅ Handle Quote PDF Response
        else if (data.response.download_url) {
            console.log(data.response);
            responseMessage += `📄 Quote PDF (v${data.response.document_version}) generated successfully! <a href="${data.response.download_url}" target="_blank">Download Here</a>`;
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
        appendMessage("agent", `<div class="senderagent">Agent: </div> <div class="message">${responseMessage}</div>`);

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
  
    messageBubble.innerHTML = message;
    chatBox.appendChild(messageBubble);

    // ✅ Ejecuta si el mensaje recién insertado contiene JSON estructurado
    if (message.includes("agent-json")) {
        enhanceStructuredAgentMessages();
    }
}

function renderQuoteDetails(quote) {
  const createdAt = new Date(quote.created_at);

  // Add 0 in front if necessary
  const month = String(createdAt.getMonth() + 1).padStart(2, '0');
  const day = String(createdAt.getDate()).padStart(2, '0');
  const year = createdAt.getFullYear();

  const hours = String(createdAt.getHours()).padStart(2, '0');
  const minutes = String(createdAt.getMinutes()).padStart(2, '0');
  const seconds = String(createdAt.getSeconds()).padStart(2, '0');

  const formattedDate = `${month}/${day}/${year} ${hours}:${minutes}:${seconds}`;

  var html = `<div class="quote-container">
              <div class="quote-header">
                  <h3>📄 Quote: ${quote.quote_name}</h3>
                  <p><strong>Status:</strong> ${quote.status}</p>
              </div>
              <div class="quote-details">
                  <p><strong>Account:</strong> ${quote.account}</p>
                  <p><strong>Opportunity:</strong> ${quote.opportunity}</p>
                  <p><strong>Created At:</strong> ${formattedDate}</p>
              </div>
              <h4>📦 Line Items</h4>`;

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
              <td><input type="number" min="1" value="${item.quantity}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="quantity" onchange="updateQuoteLine(this)"></td>
              <td>
                ${parseFloat(item.unit_price.replace('$', '')).toLocaleString('en-US', {
                    style: 'currency',
                    currency: 'USD'
                })}
              </td>
              <td class="centered-td">
               <input name="discountPercentage" type="number" min="0" max="100" value="${item.discount_percentage.replace('%', '')}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="discount_percentage" onchange="updateQuoteLine(this)">
              </td>
              <td class="centered-td">
               <input name="discountAmount" type="number" min="0" max="100" value="${item.discount_amount.replace('$', '')}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="discount_amount" onchange="updateQuoteLine(this)">
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

  html += `</tbody></table>`
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
              <td><input type="number" min="1" value="${item.quantity}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="quantity" onchange="updateQuoteLine(this)"></td>
              <td>
                ${parseFloat(item.unit_price.replace('$', '')).toLocaleString('en-US', {
                    style: 'currency',
                    currency: 'USD'
                })}
              </td>
              <td class="centered-td">
               <input name="discountPercentage" type="number" min="0" max="100" value="${item.discount_percentage.replace('%', '')}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="discount_percentage" onchange="updateQuoteLine(this)">
              </td>
              <td class="centered-td">
               <input name="discountAmount" type="number" min="0" max="100" value="${item.discount_amount.replace('$', '')}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="discount_amount" onchange="updateQuoteLine(this)">
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
      🧾 Subtotal: ${parseFloat(quote.subtotal.replace('$', '')).toLocaleString('en-US', {
          style: 'currency',
          currency: 'USD'
      })}
    </p>
    <p class="discount-amount" style="color: #333;">
      🔻 Discount:
      <span class="discount-values">
        ${quote.discount_percentage}% (-${parseFloat(quote.discount_amount).toLocaleString('en-US', {
            style: 'currency',
            currency: 'USD'
        })})
      </span>
    </p>
    <p class="total-amount">
      💰 Net Amount: ${parseFloat(quote.net_amount.replace('$', '')).toLocaleString('en-US', {
          style: 'currency',
          currency: 'USD'
      })}
    </p>
  </div>`;

  return html;
}

/**
* ✅ Render quote details as an HTML table with NOT editable fields ||| Function to show Original Price and discount effects |||

function renderReadOnlyQuoteDetails(quote) {
  let html = `
      <div class="quote-container">
          <div class="quote-header">
              <h3>📄 Quote: ${quote.quote_name}</h3>
              <p><strong>Status:</strong> ${quote.status}</p>
          </div>
          <div class="quote-details">
              <p><strong>Account:</strong> ${quote.account}</p>
              <p><strong>Opportunity:</strong> ${quote.opportunity}</p>
              <p><strong>Created At:</strong> ${quote.created_at}</p>
          </div>
          <h4>📦 Line Items</h4>
          <table class="quote-table-read-only" data-quote-id="${quote.quote_name}">
              <thead>
                  <tr>
                      <th>Product</th>
                      <th>SKU</th>
                      <th>Quantity</th>
                      <th>Unit Price</th>
                      <th>Original Price</th>
                      <th>Discount</th>
                      <th>Total Price</th>
                  </tr>
              </thead>
              <tbody>`;

  quote.line_items.forEach(item => {
    const hasDiscount = parseFloat(item.discount.replace('%', '')) > 0;
    const rowClass = hasDiscount ? 'discounted' : '';
      html += `
          <tr class="${rowClass}">
              <td>${item.product}</td>
              <td>${item.sku}</td>
              <td><input type="number" min="1" value="${item.quantity}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="quantity" disabled></td>
              <td><input type="number" step="0.01" min="0" value="${item.unit_price.replace('$', '')}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="unit_price" disabled></td>
              <td class="original-price" data-sku="${item.sku}">
              ${(item.quantity * parseFloat(item.unit_price.replace('$', ''))).toLocaleString('en-US', {
                style: 'currency',
                currency: 'USD'
                })}
              </td>
              <td><input type="number" min="0" max="100" value="${item.discount.replace('%', '')}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="discount" disabled></td>
              <td class="total-price" data-sku="${item.sku}">
                ${parseFloat(item.total_price.replace('$', '')).toLocaleString('en-US', {
                    style: 'currency',
                    currency: 'USD'
                })}
              </td>
          </tr>`;
  });

  html += `</tbody></table>
    <p class="total-amount">
        💰 Net Amount: ${parseFloat(quote.net_amount.replace('$', '')).toLocaleString('en-US', {
            style: 'currency',
            currency: 'USD'
        })}
    </p>
  </div>`;

  return html;
}
*/

function renderReadOnlyQuoteDetails(quote) {
  const createdAt = new Date(quote.created_at);

  // Add 0 in front if necessary
  const month = String(createdAt.getMonth() + 1).padStart(2, '0');
  const day = String(createdAt.getDate()).padStart(2, '0');
  const year = createdAt.getFullYear();

  const hours = String(createdAt.getHours()).padStart(2, '0');
  const minutes = String(createdAt.getMinutes()).padStart(2, '0');
  const seconds = String(createdAt.getSeconds()).padStart(2, '0');

  const formattedDate = `${month}/${day}/${year} ${hours}:${minutes}:${seconds}`;

  var html = `<div class="quote-container">
              <div class="quote-header">
                  <h3>📄 Quote: ${quote.quote_name}</h3>
                  <p><strong>Status:</strong> ${quote.status}</p>
              </div>
              <div class="quote-details">
                  <p><strong>Account:</strong> ${quote.account}</p>
                  <p><strong>Opportunity:</strong> ${quote.opportunity}</p>
                  <p><strong>Created At:</strong> ${formattedDate}</p>
              </div>
              <h4>📦 Line Items</h4>`;

  var is_subscription_cont = 0;

  quote.line_items.forEach(item => {
    if(item.is_subscription == true){
      if(is_subscription_cont == 0){
        html += `
              <table class="quote-table quote-table-read-only" data-quote-id="${quote.quote_name}">
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
              <td><input type="number" min="1" value="${item.quantity}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="quantity" onchange="updateQuoteLine(this)" disabled></td>
              <td>
                ${parseFloat(item.unit_price.replace('$', '')).toLocaleString('en-US', {
                    style: 'currency',
                    currency: 'USD'
                })}
              </td>
              <td class="centered-td">
               <input name="discountPercentage" type="number" min="0" max="100" value="${item.discount_percentage.replace('%', '')}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="discount_percentage" onchange="updateQuoteLine(this)" disabled>
              </td>
              <td class="centered-td">
               <input name="discountAmount" type="number" min="0" max="100" value="${item.discount_amount.replace('$', '')}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="discount_amount" onchange="updateQuoteLine(this)" disabled>
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
              <table class="quote-table-read-only" data-quote-id="${quote.quote_name}">
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
              <td><input type="number" min="1" value="${item.quantity}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="quantity" onchange="updateQuoteLine(this)" disabled></td>
              <td>
                ${parseFloat(item.unit_price.replace('$', '')).toLocaleString('en-US', {
                    style: 'currency',
                    currency: 'USD'
                })}
              </td>
              <td class="centered-td">
               <input name="discountPercentage" type="number" min="0" max="100" value="${item.discount_percentage.replace('%', '')}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="discount_percentage" onchange="updateQuoteLine(this)" disabled>
              </td>
              <td class="centered-td">
               <input name="discountAmount" type="number" min="0" max="100" value="${item.discount_amount.replace('$', '')}" data-quote="${quote.quote_name}" data-quoteline-id="${item.id}" data-sku="${item.sku}" class="editable-field" data-field="discount_amount" onchange="updateQuoteLine(this)" disabled>
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
      🧾 Subtotal: ${parseFloat(quote.subtotal.replace('$', '')).toLocaleString('en-US', {
          style: 'currency',
          currency: 'USD'
      })}
    </p>
    <p class="discount-amount" style="color: #333;">
      🔻 Discount:
      <span class="discount-values">
        ${quote.discount_percentage}% (-${parseFloat(quote.discount_amount).toLocaleString('en-US', {
            style: 'currency',
            currency: 'USD'
        })})
      </span>
    </p>
    <p class="total-amount">
      💰 Net Amount: ${parseFloat(quote.net_amount.replace('$', '')).toLocaleString('en-US', {
          style: 'currency',
          currency: 'USD'
      })}
    </p>
  </div>`;

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
async function updateQuoteLine(input) {
    const quoteId = input.dataset.quote;
    const sku = input.dataset.sku;
    const field = input.dataset.field;
    let newValue = input.value.trim();
    const quoteLineId = input.dataset.quotelineId;

    if (newValue <= 0){
      alert("⚠️ Invalid quantity or unit price.");
    }

    if (!quoteId || !sku || !field) {
        console.warn("⚠️ Missing data attributes.");
        return;
    }

    console.log(`🔄 Field Changed: ${field}, SKU: ${sku}, New Value: ${newValue}, Quote: ${quoteId}, QuoteLine: ${quoteLineId}`);

    const updateData = [{ sku, field, value: newValue, quote_line_id: quoteLineId, hiddenMessage: true }];
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

            //First we update very single quote line total price
            const row =input.closest("tr");

            updatedQuote.line_items.forEach(item => {
                const totalCell = row.querySelector(`.total-price[data-sku="${sku}"]`);
                if (totalCell) {
                    //1. Get the total price from quote line
                    const total = parseFloat(item.total_price);

                    //2. Formatted
                    const formattedTotal = `$${total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

                    //3. Upgrade the DOM immediately
                    totalCell.textContent = formattedTotal;
                }

                //Update discount fields
                const discountPercentage = row.querySelector(`input[name="discountPercentage"][data-sku="${item.sku}"]`)
                const discountAmount = row.querySelector(`input[name="discountAmount"][data-sku="${item.sku}"]`);
                if (discountPercentage) {
                  let discountPct = item.discount_percentage.replace("%", "");  // "10%" -> "10"
                  discountPercentage.value = discountPct.toFixed(2);
                }

                if (discountAmount) {
                  const cleanAmount = parseFloat(item.discount_amount.replace(/[$,]/g, ""));
                  discountAmount.value = cleanAmount.toFixed(2);
                }
            });

            
            // ✅ Update subtotal
            const subtotalElement = quoteContainer.querySelector(".subtotal-amount");

            if (subtotalElement) {
                const subtotal = parseFloat(updatedQuote.subtotal);
                const formattedSubtotal = `$${subtotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                subtotalElement.textContent = `🧾 Subtotal: ${formattedSubtotal}`;
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
                netAmountParagraph.textContent = `💰 Net Amount: ${formattedTotalNetAmount}`;
            }

            alert("✅ Quote updated successfully!");
        } else {
            alert("⚠️ Failed to update quote.");
        }
    } catch (error) {
        console.error("❌ Error updating quote line:", error);
        alert("❌ Failed to update quote.");
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
  const createdAt = new Date(quote.created_at);

  // Add 0 in front if necessary
  const month = String(createdAt.getMonth() + 1).padStart(2, '0');
  const day = String(createdAt.getDate()).padStart(2, '0');
  const year = createdAt.getFullYear();

  const hours = String(createdAt.getHours()).padStart(2, '0');
  const minutes = String(createdAt.getMinutes()).padStart(2, '0');
  const seconds = String(createdAt.getSeconds()).padStart(2, '0');

  const formattedDate = `${month}/${day}/${year} ${hours}:${minutes}:${seconds}`;

  var html = `
        <div>
          ⏳ Rendering temporary quote details...
        </div>
        <div class="quote-container">
              <div class="quote-header">
                  <h3>📄 Quote: ${quote.quote_name}</h3>
                  <p><strong>Status:</strong> ${quote.status}</p>
              </div>
              <div class="quote-details">
                  <p><strong>Account:</strong> ${quote.account}</p>
                  <p><strong>Opportunity:</strong> ${quote.opportunity}</p>
                  <p><strong>Created At:</strong> ${formattedDate}</p>
              </div>
              <h4>📦 Line Items</h4>`;

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

  html += `</tbody></table>`
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
      🧾 Subtotal: ${parseFloat(quote.subtotal.replace('$', '')).toLocaleString('en-US', {
          style: 'currency',
          currency: 'USD'
      })}
    </p>
    <p class="discount-amount" style="color: #333;">
      🔻 Discount:
      <span class="discount-values">
        ${quote.discount_percentage}% (-${parseFloat(quote.discount_amount).toLocaleString('en-US', {
            style: 'currency',
            currency: 'USD'
        })})
      </span>
    </p>
    <p class="total-amount">
      💰 Net Amount: ${parseFloat(quote.net_amount.replace('$', '')).toLocaleString('en-US', {
          style: 'currency',
          currency: 'USD'
      })}
    </p>
  </div>`;

  return html;
}