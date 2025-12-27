from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SingleRecordLayout',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('object_name', models.CharField(max_length=100)),
                ('layout', models.JSONField(default=dict)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='single_record_layouts', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Single Record Layout',
                'verbose_name_plural': 'Single Record Layouts',
                'unique_together': {('user', 'object_name')},
            },
        ),
    ]
