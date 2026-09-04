import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone

from agents.dealdesk_agent import dealdesk_agent
from cpq.models import Account, ApprovalRule, ApprovalStep, ApprovalWorkflow, Opportunity, Quote, Tenant

from .models import (
    AuditEvent,
    DealDeskApprovalInstance,
    DealPacket,
    SystemAuditEvent,
)
from .services import compute_template_checksum


class DealDeskBaseMixin:
    endpoint = "/api/v1/dealdesk/review"

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="dealdesk-user", password="test123")

        from cpq.models import Tenant

        self.tenant_a = Tenant.objects.create(
            tenant_id="tenant-a",
            name="Tenant A",
            domain="tenant-a.example.com",
            api_key="tenant-a-key",
            api_secret="tenant-a-secret",
        )
        self.tenant_b = Tenant.objects.create(
            tenant_id="tenant-b",
            name="Tenant B",
            domain="tenant-b.example.com",
            api_key="tenant-b-key",
            api_secret="tenant-b-secret",
        )

        self.account_a = Account.objects.create(
            name="Acme A",
            tenant_id=self.tenant_a.tenant_id,
            owner=self.user,
            created_by=self.user,
        )
        self.opportunity_a = Opportunity.objects.create(
            name="Opportunity A",
            account=self.account_a,
            amount=Decimal("15000.00"),
            created_by=self.user,
            stage="Prospecting",
        )

    def valid_payload(self, *, discount_percent=15, payment_terms="net30", has_custom_terms=False):
        return {
            "schema_version": "1.0",
            "account": {
                "id": self.account_a.id,
                "industry": "SaaS",
                "size_band": "Mid",
                "region": "NA",
            },
            "opportunity": {
                "id": self.opportunity_a.id,
                "name": self.opportunity_a.name,
                "amount": 15000,
                "close_date": "2026-03-01",
                "stage": "Negotiation",
            },
            "commercial_terms": {
                "term_months": 12,
                "billing_frequency": "monthly",
                "payment_terms": payment_terms,
                "ramp_segments": [],
            },
            "pricing_summary": {
                "list_total": 10000,
                "discount_percent": discount_percent,
                "net_total": 8500,
                "margin_band": "mid",
            },
            "concessions": [{
                "type": "custom_terms",
                "value": "legal",
                "description": "custom legal clause",
            }] if has_custom_terms else [],
            "attachments": [],
            "request_context": {
                "request_reason": "Quarter-end deal",
                "justification": "Competitive pressure",
                "competitor": "Contoso",
                "deal_notes": "Need fast review",
            },
            "policy_inputs": {
                "discount_percent": discount_percent,
                "requested_payment_terms": payment_terms,
                "margin_percent": 35,
                "has_custom_terms": has_custom_terms,
                "requires_legal": has_custom_terms,
                "required_attachments": [],
                "segment": "enterprise",
                "region_override": None,
            },
        }


class DealDeskIdempotencyConcurrencyTests(DealDeskBaseMixin, TransactionTestCase):
    reset_sequences = True

    def _post_review(self, payload, idempotency_key, host="tenant-a.example.com"):
        close_old_connections()
        client = Client()
        response = client.post(
            self.endpoint,
            data=json.dumps({"deal_packet": payload, "channel": "api"}),
            content_type="application/json",
            HTTP_X_API_KEY=self.tenant_a.api_key,
            HTTP_IDEMPOTENCY_KEY=idempotency_key,
            HTTP_HOST=host,
        )
        close_old_connections()
        return response.status_code, response.json()

    def test_concurrent_same_key_creates_single_packet_and_instance(self):
        payload = self.valid_payload(discount_percent=15, payment_terms="net30", has_custom_terms=False)
        idempotency_key = "testkey-concurrency-001"

        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            return self._post_review(payload, idempotency_key)

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            results = [future.result() for future in futures]

        self.assertEqual([status for status, _ in results], [200, 200])

        packet_ids = [body["deal_packet"]["id"] for _, body in results]
        self.assertEqual(packet_ids[0], packet_ids[1])

        packet = DealPacket.objects.get(id=packet_ids[0])
        self.assertEqual(
            DealPacket.objects.filter(
                tenant_id=self.tenant_a.tenant_id,
                idempotency_key=f"ddrv1:{self.tenant_a.tenant_id}:client:{idempotency_key}",
            ).count(),
            1,
        )
        self.assertEqual(
            DealDeskApprovalInstance.objects.filter(
                tenant_id=self.tenant_a.tenant_id,
                deal_packet=packet,
            ).count(),
            1,
        )

    def test_same_key_after_ttl_returns_409(self):
        payload = self.valid_payload(discount_percent=12)
        idempotency_key = "testkey-expiry-001"

        status_first, body_first = self._post_review(payload, idempotency_key)
        self.assertEqual(status_first, 200)

        packet_id = body_first["deal_packet"]["id"]
        DealPacket.objects.filter(id=packet_id).update(created_at=timezone.now() - timedelta(hours=25))

        status_second, body_second = self._post_review(payload, idempotency_key)
        self.assertEqual(status_second, 409)
        self.assertEqual(body_second["code"], "idempotency_key_expired")


