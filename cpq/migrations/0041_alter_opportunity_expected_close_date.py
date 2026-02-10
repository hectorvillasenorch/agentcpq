from datetime import timedelta

from django.db import migrations, models
from django.utils.timezone import now


def default_expected_close_date():
    return now().date() + timedelta(days=30)


class Migration(migrations.Migration):

    dependencies = [
        ("cpq", "0040_accesspolicy_recordaccessgrant"),
    ]

    operations = [
        migrations.AlterField(
            model_name="opportunity",
            name="expected_close_date",
            field=models.DateField(blank=True, default=default_expected_close_date, null=True),
        ),
    ]
