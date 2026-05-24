from django.contrib import admin
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.contrib import messages
from django.utils import timezone
from django.shortcuts import render
from django.http import HttpResponseRedirect
from django.utils.html import format_html
from django.urls import reverse
from .models import StaffApplication, Staff, OTPVerification, UserProfile, UserStatus
from .utils.user_status import UserStatusManager
from shops.models import ShopBranch

User = get_user_model()


# ============================================
# Custom Form for Staff with UserProfile fields
# ============================================
class StaffAdminForm(forms.ModelForm):
    """Staff form that includes UserProfile fields"""
    
    # UserProfile fields to include
    is_ceo = forms.BooleanField(
        label='CEO Status',
        help_text='Designates whether the staff member is the CEO/Company Owner.',
        required=False,
    )
    is_verified = forms.BooleanField(
        label='Identity Verified',
        help_text='Staff member identity has been verified',
        required=False,
    )
    password_changed = forms.BooleanField(
        label='Password Changed',
        help_text='Staff member has changed their initial password',
        required=False,
    )
    first_login = forms.BooleanField(
        label='First Login',
        help_text='Staff member hasn\'t logged in yet',
        required=False,
    )
    
    class Meta:
        model = Staff
        fields = '__all__'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # If editing existing staff, populate UserProfile fields
        if self.instance and self.instance.pk and self.instance.user:
            profile = getattr(self.instance.user, 'profile', None)
            if profile:
                self.initial['is_ceo'] = profile.is_ceo
                self.initial['is_verified'] = profile.is_verified
                self.initial['password_changed'] = profile.password_changed
                self.initial['first_login'] = profile.first_login
    
    def save(self, commit=True):
        staff = super().save(commit=False)
        
        if commit:
            staff.save()
            
            # Update UserProfile with the combined fields
            if staff.user:
                profile, created = UserProfile.objects.get_or_create(user=staff.user)
                profile.is_ceo = self.cleaned_data.get('is_ceo', False)
                profile.is_verified = self.cleaned_data.get('is_verified', False)
                profile.password_changed = self.cleaned_data.get('password_changed', False)
                profile.first_login = self.cleaned_data.get('first_login', True)
                
                # If marking as verified, set verification timestamp
                if profile.is_verified and not profile.verified_at:
                    profile.verified_at = timezone.now()
                
                profile.save()
        
        return staff


