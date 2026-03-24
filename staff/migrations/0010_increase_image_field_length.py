# staff/migrations/0010_increase_image_field_length.py
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('staff', '0009_add_user_status_model'),
    ]

    operations = [
        migrations.AlterField(
            model_name='staffapplication',
            name='passport_photo',
            field=models.ImageField(max_length=500, upload_to='staff_documents/passport/'),
        ),
        migrations.AlterField(
            model_name='staffapplication',
            name='id_front',
            field=models.ImageField(max_length=500, upload_to='staff_documents/id_front/'),
        ),
        migrations.AlterField(
            model_name='staffapplication',
            name='id_back',
            field=models.ImageField(max_length=500, upload_to='staff_documents/id_back/'),
        ),
        migrations.AlterField(
            model_name='staff',
            name='id_front',
            field=models.ImageField(blank=True, max_length=500, null=True, upload_to='verification/ids/'),
        ),
        migrations.AlterField(
            model_name='staff',
            name='id_back',
            field=models.ImageField(blank=True, max_length=500, null=True, upload_to='verification/ids/'),
        ),
        migrations.AlterField(
            model_name='staff',
            name='passport_photo',
            field=models.ImageField(blank=True, max_length=500, null=True, upload_to='verification/photos/'),
        ),
        migrations.AlterField(
            model_name='staff',
            name='live_photo',
            field=models.ImageField(blank=True, max_length=500, null=True, upload_to='verification/live/'),
        ),
    ]