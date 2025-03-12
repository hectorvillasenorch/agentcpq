# **AgentCPQ - AI-Powered CPQ System**

## **📌 Overview**
AgentCPQ is an AI-driven CPQ (Configure, Price, Quote) system that streamlines sales quoting, product configuration, bundle management, and pricing calculations using AI Agents.

This system is designed to be platform-agnostic, meaning it can integrate with various CRM/ERP solutions like Salesforce, HubSpot, or Microsoft Dynamics.

The architecture follows a **modular AI agent-based approach**, where each functional area is managed by a specialized agent, and all interactions are orchestrated through a central **Orchestrator AI**.

---

## **📂 Project Structure**
```
agentcpq/
│── agents/                # ✅ AI Agent logic & orchestration
│   ├── views.py           # ➜ Handles UI/API interaction, delegates to Orchestrator
│   ├── orchestrator.py    # ➜ Central AI-based Orchestrator logic
│   ├── quote_agent.py     # ➜ Handles quote-specific AI logic
│   ├── product_agent.py   # ➜ Handles product-related AI logic
│   ├── bundle_agent.py    # ➜ Handles bundle configurations  
│   ├── pricing_agent.py   # ➜ Handles pricing & discount logic
│   ├── approvals.py       # ➜ Handles approval workflows
│   ├── urls.py            # ➜ Defines agent-related API endpoints
│   ├── models.py          # ➜ Defines session tracking, logs, etc.
│   ├── templates/agents/  # ➜ HTML templates for agent UI
│   └── __init__.py
│
│── cpq/                   # ➜ Manages core CPQ logic (quotes, pricing, etc.)
│   ├── views.py           # ➜ CPQ UI/API interaction
│   ├── models.py          # ➜ Core CPQ models (Quotes, Products, etc.)
│   ├── urls.py            # ➜ CPQ-specific endpoints
│   ├── templates/cpq/     # ➜ CPQ-related HTML templates
│   └── __init__.py
│
│── dashboard/             # ➜ Handles UI navigation & user experience
│   ├── views.py           # ➜ Renders the main dashboard
│   ├── urls.py            # ➜ Dashboard-specific routing
│   ├── templates/dashboard/
│   └── static/            # ➜ Stores CSS & JS files
│
│── agentcpq/              # ➜ Django project settings
│   ├── settings.py        # ➜ Main project configuration
│   ├── urls.py            # ➜ Main routing for the application
│
└── manage.py
```

---

## **🚀 Key Features**
### **Quote Management**
✅ **Create Quotes**: AI-driven quote creation based on user input.  
✅ **Add Products to Quotes**: Select and configure products dynamically.  
✅ **Apply Discounts**: AI recommends optimal discounts based on customer history.  
✅ **Generate Quote PDF**: AI generates quote documents for sales teams.

### **Product & Bundle Management**
✅ **Create & Update Products**: Add new SKUs or modify existing products.  
✅ **Configure Bundles**: AI recommends product combinations for optimal pricing.  
✅ **Subscription Management**: Handles recurring billing and contract terms.

### **Pricing & Approval Logic**
✅ **Calculate Pricing**: AI-driven pricing logic with proration support.  
✅ **Approval Workflows**: AI submits quotes for approval based on predefined rules.  
✅ **Notifications**: Alerts sales teams when approvals are completed.

---

## **🛠️ Installation & Setup**
### **1️⃣ Clone the Repository**
```bash
git clone https://github.com/your-repo/AgentCPQ.git
cd AgentCPQ
```

### **2️⃣ Set Up Virtual Environment**
```bash
python3 -m venv venv
source venv/bin/activate  # (Linux/macOS)
venv\Scripts\activate  # (Windows)
```

### **3️⃣ Install Dependencies**
```bash
pip install -r requirements.txt
```

### **4️⃣ Set Up Environment Variables**
Create a `.env` file in the project root and add your credentials:
```
OPENAI_API_KEY=your_openai_api_key_here
DATABASE_URL=your_database_connection_string
```

### **5️⃣ Apply Migrations**
```bash
python manage.py migrate
```

### **6️⃣ Run the Server**
```bash
python manage.py runserver
```

---

## **🎯 Usage Workflow**
1️⃣ **Sales rep:** “Create a quote with Product A001 for ACME Corp.”  
2️⃣ **AI:** “✅ Created quote for ACME Corp. Would you like to add products?”  
3️⃣ **Sales rep:** “Add Product B002 and apply a 10% discount.”  
4️⃣ **AI:** “✅ Added product & discount applied. Do you need a quote PDF?”  
5️⃣ **Sales rep:** “Yes, generate the quote document.”  
6️⃣ **AI:** “📄 Your quote PDF is ready. Here’s the download link.”  

---

## **🤖 AI Orchestrator Logic**
The **Orchestrator AI** intelligently processes user requests and routes them to the appropriate agent:
```python
agent_map = {
    "CreateQuote": create_quote_agent,
    "AddProduct": add_product_agent,
    "ConfigureBundle": configure_bundle_agent,
    "ApplyDiscount": apply_discount_agent,
    "SubmitForApproval": submit_for_approval,
    "GeneralQuery": lambda msg: f"🤖 General response: {msg}"
}
```

---

## **📌 Roadmap**
✅ **MVP**: Core quoting & product functionality  

**MVP-Features**:
- Core quoting -- All CPQ functionality
- Approval Quote
- Make it send with DocuSign -- NEED 
- Allow voice to text

## ✅ **USE CASES / PROMPTS FOR MVP**

### 1. Pricing Inquiry  
**Jane from TechCorp mentioned that they’re evaluating  and asked for pricing on 25 seats.**  
*Agent should infer the need to generate a quote for 25 licenses.*

### 2. Competitive Analysis  
**Acme Inc. is looking at upgrading their existing CPQ system and wants a comparison between our AI-AgentCPQ and their current solution.**  
*Agent should recognize the need for a competitive analysis or product recommendation.*

### 3. Proposal Request  
**Michael from XYZ Enterprises liked the demo and said he’d need a proposal for a 3-year contract with an annual subscription.**  
*Agent should suggest creating a subscription quote with a multi-year term.*

### 4. Upsell Opportunity  
**I had a great call with Lisa at CloudTech—she's interested in adding 50 more licenses to their existing contract.**  
*Agent should identify this as an upsell opportunity and prepare a quote update.*

### 5. Discount Request  
**The finance team at GlobalSoft is reviewing our pricing, and they asked if we offer bulk discounts for 100+ seats.**  
*Agent should infer a request for discounting rules or pricing flexibility.*

🔜 **Integrations**: Support for Salesforce, HubSpot, and more  
🔜 **Advanced AI**: Adaptive learning for better quote recommendations  


✅ **Go to Market Strategy**: 
- Focus on big guys

## APPROVALS

“Submit quote for approval.”	✅ Quote Q-00032 submitted for approval. Awaiting Manager approval.
“Does this quote need approval?”	⚠️ This quote requires Manager approval due to a 20% discount. Would you like to submit it now?
“Approve quote Q-00032.”	✅ Quote Q-00032 has been approved.
“Reject quote Q-00032.”	❌ Quote Q-00032 has been rejected.
“Recall quote Q-00032.”	🔄 Quote Q-00032 has been recalled and can be modified again.