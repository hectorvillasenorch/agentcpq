from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cpq", "0026_closed_won_contract_trigger"),
    ]

    operations = [
        migrations.AddField(
            model_name="customobject",
            name="show_in_sidebar",
            field=models.BooleanField(
                default=True,
                help_text="Show this object in the dashboard sidebar under Accounts.",
            ),
        ),
    ]
