from django.db import migrations

STAGE_KEY = "disqualified"
STAGE_LABEL = "Disqualified"
STAGE_SORT_ORDER = 55


def add_disqualified_stage(apps, schema_editor):
    OpportunityStage = apps.get_model("cpq", "OpportunityStage")
    OpportunityStage.objects.get_or_create(
        key=STAGE_KEY,
        defaults={
            "label": STAGE_LABEL,
            "active": True,
            "is_default": False,
            "sort_order": STAGE_SORT_ORDER,
        },
    )


def remove_disqualified_stage(apps, schema_editor):
    OpportunityStage = apps.get_model("cpq", "OpportunityStage")
    OpportunityStage.objects.filter(key=STAGE_KEY).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cpq", "0049_customobjectrecord1_activity_account"),
    ]

    operations = [
        migrations.RunPython(add_disqualified_stage, remove_disqualified_stage),
    ]
