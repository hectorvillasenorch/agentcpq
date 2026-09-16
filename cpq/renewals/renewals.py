import logging, re
from datetime import date, timedelta, datetime
from django.utils.timezone import now
from dateutil.relativedelta import relativedelta
from ..models import (
    Contract,
    Subscription,
    Quote,
    QuoteLine,
    Opportunity,
    ScheduledTask,
    CPQSettings,
    OpportunityStage,
    default_opportunity_stage,
    DEFAULT_OPPORTUNITY_STAGE_KEY,
)
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

# Terminal stages a *newly created* opportunity should never start in.
_TERMINAL_STAGES = {"closedwon", "closedlost", "closed", "disqualified"}


def _open_stage_for_new_opportunity():
    """Return an OPEN (pipeline) stage for a new opportunity.

    Falls back away from the configured default if it ever points at a terminal
    stage, so renewal opportunities always begin in the pipeline — never won/lost.
    """
    stage = default_opportunity_stage()
    if stage in _TERMINAL_STAGES:
        open_stage = (
            OpportunityStage.objects.exclude(key__in=_TERMINAL_STAGES)
            .order_by("sort_order", "id")
            .values_list("key", flat=True)
            .first()
        )
        return open_stage or DEFAULT_OPPORTUNITY_STAGE_KEY
    return stage

def _is_renewal_opportunity(opportunity):
    name = (getattr(opportunity, "name", "") or "").strip().lower()
    return name.startswith("renewal") or "renewal opportunity" in name

def _push_renewal_to_salesforce(opportunity, quote):
    settings_obj = CPQSettings.safe_first() or CPQSettings()
    if not settings_obj.forecast_opportunity_enabled:
        return

    try:
        from salesforce.utils import (
            SF_API_VERSION,
            build_agentcpq_quote_link,
            get_valid_salesforce_token,
            salesforce_request,
        )
    except Exception as exc:
        logger.warning("Salesforce sync unavailable: %s", exc)
        return

    token = get_valid_salesforce_token(timeout=8)
    if not token:
        logger.warning("Salesforce token missing; renewal sync skipped.")
        return

    account_sf_id = getattr(opportunity.account, "external_id", None)
    if not account_sf_id:
        logger.warning("Opportunity %s has no Salesforce account id; renewal sync skipped.", opportunity.id)
        return

    if not opportunity.external_id:
        stage_name = settings_obj.forecast_opportunity_stage or "Forecast"
        close_date = opportunity.expected_close_date or (date.today() + timedelta(days=30))
        quote_id_value = str(quote.public_id or quote.qteid or quote.name)
        quote_number_value = str(quote.name or quote.qteid or quote.public_id)
        quote_link_value = build_agentcpq_quote_link(quote.id, quote_label=quote_number_value)
        payload = {
            "Name": opportunity.name,
            "AccountId": account_sf_id,
            "StageName": stage_name,
            "CloseDate": close_date.isoformat(),
            "Amount": str(quote.net_amount),
            "AgentCPQ_Quote_Id__c": quote_id_value,
            "AgentCPQ_Quote_Number__c": quote_number_value,
            "AgentCPQ_NACV__c": str(quote.net_amount),
            "AgentCPQ_ACV__c": str(quote.net_amount),
        }
        if quote_link_value:
            payload["AgentCPQ_Quote_Link__c"] = quote_link_value

        create_url = f"{token.instance_url}/services/data/{SF_API_VERSION}/sobjects/Opportunity"
        response = salesforce_request(token, "POST", create_url, json=payload, timeout=8)
        if not response or response.status_code not in {200, 201}:
            logger.warning(
                "Failed to create Salesforce renewal opportunity (HTTP %s).",
                getattr(response, "status_code", "n/a"),
            )
            return
        sf_id = response.json().get("id")
        if sf_id:
            opportunity.external_id = sf_id
            opportunity.save(update_fields=["external_id"])
            quote.sf_opportunity_id = sf_id
            quote.save(update_fields=["sf_opportunity_id"])

    if opportunity.external_id:
        try:
            from salesforce.views import sync_quote_to_salesforce
            sync_quote_to_salesforce(None, quote.id)
        except Exception as exc:
            logger.warning("Failed to sync renewal quote lines to Salesforce: %s", exc)

