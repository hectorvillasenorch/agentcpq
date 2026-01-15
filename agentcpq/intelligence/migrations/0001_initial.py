import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name="FeatureFlag",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("tenant_id", models.CharField(max_length=50, db_index=True)),
                ("key", models.CharField(max_length=128, db_index=True)),
                ("enabled", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "intelligence_featureflag",
            },
        ),
        migrations.CreateModel(
            name="MetricDefinition",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("tenant_id", models.CharField(max_length=50, db_index=True)),
                ("domain", models.CharField(max_length=64, db_index=True)),
                ("metric_key", models.CharField(max_length=128, db_index=True)),
                ("display_name", models.CharField(max_length=128)),
                ("description", models.TextField(null=True, blank=True)),
                ("unit", models.CharField(max_length=32, null=True, blank=True)),
                ("compute_method", models.CharField(max_length=32)),
                ("compute_spec", models.JSONField(null=True, blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "intelligence_metricdefinition",
            },
        ),
        migrations.CreateModel(
            name="MetricSnapshot",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("tenant_id", models.CharField(max_length=50, db_index=True)),
                ("domain", models.CharField(max_length=64, db_index=True)),
                ("metric_key", models.CharField(max_length=128, db_index=True)),
                ("timeframe_key", models.CharField(max_length=64, db_index=True)),
                ("period_start", models.DateField(db_index=True)),
                ("period_end", models.DateField(db_index=True)),
                ("value_number", models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)),
                ("value_json", models.JSONField(null=True, blank=True)),
                ("generated_at", models.DateTimeField(db_index=True)),
                ("source_fingerprint", models.CharField(max_length=256, null=True, blank=True)),
            ],
            options={
                "db_table": "intelligence_metricsnapshot",
            },
        ),
        migrations.CreateModel(
            name="ThresholdRule",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("tenant_id", models.CharField(max_length=50, db_index=True)),
                ("domain", models.CharField(max_length=64, db_index=True)),
                ("rule_key", models.CharField(max_length=128, db_index=True)),
                ("severity", models.CharField(max_length=16, choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")], db_index=True)),
                ("condition", models.JSONField()),
                ("message_template", models.TextField()),
                ("audience_roles", models.JSONField()),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "intelligence_thresholdrule",
            },
        ),
        migrations.CreateModel(
            name="NotificationPreference",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("tenant_id", models.CharField(max_length=50, db_index=True)),
                ("user_id", models.UUIDField(db_index=True)),
                ("role_key", models.CharField(max_length=64, db_index=True)),
                ("channels", models.JSONField(default=["in_app"])),
                ("max_per_day", models.IntegerField(default=1)),
                ("quiet_hours", models.JSONField(null=True, blank=True)),
                ("digest_enabled", models.BooleanField(default=True)),
                ("digest_frequency", models.CharField(max_length=16, choices=[("daily", "Daily"), ("weekly", "Weekly")], default="weekly")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "intelligence_notificationpreference",
            },
        ),
        migrations.CreateModel(
            name="NotificationEvent",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("tenant_id", models.CharField(max_length=50, db_index=True)),
                ("user_id", models.UUIDField(db_index=True)),
                ("role_key", models.CharField(max_length=64, db_index=True)),
                ("domain", models.CharField(max_length=64, db_index=True)),
                ("rule_key", models.CharField(max_length=128, db_index=True)),
                ("severity", models.CharField(max_length=16, db_index=True)),
                ("title", models.CharField(max_length=160)),
                ("body", models.TextField()),
                ("payload", models.JSONField(null=True, blank=True)),
                ("channels_sent", models.JSONField(default=list)),
                ("dedupe_key", models.CharField(max_length=256, db_index=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "intelligence_notificationevent",
            },
        ),
        migrations.CreateModel(
            name="PlanningConfig",
            fields=[
                ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ("tenant_id", models.CharField(max_length=50, db_index=True)),
                ("domain", models.CharField(max_length=64, db_index=True)),
                ("timeframe_key", models.CharField(max_length=64, db_index=True)),
                ("period_start", models.DateField(db_index=True)),
                ("period_end", models.DateField(db_index=True)),
                ("pipeline_required_leads", models.IntegerField(null=True, blank=True)),
                ("derived_spec", models.JSONField(null=True, blank=True)),
                ("owner_role", models.CharField(max_length=64, default="bizops")),
                ("locked", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "intelligence_planningconfig",
            },
        ),
        migrations.AddIndex(
            model_name="metricsnapshot",
            index=models.Index(
                fields=["tenant_id", "domain", "metric_key", "timeframe_key", "period_start", "period_end"],
                name="intell_msnap_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="notificationevent",
            index=models.Index(
                fields=["tenant_id", "user_id", "domain", "rule_key", "created_at"],
                name="intell_nevent_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="planningconfig",
            index=models.Index(
                fields=["tenant_id", "domain", "timeframe_key", "period_start", "period_end"],
                name="intell_pcfg_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="featureflag",
            constraint=models.UniqueConstraint(
                fields=["tenant_id", "key"],
                name="intell_ff_tenant_key_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="metricdefinition",
            constraint=models.UniqueConstraint(
                fields=["tenant_id", "domain", "metric_key"],
                name="intell_md_tenant_key_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="thresholdrule",
            constraint=models.UniqueConstraint(
                fields=["tenant_id", "domain", "rule_key"],
                name="intell_tr_tenant_key_uq",
            ),
        ),
        migrations.AddConstraint(
            model_name="notificationpreference",
            constraint=models.UniqueConstraint(
                fields=["tenant_id", "user_id", "role_key"],
                name="intell_np_tenant_user_uq",
            ),
        ),
    ]
