from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver
from django.contrib.auth.models import Group
from datetime import timedelta
import random
import string
import os

User = get_user_model()

# ============================================
# File Upload Path Functions
# ============================================
def passport_upload_path(instance, filename):
    return f'staff_documents/passport/{instance.id}/{filename}'

def id_front_upload_path(instance, filename):
    return f'staff_documents/id_front/{instance.id}/{filename}'

def id_back_upload_path(instance, filename):
    return f'staff_documents/id_back/{instance.id}/{filename}'


# ============================================
# SINGLE SOURCE OF TRUTH - Position to Group Mapping
# ============================================
POSITION_TO_GROUP_MAP = {
    'administrator': 'Administrator',
    'assistant_manager': 'Assistant Manager',
    'sales_manager': 'Sales Manager',
    'sales_agent': 'Sales Agent',
    'cashier': 'Cashier',
    'store_manager': 'Store Manager',
    'credit_manager': 'Credit Manager',
    'credit_officer': 'Credit Officer',
    'customer_service': 'Customer Service',
    'finance_manager': 'Finance Manager',
    'security': 'Security Officer',
    'cleaner': 'Cleaner',
    'inventory_manager': 'Inventory Manager',
    'mpesa_agent': 'M-Pesa Agent',
    'technician': 'Technician',
}

# Generate POSITION_CHOICES automatically from the map
POSITION_CHOICES = [(key, value) for key, value in POSITION_TO_GROUP_MAP.items()]

# Generate DEFAULT_GROUPS automatically from the map
DEFAULT_GROUPS = list(POSITION_TO_GROUP_MAP.values())


# ============================================
# Staff Application Model
# ============================================
class StaffApplication(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('under_review', 'Under Review'),
    ]
    
    # Use the global POSITION_CHOICES
    POSITION_CHOICES = POSITION_CHOICES
    
    # Personal Information
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20)
    id_number = models.CharField(max_length=50, unique=True)
    address = models.TextField(blank=True)
    
    # Application Details
    position = models.CharField(max_length=50, choices=POSITION_CHOICES)
    experience = models.TextField(blank=True)
    
    # Document Uploads
    passport_photo = models.ImageField(upload_to=passport_upload_path, max_length=500)
    id_front = models.ImageField(upload_to=id_front_upload_path, max_length=500)
    id_back = models.ImageField(upload_to=id_back_upload_path, max_length=500)
    
    # Status Tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    application_date = models.DateTimeField(default=timezone.now)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, 
        related_name='reviewed_applications'
    )
    review_date = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True, null=True, help_text='Notes from the review process')
    
    # Terms Acceptance
    terms_accepted = models.BooleanField(default=False)
    privacy_accepted = models.BooleanField(default=False)
    
    # System Fields
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_applications',
        help_text='User account created when application was approved'
    )

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.get_position_display()}"
    
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def get_status_badge(self):
        badges = {
            'pending': 'warning',
            'approved': 'success',
            'rejected': 'danger',
            'under_review': 'info',
        }
        return badges.get(self.status, 'secondary')
    
    @classmethod
    def get_group_for_position(cls, position):
        """Get the group name for a given position"""
        return POSITION_TO_GROUP_MAP.get(position)
    
    @classmethod
    def get_all_groups(cls):
        """Get all unique group names"""
        return set(POSITION_TO_GROUP_MAP.values())
    
    class Meta:
        ordering = ['-application_date']
        verbose_name = 'Staff Application'
        verbose_name_plural = 'Staff Applications'


