import uuid

from django.db import migrations, models


SLA_KEY = "LEADS_NEW_SLA_DAYS"
SLA_DEFAULT = 1


def seed_sla_config(apps, schema_editor):
    SlaConfig = apps.get_model("intelligence", "SlaConfig")
    Tenant = apps.get_model("cpq", "Tenant")
    for tenant in Tenant.objects.all():
        tenant_id = str(getattr(tenant, "tenant_id", None) or getattr(tenant, "pk", ""))
        if not tenant_id:
            continue
        SlaConfig.objects.get_or_create(
            tenant_id=tenant_id,
            key=SLA_KEY,
            defaults={"value": SLA_DEFAULT},
        )


def unseed_sla_config(apps, schema_editor):
    SlaConfig = apps.get_model("intelligence", "SlaConfig")
    SlaConfig.objects.filter(key=SLA_KEY).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("intelligence", "0002_seed_intelligence_defaults"),
        ("cpq", "0026_closed_won_contract_trigger"),
    ]

    operations = [
        migrations.CreateModel(
            name="SlaConfig",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("tenant_id", models.CharField(max_length=50, db_index=True)),
                ("key", models.CharField(max_length=128, db_index=True)),
                ("value", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "intelligence_slaconfig",
            },
        ),
        migrations.AddConstraint(
            model_name="slaconfig",
            constraint=models.UniqueConstraint(fields=("tenant_id", "key"), name="intell_sla_tenant_key_uq"),
        ),
        migrations.RunPython(seed_sla_config, unseed_sla_config),
    ]
