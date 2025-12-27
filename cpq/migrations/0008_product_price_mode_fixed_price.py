from django.db import migrations, models
import decimal


class Migration(migrations.Migration):

    dependencies = [
        ('cpq', '0007_actionlog_alter_actiontrigger_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='fixed_price',
            field=models.DecimalField(decimal_places=2, default=decimal.Decimal('0.00'), max_digits=10),
        ),
        migrations.AddField(
            model_name='product',
            name='price_mode',
            field=models.CharField(choices=[('fixed', 'Fixed'), ('sum', 'Sum of Components')], default='sum', max_length=10),
        ),
    ]
