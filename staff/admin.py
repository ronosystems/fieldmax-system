from django.contrib import admin
from django.contrib import admin
from django.utils.html import format_html
from .models import StaffApplication
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group


User = get_user_model()




@admin.register(StaffApplication)
class StaffApplicationAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'email', 'phone', 'position', 'status_badge', 'application_date']
    list_filter = ['status', 'position', 'application_date']
    search_fields = ['first_name', 'last_name', 'email', 'phone', 'id_number']
    readonly_fields = ['application_date', 'ip_address', 'user_agent', 'document_preview']
    
    fieldsets = (
        ('Personal Information', {
            'fields': ('first_name', 'last_name', 'email', 'phone', 'id_number', 'address')
        }),
        ('Application Details', {
            'fields': ('position', 'experience')
        }),
        ('Documents', {
            'fields': ('passport_photo', 'id_front', 'id_back', 'document_preview')
        }),
        ('Status', {
            'fields': ('status', 'reviewed_by', 'review_date', 'review_notes')
        }),
        ('Terms & System', {
            'fields': ('terms_accepted', 'privacy_accepted', 'ip_address', 'user_agent', 'created_user', 'application_date'),
            'classes': ('collapse',)
        }),
    )
    
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
    
    def document_preview(self, obj):
        html = '<div style="display: flex; gap: 10px;">'
        
        if obj.passport_photo:
            html += f'''
            <div style="text-align: center;">
                <img src="{obj.passport_photo.url}" style="max-height: 100px; max-width: 100px;">
                <br>Passport
            </div>
            '''
        
        if obj.id_front:
            html += f'''
            <div style="text-align: center;">
                <img src="{obj.id_front.url}" style="max-height: 100px; max-width: 100px;">
                <br>ID Front
            </div>
            '''
        
        if obj.id_back:
            html += f'''
            <div style="text-align: center;">
                <img src="{obj.id_back.url}" style="max-height: 100px; max-width: 100px;">
                <br>ID Back
            </div>
            '''
        
        html += '</div>'
        return format_html(html)
    document_preview.short_description = 'Document Preview'
    
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


# staff/admin.py
from django.contrib import admin
from .models import StaffApplication, Staff, OTPVerification, UserProfile

@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ['staff_id', 'user', 'position', 'is_identity_verified', 'created_at']
    list_filter = ['is_identity_verified', 'position']
    search_fields = ['staff_id', 'user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at']