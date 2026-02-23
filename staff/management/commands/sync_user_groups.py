from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from staff.models import StaffApplication

User = get_user_model()

class Command(BaseCommand):
    help = 'Sync user groups based on their staff application positions'

    def handle(self, *args, **options):
        # Define position to group mapping
        position_to_group = {
            'sales_agent': 'Sales Agent',
            'cashier': 'Cashier',
            'store_manager': 'Store Manager',
            'sales_manager': 'Sales Manager',
            'credit_manager': 'Credit Officer',
            'customer_service': 'Customer Service',
            'supervisor': 'Supervisor',
            'security': 'Security Officer',
            'cleaner': 'Cleaner',
            'assistant_manager': 'Assistant Manager',
        }
        
        self.stdout.write(self.style.NOTICE('Starting group synchronization...'))
        
        # Get all approved staff applications
        applications = StaffApplication.objects.filter(status='approved')
        
        if not applications.exists():
            self.stdout.write(self.style.WARNING('No approved staff applications found'))
            return
        
        synced_count = 0
        skipped_count = 0
        
        for app in applications:
            if app.created_user:
                user = app.created_user
                position = app.position
                
                if position in position_to_group:
                    group_name = position_to_group[position]
                    group, created = Group.objects.get_or_create(name=group_name)
                    
                    if created:
                        self.stdout.write(self.style.NOTICE(f'Created new group: {group_name}'))
                    
                    # Remove user from all other position groups
                    other_groups = list(position_to_group.values())
                    for other_group_name in other_groups:
                        if other_group_name != group_name:
                            try:
                                other_group = Group.objects.get(name=other_group_name)
                                user.groups.remove(other_group)
                            except Group.DoesNotExist:
                                pass
                    
                    # Add to correct group
                    user.groups.add(group)
                    
                    self.stdout.write(
                        self.style.SUCCESS(f'✓ {user.username} → {group_name}')
                    )
                    synced_count += 1
                else:
                    self.stdout.write(
                        self.style.WARNING(f'⚠ No group mapping for position "{position}" for user {user.username}')
                    )
                    skipped_count += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f'⚠ Application #{app.id} has no linked user')
                )
                skipped_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Successfully synced {synced_count} users'))
        if skipped_count > 0:
            self.stdout.write(self.style.WARNING(f'⚠ Skipped {skipped_count} items'))