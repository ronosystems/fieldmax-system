# staff/management/commands/migrate_staff_to_cloudinary.py
from django.core.management.base import BaseCommand
from staff.models import Staff
from cloudinary.uploader import upload
import cloudinary
from django.conf import settings
import os
import time

class Command(BaseCommand):
    help = 'Migrate existing staff images to Cloudinary'

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write("Migrating Staff images to Cloudinary...")
        self.stdout.write("=" * 60)

        # Configure Cloudinary
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_STORAGE['CLOUD_NAME'],
            api_key=settings.CLOUDINARY_STORAGE['API_KEY'],
            api_secret=settings.CLOUDINARY_STORAGE['API_SECRET'],
            secure=True
        )

        migrated_count = 0
        error_count = 0
        skipped_count = 0

        for staff in Staff.objects.all():
            self.stdout.write(f"\n📝 Processing: {staff.user.username} (Staff ID: {staff.staff_id})")
            updated = False

            # Migrate ID Front
            if staff.id_front and staff.id_front.name:
                current_url = staff.id_front.url
                if current_url.startswith('/media/') or 'verification/ids/' in current_url:
                    try:
                        file_path = staff.id_front.path
                        if os.path.exists(file_path):
                            self.stdout.write("  📤 Uploading ID Front...")
                            result = upload(file_path, folder='staff/ids/')
                            staff.id_front = result['secure_url']
                            self.stdout.write("  ✅ ID Front migrated to Cloudinary")
                            updated = True
                        else:
                            self.stdout.write(f"  ⚠️ File not found: {file_path}")
                            skipped_count += 1
                    except Exception as e:
                        self.stdout.write(f"  ❌ Error: {e}")
                        error_count += 1
                else:
                    self.stdout.write("  ℹ️ ID Front already on Cloudinary")
            else:
                self.stdout.write("  ℹ️ No ID Front to migrate")

            # Migrate ID Back
            if staff.id_back and staff.id_back.name:
                current_url = staff.id_back.url
                if current_url.startswith('/media/') or 'verification/ids/' in current_url:
                    try:
                        file_path = staff.id_back.path
                        if os.path.exists(file_path):
                            self.stdout.write("  📤 Uploading ID Back...")
                            result = upload(file_path, folder='staff/ids/')
                            staff.id_back = result['secure_url']
                            self.stdout.write("  ✅ ID Back migrated to Cloudinary")
                            updated = True
                        else:
                            self.stdout.write(f"  ⚠️ File not found: {file_path}")
                            skipped_count += 1
                    except Exception as e:
                        self.stdout.write(f"  ❌ Error: {e}")
                        error_count += 1
                else:
                    self.stdout.write("  ℹ️ ID Back already on Cloudinary")
            else:
                self.stdout.write("  ℹ️ No ID Back to migrate")

            # Migrate Passport Photo
            if staff.passport_photo and staff.passport_photo.name:
                current_url = staff.passport_photo.url
                if current_url.startswith('/media/') or 'verification/photos/' in current_url:
                    try:
                        file_path = staff.passport_photo.path
                        if os.path.exists(file_path):
                            self.stdout.write("  📤 Uploading Passport Photo...")
                            result = upload(file_path, folder='staff/passports/')
                            staff.passport_photo = result['secure_url']
                            self.stdout.write("  ✅ Passport Photo migrated to Cloudinary")
                            updated = True
                        else:
                            self.stdout.write(f"  ⚠️ File not found: {file_path}")
                            skipped_count += 1
                    except Exception as e:
                        self.stdout.write(f"  ❌ Error: {e}")
                        error_count += 1
                else:
                    self.stdout.write("  ℹ️ Passport Photo already on Cloudinary")
            else:
                self.stdout.write("  ℹ️ No Passport Photo to migrate")

            # Migrate Live Photo
            if staff.live_photo and staff.live_photo.name:
                current_url = staff.live_photo.url
                if current_url.startswith('/media/') or 'verification/live/' in current_url:
                    try:
                        file_path = staff.live_photo.path
                        if os.path.exists(file_path):
                            self.stdout.write("  📤 Uploading Live Photo...")
                            result = upload(file_path, folder='staff/live/')
                            staff.live_photo = result['secure_url']
                            self.stdout.write("  ✅ Live Photo migrated to Cloudinary")
                            updated = True
                        else:
                            self.stdout.write(f"  ⚠️ File not found: {file_path}")
                            skipped_count += 1
                    except Exception as e:
                        self.stdout.write(f"  ❌ Error: {e}")
                        error_count += 1
                else:
                    self.stdout.write("  ℹ️ Live Photo already on Cloudinary")
            else:
                self.stdout.write("  ℹ️ No Live Photo to migrate")

            if updated:
                staff.save()
                migrated_count += 1
                self.stdout.write(f"  💾 Staff {staff.user.username} saved")
            
            # Small delay to avoid rate limiting
            time.sleep(0.5)

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"✅ Migration Complete!")
        self.stdout.write(f"📊 Staff updated: {migrated_count}")
        self.stdout.write(f"⚠️ Errors: {error_count}")
        self.stdout.write(f"📁 Files not found: {skipped_count}")
        self.stdout.write(f"{'='*60}")