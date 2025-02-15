<div>
                <h3>✅ ${quote.quote_name}</h3>
                <p><strong>Quote Name:</strong> ${quote.quote_name}</p>
                <p><strong>Account:</strong> ${quote.account}</p>
                <p><strong>Opportunity:</strong> ${quote.opportunity}</p>
                <p><strong>Status:</strong> ${quote.status}</p>
                <p><strong>Created At:</strong> ${quote.created_at}</p>
                <p><strong>Net Amount:</strong> ${quote.net_amount}</p>
                
                <h4>📦 Line Items</h4>
                <table border="1" style="width: 100%; border-collapse: collapse; text-align: left;">
                    <thead>
                        <tr style="background-color: #e0f7fa;">
                            <th style="padding: 8px;">Product</th>
                            <th style="padding: 8px;">SKU</th>
                            <th style="padding: 8px;">Quantity</th>
                            <th style="padding: 8px;">Unit Price</th>
                            <th style="padding: 8px;">Total Price</th>
                        </tr>
                    </thead>
                    <tbody>`;
    
        quote.line_items.forEach(item => {
            html += `
                <tr>
                    <td style="padding: 8px;">${item.product}</td>
                    <td style="padding: 8px;">${item.sku}</td>
                    
                    <!-- Editable Quantity -->
                    <td style="padding: 8px;">
                        <input type="number" min="1" value="${item.quantity}" 
                               data-quote="${quote.quote_name}" 
                               data-sku="${item.sku}" 
                               class="editable-field" 
                               data-field="quantity"
                               onchange="updateQuoteLine(this)">
                    </td>
    
                    <!-- Editable Price -->
                    <td style="padding: 8px;">
                        <input type="number" step="0.01" min="0" value="${item.unit_price.replace('$', '')}" 
                               data-quote="${quote.quote_name}" 
                               data-sku="${item.sku}" 
                               class="editable-field" 
                               data-field="unit_price"
                               onchange="updateQuoteLine(this)">
                    </td>
    
                    <!-- Non-editable Total -->
                    <td style="padding: 8px;" id="total-${item.sku}">${item.total_price}</td>
                </tr>`;
        });
    
        html += `</tbody></table></div>`;
        return html;
    }