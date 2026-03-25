# staff/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import StaffApplication, Staff, OTPVerification, UserProfile, UserStatus
from .utils.user_status import UserStatusManager
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


# ============================================
# Staff Application Admin
# ============================================
@admin.register(StaffApplication)
class StaffApplicationAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'phone', 'position', 'status_badge', 'application_date']
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
    
    def status_badge(self, obj):
        colors = {
            'pending': 'warning',
            'approved': 'success',
            'rejected': 'danger',
            'under_review': 'info',
        }
        color = colors.get(obj.status, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    actions = ['approve_applications', 'reject_applications', 'mark_under_review']
    
    def approve_applications(self, request, queryset):
        updated = queryset.update(
            status='approved',
            reviewed_by=request.user,
            review_date=timezone.now()
        )
        self.message_user(request, f'{updated} applications approved.')
    approve_applications.short_description = "Approve selected applications"
    
    def reject_applications(self, request, queryset):
        updated = queryset.update(
            status='rejected',
            reviewed_by=request.user,
            review_date=timezone.now()
        )
        self.message_user(request, f'{updated} applications rejected.')
    reject_applications.short_description = "Reject selected applications"
    
    def mark_under_review(self, request, queryset):
        updated = queryset.update(
            status='under_review',
            reviewed_by=request.user,
            review_date=timezone.now()
        )
        self.message_user(request, f'{updated} applications marked under review.')
    mark_under_review.short_description = "Mark as under review"


# ============================================
# Staff Admin - Simplified version without preview
# ============================================
@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
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
# User Status Admin (Inline already used)
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
    list_display = ('username', 'email', 'first_name', 'last_name', 'status_badge', 'is_staff', 'is_active')
    list_filter = ('is_active', 'is_staff', 'is_superuser')
    
    def status_badge(self, obj):
        """Display user status with colored badge"""
        try:
            if hasattr(obj, 'status'):
                if not obj.is_active:
                    return mark_safe('<span class="badge bg-danger">Deactivated</span>')
                if obj.status.is_locked:
                    return mark_safe('<span class="badge bg-info">Locked</span>')
                if obj.status.is_suspended:
                    return mark_safe('<span class="badge bg-warning">Suspended</span>')
            return mark_safe('<span class="badge bg-success">Active</span>')
        except:
            return mark_safe('<span class="badge bg-secondary">Unknown</span>')
    status_badge.short_description = 'Status'
    
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