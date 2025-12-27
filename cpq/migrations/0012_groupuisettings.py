from django.db import migrations, models
from django.conf import settings
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("cpq", "0011_customobjectpermission"),
    ]

    operations = [
        migrations.CreateModel(
            name="GroupUISettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("hide_custom_object_nav", models.BooleanField(default=False, help_text="Hide the Custom Objects links in the dashboard sidebar for users in this group.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("group", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="ui_settings", to="auth.group")),
            ],
            options={
                "verbose_name": "Group UI Settings",
                "verbose_name_plural": "Group UI Settings",
            },
        ),
    ]

