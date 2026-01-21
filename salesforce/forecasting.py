import logging

import requests

from salesforce.utils import SF_API_VERSION, get_valid_salesforce_token, soql_query_all

logger = logging.getLogger(__name__)


def _salesforce_headers(token):
    return {
        "Authorization": f"Bearer {token.access_token}",
        "Content-Type": "application/json",
    }


def sync_forecast_opportunity(opportunity, quote, account, forecast_amount, settings_obj, timeout=8):
    token = get_valid_salesforce_token(timeout=timeout)
    if not token:
        return {"status": "skipped", "reason": "missing_token"}

    if not quote.public_id:
        return {"status": "skipped", "reason": "missing_quote_public_id"}

    if not account.external_id:
        return {"status": "skipped", "reason": "missing_account_external_id"}

    quote_id_value = str(quote.public_id)
    soql = (
        "SELECT Id FROM Opportunity "
        f"WHERE AgentCPQ_Quote_Id__c = '{quote_id_value}'"
    )
    records, response = soql_query_all(token, soql, timeout=timeout)
    if records is None:
        logger.warning("Salesforce Opportunity lookup failed (HTTP %s).", response.status_code)
        return {"status": "error", "reason": "lookup_failed"}

    payload = {
        "Name": opportunity.name,
        "StageName": settings_obj.forecast_opportunity_stage or "Forecast",
        "CloseDate": opportunity.expected_close_date.isoformat() if opportunity.expected_close_date else None,
        "Amount": str(forecast_amount),
        "AccountId": account.external_id,
        "AgentCPQ_Quote_Id__c": quote_id_value,
        "AgentCPQ_Forecast_Strategy__c": settings_obj.forecast_amount_strategy or "TOTAL_CONTRACT_VALUE",
        "AgentCPQ_NACV__c": str(forecast_amount),
        "AgentCPQ_ACV__c": str(forecast_amount),
    }
    payload = {key: value for key, value in payload.items() if value is not None}

    if records:
        sf_id = records[0].get("Id")
        url = f"{token.instance_url}/services/data/{SF_API_VERSION}/sobjects/Opportunity/{sf_id}"
        res = requests.patch(url, headers=_salesforce_headers(token), json=payload, timeout=timeout)
        if res.status_code in {204, 200}:
            return {"status": "updated", "salesforce_id": sf_id}
        logger.warning("Salesforce Opportunity update failed (HTTP %s).", res.status_code)
        return {"status": "error", "reason": "update_failed"}

    url = f"{token.instance_url}/services/data/{SF_API_VERSION}/sobjects/Opportunity"
    res = requests.post(url, headers=_salesforce_headers(token), json=payload, timeout=timeout)
    if res.status_code in {200, 201}:
        return {"status": "created", "salesforce_id": res.json().get("id")}

    logger.warning("Salesforce Opportunity create failed (HTTP %s).", res.status_code)
    return {"status": "error", "reason": "create_failed"}