# ============================================
# Staff Model (for verified staff members) - UPDATED with sequential staff_id
# ============================================
class Staff(models.Model):
    """Staff member profile linked to User account"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='staff_profile')
    staff_id = models.CharField(max_length=20, unique=True, blank=True)
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Phone Number")
    id_number = models.CharField(max_length=50, unique=True, blank=True, null=True) 
    position = models.CharField(max_length=50, choices=POSITION_CHOICES)
    department = models.CharField(max_length=100, blank=True)
    
    # ITP Verification fields
    verification_code = models.CharField(max_length=10, blank=True, null=True)
    verification_sent_at = models.DateTimeField(blank=True, null=True)
    verification_submitted_at = models.DateTimeField(blank=True, null=True)
    verified_at = models.DateTimeField(blank=True, null=True)
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, 
        related_name='verified_staff'
    )
    verification_attempts = models.IntegerField(default=0)
    is_identity_verified = models.BooleanField(default=False)
    verification_notes = models.TextField(blank=True)
    
    # Document uploads for verification
    id_front = models.ImageField(upload_to='verification/ids/', blank=True, null=True, max_length=500)
    id_back = models.ImageField(upload_to='verification/ids/', blank=True, null=True, max_length=500)
    passport_photo = models.ImageField(upload_to='verification/photos/', blank=True, null=True, max_length=500)
    live_photo = models.ImageField(upload_to='verification/live/', blank=True, null=True, max_length=500)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    assigned_shop = models.ForeignKey(
        'shops.ShopBranch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_staff',
        help_text="Shop branch assigned to this staff member"
    )
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.staff_id}"
    
    def generate_staff_id(self):
        """Generate sequential staff ID (FM001, FM002, FM003, etc.)"""
        # Get the last staff ID
        last_staff = Staff.objects.order_by('-id').first()
        
        if not last_staff or not last_staff.staff_id:
            # First staff member - start with FM001
            return 'FM001'
        
        # Extract the number from the last staff_id
        last_id = last_staff.staff_id
        try:
            # Get the numeric part (after FM)
            numeric_part = last_id[2:]  # Remove 'FM' prefix
            next_number = int(numeric_part) + 1
            # Format with leading zeros (001, 002, etc.)
            return f'FM{next_number:03d}'
        except (ValueError, IndexError):
            # If there's an error, fall back to FM001
            return 'FM001'
    
    @classmethod
    def get_group_for_position(cls, position):
        """Get the group name for a given position"""
        return POSITION_TO_GROUP_MAP.get(position)
    
    def save(self, *args, **kwargs):
        if not self.staff_id:
            self.staff_id = self.generate_staff_id()
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = 'Staff Member'
        verbose_name_plural = 'Staff Members'
        ordering = ['staff_id']



class ApplicationExtraData(models.Model):
    """Additional data for staff applications"""
    application = models.OneToOneField(
        StaffApplication, 
        on_delete=models.CASCADE, 
        related_name='extra_data'
    )
    resident = models.TextField(blank=True, help_text="Current residence address")
    former_employer = models.CharField(max_length=200, blank=True)
    preferred_salary = models.CharField(max_length=50, blank=True)
    signature = models.TextField(blank=True, help_text="Digital signature")
    other_documents = models.FileField(
        upload_to='staff_documents/other/', 
        blank=True, 
        null=True,
        help_text="Additional supporting documents (CV, certificates, etc.)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Extra data for {self.application.full_name()}"





# ============================================
# OTP Verification Model
# ============================================
class OTPVerification(models.Model):
    """Store OTP codes for role-based access verification"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otp_verifications')
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    purpose = models.CharField(max_length=50, default='dashboard_access')
    
    class Meta:
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.user.username} - {self.otp_code} - {'Used' if self.is_used else 'Active'}"
    
    def is_valid(self):
        return not self.is_used and timezone.now() <= self.expires_at
    
    @classmethod
    def generate_otp(cls, user, purpose='dashboard_access', expiry_minutes=5):
        otp_code = ''.join(random.choices(string.digits, k=6))
        expires_at = timezone.now() + timedelta(minutes=expiry_minutes)
        
        cls.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)
        
        otp = cls.objects.create(
            user=user,
            otp_code=otp_code,
            expires_at=expires_at,
            purpose=purpose
        )
        return otp
    
    @classmethod
    def verify_otp(cls, user, otp_code, purpose='dashboard_access'):
        try:
            otp = cls.objects.filter(
                user=user,
                otp_code=otp_code,
                purpose=purpose,
                is_used=False
            ).latest('created_at')
            
            if otp.is_valid():
                otp.is_used = True
                otp.save()
                return True, "OTP verified successfully"
            else:
                return False, "OTP has expired"
        except cls.DoesNotExist:
            return False, "Invalid OTP code"


