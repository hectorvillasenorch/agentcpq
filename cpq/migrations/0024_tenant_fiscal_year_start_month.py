from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cpq", "0023_ensure_knowledge_table"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="fiscal_year_start_month",
            field=models.PositiveSmallIntegerField(default=1),
        ),
    ]
