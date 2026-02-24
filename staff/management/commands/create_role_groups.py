from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Create role groups in Django auth_group table'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Creating role groups...'))
        
        # List of all roles to add as groups
        ROLES = [
            'Administrator',
            'Supervisor',
            'Sales Manager',
            'Store Manager',
            'Credit Officer',
            'Assistant Manager',
            'Credit Manager',
            'Customer Service',
            'Security Officer',
            'Sales Agent',
            'Cashier',
            'Cleaner',
        ]
        
        created_count = 0
        existing_count = 0
        
        for role_name in ROLES:
            group, created = Group.objects.get_or_create(name=role_name)
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'✓ Created group: {role_name}'))
            else:
                existing_count += 1
                self.stdout.write(self.style.WARNING(f'• Group already exists: {role_name}'))
        
        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Done! Created {created_count} new groups, {existing_count} already existed.'
        ))