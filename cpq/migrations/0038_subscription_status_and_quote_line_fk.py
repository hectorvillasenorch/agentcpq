from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("cpq", "0037_external_id_standard_objects"),
    ]

    operations = [
        migrations.AlterField(
            model_name="subscription",
            name="quote_line",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="subscriptions",
                to="cpq.quoteline",
            ),
        ),
        migrations.AddField(
            model_name="subscription",
            name="status",
            field=models.CharField(
                choices=[("Active", "Active"), ("Deprecated", "Deprecated")],
                default="Active",
                max_length=20,
            ),
        ),
    ]
