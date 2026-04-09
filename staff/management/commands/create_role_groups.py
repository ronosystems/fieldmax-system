from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from staff.models import StaffApplication

User = get_user_model()

class Command(BaseCommand):
    help = 'Sync user groups based on their staff application positions (without overriding existing assignments)'

    def handle(self, *args, **options):
        # Define position to group mapping
        position_to_group = {
            'sales_agent': 'Sales Agent',
            'cashier': 'Cashier',
            'store_manager': 'Store Manager',
            'inventory_manager': 'Inventory Manager',
            'sales_manager': 'Sales Manager',
            'credit_manager': 'Credit Manager',
            'credit_officer': 'Credit Officer',
            'customer_service': 'Customer Service',
            'finance_manager': 'Finance Manager',
            'security': 'Security Officer',
            'cleaner': 'Cleaner',
            'assistant_manager': 'Assistant Manager',
            'mpesa_agent': 'M-Pesa Agent',
            'administrator': 'Administrator',
        }
        
        self.stdout.write(self.style.NOTICE('=' * 60))
        self.stdout.write(self.style.NOTICE('Starting Group Synchronization (Preserve Mode)...'))
        self.stdout.write(self.style.NOTICE('=' * 60))
        
        # Create all groups first if they don't exist
        self.stdout.write(self.style.NOTICE('\n📋 Ensuring all groups exist...'))
        for group_name in set(position_to_group.values()):
            group, created = Group.objects.get_or_create(name=group_name)
            if created:
                self.stdout.write(self.style.SUCCESS(f'  ✓ Created group: {group_name}'))
            else:
                self.stdout.write(self.style.NOTICE(f'  • Group already exists: {group_name}'))
        
        # Get all approved staff applications with users
        applications = StaffApplication.objects.filter(status='approved', created_user__isnull=False)
        
        if not applications.exists():
            self.stdout.write(self.style.WARNING('\n⚠ No approved staff applications with linked users found'))
            return
        
        self.stdout.write(self.style.NOTICE(f'\n📊 Found {applications.count()} approved applications with users\n'))
        
        synced_count = 0
        skipped_count = 0
        already_correct_count = 0
        group_stats = {}
        
        for app in applications:
            user = app.created_user
            position = app.position
            
            if position in position_to_group:
                expected_group_name = position_to_group[position]
                expected_group = Group.objects.get(name=expected_group_name)
                
                # Track statistics
                if expected_group_name not in group_stats:
                    group_stats[expected_group_name] = 0
                
                # Check if user is already in a group (has any role assigned)
                user_groups = user.groups.all()
                
                if user_groups.exists():
                    # User already has groups assigned by admin
                    current_group_names = [g.name for g in user_groups]
                    
                    # Check if user is already in the expected group
                    if expected_group in user_groups:
                        self.stdout.write(
                            self.style.NOTICE(f'• {user.username} already in {expected_group_name} (correct)')
                        )
                        already_correct_count += 1
                        group_stats[expected_group_name] += 1
                    else:
                        # User has different groups - DO NOT override admin decision
                        self.stdout.write(
                            self.style.WARNING(f'⚠ {user.username} - SKIPPED: Admin assigned to {", ".join(current_group_names)} (applied for {expected_group_name})')
                        )
                        self.stdout.write(
                            self.style.NOTICE(f'  └─ To change, manually update groups in admin panel')
                        )
                        skipped_count += 1
                else:
                    # User has NO groups - assign based on application
                    user.groups.add(expected_group)
                    self.stdout.write(
                        self.style.SUCCESS(f'✓ {user.username} → {expected_group_name} (first time assignment)')
                    )
                    synced_count += 1
                    group_stats[expected_group_name] += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f'⚠ No group mapping for position "{position}" for user {user.username}')
                )
                skipped_count += 1
        
        # Display summary
        self.stdout.write(self.style.NOTICE('\n' + '=' * 60))
        self.stdout.write(self.style.SUCCESS('SYNC SUMMARY'))
        self.stdout.write(self.style.NOTICE('=' * 60))
        self.stdout.write(self.style.SUCCESS(f'✓ Newly assigned: {synced_count} users'))
        self.stdout.write(self.style.NOTICE(f'• Already correct: {already_correct_count} users'))
        self.stdout.write(self.style.WARNING(f'⚠ Skipped (admin override): {skipped_count} users'))
        
        self.stdout.write(self.style.NOTICE('\n📊 Group Statistics:'))
        for group_name, count in sorted(group_stats.items()):
            self.stdout.write(self.style.NOTICE(f'  • {group_name}: {count} user(s)'))
        
        # Display users that were skipped (admin overrides)
        if skipped_count > 0:
            self.stdout.write(self.style.WARNING('\n⚠ Users with Admin Overrides (not changed):'))
            for app in applications:
                user = app.created_user
                position = app.position
                if position in position_to_group:
                    expected_group_name = position_to_group[position]
                    expected_group = Group.objects.get(name=expected_group_name)
                    user_groups = user.groups.all()
                    if user_groups.exists() and expected_group not in user_groups:
                        self.stdout.write(
                            self.style.WARNING(f'  • {user.username}: Applied for {expected_group_name} but admin assigned to {", ".join([g.name for g in user_groups])}')
                        )
        
        self.stdout.write(self.style.SUCCESS('\n✅ Group synchronization completed!'))
        self.stdout.write(self.style.NOTICE('💡 To change a user\'s group, use Django admin panel.'))