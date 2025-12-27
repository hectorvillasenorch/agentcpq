from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cpq", "0012_groupuisettings"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="sidebar_bg_color_1",
            field=models.CharField(blank=True, default="#041530", max_length=7, null=True),
        ),
        migrations.AddField(
            model_name="tenant",
            name="sidebar_bg_color_2",
            field=models.CharField(blank=True, default="#233049", max_length=7, null=True),
        ),
        migrations.AddField(
            model_name="tenant",
            name="sidebar_text_color",
            field=models.CharField(blank=True, default="#ffffff", max_length=7, null=True),
        ),
    ]

