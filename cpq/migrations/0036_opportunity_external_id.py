from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cpq", "0035_product_last_synced_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="opportunity",
            name="external_id",
            field=models.CharField(blank=True, max_length=18, null=True, unique=True),
        ),
    ]
