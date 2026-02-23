
from django.contrib.auth.models import User
from django.utils import timezone
from django.db import models
from django.contrib.auth import get_user_model
from datetime import timedelta
import random
import string
import os

def passport_upload_path(instance, filename):
    # Upload to: staff_documents/passport/{application_id}/{filename}
    return f'staff_documents/passport/{instance.id}/{filename}'

def id_front_upload_path(instance, filename):
    return f'staff_documents/id_front/{instance.id}/{filename}'

def id_back_upload_path(instance, filename):
    return f'staff_documents/id_back/{instance.id}/{filename}'

class StaffApplication(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('under_review', 'Under Review'),
    ]
    
    POSITION_CHOICES = [
        ('sales_agent', 'Sales Officer'),
        ('cashier', 'Cashier Desk'),
        ('store_manager', 'Store Manager'),
        ('sales_manager', 'Sales Manager'),
        ('credit_manager', 'Credit Manager'),
        ('customer_service', 'Customer Care Service'),
        ('supervisor', 'Supervisor'),
        ('security', 'Security Officer'),
        ('cleaner', 'Office Cleaner'),
    ]
    
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
    passport_photo = models.ImageField(upload_to=passport_upload_path)
    id_front = models.ImageField(upload_to=id_front_upload_path)
    id_back = models.ImageField(upload_to=id_back_upload_path)
    
    # Status Tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    application_date = models.DateTimeField(default=timezone.now)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_applications')
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
    
    class Meta:
        ordering = ['-application_date']
        verbose_name = 'Staff Application'
        verbose_name_plural = 'Staff Applications'






User = get_user_model()

class OTPVerification(models.Model):
    """Store OTP codes for role-based access verification"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otp_verifications')
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    purpose = models.CharField(max_length=50, default='dashboard_access')  # dashboard_access, approval, etc.
    
    class Meta:
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.user.username} - {self.otp_code} - {'Used' if self.is_used else 'Active'}"
    
    def is_valid(self):
        """Check if OTP is still valid (not expired and not used)"""
        return not self.is_used and timezone.now() <= self.expires_at
    
    @classmethod
    def generate_otp(cls, user, purpose='dashboard_access', expiry_minutes=5):
        """Generate a new OTP for user"""
        # Generate 6-digit OTP
        otp_code = ''.join(random.choices(string.digits, k=6))
        
        # Set expiry time
        expires_at = timezone.now() + timedelta(minutes=expiry_minutes)
        
        # Invalidate previous unused OTPs for this user and purpose
        cls.objects.filter(
            user=user, 
            purpose=purpose, 
            is_used=False
        ).update(is_used=True)  # Mark as used (effectively invalid)
        
        # Create new OTP
        otp = cls.objects.create(
            user=user,
            otp_code=otp_code,
            expires_at=expires_at,
            purpose=purpose
        )
        
        return otp
    
    @classmethod
    def verify_otp(cls, user, otp_code, purpose='dashboard_access'):
        """Verify OTP code for user"""
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
        



from django.contrib.auth.models import AbstractUser
from django.db import models

# Add this to your User model (if using custom User model)
# Or add a profile model to track password change

class UserProfile(models.Model):
    """Extended profile for User to track password change"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    password_changed = models.BooleanField(default=False)
    first_login = models.BooleanField(default=True)
    last_password_change = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.user.username}'s profile"

# Signal to auto-create profile when user is created
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        UserProfile.objects.create(user=instance)
    instance.profile.save()