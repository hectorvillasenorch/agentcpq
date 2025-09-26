import hmac
import hashlib
import requests
from django.core.management.base import BaseCommand
from django.utils.timezone import now
from urllib.parse import urlencode
from cpq.models import Tenant, TenantUsageReport
from datetime import date

class Command(BaseCommand):
    help = "Fetch and store monthly usage reports from all tenants"

    def handle(self, *args, **kwargs):
        today = date.today()
        start = today.replace(day=1)
        end = today

        for tenant in Tenant.objects.exclude(api_key__isnull=True).exclude(api_secret__isnull=True):
            print(f"⏳ Fetching usage for {tenant.name}...")

            # Build URL
            params = {
                "start": start.isoformat(),
                "end": end.isoformat()
            }
            path = f"/api/usage/?{urlencode(params)}"
            use_dev = False  # ← Toggle for testing

            if use_dev:
                # Local development
                url = f"http://localhost:8000{path}"
            else:
                # Production domain with subdomain
                subdomain = tenant.name.lower().replace(" ", "")
                url = f"https://{subdomain}.agentcpq.ai{path}"

            # Timestamp + message + HMAC signature
            timestamp = now().isoformat()
            message = f"GET{path}{''}{timestamp}"
            signature = hmac.new(
                tenant.api_secret.encode(),
                msg=message.encode(),
                digestmod=hashlib.sha256
            ).hexdigest()

            try:
                res = requests.get(url, headers={
                    "X-API-KEY": tenant.api_key,
                    "X-Timestamp": timestamp,
                    "X-Signature": signature,
                }, timeout=10)

                if res.status_code != 200:
                    print(f"❌ Failed for {tenant.name}: {res.status_code} {res.text}")
                    continue

                data = res.json()
                print(f"✅ ✅ ✅ ✅ ✅ DATA ✅ ✅ ✅  {tenant.id}: {data['tenant_id']}")

                usage_report, created = TenantUsageReport.objects.update_or_create(
                    tenant_id=tenant.id,
                    tenant_long_id=data["tenant_id"],
                    billing_period=start,
                    defaults={
                        "total_actions": data["total_actions"],
                        "overflow_actions": data["overflow_actions"]
                    }
                )
                print(f"✅ Saved usage for {tenant.name}: {data['total_actions']} actions")

            except Exception as e:
                print(f"🔥 Error with {tenant.name}: {str(e)}")