# ============================================
# Combined Staff Admin
# ============================================
@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    form = StaffAdminForm
    
    list_display = [
        'staff_id',
        'full_name',
        'username_display',
        'role_group_display',
        'assigned_shop_display',
        'is_ceo_icon',
        'is_verified_icon',
        'password_changed_icon',
        'first_login_status',
        'account_status_display',
        'security_status_display',
        'view_user_profile_link',
    ]
    
    list_filter = [
        'position',
        'assigned_shop',
        'user__profile__is_ceo',
        'user__profile__is_verified',
        'user__profile__password_changed',
        'user__profile__first_login',
        'user__is_active',
        'user__status__is_locked',
        'user__status__is_suspended',
    ]
    
    search_fields = [
        'staff_id',
        'user__username',
        'user__email',
        'user__first_name',
        'user__last_name',
        'id_number'
    ]
    
    list_per_page = 25
    ordering = ['-created_at']
    
    fieldsets = (
        ('👤 Staff Information', {
            'fields': (
                ('user', 'staff_id'),
                ('id_number', 'position'),
                ('department', 'assigned_shop'),
            ),
        }),
        
        ('👔 User Profile Settings', {
            'fields': (
                ('is_ceo', 'is_verified'),
                ('password_changed', 'first_login'),
            ),
        }),
        
        ('✅ Identity Verification (ITP)', {
            'fields': (
                'is_identity_verified',
                'verification_code',
                'verification_sent_at',
                'verification_submitted_at',
                ('verified_at', 'verified_by'),
                'verification_notes',
            ),
            'classes': ('collapse',),
        }),
        
        ('📄 Verification Documents', {
            'fields': (
                'passport_photo',
                'live_photo',
                'id_front',
                'id_back',
            ),
            'classes': ('collapse',),
        }),
        
        ('📅 System Timestamps', {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )
    
    readonly_fields = [
        'created_at',
        'updated_at',
        'verification_code',
        'verification_sent_at',
        'verification_submitted_at',
        'verified_at',
        'staff_id',
    ]
    
    def full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.username
    full_name.short_description = 'Full Name'
    full_name.admin_order_field = 'user__first_name'
    
    def username_display(self, obj):
        return obj.user.username
    username_display.short_description = 'Username'
    username_display.admin_order_field = 'user__username'
    
    def role_group_display(self, obj):
        groups = obj.user.groups.all()
        if groups:
            return ', '.join([group.name for group in groups])
        return 'No Role Assigned'
    role_group_display.short_description = 'Role Group'
    
    def assigned_shop_display(self, obj):
        if obj.assigned_shop:
            return obj.assigned_shop.name
        return 'Not Assigned'
    assigned_shop_display.short_description = 'Assigned Shop'
    
    def is_ceo_icon(self, obj):
        if hasattr(obj.user, 'profile'):
            return obj.user.profile.is_ceo
        return False
    is_ceo_icon.short_description = 'Is CEO'
    is_ceo_icon.boolean = True
    
    def is_verified_icon(self, obj):
        if hasattr(obj.user, 'profile'):
            return obj.user.profile.is_verified
        return False
    is_verified_icon.short_description = 'Is Verified'
    is_verified_icon.boolean = True
    
    def password_changed_icon(self, obj):
        if hasattr(obj.user, 'profile'):
            return obj.user.profile.password_changed
        return False
    password_changed_icon.short_description = 'Password Changed'
    password_changed_icon.boolean = True
    
    def first_login_status(self, obj):
        if hasattr(obj.user, 'profile'):
            return obj.user.profile.first_login
        return True
    first_login_status.short_description = 'First Login'
    first_login_status.boolean = True
    
    def account_status_display(self, obj):
        if not obj.user.is_active:
            return format_html('<span style="color: #ba2121;">❌ Deactivated</span>')
        return format_html('<span style="color: #2bde3f;">✅ Active</span>')
    account_status_display.short_description = 'Account Status'
    
    def security_status_display(self, obj):
        try:
            status = UserStatus.objects.get(user=obj.user)
            if status.is_locked:
                return format_html('<span style="color: #ba2121;">🔒 Locked</span>')
            if status.is_suspended:
                return format_html('<span style="color: #ff8c00;">⛔ Suspended</span>')
            return format_html('<span style="color: #2bde3f;">🔓 Active</span>')
        except UserStatus.DoesNotExist:
            return format_html('<span style="color: #2bde3f;">✅ Normal</span>')
    security_status_display.short_description = 'Security Status'
    
    def view_user_profile_link(self, obj):
        if obj.user and hasattr(obj.user, 'profile'):
            url = reverse('admin:staff_userprofile_change', args=[obj.user.profile.id])
            return format_html('<a href="{}" style="font-weight: bold; color: #007bff;">📋 View Profile</a>', url)
        return '-'
    view_user_profile_link.short_description = 'User Profile'
    
    actions = [
        'lock_users', 'unlock_users',
        'suspend_users', 'unsuspend_users',
        'activate_users', 'deactivate_users',
        'verify_profile_identity',
        'assign_shop_to_selected',
        'mark_as_ceo', 'unmark_as_ceo',
    ]
    
    def lock_users(self, request, queryset):
        count = 0
        for staff in queryset:
            UserStatusManager.lock_user(staff.user, 'admin', request)
            count += 1
        self.message_user(request, f'🔒 {count} staff account(s) locked.', messages.SUCCESS)
    lock_users.short_description = "🔒 Lock selected staff accounts"
    
    def unlock_users(self, request, queryset):
        count = 0
        for staff in queryset:
            UserStatusManager.unlock_user(staff.user, request)
            count += 1
        self.message_user(request, f'🔓 {count} staff account(s) unlocked.', messages.SUCCESS)
    unlock_users.short_description = "🔓 Unlock selected staff accounts"
    
    def suspend_users(self, request, queryset):
        count = 0
        for staff in queryset:
            UserStatusManager.suspend_user(staff.user, 'Admin suspension', request.user, 30, request)
            count += 1
        self.message_user(request, f'⛔ {count} staff account(s) suspended for 30 days.', messages.SUCCESS)
    suspend_users.short_description = "⛔ Suspend selected staff (30 days)"
    
    def unsuspend_users(self, request, queryset):
        count = 0
        for staff in queryset:
            UserStatusManager.unsuspend_user(staff.user, request)
            count += 1
        self.message_user(request, f'✅ {count} staff account(s) unsuspended.', messages.SUCCESS)
    unsuspend_users.short_description = "✅ Unsuspend selected staff"
    
    def deactivate_users(self, request, queryset):
        count = 0
        for staff in queryset:
            UserStatusManager.deactivate_user(staff.user, 'Admin deactivation', request.user, request)
            count += 1
        self.message_user(request, f'❌ {count} staff account(s) deactivated.', messages.SUCCESS)
    deactivate_users.short_description = "❌ Deactivate selected staff"
    
    def activate_users(self, request, queryset):
        count = 0
        for staff in queryset:
            UserStatusManager.activate_user(staff.user, request)
            count += 1
        self.message_user(request, f'✅ {count} staff account(s) activated.', messages.SUCCESS)
    activate_users.short_description = "✅ Activate selected staff"
    
    def verify_profile_identity(self, request, queryset):
        count = 0
        for staff in queryset:
            if staff.user and hasattr(staff.user, 'profile'):
                profile = staff.user.profile
                if not profile.is_verified:
                    profile.is_verified = True
                    profile.verified_at = timezone.now()
                    profile.save()
                    count += 1
        self.message_user(request, f'✅ {count} staff profile(s) marked as verified.', messages.SUCCESS)
    verify_profile_identity.short_description = "✅ Verify UserProfile for selected staff"
    
    def mark_as_ceo(self, request, queryset):
        count = 0
        for staff in queryset:
            if staff.user and hasattr(staff.user, 'profile'):
                profile = staff.user.profile
                if not profile.is_ceo:
                    profile.is_ceo = True
                    profile.save()
                    count += 1
        self.message_user(request, f'👑 {count} staff member(s) marked as CEO.', messages.SUCCESS)
    mark_as_ceo.short_description = "👑 Mark selected as CEO"
    
    def unmark_as_ceo(self, request, queryset):
        count = 0
        for staff in queryset:
            if staff.user and hasattr(staff.user, 'profile'):
                profile = staff.user.profile
                if profile.is_ceo:
                    profile.is_ceo = False
                    profile.save()
                    count += 1
        self.message_user(request, f'📋 CEO status removed from {count} staff member(s).', messages.SUCCESS)
    unmark_as_ceo.short_description = "📋 Remove CEO status"
    
    def assign_shop_to_selected(self, request, queryset):
        if request.method == 'POST' and 'assigned_shop' in request.POST:
            shop_id = request.POST.get('assigned_shop')
            if shop_id:
                try:
                    shop = ShopBranch.objects.get(id=shop_id)
                    count = queryset.update(assigned_shop=shop)
                    self.message_user(request, f'✅ Successfully assigned {count} staff member(s) to {shop.name}', messages.SUCCESS)
                except ShopBranch.DoesNotExist:
                    self.message_user(request, '❌ Selected shop does not exist.', messages.ERROR)
            else:
                self.message_user(request, '❌ Please select a shop.', messages.ERROR)
            return HttpResponseRedirect(request.get_full_path())
        else:
            shops = ShopBranch.objects.filter(is_active=True)
            return render(request, 'admin/assign_shop_form.html', {
                'shops': shops,
                'staff_count': queryset.count(),
                'staff_list': queryset,
                'action': 'assign_shop_to_selected'
            })
    assign_shop_to_selected.short_description = "🏪 Assign selected staff to a shop"
    
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        
        if obj.user:
            profile, created = UserProfile.objects.get_or_create(user=obj.user)
            profile.is_ceo = form.cleaned_data.get('is_ceo', False)
            profile.is_verified = form.cleaned_data.get('is_verified', False)
            profile.password_changed = form.cleaned_data.get('password_changed', False)
            profile.first_login = form.cleaned_data.get('first_login', True)
            profile.save()
        
        # Handle group assignment based on position
        from django.contrib.auth.models import Group
        group_name = Staff.get_group_for_position(obj.position)
        if group_name:
            group, _ = Group.objects.get_or_create(name=group_name)
            obj.user.groups.clear()
            obj.user.groups.add(group)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'user__profile', 'assigned_shop'
        ).prefetch_related('user__groups', 'user__status')


# ============================================
# CUSTOM USER ADMIN - Shows Staff fields in User table
# ============================================
class CustomUserAdmin(BaseUserAdmin):
    """Custom User Admin that displays Staff-related fields"""
    
    list_display = [
        'username',
        'staff_id_display',
        'role_group_display',
        'email',
        'first_name',
        'last_name',
        'is_superuser',           # This is native - returns boolean
        'is_ceo_display',         # Custom - returns boolean
        'is_verified_display',    # Custom - returns boolean
        'is_staff',
        'is_active',
        'staff_member_link',
    ]
    
    list_filter = [
        'is_staff',
        'is_active',
        'is_superuser',
        'groups',
        'staff_profile__position',
        'staff_profile__assigned_shop',
        'profile__is_ceo',
        'profile__is_verified',
    ]
    
    search_fields = [
        'username',
        'email',
        'first_name',
        'last_name',
        'staff_profile__staff_id',
        'staff_profile__id_number',
    ]
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email')}),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    def staff_id_display(self, obj):
        try:
            staff = Staff.objects.get(user=obj)
            return staff.staff_id
        except Staff.DoesNotExist:
            return '-'
    staff_id_display.short_description = 'Staff ID'
    staff_id_display.admin_order_field = 'staff_profile__staff_id'
    
    def role_group_display(self, obj):
        groups = obj.groups.all()
        if groups:
            return ', '.join([group.name for group in groups])
        return '-'
    role_group_display.short_description = 'Role Group'
    
    def is_ceo_display(self, obj):
        """Return boolean for CEO status - Django will handle the icon"""
        if hasattr(obj, 'profile') and obj.profile.is_ceo:
            return True
        return False
    is_ceo_display.short_description = 'CEO'
    is_ceo_display.boolean = True  # This tells Django to show yes/no icon
    is_ceo_display.admin_order_field = 'profile__is_ceo'
    
    def is_verified_display(self, obj):
        """Return boolean for verified status - Django will handle the icon"""
        if hasattr(obj, 'profile') and obj.profile.is_verified:
            return True
        return False
    is_verified_display.short_description = 'Verified'
    is_verified_display.boolean = True  # This tells Django to show yes/no icon
    is_verified_display.admin_order_field = 'profile__is_verified'
    
    def staff_member_link(self, obj):
        try:
            staff = Staff.objects.get(user=obj)
            url = reverse('admin:staff_staff_change', args=[staff.id])
            return format_html(
                '<a href="{}" style="font-weight: bold; color: #28a745;">👤 View Staff</a>',
                url
            )
        except Staff.DoesNotExist:
            add_url = reverse('admin:staff_staff_add') + f'?user={obj.id}'
            return format_html(
                '<a href="{}" style="font-weight: bold; color: #ff8c00;">➕ Create Staff</a>',
                add_url
            )
    staff_member_link.short_description = 'Staff Member'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('staff_profile', 'profile').prefetch_related('groups')


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
        from django.contrib.auth.models import Group
        
        count = 0
        for application in queryset:
            if application.status != 'approved':
                username = f"{application.first_name.lower()}.{application.last_name.lower()}"[:150]
                base_username = username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}{counter}"
                    counter += 1
                
                user = User.objects.create(
                    username=username,
                    email=application.email,
                    first_name=application.first_name,
                    last_name=application.last_name,
                    is_active=True,
                    is_staff=True,
                )
                
                staff = Staff.objects.create(
                    user=user,
                    id_number=application.id_number,
                    position=application.position,
                )
                
                UserProfile.objects.create(user=user)
                UserStatus.objects.create(user=user)
                
                group_name = Staff.get_group_for_position(application.position)
                if group_name:
                    group, _ = Group.objects.get_or_create(name=group_name)
                    user.groups.add(group)
                
                application.created_user = user
                count += 1
        
        updated = queryset.update(
            status='approved',
            reviewed_by=request.user,
            review_date=timezone.now()
        )
        self.message_user(request, f'{updated} applications approved. {count} user accounts created.')
    approve_applications.short_description = "Approve and create user accounts"
    
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
# OTP Verification Admin
# ============================================
@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'otp_code', 'created_at', 'expires_at', 'is_used', 'purpose']
    list_filter = ['is_used', 'purpose', 'created_at']
    search_fields = ['user__username', 'otp_code']
    readonly_fields = ['created_at']