# ============================================
# User Profile Model - UPDATED with verification fields
# ============================================
class UserProfile(models.Model):
    """Extended profile for User to track password change"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    password_changed = models.BooleanField(default=False)
    first_login = models.BooleanField(default=True)
    last_password_change = models.DateTimeField(null=True, blank=True)
    is_ceo = models.BooleanField(default=False, help_text='CEO/Company Owner status')
    is_verified = models.BooleanField(default=False, help_text='User identity verified')
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='verified_users'
    )
    
    def __str__(self):
        return f"{self.user.username}'s profile"
    
    def mark_as_verified(self, verified_by=None):
        """Mark user as verified"""
        self.is_verified = True
        self.verified_at = timezone.now()
        self.verified_by = verified_by
        self.save()


# ============================================
# User Status Model
# ============================================
class UserStatus(models.Model):
    """Extended user status management (One-to-One with Django User)"""
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='status'
    )
    
    # Lock fields
    is_locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    lock_reason = models.CharField(max_length=50, choices=[
        ('failed_login', 'Multiple Failed Logins'),
        ('suspicious', 'Suspicious Activity'),
        ('admin', 'Admin Lock'),
    ], blank=True)
    failed_login_attempts = models.IntegerField(default=0)
    last_failed_login = models.DateTimeField(null=True, blank=True)
    
    # Suspension fields
    is_suspended = models.BooleanField(default=False)
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_until = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.TextField(blank=True)
    suspended_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='suspended_users'
    )
    
    # Deactivation tracking
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_reason = models.TextField(blank=True)
    deactivated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='deactivated_users'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'User Status'
        verbose_name_plural = 'User Statuses'
        indexes = [
            models.Index(fields=['is_locked', 'is_suspended']),
            models.Index(fields=['user', 'is_locked']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {'Locked' if self.is_locked else 'Unlocked'} / {'Suspended' if self.is_suspended else 'Active'}"
    
    @property
    def can_login(self):
        if not self.user.is_active:
            return False, 'deactivated', 'Your account has been deactivated.'
        if self.is_locked:
            return False, 'locked', 'Your account is temporarily locked.'
        if self.is_suspended:
            return False, 'suspended', f'Your account is suspended until {self.suspended_until}.'
        return True, None, None


# ============================================
# Signals - UPDATED with auto-verify for superuser
# ============================================

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Create UserProfile when User is created"""
    if created:
        profile = UserProfile.objects.create(user=instance)
        
        # Auto-verify superusers
        if instance.is_superuser:
            profile.is_verified = True
            profile.verified_at = timezone.now()
            profile.verified_by = instance
            profile.save()
            print(f"✅ Superuser {instance.username} auto-verified")

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Save UserProfile when User is saved"""
    if not hasattr(instance, 'profile'):
        profile = UserProfile.objects.create(user=instance)
        # Auto-verify superusers
        if instance.is_superuser:
            profile.is_verified = True
            profile.verified_at = timezone.now()
            profile.verified_by = instance
            profile.save()
    else:
        instance.profile.save()

@receiver(post_save, sender=User)
def create_staff_profile_for_staff_users(sender, instance, created, **kwargs):
    """Create Staff profile for users that are staff members"""
    if created and instance.is_staff:
        if not hasattr(instance, 'staff_profile'):
            Staff.objects.create(
                user=instance,
                position='sales_agent',
            )


# ============================================
# Auto-create groups on migration
# ============================================

@receiver(post_migrate)
def create_groups_on_migration(sender, **kwargs):
    """Auto-create all default groups whenever migrations run"""
    if sender.name == 'staff':
        created_count = 0
        existing_count = 0
        
        print("\n" + "=" * 60)
        print("🔧 Auto-creating default groups...")
        print("=" * 60)
        
        for group_name in DEFAULT_GROUPS:
            group, created = Group.objects.get_or_create(name=group_name)
            if created:
                print(f"  ✅ Created group: {group_name}")
                created_count += 1
            else:
                print(f"  • Group already exists: {group_name}")
                existing_count += 1
        
        print("=" * 60)
        print(f"📊 Summary: {created_count} created, {existing_count} existing")
        print("✅ Groups are ready!")
        print("=" * 60 + "\n")


# ====================================================
# Auto-create default admin user with ALL permissions
# ====================================================

@receiver(post_migrate)
def create_default_admin(sender, **kwargs):
    """Create default admin user with full permissions and verification"""
    if sender.name == 'staff':
        if not User.objects.filter(is_superuser=True).exists():
            admin = User.objects.create_superuser(
                username='RONOSYSTEMS',
                email='ronosystems@gmail.com',
                password='Kiprono@1997',
                first_name='ELKANA',
                last_name='KIPRONO'
            )
            
            # Set all required flags on User model
            admin.is_superuser = True
            admin.is_staff = True
            admin.is_active = True
            admin.save()
            
            # Create and verify Staff profile
            staff_profile, _ = Staff.objects.get_or_create(
                user=admin,
                defaults={
                    'position': 'administrator',
                    'is_identity_verified': True,
                    'verified_at': timezone.now(),
                    'verified_by': admin
                }
            )
            if not staff_profile.is_identity_verified:
                staff_profile.is_identity_verified = True
                staff_profile.verified_at = timezone.now()
                staff_profile.verified_by = admin
                staff_profile.save()
            
            # Set CEO and Verified status in UserProfile
            if hasattr(admin, 'profile'):
                admin.profile.is_ceo = True
                admin.profile.is_verified = True
                admin.profile.verified_at = timezone.now()
                admin.profile.verified_by = admin
                admin.profile.password_changed = True
                admin.profile.first_login = False
                admin.profile.save()
            
            # Assign to Administrator group
            admin_group, _ = Group.objects.get_or_create(name='Administrator')
            admin.groups.add(admin_group)
            
            print("\n" + "=" * 60)
            print("✅ Default admin user created with FULL VERIFICATION!")
            print("=" * 60)
            print(f"   Username: RONOSYSTEMS")
            print(f"   Password: Kiprono@1997")
            print(f"   " + "-" * 40)
            print(f"   ✓ is_superuser: True")
            print(f"   ✓ is_staff: True")
            print(f"   ✓ is_active: True")
            print(f"   ✓ is_ceo: True")
            print(f"   ✓ is_verified (Profile): True")
            print(f"   ✓ is_identity_verified (Staff): True")
            print(f"   ✓ Group: Administrator")
            print("=" * 60 + "\n")