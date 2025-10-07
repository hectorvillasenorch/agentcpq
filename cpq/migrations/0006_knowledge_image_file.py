from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cpq", "0005_alter_knowledge_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="knowledge",
            name="image_file",
            field=models.ImageField(blank=True, null=True, upload_to="sympletech/knowledge/images/"),
        ),
    ]
