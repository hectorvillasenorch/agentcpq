from django.db import migrations


def create_closed_won_contract_trigger(apps, schema_editor):
    ActionTrigger = apps.get_model("cpq", "ActionTrigger")

    trigger_name = "Create Contract on Closed Won"
    if ActionTrigger.objects.filter(name=trigger_name).exists():
        return

    ActionTrigger.objects.create(
        name=trigger_name,
        description="Create or refresh contract/subscriptions when an opportunity is Closed Won.",
        event_type="opportunity.closedwon",
        signal_timing="post_save",
        active=True,
        priority=50,
        conditions=None,
        actions=[
            {
                "operation": "CREATE",
                "target": "contract",
                "mode": "closed_won_contract",
            }
        ],
    )


def remove_closed_won_contract_trigger(apps, schema_editor):
    ActionTrigger = apps.get_model("cpq", "ActionTrigger")
    ActionTrigger.objects.filter(name="Create Contract on Closed Won").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("cpq", "0025_tenant_fiscal_year_label_mode"),
    ]

    operations = [
        migrations.RunPython(create_closed_won_contract_trigger, remove_closed_won_contract_trigger),
    ]
