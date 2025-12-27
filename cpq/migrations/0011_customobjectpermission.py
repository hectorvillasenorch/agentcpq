from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("cpq", "0010_product_is_active"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomObjectPermission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("can_view", models.BooleanField(default=False)),
                ("can_add", models.BooleanField(default=False)),
                ("can_change", models.BooleanField(default=False)),
                ("can_delete", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "custom_object",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="group_permissions",
                        to="cpq.customobject",
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="custom_object_permissions",
                        to="auth.group",
                    ),
                ),
            ],
            options={
                "verbose_name": "Custom Object Permission",
                "verbose_name_plural": "Custom Object Permissions",
                "unique_together": {("group", "custom_object")},
            },
        ),
    ]

