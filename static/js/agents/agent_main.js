document.addEventListener("DOMContentLoaded", function () {
  setupChatListeners();
  setupSessionSwitching(); 
  enhanceStructuredAgentMessages(); // 🔥
});

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
          div.innerHTML = `<div class="error-message">❌ JSON parsing error</div>`;
        }
      } else {
        div.innerHTML = `<div class="error-message">⚠️ Could not find quote details JSON</div>`;
      }
    });
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
    appendMessage("user", `<strong>You:</strong> ${userMessage}`);

    inputField.value = ""; // Clear input field

    try {
        const response = await fetch("/agents/chat/", {   
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: userMessage })
        });

        console.log("Full Response:", response);

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP error! Status: ${response.status} - ${errorText}`);
        }

        const data = await response.json();
        console.log("Parsed JSON:", data);

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
            responseMessage += `📄 Quote PDF generated! <a href="${data.response.download_url}" target="_blank">Download Here</a>`;
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
        appendMessage("agent", responseMessage);

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

/**
* ✅ Render quote details as an HTML table with editable fields
*/
function renderQuoteDetails(quote) {
  let html = `
      <div class="quote-container">
          <div class="quote-header">
              <h3>📄 Quote: ${quote.quote_name}</h3>
              <p><strong>Status:</strong> ${quote.status}</p>
          </div>
          <div class="quote-details">
              <p><strong>Company:</strong> ${quote.account}</p>
              <p><strong>Deal:</strong> ${quote.opportunity}</p>
              <p><strong>Created At:</strong> ${quote.created_at}</p>
          </div>
          <h4>📦 Line Items</h4>
          <table class="quote-table" data-quote-id="${quote.quote_name}">
              <thead>
                  <tr>
                      <th>Product</th>
                      <th>SKU</th>
                      <th>Quantity</th>
                      <th>Unit Price</th>
                      <th>Total Price</th>
                  </tr>
              </thead>
              <tbody>`;

  quote.line_items.forEach(item => {
      html += `
          <tr>
              <td>${item.product}</td>
              <td>${item.sku}</td>
              <td><input type="number" min="1" value="${item.quantity}" data-quote="${quote.quote_name}" data-sku="${item.sku}" class="editable-field" data-field="quantity" onchange="updateQuoteLine(this)"></td>
              <td><input type="number" step="0.01" min="0" value="${item.unit_price.replace('$', '')}" data-quote="${quote.quote_name}" data-sku="${item.sku}" class="editable-field" data-field="unit_price" onchange="updateQuoteLine(this)"></td>
              <td class="total-price" data-sku="${item.sku}">${item.total_price}</td>
          </tr>`;
  });

  html += `</tbody></table>
      <p class="total-amount">💰 Net Amount: ${quote.net_amount}</p>
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
    const newValue = input.value.trim();

    if (!quoteId || !sku || !field) {
        console.warn("⚠️ Missing data attributes.");
        return;
    }

    console.log(`🔄 Field Changed: ${field}, SKU: ${sku}, New Value: ${newValue}, Quote: ${quoteId}`);

    const updateData = [{ sku, field, value: newValue }];
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
            });

            //Finally we update the Net Amount
            
            const quoteContainer = input.closest(".quote-container");
            const netAmountParagraph = quoteContainer.querySelector(".total-amount");

            if (netAmountParagraph) {

                //1. Get the Net Amount from quote
                const totalNetAmount = parseFloat(updatedQuote.net_amount);

                //2. Formatted
                const formattedTotalNetAmount = `$${totalNetAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

                netAmountParagraph.textContent = `💰 Net Amount: ${formattedTotalNetAmount}`;
                console.log("Se actualiza el Net Amount");
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