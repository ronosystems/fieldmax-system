# staff/management/commands/migrate_applications_to_cloudinary.py
from django.core.management.base import BaseCommand
from staff.models import StaffApplication
from cloudinary.uploader import upload
import cloudinary
from django.conf import settings
import os

class Command(BaseCommand):
    help = 'Migrate existing application images to Cloudinary'

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write("Migrating application images to Cloudinary...")
        self.stdout.write("=" * 60)

        # Configure Cloudinary
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_STORAGE['CLOUD_NAME'],
            api_key=settings.CLOUDINARY_STORAGE['API_KEY'],
            api_secret=settings.CLOUDINARY_STORAGE['API_SECRET'],
            secure=True
        )

        migrated = 0
        errors = 0

        for app in StaffApplication.objects.all():
            self.stdout.write(f"\n📝 Processing: {app.full_name()} (ID: {app.id})")
            updated = False

            # Migrate passport photo
            if app.passport_photo and app.passport_photo.name:
                if app.passport_photo.url.startswith('/media/'):
                    try:
                        file_path = app.passport_photo.path
                        if os.path.exists(file_path):
                            self.stdout.write("  📤 Uploading passport photo...")
                            result = upload(file_path, folder='applications/passport/')
                            app.passport_photo = result['secure_url']
                            self.stdout.write("  ✅ Passport photo migrated")
                            updated = True
                        else:
                            self.stdout.write(f"  ⚠️ File not found: {file_path}")
                    except Exception as e:
                        self.stdout.write(f"  ❌ Error: {e}")
                        errors += 1

            # Migrate ID Front
            if app.id_front and app.id_front.name:
                if app.id_front.url.startswith('/media/'):
                    try:
                        file_path = app.id_front.path
                        if os.path.exists(file_path):
                            self.stdout.write("  📤 Uploading ID front...")
                            result = upload(file_path, folder='applications/id_front/')
                            app.id_front = result['secure_url']
                            self.stdout.write("  ✅ ID front migrated")
                            updated = True
                        else:
                            self.stdout.write(f"  ⚠️ File not found: {file_path}")
                    except Exception as e:
                        self.stdout.write(f"  ❌ Error: {e}")
                        errors += 1

            # Migrate ID Back
            if app.id_back and app.id_back.name:
                if app.id_back.url.startswith('/media/'):
                    try:
                        file_path = app.id_back.path
                        if os.path.exists(file_path):
                            self.stdout.write("  📤 Uploading ID back...")
                            result = upload(file_path, folder='applications/id_back/')
                            app.id_back = result['secure_url']
                            self.stdout.write("  ✅ ID back migrated")
                            updated = True
                        else:
                            self.stdout.write(f"  ⚠️ File not found: {file_path}")
                    except Exception as e:
                        self.stdout.write(f"  ❌ Error: {e}")
                        errors += 1

            if updated:
                app.save()
                migrated += 1
                self.stdout.write(f"  💾 Application {app.id} saved")

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"✅ Migration Complete!")
        self.stdout.write(f"📊 Applications updated: {migrated}")
        self.stdout.write(f"⚠️ Errors: {errors}")
        self.stdout.write(f"{'='*60}")