class DealDeskTenantConflictTests(DealDeskBaseMixin, TestCase):
    def test_api_subdomain_and_api_key_mismatch_writes_only_system_audit(self):
        client = Client()
        response = client.post(
            self.endpoint,
            data=json.dumps({"deal_packet": self.valid_payload(), "channel": "api"}),
            content_type="application/json",
            HTTP_X_API_KEY=self.tenant_b.api_key,
            HTTP_HOST=self.tenant_a.domain,
            HTTP_IDEMPOTENCY_KEY="conflict-001",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(DealPacket.objects.count(), 0)
        self.assertEqual(AuditEvent.objects.count(), 0)
        self.assertEqual(SystemAuditEvent.objects.count(), 1)


class DealDeskApprovalRoutingSafetyTests(DealDeskBaseMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.template_workflow = ApprovalWorkflow.objects.create(
            name="Template WF",
            description="Reusable template",
        )
        self.template_rule = ApprovalRule.objects.create(
            workflow=self.template_workflow,
            name="Template Rule",
            priority=10,
        )
        ApprovalStep.objects.create(rule=self.template_rule, sequence=1, approver_role="Sales Director")

    def _post(self, payload, key):
        client = Client()
        return client.post(
            self.endpoint,
            data=json.dumps({"deal_packet": payload, "channel": "api"}),
            content_type="application/json",
            HTTP_X_API_KEY=self.tenant_a.api_key,
            HTTP_HOST=self.tenant_a.domain,
            HTTP_IDEMPOTENCY_KEY=key,
        )

    def test_instance_fallback_does_not_mutate_templates(self):
        before_checksum = compute_template_checksum([self.template_workflow.id])

        payload = self.valid_payload(discount_percent=30, payment_terms="net60", has_custom_terms=True)
        response = self._post(payload, "approval-fallback-001")
        self.assertEqual(response.status_code, 200)

        instance = DealDeskApprovalInstance.objects.order_by("-id").first()
        self.assertIsNotNone(instance)
        self.assertEqual(instance.routing_mode, DealDeskApprovalInstance.ROUTING_INSTANCE_FALLBACK)
        self.assertIsNotNone(instance.instance_workflow_ref_id)
        self.assertIsNone(instance.template_workflow_ref_id)

        after_checksum = compute_template_checksum([self.template_workflow.id])
        self.assertEqual(before_checksum, after_checksum)

    def test_template_match_uses_template_without_mutation(self):
        before_checksum = compute_template_checksum([self.template_workflow.id])

        payload = self.valid_payload(discount_percent=15, payment_terms="net30", has_custom_terms=False)
        response = self._post(payload, "approval-template-001")
        self.assertEqual(response.status_code, 200)

        instance = DealDeskApprovalInstance.objects.order_by("-id").first()
        self.assertIsNotNone(instance)
        self.assertEqual(instance.routing_mode, DealDeskApprovalInstance.ROUTING_TEMPLATE_USED)
        self.assertEqual(instance.template_workflow_ref_id, self.template_workflow.id)

        after_checksum = compute_template_checksum([self.template_workflow.id])
        self.assertEqual(before_checksum, after_checksum)


class DealDeskChatAgentTests(DealDeskBaseMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.quote = Quote.objects.create(
            name="Q-99001",
            account=self.account_a,
            opportunity=self.opportunity_a,
            net_amount=Decimal("0.00"),
            discount_percentage=Decimal("15.00"),
            created_by=self.user,
            updated_by=self.user,
            owner=self.user,
        )
        self.session_data = {
            "active_quote": {
                "quote_id": self.quote.id,
                "quote_name": self.quote.name,
            }
        }

    def test_submit_for_approval_via_chat_creates_packet_and_route(self):
        preview = dealdesk_agent(self.user, "SubmitForApproval", "submit this quote for approval", self.session_data)
        self.assertIn("approval_preview", preview)
        self.assertEqual(DealPacket.objects.count(), 0)

        response = dealdesk_agent(self.user, "SubmitForApproval", "submit anyway", self.session_data)

        self.assertIn("deal_packet", response)
        packet_id = response["deal_packet"]["id"]
        packet = DealPacket.objects.get(id=packet_id)

        self.assertEqual(packet.tenant_id, self.tenant_a.tenant_id)
        self.assertEqual(packet.external_ref_type, DealPacket.EXTERNAL_REF_QUOTE)
        self.assertEqual(packet.external_ref_id, str(self.quote.id))
        self.assertEqual(packet.status, DealPacket.STATUS_IN_APPROVAL)
        self.assertEqual(DealDeskApprovalInstance.objects.filter(deal_packet=packet).count(), 1)

        self.quote.refresh_from_db()
        self.assertEqual(self.quote.status, "Pending Approval")
        latest_approval = self.quote.approvals.order_by("-id").first()
        self.assertIsNotNone(latest_approval)
        self.assertEqual(latest_approval.status, "Pending")

    def test_submit_for_approval_via_chat_replays_idempotent_request(self):
        first = dealdesk_agent(self.user, "SubmitForApproval", "submit anyway", self.session_data)
        second = dealdesk_agent(self.user, "SubmitForApproval", "submit anyway", self.session_data)

        self.assertIn("deal_packet", first)
        self.assertIn("deal_packet", second)
        self.assertEqual(first["deal_packet"]["id"], second["deal_packet"]["id"])
        self.assertTrue(second.get("replayed"))
        self.assertEqual(
            DealPacket.objects.filter(
                tenant_id=self.tenant_a.tenant_id,
                external_ref_type=DealPacket.EXTERNAL_REF_QUOTE,
                external_ref_id=str(self.quote.id),
            ).count(),
            1,
        )

    def test_check_approval_status_via_chat_returns_current_state(self):
        dealdesk_agent(self.user, "SubmitForApproval", "submit anyway", self.session_data)
        response = dealdesk_agent(self.user, "CheckApprovalStatus", "check approval status", self.session_data)

        self.assertEqual(response["deal_packet_status"], DealPacket.STATUS_IN_APPROVAL)
        self.assertIn("deal_packet_id", response)
        self.assertIn("required_approvals", response)

    def test_approve_quote_via_chat_updates_quote_and_packet(self):
        submit_response = dealdesk_agent(self.user, "SubmitForApproval", "submit anyway", self.session_data)
        packet_id = submit_response["deal_packet"]["id"]

        approve_response = dealdesk_agent(self.user, "ApproveQuote", "approve this quote", self.session_data)
        self.assertIn("approved", approve_response["message"].lower())

        self.quote.refresh_from_db()
        self.assertEqual(self.quote.status, "Approved")

        packet = DealPacket.objects.get(id=packet_id)
        self.assertEqual(packet.status, DealPacket.STATUS_APPROVED)

        latest_approval = self.quote.approvals.order_by("-id").first()
        self.assertIsNotNone(latest_approval)
        self.assertEqual(latest_approval.status, "Approved")

    def test_chat_flow_uses_first_tenant(self):
        self.assertEqual(Tenant.objects.first().id, self.tenant_a.id)

        account_b = Account.objects.create(
            name="Tenant B Account",
            tenant_id=self.tenant_b.tenant_id,
            owner=self.user,
            created_by=self.user,
        )
        opportunity_b = Opportunity.objects.create(
            name="Tenant B Opportunity",
            account=account_b,
            amount=Decimal("8000.00"),
            created_by=self.user,
            stage="Prospecting",
        )
        quote_b = Quote.objects.create(
            name="Q-99002",
            account=account_b,
            opportunity=opportunity_b,
            net_amount=Decimal("0.00"),
            discount_percentage=Decimal("15.00"),
            created_by=self.user,
            updated_by=self.user,
            owner=self.user,
        )

        session_data = {"active_quote": {"quote_id": quote_b.id, "quote_name": quote_b.name}}
        response = dealdesk_agent(self.user, "SubmitForApproval", "submit anyway", session_data)

        packet = DealPacket.objects.get(id=response["deal_packet"]["id"])
        self.assertEqual(packet.tenant_id, self.tenant_a.tenant_id)

    def test_status_before_submit_returns_preview_intelligence(self):
        response = dealdesk_agent(self.user, "CheckApprovalStatus", "check approval status", self.session_data)
        self.assertIn("approval_preview", response)
        self.assertIn("Predicted status", response["message"])
        self.assertEqual(DealPacket.objects.count(), 0)
