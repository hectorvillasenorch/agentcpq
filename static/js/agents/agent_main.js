document.addEventListener("DOMContentLoaded", function () {
  setupChatListeners();
});

/**
* ✅ Setup chat listeners for message input and button click
*/
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

/**
* ✅ Send user message to the agent and handle response
*/
async function sendMessage() {
  const inputField = document.getElementById("user-input");
  const chatBox = document.getElementById("chat-box");

  let userMessage = inputField.value.trim();
  if (!userMessage) return;

  // Append user message to chat
  appendMessage("user-message", `<strong>You:</strong> ${userMessage}`);

  inputField.value = ""; // Clear input field

  try {
      const response = await fetch("/agents/chat/", {   
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: userMessage })
      });

      if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);

      const data = await response.json();

      // Handle agent response
      if (data.response && data.response.quote_details) {
          appendMessage("agent-message", renderQuoteDetails(data.response.quote_details));
      } else if (data.response.download_url) {
          appendMessage("agent-message", `📄 Quote PDF generated! <a href="${data.response.download_url}" target="_blank">Download Here</a>`);
      } else {
          appendMessage("agent-message", `🤖 Agent: ${data.response.message}`);
      }

      chatBox.scrollTop = chatBox.scrollHeight; // Auto-scroll chat
  } catch (error) {
      console.error("Error:", error);
      appendMessage("agent-message", `<strong>Error:</strong> Could not reach the server.`);
  }
}

/**
* ✅ Append message to the chat box
*/
function appendMessage(className, message) {
  const chatBox = document.getElementById("chat-box");
  let messageBubble = document.createElement("div");
  messageBubble.classList.add(className);
  messageBubble.innerHTML = message;
  chatBox.appendChild(messageBubble);
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
              <p><strong>Account:</strong> ${quote.account}</p>
              <p><strong>Opportunity:</strong> ${quote.opportunity}</p>
              <p><strong>Created At:</strong> ${quote.created_at}</p>
          </div>
          <h4>📦 Line Items</h4>
          <table class="quote-table">
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
              <td id="total-${item.sku}">${item.total_price}</td>
          </tr>`;
  });

  html += `</tbody></table>
      <p class="total-amount">💰 Net Amount: ${quote.net_amount}</p>
  </div>`;

  return html;
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
* ✅ Send updated quote line details to the server
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

      alert(data.response ? "✅ Quote updated successfully!" : "⚠️ Failed to update quote.");
  } catch (error) {
      console.error("❌ Error updating quote line:", error);
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