from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cpq", "0036_opportunity_external_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="external_id",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="activity",
            name="external_id",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="quote",
            name="external_id",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="contract",
            name="external_id",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="subscription",
            name="external_id",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="opportunity",
            name="external_id",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
    ]
