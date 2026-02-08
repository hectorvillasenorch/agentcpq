import { LightningElement, api, wire } from "lwc";
import { getFieldValue, getRecord } from "lightning/uiRecordApi";
import AGENTCPQ_ACV from "@salesforce/schema/Opportunity.AgentCPQ_ACV__c";
import AGENTCPQ_MRR from "@salesforce/schema/Opportunity.AgentCPQ_MRR__c";
import AGENTCPQ_NACV from "@salesforce/schema/Opportunity.AgentCPQ_NACV__c";
import AGENTCPQ_QUOTE_LINK from "@salesforce/schema/Opportunity.AgentCPQ_Quote_Link__c";
import AGENTCPQ_QUOTE_NUMBER from "@salesforce/schema/Opportunity.AgentCPQ_Quote_Number__c";
import AGENTCPQ_TCV from "@salesforce/schema/Opportunity.AgentCPQ_TCV__c";

const FIELDS = [
  AGENTCPQ_ACV,
  AGENTCPQ_MRR,
  AGENTCPQ_NACV,
  AGENTCPQ_QUOTE_LINK,
  AGENTCPQ_QUOTE_NUMBER,
  AGENTCPQ_TCV,
];

export default class AgentcpqQuotePanel extends LightningElement {
  @api recordId;

  @wire(getRecord, { recordId: "$recordId", fields: FIELDS })
  record;

  get currencyCode() {
    return "USD";
  }

  get quoteLink() {
    return getFieldValue(this.record.data, AGENTCPQ_QUOTE_LINK);
  }

  get quoteNumber() {
    return getFieldValue(this.record.data, AGENTCPQ_QUOTE_NUMBER);
  }

  get quoteNumberDisplay() {
    return this.formatText(this.quoteNumber);
  }

  get acvDisplay() {
    return this.formatCurrency(getFieldValue(this.record.data, AGENTCPQ_ACV));
  }

  get nacvDisplay() {
    return this.formatCurrency(getFieldValue(this.record.data, AGENTCPQ_NACV));
  }

  get tcvDisplay() {
    return this.formatCurrency(getFieldValue(this.record.data, AGENTCPQ_TCV));
  }

  get mrrDisplay() {
    return this.formatCurrency(getFieldValue(this.record.data, AGENTCPQ_MRR));
  }

  formatText(value) {
    if (value === null || value === undefined || value === "") {
      return "—";
    }
    return value;
  }

  formatCurrency(value) {
    if (value === null || value === undefined || value === "") {
      return "—";
    }
    try {
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: this.currencyCode,
      }).format(value);
    } catch (error) {
      return value;
    }
  }
}
