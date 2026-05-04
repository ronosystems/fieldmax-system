from django.contrib import admin
from django.utils.html import format_html

# Correct import - note it's 'shops' (plural), not 'shop'
from shops.models import ShopBranch

from .models import RepairJob, RepairJobExpense


@admin.register(RepairJob)
class RepairJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'shop', 'customer_name', 'device_type', 'status', 'total_amount', 'amount_paid', 'remaining_balance', 'created_at')
    list_filter = ('status', 'shop', 'payment_method', 'created_at')
    search_fields = ('customer_name', 'customer_phone', 'device_type', 'device_model', 'technician_name', 'shop__name')
    readonly_fields = ('total_amount', 'remaining_balance', 'created_at', 'updated_at', 'completed_at', 'picked_up_at')
    list_editable = ('status',)
    
    fieldsets = (
        ('Shop Information', {
            'fields': ('shop',)
        }),
        ('Customer Information', {
            'fields': ('customer_name', 'customer_phone', 'technician_name')
        }),
        ('Device Information', {
            'fields': ('device_type', 'device_model', 'issue_description')
        }),
        ('Repair Status', {
            'fields': ('status', 'warranty_days', 'notes')
        }),
        ('Financial Details', {
            'fields': ('material_cost', 'labor_cost', 'total_amount', 'amount_paid', 'remaining_balance')
        }),
        ('Payment Information', {
            'fields': ('payment_method', 'mpesa_transaction_code')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'completed_at', 'picked_up_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('shop')
    
    def colored_status(self, obj):
        colors = {
            'pending': 'orange',
            'in_progress': 'blue',
            'completed': 'green',
            'picked_up': 'purple',
            'cancelled': 'red',
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    colored_status.short_description = 'Status'


@admin.register(RepairJobExpense)
class RepairJobExpenseAdmin(admin.ModelAdmin):
    list_display = ('repair_job', 'description', 'amount', 'date_incurred')
    list_filter = ('date_incurred',)
    search_fields = ('repair_job__customer_name', 'description')