# ============================================
# UserProfile Admin - HIDDEN from admin menu
# ============================================
class HiddenUserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_ceo', 'is_verified', 'password_changed', 'first_login', 'view_staff_link']
    list_filter = ['is_ceo', 'is_verified', 'password_changed', 'first_login']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['verified_at', 'verified_by', 'last_password_change']
    
    def view_staff_link(self, obj):
        try:
            staff = Staff.objects.get(user=obj.user)
            url = reverse('admin:staff_staff_change', args=[staff.id])
            return format_html('<a href="{}" style="font-weight: bold; color: #28a745;">👤 View Staff Member</a>', url)
        except Staff.DoesNotExist:
            add_url = reverse('admin:staff_staff_add') + f'?user={obj.user.id}'
            return format_html('<a href="{}" style="font-weight: bold; color: #ff8c00;">➕ Create Staff Record</a>', add_url)
    view_staff_link.short_description = 'Staff Member'
    
    def has_module_permission(self, request):
        return False


# ============================================
# UserStatus Admin
# ============================================
@admin.register(UserStatus)
class UserStatusAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_locked', 'is_suspended', 'failed_login_attempts', 'view_staff_link']
    list_filter = ['is_locked', 'is_suspended']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['locked_at', 'suspended_at', 'deactivated_at']
    
    def view_staff_link(self, obj):
        try:
            staff = Staff.objects.get(user=obj.user)
            url = reverse('admin:staff_staff_change', args=[staff.id])
            return format_html('<a href="{}" style="color: #28a745;">👤 View Staff</a>', url)
        except Staff.DoesNotExist:
            return '-'
    view_staff_link.short_description = 'Staff Member'
    
    def has_add_permission(self, request):
        return False


# ============================================
# Register all admins
# ============================================

# Register UserProfile as HIDDEN
admin.site.register(UserProfile, HiddenUserProfileAdmin)

# Unregister default User admin and register custom one
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

# Register custom User admin with staff fields
admin.site.register(User, CustomUserAdmin)