def create_contract_after_closed_won(opportunity):
    quote = opportunity.primary_quote or opportunity.quotes.order_by("-id").first()
    tomorrow = date.today() + timedelta(days=1)
    if not quote:
        logger.warning("⚠️ Opportunity %s has no quote; skipping contract creation.", opportunity.id)
        return

    existing_contracts = Contract.objects.filter(opportunity=opportunity, contract_status="Active")
    if existing_contracts.exists():
        if _is_renewal_opportunity(opportunity):
            Contract.objects.filter(pk__in=existing_contracts.values_list("pk", flat=True)).update(
                contract_status="Renewed"
            )
            Subscription.objects.filter(contract__in=existing_contracts).update(
                status="Deprecated"
            )
        else:
            Contract.objects.filter(pk__in=existing_contracts.values_list("pk", flat=True)).update(
                contract_status="Cancelled"
            )
            Subscription.objects.filter(contract__in=existing_contracts).update(
                status="Cancelled"
            )

    # A renewal opportunity replaces the contract of the opportunity it renews.
    if _is_renewal_opportunity(opportunity):
        source = getattr(opportunity, "renews_opportunity", None)
        if source is not None:
            source_contracts = Contract.objects.filter(opportunity=source, contract_status="Active")
            Contract.objects.filter(pk__in=source_contracts.values_list("pk", flat=True)).update(
                contract_status="Renewed"
            )
            Subscription.objects.filter(contract__in=source_contracts).update(status="Deprecated")

    contract = Contract.objects.create(
        opportunity=opportunity,
        start_date=tomorrow,
        end_date=tomorrow + relativedelta(months=12),
        contract_status="Active",
    )

    print(f"\nContract created ✅ for opportunity {opportunity.name}\n")

    max_term = 0

    for line in quote.quote_lines.all():
        if line.is_subscription:
            term_value = line.term if line.term and line.term > 0 else 12

            Subscription.objects.create(
                quote=quote,
                quote_line=line,
                product=line.product,
                contract=contract,
                start_date=tomorrow,
                billing_cycle=line.billing_frequency,
                price_per_cycle=line.total_price,
                term=term_value,
                end_date=tomorrow + relativedelta(months=term_value),
                status="Active",
            )

            print(f"\nSubscription for line {line.product} created ✅\n")

            if term_value > max_term:
                max_term = term_value

    if max_term and max_term > 0:
        contract.end_date = tomorrow + relativedelta(months=max_term)
    else:
        contract.end_date = tomorrow + relativedelta(months=12)
    contract.save()

    # Final signed value → NACV / Amount (renewals: this is the new annual contract value).
    # Raw UPDATE (no signals) so the closed-won trigger does not re-fire on itself.
    Opportunity.objects.filter(pk=opportunity.pk).update(
        nacv=quote.net_amount,
        amount=quote.net_amount,
    )
    opportunity.nacv = quote.net_amount
    opportunity.amount = quote.net_amount

    return

