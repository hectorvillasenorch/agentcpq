from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cpq", "0006_knowledge_image_file"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledge",
            name="embedding",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
