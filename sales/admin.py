from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Sum, Count, Q
from django.utils import timezone
from decimal import Decimal
from .models import (
    Sale, SaleItem, SaleCounter, PaymentRecord, SaleReversal,
    FiscalReceipt, Customer, LoyaltyTransaction, LoyaltySettings
)


class SaleItemInline(admin.TabularInline):
    """Inline for sale items"""
    model = SaleItem
    extra = 0
    readonly_fields = [
        'product_code', 'product_name', 'sku_value', 'quantity',
        'unit_price', 'total_price', 'product_age_days'
    ]
    fields = [
        'product_code', 'product_name', 'quantity',
        'unit_price', 'total_price'
    ]
    can_delete = False
    max_num = 0
    
    def has_add_permission(self, request, obj=None):
        return False


class PaymentRecordInline(admin.TabularInline):
    """Inline for payment records (split payments)"""
    model = PaymentRecord
    extra = 0
    readonly_fields = [
        'method', 'amount', 'cash_tendered', 'cash_change',
        'mpesa_phone', 'mpesa_transaction_id', 'bank_name',
        'card_last_four', 'points_redeemed', 'created_at'
    ]
    fields = ['method', 'amount', 'created_at']
    can_delete = False
    max_num = 0
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = [
        'sale_id', 'sale_date_display', 'seller', 'buyer_name',
        'total_amount_colored', 'payment_method', 'is_credit_badge',
        'is_reversed_badge', 'etr_status_badge'
    ]
    list_filter = [
        'payment_method', 'is_credit', 'is_reversed', 'etr_status',
        'sale_date', 'seller'
    ]
    search_fields = [
        'sale_id', 'etr_receipt_number', 'buyer_name', 'buyer_phone',
        'buyer_id_number', 'seller__username'
    ]
    readonly_fields = [
        'sale_id', 'sequence_number', 'etr_receipt_number',
        'total_quantity', 'subtotal', 'tax_amount', 'total_amount',
        'sale_date', 'change_display', 'balance_display', 'points_discount_display'
    ]
    list_select_related = ['seller', 'customer']
    list_per_page = 50
    inlines = [SaleItemInline, PaymentRecordInline]
    date_hierarchy = 'sale_date'
    
    fieldsets = (
        ('Transaction Information', {
            'fields': (
                'sale_id', 'sequence_number', 'sale_date',
                'etr_receipt_number', 'fiscal_receipt_number'
            )
        }),
        ('Seller Information', {
            'fields': ('seller',)
        }),
        ('Customer Information', {
            'fields': (
                'buyer_name', 'buyer_phone', 'buyer_id_number',
                'nok_name', 'nok_phone', 'customer'
            )
        }),
        ('Financial Summary', {
            'fields': (
                'total_quantity', 'subtotal', 'tax_amount',
                'total_amount', 'amount_paid', 'change_display',
                'balance_display'
            )
        }),
        ('Payment Details', {
            'fields': ('payment_method', 'is_split_payment', 'payment_breakdown')
        }),
        ('Loyalty Points', {
            'fields': (
                'points_redeemed', 'points_discount_display',
                'original_subtotal', 'points_earned'
            ),
            'classes': ('collapse',)
        }),
        ('Credit Sale Information', {
            'fields': ('is_credit', 'credit_sale_id'),
            'classes': ('collapse',)
        }),
        ('ETR Processing', {
            'fields': ('etr_status', 'etr_processed_at', 'etr_error_message'),
            'classes': ('collapse',)
        }),
        ('Reversal Information', {
            'fields': ('is_reversed', 'reversed_at', 'reversed_by', 'reversal_reason'),
            'classes': ('collapse',)
        }),
        ('Additional Information', {
            'fields': ('batch_id',),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('items', 'payment_records')
    
    def sale_date_display(self, obj):
        return obj.sale_date.strftime('%Y-%m-%d %H:%M')
    sale_date_display.short_description = 'Sale Date'
    sale_date_display.admin_order_field = 'sale_date'
    
    def total_amount_colored(self, obj):
        if obj.is_reversed:
            color = '#999'
        elif obj.is_credit:
            color = '#dc3545'
        else:
            color = '#28a745'
        return format_html('<span style="color: {}; font-weight: bold;">KSH {:,.2f}</span>', 
                          color, obj.total_amount)
    total_amount_colored.short_description = 'Total Amount'
    total_amount_colored.admin_order_field = 'total_amount'
    
    def change_display(self, obj):
        if obj.change > 0:
            return format_html('<span style="color: #28a745;">KSH {:,.2f}</span>', obj.change)
        return 'KSH 0.00'
    change_display.short_description = 'Change'
    
    def balance_display(self, obj):
        if obj.balance > 0:
            return format_html('<span style="color: #dc3545;">KSH {:,.2f}</span>', obj.balance)
        return 'KSH 0.00'
    balance_display.short_description = 'Balance Due'
    
    def points_discount_display(self, obj):
        if obj.points_discount > 0:
            return format_html('<span style="color: #6f42c1;">KSH {:,.2f}</span>', obj.points_discount)
        return 'KSH 0.00'
    points_discount_display.short_description = 'Points Discount'
    
    def is_credit_badge(self, obj):
        if obj.is_credit:
            return format_html('<span style="background-color: #dc3545; color: white; padding: 2px 8px; border-radius: 12px;">Credit</span>')
        return format_html('<span style="background-color: #28a745; color: white; padding: 2px 8px; border-radius: 12px;">Cash</span>')
    is_credit_badge.short_description = 'Type'
    
    def is_reversed_badge(self, obj):
        if obj.is_reversed:
            return format_html('<span style="background-color: #6c757d; color: white; padding: 2px 8px; border-radius: 12px;">Reversed</span>')
        return format_html('<span style="background-color: #007bff; color: white; padding: 2px 8px; border-radius: 12px;">Active</span>')
    is_reversed_badge.short_description = 'Status'
    
    def etr_status_badge(self, obj):
        colors = {
            'pending': '#ffc107',
            'processed': '#28a745',
            'failed': '#dc3545'
        }
        color = colors.get(obj.etr_status, '#6c757d')
        return format_html('<span style="background-color: {}; color: white; padding: 2px 8px; border-radius: 12px;">{}</span>', 
                          color, obj.get_etr_status_display())
    etr_status_badge.short_description = 'ETR Status'
    
    def has_add_permission(self, request):
        # Disable adding through admin (use POS interface instead)
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    actions = ['reverse_selected_sales']
    
    @admin.action(description='Reverse selected sales')
    def reverse_selected_sales(self, request, queryset):
        reversed_count = 0
        errors = []
        
        for sale in queryset:
            if sale.is_reversed:
                errors.append(f"Sale {sale.sale_id} is already reversed")
                continue
            
            try:
                reversal = SaleReversal.objects.create(
                    sale=sale,
                    reversed_by=request.user,
                    reason="Admin reversal from admin panel"
                )
                reversal.process_reversal()
                reversed_count += 1
            except Exception as e:
                errors.append(f"Sale {sale.sale_id}: {str(e)}")
        
        message = f"Successfully reversed {reversed_count} sale(s)."
        if errors:
            message += f" Errors: {'; '.join(errors[:5])}"
        self.message_user(request, message)


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = [
        'sale_link', 'product_code', 'product_name', 'quantity',
        'unit_price', 'total_price', 'product_age_days'
    ]
    list_filter = ['created_at', 'sale__payment_method']
    search_fields = [
        'sale__sale_id', 'product_code', 'product_name',
        'product__sku_code', 'product__display_name'
    ]
    readonly_fields = [
        'sale', 'product', 'product_code', 'product_name',
        'sku_value', 'quantity', 'unit_price', 'total_price',
        'product_unit', 'product_age_days', 'created_at'
    ]
    list_select_related = ['sale', 'product']
    list_per_page = 50
    
    def sale_link(self, obj):
        url = reverse('admin:sales_sale_change', args=[obj.sale.sale_id])
        return format_html('<a href="{}">{}</a>', url, obj.sale.sale_id)
    sale_link.short_description = 'Sale'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = [
        'sale_link', 'method', 'amount_display', 'mpesa_transaction_id',
        'points_redeemed', 'created_at'
    ]
    list_filter = ['method', 'created_at']
    search_fields = [
        'sale__sale_id', 'mpesa_transaction_id',
        'mpesa_phone', 'bank_name'
    ]
    readonly_fields = [
        'sale', 'method', 'amount', 'cash_tendered', 'cash_change',
        'mpesa_phone', 'mpesa_transaction_id', 'mpesa_checkout_request_id',
        'bank_name', 'card_last_four', 'points_redeemed',
        'created_at', 'processed_by'
    ]
    list_select_related = ['sale', 'processed_by']
    list_per_page = 50
    
    def sale_link(self, obj):
        url = reverse('admin:sales_sale_change', args=[obj.sale.sale_id])
        return format_html('<a href="{}">{}</a>', url, obj.sale.sale_id)
    sale_link.short_description = 'Sale'
    
    def amount_display(self, obj):
        return format_html('KSH {:,.2f}', obj.amount)
    amount_display.short_description = 'Amount'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SaleCounter)
class SaleCounterAdmin(admin.ModelAdmin):
    list_display = ['id', 'counter_display', 'last_used']
    readonly_fields = ['counter', 'last_used']
    
    def counter_display(self, obj):
        return f"{obj.counter:05d}"
    counter_display.short_description = 'Current Counter'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        # Allow viewing but not editing
        if obj:
            return False
        return super().has_change_permission(request, obj)


@admin.register(SaleReversal)
class SaleReversalAdmin(admin.ModelAdmin):
    list_display = [
        'sale_link', 'reversed_at', 'reversed_by', 'items_processed',
        'total_amount_reversed_display', 'is_successful_badge'
    ]
    list_filter = ['reversed_at', 'reversed_by']
    search_fields = ['sale__sale_id', 'reversal_reference', 'reason']
    readonly_fields = [
        'sale', 'reversed_at', 'reversed_by', 'reason',
        'items_processed', 'total_amount_reversed', 'reversal_reference'
    ]
    list_select_related = ['sale', 'reversed_by']
    list_per_page = 50
    
    def sale_link(self, obj):
        url = reverse('admin:sales_sale_change', args=[obj.sale.sale_id])
        return format_html('<a href="{}">{}</a>', url, obj.sale.sale_id)
    sale_link.short_description = 'Sale'
    
    def total_amount_reversed_display(self, obj):
        return format_html('KSH {:,.2f}', obj.total_amount_reversed)
    total_amount_reversed_display.short_description = 'Amount Reversed'
    
    def is_successful_badge(self, obj):
        if obj.is_successful:
            return format_html('<span style="color: #28a745;">✓ Successful</span>')
        return format_html('<span style="color: #dc3545;">✗ Failed</span>')
    is_successful_badge.short_description = 'Status'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FiscalReceipt)
class FiscalReceiptAdmin(admin.ModelAdmin):
    list_display = ['receipt_number', 'sale_link', 'issued_at', 'has_qr_badge']
    list_filter = ['issued_at']
    search_fields = ['receipt_number', 'sale__sale_id']
    readonly_fields = [
        'sale', 'receipt_number', 'issued_at', 'qr_code',
        'verification_url', 'receipt_data'
    ]
    list_select_related = ['sale']
    list_per_page = 50
    
    def sale_link(self, obj):
        url = reverse('admin:sales_sale_change', args=[obj.sale.sale_id])
        return format_html('<a href="{}">{}</a>', url, obj.sale.sale_id)
    sale_link.short_description = 'Sale'
    
    def has_qr_badge(self, obj):
        if obj.qr_code:
            return format_html('<span style="color: #28a745;">✓ Has QR</span>')
        return format_html('<span style="color: #999;">No QR</span>')
    has_qr_badge.short_description = 'QR Code'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


class LoyaltyTransactionInline(admin.TabularInline):
    model = LoyaltyTransaction
    extra = 0
    readonly_fields = [
        'points', 'transaction_type', 'description', 'created_at'
    ]
    fields = ['transaction_type', 'points', 'description', 'created_at']
    can_delete = False
    max_num = 10
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = [
        'phone_number', 'full_name', 'points_balance_display',
        'total_purchases', 'total_spent_display', 'last_purchase_date',
        'is_active_badge'
    ]
    list_filter = ['is_active', 'created_at']
    search_fields = [
        'phone_number', 'full_name', 'email', 'id_number'
    ]
    readonly_fields = [
        'points_balance', 'total_points_earned', 'total_points_redeemed',
        'total_purchases', 'total_spent', 'last_purchase_date',
        'created_at', 'updated_at'
    ]
    list_select_related = ['registered_by']
    list_per_page = 50
    inlines = [LoyaltyTransactionInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'phone_number', 'full_name', 'email', 'id_number'
            )
        }),
        ('Loyalty Points', {
            'fields': (
                'points_balance', 'total_points_earned', 'total_points_redeemed'
            )
        }),
        ('Purchase Statistics', {
            'fields': (
                'total_purchases', 'total_spent', 'last_purchase_date'
            )
        }),
        ('Registration Information', {
            'fields': ('registered_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )
    
    def points_balance_display(self, obj):
        points = float(obj.points_balance)
        if points == int(points):
            return f"{int(points):,}"
        return f"{points:,}"
    points_balance_display.short_description = 'Points Balance'
    points_balance_display.admin_order_field = 'points_balance'
    
    def total_spent_display(self, obj):
        return format_html('KSH {:,.2f}', obj.total_spent)
    total_spent_display.short_description = 'Total Spent'
    total_spent_display.admin_order_field = 'total_spent'
    
    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html('<span style="color: #28a745;">✓ Active</span>')
        return format_html('<span style="color: #dc3545;">✗ Inactive</span>')
    is_active_badge.short_description = 'Status'
    
    actions = ['activate_customers', 'deactivate_customers', 'add_points_to_customers']
    
    @admin.action(description='Activate selected customers')
    def activate_customers(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} customer(s) activated.")
    
    @admin.action(description='Deactivate selected customers')
    def deactivate_customers(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} customer(s) deactivated.")
    
    @admin.action(description='Add points to selected customers')
    def add_points_to_customers(self, request, queryset):
        # This would typically show an intermediate form
        # For simplicity, we'll add 10 points to each
        for customer in queryset:
            customer.add_points(10, description="Admin bonus points")
        self.message_user(request, f"Added 10 points to {queryset.count()} customer(s).")


@admin.register(LoyaltyTransaction)
class LoyaltyTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'customer_link', 'points_display', 'transaction_type_badge',
        'sale_link', 'description', 'created_at'
    ]
    list_filter = ['transaction_type', 'created_at']
    search_fields = [
        'customer__phone_number', 'customer__full_name',
        'sale__sale_id', 'description'
    ]
    readonly_fields = [
        'customer', 'sale', 'points', 'transaction_type',
        'description', 'created_at', 'created_by'
    ]
    list_select_related = ['customer', 'sale', 'created_by']
    list_per_page = 50
    
    def customer_link(self, obj):
        url = reverse('admin:sales_customer_change', args=[obj.customer.pk])
        return format_html('<a href="{}">{}</a>', url, obj.customer.phone_number)
    customer_link.short_description = 'Customer'
    
    def sale_link(self, obj):
        if obj.sale:
            url = reverse('admin:sales_sale_change', args=[obj.sale.sale_id])
            return format_html('<a href="{}">{}</a>', url, obj.sale.sale_id)
        return '-'
    sale_link.short_description = 'Sale'
    
    def points_display(self, obj):
        if obj.points > 0:
            return format_html('<span style="color: #28a745;">+{}</span>', obj.display_points)
        else:
            return format_html('<span style="color: #dc3545;">{}</span>', obj.display_points)
    points_display.short_description = 'Points'
    
    def transaction_type_badge(self, obj):
        colors = {
            'earned': '#28a745',
            'redeemed': '#dc3545',
            'expired': '#6c757d',
            'adjusted': '#ffc107'
        }
        color = colors.get(obj.transaction_type, '#6c757d')
        return format_html('<span style="background-color: {}; color: white; padding: 2px 8px; border-radius: 12px;">{}</span>', 
                          color, obj.get_transaction_type_display())
    transaction_type_badge.short_description = 'Type'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LoyaltySettings)
class LoyaltySettingsAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'points_percentage_display', 'min_purchase_for_points',
        'max_points_per_transaction', 'min_redeem_points',
        'max_redeem_percentage', 'points_expiry_days'
    ]
    fieldsets = (
        ('Point Earning Settings', {
            'fields': (
                'min_purchase_for_points', 'points_percentage',
                'max_points_per_transaction'
            )
        }),
        ('Point Redemption Settings', {
            'fields': (
                'min_redeem_points', 'max_redeem_percentage'
            )
        }),
        ('Points Expiry', {
            'fields': ('points_expiry_days',)
        }),
        ('Registration Settings', {
            'fields': (
                'welcome_points', 'require_id_for_registration',
                'require_email_for_registration'
            )
        }),
    )
    
    def points_percentage_display(self, obj):
        return f"{obj.points_percentage}% of sale"
    points_percentage_display.short_description = 'Earning Rate'
    
    def has_add_permission(self, request):
        # Prevent creating multiple instances
        if self.model.objects.exists():
            return False
        return super().has_add_permission(request)
    
    def has_delete_permission(self, request, obj=None):
        return False


# Custom admin site configuration
admin.site.site_header = 'Sales Management System'
admin.site.site_title = 'Sales Admin'
admin.site.index_title = 'Welcome to Sales Management'