def make_opportunity_renewal(opportunity):
    try:
        account = opportunity.account
        original_quote = opportunity.primary_quote
        user = opportunity.created_by

        if not original_quote:
            logger.warning(f"⚠️ Opportunity {opportunity.id} has no quotes to renew.")
            return None

        # Determine the renewal contract window
        subscription_terms = []
        for line in original_quote.quote_lines.all():
            if line.is_subscription:
                subscription_terms.append(line.term if line.term and line.term > 0 else 12)

        term_months = max(subscription_terms) if subscription_terms else 12

        current_contract = opportunity.contracts.order_by("start_date").first()

        def _normalize_date(value):
            if isinstance(value, datetime):
                return value.date()
            return value

        contract_end_date = _normalize_date(current_contract.end_date) if current_contract and current_contract.end_date else None
        contract_start_date = _normalize_date(current_contract.start_date) if current_contract and current_contract.start_date else None

        if contract_end_date:
            renewal_start_date = contract_end_date + timedelta(days=1)
        elif contract_start_date:
            renewal_start_date = contract_start_date + relativedelta(months=term_months)
        else:
            renewal_start_date = date.today() + timedelta(days=1)

        renewal_end_date = renewal_start_date + relativedelta(months=term_months)
        expected_close_date = renewal_start_date + timedelta(days=30)

        start_str = renewal_start_date.strftime("%m-%d-%Y")
        end_str = renewal_end_date.strftime("%m-%d-%Y")

        # 1. Create a new opportunity (guard against duplicates for the same account/opportunity)
        renewal_name = f"Renewal Opportunity - {account.name} - ({start_str} - {end_str})"

        with transaction.atomic():
            # Lock the base opportunity row so concurrent triggers serialize
            Opportunity.objects.select_for_update().filter(pk=opportunity.pk).exists()

            existing_renewal = Opportunity.objects.filter(name=renewal_name, account=account).first()
            if existing_renewal:
                if not existing_renewal.renews_opportunity_id:
                    existing_renewal.renews_opportunity = opportunity
                    existing_renewal.save(update_fields=["renews_opportunity"])
                if existing_renewal.expected_close_date != expected_close_date:
                    existing_renewal.expected_close_date = expected_close_date
                    existing_renewal.save(update_fields=["expected_close_date"])
                logger.info(
                    "ℹ️ Renewal opportunity %s already exists for opportunity %s (id=%s). Skipping creation.",
                    existing_renewal.name,
                    opportunity.name,
                    opportunity.id,
                )
                return True

            renewal_opp = Opportunity.objects.create(
                name=renewal_name,
                account=account,
                amount=original_quote.net_amount,
                stage=_open_stage_for_new_opportunity(),
                owner=opportunity.owner,
                expected_close_date=expected_close_date,
                created_by=user,
                hs_deal_id=None,
                nacv=original_quote.net_amount,
                renewal_baseline=original_quote.net_amount,
                renews_opportunity=opportunity,
            )

        # 2. (Quote name is auto-assigned as Q-##### by the Quote model on save.)

        # 3. Calculate expiration date (timezone aware)
        first_contract = opportunity.contracts.first()
        if first_contract and first_contract.end_date:
            expiration_date = first_contract.end_date + relativedelta(months=1)
        else:
            expiration_date = date.today() + relativedelta(months=1)

        # Convert to datetime if it's a date
        if isinstance(expiration_date, date) and not isinstance(expiration_date, datetime):
            expiration_date = datetime.combine(expiration_date, datetime.min.time())

        # Make it timezone aware
        expiration_date = timezone.make_aware(expiration_date)

        # 4. Create a new quote (copy of the original)
        renewal_quote = Quote.objects.create(
            account=account,
            opportunity=renewal_opp,
            subtotal=original_quote.subtotal,
            net_amount=original_quote.net_amount,
            tax_percentage=original_quote.tax_percentage,
            tax_amount=original_quote.tax_amount,
            discount_type=original_quote.discount_type,
            discount_percentage=original_quote.discount_percentage,
            discount_amount=original_quote.discount_amount,
            expiration_date=expiration_date,
            notes=original_quote.notes,
            owner=original_quote.owner or user,
            created_by=user,
        )

        renewal_opp.primary_quote = renewal_quote
        renewal_opp.save(update_fields=["primary_quote"])

        # 5. Copy quote lines
        for line in original_quote.quote_lines.all():
            QuoteLine.objects.create(
                quote=renewal_quote,
                product=line.product,
                product_name=line.product_name,
                quantity=line.quantity,
                unit_price=line.unit_price,
                special_price=line.special_price,
                discount_type=line.discount_type,
                discount_percentage=line.discount_percentage,
                discount_amount=line.discount_amount,
                subtotal=line.subtotal,
                total_price=line.total_price,
                parent_quote=line.parent_quote,
                is_subscription=line.is_subscription,
                is_bundle_parent=line.is_bundle_parent,
                is_bundle_child=line.is_bundle_child,
                is_bundle_component_selected=line.is_bundle_component_selected,
                parent_line=line.parent_line,
                product_option=line.product_option,
                billing_frequency=line.billing_frequency,
                term=line.term,
                billing_start_date=line.billing_start_date,
                billing_end_date=line.billing_end_date,
                sku=line.sku,
                description=line.description,
                tax_rate=line.tax_rate,
                created_by=user,
            )

        renewal_quote.save()

        # 6. Update opportunity with the new quote + refresh renewal metrics (NACV tracks the renewal quote)
        Opportunity.objects.filter(pk=renewal_opp.pk).update(
            nacv=renewal_quote.net_amount,
            amount=renewal_quote.net_amount,
            primary_quote_id=renewal_quote.pk,
        )
        renewal_opp.nacv = renewal_quote.net_amount
        renewal_opp.amount = renewal_quote.net_amount
        renewal_opp.primary_quote = renewal_quote

        logger.info(f"✅ Renewal {renewal_opp.name} created with Quote {renewal_quote.name}")
        _push_renewal_to_salesforce(renewal_opp, renewal_quote)
        return True

    except Exception as e:
        error_msg = str(e)
        logger.exception(f"❌ Error creating renewal opportunity for {opportunity.id}: {error_msg}")
        return False, error_msg
    
def create_renewal_task_for_opportunity(opportunity, months_before: int):
    """
    Creates a record in ScheduledTask for the specified opportunity,
    scheduling the execution a number of months before the first contract's expiration.
    
    Args:
        opportunity (Opportunity): The opportunity for which the task is created.
        months_before (int): Number of months before the contract when the task should be executed.
    """
    try:
        contract = opportunity.contracts.first()
        if not contract or not contract.end_date:
            logger.warning(f"⚠️ Opportunity {opportunity.id} has no contract or contract end date")
            return None

        # Calculate execute_at by subtracting months_before months from the contract's end_date
        naive_execute_at = contract.end_date - relativedelta(months=months_before)
        # Convert to a timezone-aware datetime (time set to 00:00:00 of the day)
        execute_at = timezone.make_aware(
            datetime.combine(naive_execute_at, datetime.min.time())
        )

        # Create ScheduledTask
        renewal_task = ScheduledTask.objects.create(
            opportunity=opportunity,
            execute_at=execute_at,
            status="pending",
            attempts=0,
            last_error=None,
            created_at=now(),
            updated_at=now()
        )

        logger.info(f"✅ ScheduledTask created for Opportunity {opportunity.id} scheduled at {execute_at}")
        return renewal_task

    except Exception as e:
        logger.exception(f"❌ Error creating renewal task for Opportunity {opportunity.id}: {e}")
        return None
