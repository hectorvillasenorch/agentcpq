from django.db import migrations


def update_leads_by_status_metric(apps, schema_editor):
    MetricDefinition = apps.get_model("intelligence", "MetricDefinition")
    MetricSnapshot = apps.get_model("intelligence", "MetricSnapshot")
    MetricDefinition.objects.filter(domain="leads", metric_key="leads_by_status").update(
        compute_spec={
            "table": "cpq_lead",
            "group_by": "status",
            "aggregation": "count",
        }
    )
    MetricSnapshot.objects.filter(domain="leads", metric_key="leads_by_status").delete()


def noop(apps, schema_editor):
    return


class Migration(migrations.Migration):
    dependencies = [
        ("intelligence", "0003_slaconfig"),
    ]

    operations = [
        migrations.RunPython(update_leads_by_status_metric, noop),
    ]
