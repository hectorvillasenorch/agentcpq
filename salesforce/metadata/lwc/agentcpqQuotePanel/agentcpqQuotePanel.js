import { LightningElement, api, wire } from "lwc";
import { getFieldValue, getRecord } from "lightning/uiRecordApi";
import AGENTCPQ_ACV from "@salesforce/schema/Opportunity.AgentCPQ_ACV__c";
import AGENTCPQ_QUOTE_LINK from "@salesforce/schema/Opportunity.AgentCPQ_Quote_Link__c";
import AGENTCPQ_NACV from "@salesforce/schema/Opportunity.AgentCPQ_NACV__c";
import AGENTCPQ_QUOTE_NUMBER from "@salesforce/schema/Opportunity.AgentCPQ_Quote_Number__c";
import AGENTCPQ_MRR from "@salesforce/schema/Opportunity.AgentCPQ_MRR__c";
import AGENTCPQ_QUOTE_ID from "@salesforce/schema/Opportunity.AgentCPQ_Quote_Id__c";
import AGENTCPQ_FORECAST_STRATEGY from "@salesforce/schema/Opportunity.AgentCPQ_Forecast_Strategy__c";
import CURRENCY_ISO_CODE from "@salesforce/schema/Opportunity.CurrencyIsoCode";

const FIELDS = [
  AGENTCPQ_ACV,
  AGENTCPQ_QUOTE_LINK,
  AGENTCPQ_NACV,
  AGENTCPQ_QUOTE_NUMBER,
  AGENTCPQ_MRR,
  AGENTCPQ_QUOTE_ID,
  AGENTCPQ_FORECAST_STRATEGY,
  CURRENCY_ISO_CODE,
];

export default class AgentcpqQuotePanel extends LightningElement {
  @api recordId;

  @wire(getRecord, { recordId: "$recordId", fields: FIELDS })
  record;

  get currencyCode() {
    return getFieldValue(this.record.data, CURRENCY_ISO_CODE) || "USD";
  }

  get quoteLink() {
    return getFieldValue(this.record.data, AGENTCPQ_QUOTE_LINK);
  }

  get quoteNumber() {
    return getFieldValue(this.record.data, AGENTCPQ_QUOTE_NUMBER);
  }

  get quoteId() {
    return getFieldValue(this.record.data, AGENTCPQ_QUOTE_ID);
  }

  get forecastStrategy() {
    return getFieldValue(this.record.data, AGENTCPQ_FORECAST_STRATEGY);
  }

  get acvDisplay() {
    return this.formatCurrency(getFieldValue(this.record.data, AGENTCPQ_ACV));
  }

  get nacvDisplay() {
    return this.formatCurrency(getFieldValue(this.record.data, AGENTCPQ_NACV));
  }

  get mrrDisplay() {
    return this.formatCurrency(getFieldValue(this.record.data, AGENTCPQ_MRR));
  }

  get quoteNumberDisplay() {
    return this.formatText(this.quoteNumber);
  }

  get quoteIdDisplay() {
    return this.formatText(this.quoteId);
  }

  get forecastStrategyDisplay() {
    return this.formatText(this.forecastStrategy);
  }

  get quoteLinkLabel() {
    return this.quoteNumber ? `Show Quote Details ${this.quoteNumber}` : "Show Quote Details";
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
