from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cpq", "0024_tenant_fiscal_year_start_month"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="fiscal_year_label_mode",
            field=models.CharField(
                choices=[("start", "Start Year"), ("end", "End Year")],
                default="start",
                max_length=5,
            ),
        ),
    ]
