from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

def seed_knowledge_entries(apps, schema_editor):
    Knowledge = apps.get_model('cpq', 'Knowledge')

    entries = [
        {
            "title": "How to create a quote",
            "content_text": (
                "Navigate to the Quotes view, choose 'New Quote', select the account, and add the required products. "
                "Review pricing before saving."
            ),
            "tags": "quote,creation,getting-started",
        },
        {
            "title": "Approving a discount request",
            "content_text": (
                "Submit the quote for approval from the quote detail page. Approvers receive an email and can approve or "
                "reject from the dashboard."
            ),
            "tags": "approval,discount",
            "video_url": "https://example.com/videos/approvals",
            "language": "en",
            "has_video": True,
        },
        {
            "title": "Actualizar un presupuesto",
            "content_text": (
                "Abre el presupuesto desde el panel, selecciona la línea que deseas cambiar y usa la opción 'Actualizar'. "
                "Recuerda reenviar para aprobación si cambia el descuento."
            ),
            "tags": "quote,actualizar",
            "language": "es",
        },
    ]

    for data in entries:
        Knowledge.objects.update_or_create(
            title=data["title"],
            defaults=data,
        )


def remove_seeded_entries(apps, schema_editor):
    Knowledge = apps.get_model('cpq', 'Knowledge')
    Knowledge.objects.filter(
        title__in=[
            "How to create a quote",
            "Approving a discount request",
            "Actualizar un presupuesto",
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('cpq', '0003_quote_updated_by'),
    ]

    operations = [
        migrations.CreateModel(
            name='Knowledge',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('content_text', models.TextField()),
                ('video_url', models.URLField(blank=True, null=True)),
                ('image_url', models.URLField(blank=True, null=True)),
                ('has_video', models.BooleanField(default=False)),
                ('tags', models.CharField(blank=True, max_length=255)),
                ('language', models.CharField(default='en', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='knowledge_created', to=settings.AUTH_USER_MODEL)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='knowledge_updated', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at', 'title'],
            },
        ),
        migrations.RunPython(seed_knowledge_entries, remove_seeded_entries),
    ]
