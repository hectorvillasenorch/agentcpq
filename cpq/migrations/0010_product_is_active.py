from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cpq', '0009_opportunitystage_alter_opportunity_stage_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='is_active',
            field=models.BooleanField(default=True, help_text='Set to false to soft-hide this product without deleting it.'),
        ),
    ]

