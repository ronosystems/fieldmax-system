# staff/admin.py
from django.contrib import admin
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.contrib import messages
from django.utils import timezone
from .models import StaffApplication, Staff, OTPVerification, UserProfile, UserStatus
from .utils.user_status import UserStatusManager

User = get_user_model()


# ============================================
# Custom Form for Staff to handle Cloudinary URLs
# ============================================
class StaffAdminForm(forms.ModelForm):
    """Custom form for Staff to handle image fields properly"""
    
    class Meta:
        model = Staff
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # For each image field, set required=False and disable URL display
        for field_name in ['id_front', 'id_back', 'passport_photo', 'live_photo']:
            if field_name in self.fields:
                field = self.fields[field_name]
                field.required = False
                # Disable the "Currently:" link that tries to generate a URL
                if hasattr(field, 'widget'):
                    field.widget.is_initial = lambda value: False
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Handle file uploads manually
        for field_name in ['id_front', 'id_back', 'passport_photo', 'live_photo']:
            if field_name in self.files:
                setattr(instance, field_name, self.files[field_name])
        
        if commit:
            instance.save()
        return instance


# ============================================
# Staff Application Admin
# ============================================
@admin.register(StaffApplication)
class StaffApplicationAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'phone', 'position', 'status', 'application_date']
    list_filter = ['status', 'position', 'application_date']
    search_fields = ['first_name', 'last_name', 'email', 'phone', 'id_number']
    readonly_fields = ['application_date', 'ip_address', 'user_agent']
    
    fieldsets = (
        ('Personal Information', {
            'fields': ('first_name', 'last_name', 'email', 'phone', 'id_number', 'address')
        }),
        ('Application Details', {
            'fields': ('position', 'experience')
        }),
        ('Documents', {
            'fields': ('passport_photo', 'id_front', 'id_back')
        }),
        ('Status', {
            'fields': ('status', 'reviewed_by', 'review_date', 'review_notes')
        }),
        ('Terms & System', {
            'fields': ('terms_accepted', 'privacy_accepted', 'ip_address', 'user_agent', 'created_user', 'application_date'),
            'classes': ('collapse',)
        }),
    )
    
    def full_name(self, obj):
        return obj.full_name()
    full_name.short_description = 'Full Name'
    
    actions = ['approve_applications', 'reject_applications', 'mark_under_review']
    
    def approve_applications(self, request, queryset):
        updated = queryset.update(
            status='approved',
            reviewed_by=request.user,
            review_date=timezone.now()
        )
        self.message_user(request, f'{updated} applications approved.')
    
    def reject_applications(self, request, queryset):
        updated = queryset.update(
            status='rejected',
            reviewed_by=request.user,
            review_date=timezone.now()
        )
        self.message_user(request, f'{updated} applications rejected.')
    
    def mark_under_review(self, request, queryset):
        updated = queryset.update(
            status='under_review',
            reviewed_by=request.user,
            review_date=timezone.now()
        )
        self.message_user(request, f'{updated} applications marked under review.')


# ============================================
# Staff Admin
# ============================================
@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    form = StaffAdminForm
    list_display = ['staff_id', 'user', 'position', 'is_identity_verified', 'created_at']
    list_filter = ['is_identity_verified', 'position']
    search_fields = ['staff_id', 'user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Staff Information', {
            'fields': ('user', 'staff_id', 'id_number', 'position', 'department')
        }),
        ('Verification', {
            'fields': ('is_identity_verified', 'verification_code', 'verification_sent_at', 
                      'verification_submitted_at', 'verified_at', 'verified_by', 'verification_notes')
        }),
        ('Documents', {
            'fields': ('id_front', 'id_back', 'passport_photo', 'live_photo')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ============================================
# OTP Verification Admin
# ============================================
@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'otp_code', 'created_at', 'expires_at', 'is_used', 'purpose']
    list_filter = ['is_used', 'purpose', 'created_at']
    search_fields = ['user__username', 'otp_code']
    readonly_fields = ['created_at']


# ============================================
# User Profile Admin
# ============================================
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'password_changed', 'first_login', 'last_password_change']
    list_filter = ['password_changed', 'first_login']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['last_password_change']


# ============================================
# User Status Admin
# ============================================
@admin.register(UserStatus)
class UserStatusAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_locked', 'is_suspended', 'failed_login_attempts', 'updated_at']
    list_filter = ['is_locked', 'is_suspended']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at']


# ============================================
# Custom User Admin with Status Inline
# ============================================
class UserStatusInline(admin.StackedInline):
    model = UserStatus
    can_delete = False
    verbose_name_plural = 'Account Status'
    fk_name = 'user'
    fields = ('is_locked', 'lock_reason', 'locked_at', 
              'is_suspended', 'suspended_until', 'suspension_reason',
              'failed_login_attempts', 'last_failed_login')
    readonly_fields = ('locked_at', 'suspended_at', 'deactivated_at', 'created_at', 'updated_at')


class CustomUserAdmin(BaseUserAdmin):
    inlines = [UserStatusInline]
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active')
    list_filter = ('is_active', 'is_staff', 'is_superuser')
    
    actions = ['lock_users', 'unlock_users', 'suspend_users', 'unsuspend_users', 'deactivate_users', 'activate_users']
    
    def lock_users(self, request, queryset):
        count = 0
        for user in queryset:
            UserStatusManager.lock_user(user, 'admin', request)
            count += 1
        self.message_user(request, f'{count} user(s) locked.', messages.SUCCESS)
    lock_users.short_description = "Lock selected users"
    
    def unlock_users(self, request, queryset):
        count = 0
        for user in queryset:
            UserStatusManager.unlock_user(user, request)
            count += 1
        self.message_user(request, f'{count} user(s) unlocked.', messages.SUCCESS)
    unlock_users.short_description = "Unlock selected users"
    
    def suspend_users(self, request, queryset):
        count = 0
        for user in queryset:
            UserStatusManager.suspend_user(user, 'Admin suspension', request.user, 30, request)
            count += 1
        self.message_user(request, f'{count} user(s) suspended for 30 days.', messages.SUCCESS)
    suspend_users.short_description = "Suspend selected users (30 days)"
    
    def unsuspend_users(self, request, queryset):
        count = 0
        for user in queryset:
            UserStatusManager.unsuspend_user(user, request)
            count += 1
        self.message_user(request, f'{count} user(s) unsuspended.', messages.SUCCESS)
    unsuspend_users.short_description = "Unsuspend selected users"
    
    def deactivate_users(self, request, queryset):
        count = 0
        for user in queryset:
            UserStatusManager.deactivate_user(user, 'Admin deactivation', request.user, request)
            count += 1
        self.message_user(request, f'{count} user(s) deactivated.', messages.SUCCESS)
    deactivate_users.short_description = "Deactivate selected users"
    
    def activate_users(self, request, queryset):
        count = 0
        for user in queryset:
            UserStatusManager.activate_user(user, request)
            count += 1
        self.message_user(request, f'{count} user(s) activated.', messages.SUCCESS)
    activate_users.short_description = "Activate selected users"


# Unregister default User admin and register custom one
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass
admin.site.register(User, CustomUserAdmin)