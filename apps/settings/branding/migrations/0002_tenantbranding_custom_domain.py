from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_branding', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenantbranding',
            name='custom_domain',
            field=models.CharField(
                blank=True,
                max_length=253,
                default='',
                help_text='Tenant custom domain (e.g. app.mygym.com). Used to brand payment and checkout links.',
            ),
            preserve_default=False,
        ),
    ]
