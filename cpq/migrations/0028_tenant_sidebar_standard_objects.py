from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cpq", "0027_customobject_show_in_sidebar"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="sidebar_standard_objects",
            field=models.JSONField(
                blank=True,
                null=True,
                default=None,
                help_text="Standard object keys to show in the dashboard sidebar.",
            ),
        ),
    ]
