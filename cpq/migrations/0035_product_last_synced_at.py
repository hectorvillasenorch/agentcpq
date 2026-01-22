from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cpq", "0034_domainevent_alter_quote_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="last_synced_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
