from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_default_access_policy(apps, schema_editor):
    AccessPolicy = apps.get_model("cpq", "AccessPolicy")
    if not AccessPolicy.objects.filter(is_active=True).exists():
        AccessPolicy.objects.create(
            key="global",
            label="Global Policy",
            strategy="legacy_partner",
            is_active=True,
            allow_superuser=True,
            allow_staff=True,
            include_partner_scope=True,
            allow_unassigned_records=False,
            use_record_grants=True,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("cpq", "0039_contract_cancelled_status"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccessPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "key",
                    models.CharField(
                        default="global",
                        help_text="Unique key for this policy (for example: global).",
                        max_length=80,
                        unique=True,
                    ),
                ),
                ("label", models.CharField(blank=True, max_length=120)),
                (
                    "strategy",
                    models.CharField(
                        choices=[
                            ("legacy_partner", "Legacy Partner Scope"),
                            ("creator_only", "Creator Only"),
                            ("creator_or_group", "Creator Or Group Grant"),
                            ("owner_or_group", "Owner Or Group Grant"),
                            ("creator_or_owner_or_group", "Creator/Owner Or Group Grant"),
                        ],
                        default="legacy_partner",
                        max_length=40,
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Only one active access policy should exist at a time.",
                    ),
                ),
                ("allow_superuser", models.BooleanField(default=True)),
                ("allow_staff", models.BooleanField(default=True)),
                (
                    "include_partner_scope",
                    models.BooleanField(
                        default=True,
                        help_text="Apply existing partner account/contact scoping before record ACL evaluation.",
                    ),
                ),
                (
                    "allow_unassigned_records",
                    models.BooleanField(
                        default=False,
                        help_text="Allow records with no owner/creator under strict strategies.",
                    ),
                ),
                (
                    "use_record_grants",
                    models.BooleanField(
                        default=True,
                        help_text="Enable explicit user/group grants for record access.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Access Policy",
                "verbose_name_plural": "Access Policies",
            },
        ),
        migrations.CreateModel(
            name="RecordAccessGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("object_id", models.PositiveBigIntegerField(db_index=True)),
                ("can_view", models.BooleanField(default=True)),
                ("can_change", models.BooleanField(default=False)),
                ("can_delete", models.BooleanField(default=False)),
                ("can_share", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "content_type",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="contenttypes.contenttype"),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="record_access_grants_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "group",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="record_access_grants",
                        to="auth.group",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="record_access_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Record Access Grant",
                "verbose_name_plural": "Record Access Grants",
            },
        ),
        migrations.AddConstraint(
            model_name="recordaccessgrant",
            constraint=models.CheckConstraint(
                check=(
                    (models.Q(user__isnull=False, group__isnull=True))
                    | (models.Q(user__isnull=True, group__isnull=False))
                ),
                name="record_access_grant_user_xor_group",
            ),
        ),
        migrations.AddConstraint(
            model_name="recordaccessgrant",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(can_view=True)
                    | models.Q(can_change=True)
                    | models.Q(can_delete=True)
                    | models.Q(can_share=True)
                ),
                name="record_access_grant_requires_permission",
            ),
        ),
        migrations.AddConstraint(
            model_name="recordaccessgrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(user__isnull=False),
                fields=("content_type", "object_id", "user"),
                name="record_access_grant_unique_user",
            ),
        ),
        migrations.AddConstraint(
            model_name="recordaccessgrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(group__isnull=False),
                fields=("content_type", "object_id", "group"),
                name="record_access_grant_unique_group",
            ),
        ),
        migrations.AddIndex(
            model_name="recordaccessgrant",
            index=models.Index(fields=["content_type", "object_id"], name="cpq_recorda_content_518edd_idx"),
        ),
        migrations.AddIndex(
            model_name="recordaccessgrant",
            index=models.Index(fields=["user"], name="cpq_recorda_user_id_11cd8f_idx"),
        ),
        migrations.AddIndex(
            model_name="recordaccessgrant",
            index=models.Index(fields=["group"], name="cpq_recorda_group_i_65db8b_idx"),
        ),
        migrations.RunPython(create_default_access_policy, migrations.RunPython.noop),
    ]
