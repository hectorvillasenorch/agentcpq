import { LightningElement, api, wire } from "lwc";
import { getFieldValue, getRecord } from "lightning/uiRecordApi";
import AGENTCPQ_QUOTE_NUMBER from "@salesforce/schema/Opportunity.AgentCPQ_Quote_Number__c";

const FIELDS = [AGENTCPQ_QUOTE_NUMBER];

export default class AgentcpqQuotePanel extends LightningElement {
  @api recordId;

  @wire(getRecord, { recordId: "$recordId", fields: FIELDS })
  record;

  get quoteNumber() {
    return getFieldValue(this.record.data, AGENTCPQ_QUOTE_NUMBER);
  }

  get quoteNumberDisplay() {
    return this.formatText(this.quoteNumber);
  }

  formatText(value) {
    if (value === null || value === undefined || value === "") {
      return "—";
    }
    return value;
  }
}
