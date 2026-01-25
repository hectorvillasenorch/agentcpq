from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cpq", "0038_subscription_status_and_quote_line_fk"),
    ]

    operations = [
        migrations.AlterField(
            model_name="contract",
            name="contract_status",
            field=models.CharField(
                choices=[
                    ("Active", "Active"),
                    ("Expired", "Expired"),
                    ("Renewed", "Renewed"),
                    ("Cancelled", "Cancelled"),
                ],
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="subscription",
            name="status",
            field=models.CharField(
                choices=[
                    ("Active", "Active"),
                    ("Deprecated", "Deprecated"),
                    ("Cancelled", "Cancelled"),
                ],
                default="Active",
                max_length=20,
            ),
        ),
    ]
