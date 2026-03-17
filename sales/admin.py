# sales/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from django.db.models import Sum, Count
from .models import (
    Sale, SaleItem, SaleCounter, SaleReversal, 
    FiscalReceipt, Customer, LoyaltyTransaction, LoyaltySettings
)

# ============================================
# SALE COUNTER ADMIN
# ============================================
@admin.register(SaleCounter)
class SaleCounterAdmin(admin.ModelAdmin):
    list_display = ['year', 'counter']
    list_display_links = ['year']
    search_fields = ['year']
    readonly_fields = ['year', 'counter']
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


# ============================================
# SALE ITEM INLINE
# ============================================
class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0
    readonly_fields = ['product', 'product_code', 'product_name', 'sku_value', 
                       'quantity', 'unit_price', 'total_price', 'product_age_days']
    fields = ['product', 'product_code', 'product_name', 'sku_value', 
              'quantity', 'unit_price', 'total_price', 'product_age_days']
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


# ============================================
# SALE ADMIN
# ============================================
@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ['sale_id', 'sale_date', 'seller', 'buyer_name', 'buyer_phone', 
                    'total_amount', 'payment_method', 'is_credit', 'is_reversed', 
                    'etr_receipt_number']
    list_filter = ['payment_method', 'is_credit', 'is_reversed', 'etr_status', 'sale_date']
    search_fields = ['sale_id', 'buyer_name', 'buyer_phone', 'etr_receipt_number']
    readonly_fields = ['sale_id', 'created_at_display', 'reversal_info', 'points_summary']
    inlines = [SaleItemInline]
    
    fieldsets = (
        ('Sale Information', {
            'fields': ('sale_id', 'sale_date', 'seller')
        }),
        ('Customer Details', {
            'fields': ('buyer_name', 'buyer_phone', 'buyer_id_number', 'nok_name', 'nok_phone')
        }),
        ('Financial', {
            'fields': ('subtotal', 'tax_amount', 'total_amount', 'amount_paid', 'payment_method', 'is_credit')
        }),
        ('Points & Loyalty', {
            'fields': ('points_summary',),
            'classes': ('collapse',),
        }),
        ('ETR Information', {
            'fields': ('etr_receipt_number', 'etr_receipt_counter', 'fiscal_receipt_number', 
                      'etr_status', 'etr_processed_at', 'etr_error_message'),
            'classes': ('collapse',),
        }),
        ('Reversal Information', {
            'fields': ('reversal_info',),
            'classes': ('collapse',),
        }),
        ('Metadata', {
            'fields': ('batch_id', 'total_quantity', 'created_at_display'),
            'classes': ('collapse',),
        }),
    )
    
    def created_at_display(self, obj):
        return obj.sale_date
    created_at_display.short_description = "Created At"
    
    def reversal_info(self, obj):
        if obj.is_reversed:
            return format_html(
                '<span style="color: red;">✓ Reversed on {} by {}<br>Reason: {}</span>',
                obj.reversed_at.strftime('%Y-%m-%d %H:%M') if obj.reversed_at else 'Unknown',
                obj.reversed_by.username if obj.reversed_by else 'System',
                obj.reversal_reason or 'No reason provided'
            )
        return "Not Reversed"
    reversal_info.short_description = "Reversal Status"
    
    def points_summary(self, obj):
        points_earned = LoyaltyTransaction.objects.filter(
            sale=obj, transaction_type='earned'
        ).aggregate(total=Sum('points'))['total'] or 0
        
        points_redeemed = abs(LoyaltyTransaction.objects.filter(
            sale=obj, transaction_type='redeemed'
        ).aggregate(total=Sum('points'))['total'] or 0)
        
        if points_earned or points_redeemed:
            return format_html(
                '<span style="color: green;">✓ Points Earned: {}</span><br>'
                '<span style="color: orange;">✓ Points Redeemed: {}</span><br>'
                '<span style="color: blue;">✓ Points Discount: KSH {}</span>',
                points_earned, points_redeemed, obj.points_discount
            )
        return "No points transactions"
    points_summary.short_description = "Points Summary"
    
    actions = ['mark_as_reversed']
    
    def mark_as_reversed(self, request, queryset):
        updated = queryset.update(is_reversed=True, reversed_at=timezone.now())
        self.message_user(request, f'{updated} sales marked as reversed.')
    mark_as_reversed.short_description = "Mark selected sales as reversed"
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('seller', 'reversed_by')


# ============================================
# SALE REVERSAL ADMIN
# ============================================
@admin.register(SaleReversal)
class SaleReversalAdmin(admin.ModelAdmin):
    list_display = ['sale_link', 'reversed_at', 'reversed_by', 'items_processed', 
                    'formatted_amount', 'reason']
    list_filter = ['reversed_at', 'reversed_by']
    search_fields = ['sale__sale_id', 'reason', 'reversal_reference']
    readonly_fields = ['sale', 'reversed_at', 'reversed_by', 'items_processed', 
                       'total_amount_reversed', 'reversal_reference', 'reason']
    
    fieldsets = (
        ('Reversal Information', {
            'fields': ('sale_link_detail', 'reversed_at', 'reversed_by', 'reason')
        }),
        ('Details', {
            'fields': ('items_processed', 'total_amount_reversed', 'reversal_reference')
        }),
    )
    
    def sale_link(self, obj):
        url = reverse('admin:sales_sale_change', args=[obj.sale.sale_id])
        return format_html('<a href="{}">{}</a>', url, obj.sale.sale_id)
    sale_link.short_description = "Sale"
    
    def sale_link_detail(self, obj):
        url = reverse('admin:sales_sale_change', args=[obj.sale.sale_id])
        return format_html('<a href="{}" target="_blank">{}</a>', url, obj.sale.sale_id)
    sale_link_detail.short_description = "Sale"
    
    def formatted_amount(self, obj):
        return f"KSH {obj.total_amount_reversed:,.0f}"
    formatted_amount.short_description = "Amount Reversed"
    
    def has_add_permission(self, request):
        return False


# ============================================
# FISCAL RECEIPT ADMIN
# ============================================
@admin.register(FiscalReceipt)
class FiscalReceiptAdmin(admin.ModelAdmin):
    list_display = ['receipt_number', 'sale_link', 'issued_at']
    list_filter = ['issued_at']
    search_fields = ['receipt_number', 'sale__sale_id']
    readonly_fields = ['sale', 'receipt_number', 'issued_at', 'qr_code', 'verification_url']
    
    def sale_link(self, obj):
        url = reverse('admin:sales_sale_change', args=[obj.sale.sale_id])
        return format_html('<a href="{}">{}</a>', url, obj.sale.sale_id)
    sale_link.short_description = "Sale"
    
    def has_add_permission(self, request):
        return False


# ============================================
# CUSTOMER ADMIN
# ============================================
@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'phone_number', 'email', 'tier_badge', 
                    'points_display', 'total_spent_display', 'total_purchases', 
                    'last_purchase', 'is_active']
    list_filter = ['tier', 'is_active', 'created_at']
    search_fields = ['phone_number', 'full_name', 'email', 'id_number']
    readonly_fields = ['created_at', 'updated_at', 'points_summary', 
                       'transaction_history_link', 'purchase_stats']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('phone_number', 'full_name', 'email', 'id_number')
        }),
        ('Loyalty Points', {
            'fields': ('points_balance', 'total_points_earned', 'total_points_redeemed', 
                      'points_summary'),
        }),
        ('Tier & Statistics', {
            'fields': ('tier', 'total_purchases', 'total_spent', 'last_purchase_date',
                      'purchase_stats'),
        }),
        ('Registration', {
            'fields': ('registered_by', 'registration_note', 'is_active'),
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
        ('Transaction History', {
            'fields': ('transaction_history_link',),
            'classes': ('collapse',),
        }),
    )
    
    def tier_badge(self, obj):
        colors = {
            'bronze': '#cd7f32',
            'silver': '#c0c0c0',
            'gold': '#ffd700',
            'platinum': '#e5e4e2'
        }
        text_colors = {
            'bronze': 'white',
            'silver': 'black',
            'gold': 'black',
            'platinum': 'black'
        }
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 10px; '
            'border-radius: 20px; font-weight: bold;">{}</span>',
            colors.get(obj.tier, '#6c757d'),
            text_colors.get(obj.tier, 'white'),
            obj.get_tier_display().upper()
        )
    tier_badge.short_description = "Tier"
    
    def points_display(self, obj):
        return format_html(
            '<span style="font-weight: bold; color: #28a745;">{} pts</span> '
            '<span style="color: #6c757d;">(KSH {})</span>',
            obj.points_balance, obj.points_balance
        )
    points_display.short_description = "Points"
    
    def total_spent_display(self, obj):
        return f"KSH {obj.total_spent:,.0f}"
    total_spent_display.short_description = "Total Spent"
    
    def last_purchase(self, obj):
        if obj.last_purchase_date:
            return format_html(
                '<span title="{}">{}</span>',
                obj.last_purchase_date.strftime('%Y-%m-%d %H:%M'),
                obj.last_purchase_date.strftime('%Y-%m-%d')
            )
        return "Never"
    last_purchase.short_description = "Last Purchase"
    
    def points_summary(self, obj):
        return format_html(
            '<div style="background: #f8f9fa; padding: 10px; border-radius: 5px;">'
            '<strong>Current Balance:</strong> {} points (KSH {})<br>'
            '<strong>Total Earned:</strong> {} points<br>'
            '<strong>Total Redeemed:</strong> {} points<br>'
            '<strong>Points Value:</strong> KSH {}'
            '</div>',
            obj.points_balance, obj.points_balance,
            obj.total_points_earned,
            obj.total_points_redeemed,
            obj.points_balance
        )
    points_summary.short_description = "Points Summary"
    
    def purchase_stats(self, obj):
        avg_spent = obj.total_spent / obj.total_purchases if obj.total_purchases > 0 else 0
        return format_html(
            '<div style="background: #f8f9fa; padding: 10px; border-radius: 5px;">'
            '<strong>Average Purchase:</strong> KSH {:.0f}<br>'
            '<strong>Lifetime Value:</strong> KSH {:.0f}'
            '</div>',
            avg_spent, obj.total_spent
        )
    purchase_stats.short_description = "Purchase Statistics"
    
    def transaction_history_link(self, obj):
        url = reverse('admin:sales_loyaltytransaction_changelist') + f'?customer__id__exact={obj.id}'
        count = LoyaltyTransaction.objects.filter(customer=obj).count()
        return format_html(
            '<a href="{}" target="_blank">View {} transactions →</a>',
            url, count
        )
    transaction_history_link.short_description = "Transactions"
    
    actions = ['activate_customers', 'deactivate_customers', 'reset_points']
    
    def activate_customers(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} customers activated.')
    activate_customers.short_description = "Activate selected customers"
    
    def deactivate_customers(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} customers deactivated.')
    deactivate_customers.short_description = "Deactivate selected customers"
    
    def reset_points(self, request, queryset):
        for customer in queryset:
            customer.points_balance = 0
            customer.save()
        self.message_user(request, f'{queryset.count()} customers points reset to 0.')
    reset_points.short_description = "Reset points to 0"


# ============================================
# LOYALTY TRANSACTION ADMIN
# ============================================
@admin.register(LoyaltyTransaction)
class LoyaltyTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer_link', 'points_display', 'transaction_type_badge', 
                    'sale_link', 'description', 'created_at']
    list_filter = ['transaction_type', 'created_at']
    search_fields = ['customer__phone_number', 'customer__full_name', 'description']
    readonly_fields = ['customer', 'sale', 'points', 'transaction_type', 
                      'description', 'created_at', 'created_by']
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('customer', 'sale', 'points_display_detail', 'transaction_type')
        }),
        ('Description', {
            'fields': ('description',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'created_by')
        }),
    )
    
    def customer_link(self, obj):
        url = reverse('admin:sales_customer_change', args=[obj.customer.id])
        return format_html('<a href="{}">{}</a>', url, obj.customer.full_name or obj.customer.phone_number)
    customer_link.short_description = "Customer"
    
    def sale_link(self, obj):
        if obj.sale:
            url = reverse('admin:sales_sale_change', args=[obj.sale.sale_id])
            return format_html('<a href="{}">{}</a>', url, obj.sale.sale_id)
        return "-"
    sale_link.short_description = "Sale"
    
    def points_display(self, obj):
        color = 'green' if obj.points > 0 else 'orange'
        sign = '+' if obj.points > 0 else ''
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}{}</span>',
            color, sign, obj.points
        )
    points_display.short_description = "Points"
    
    def points_display_detail(self, obj):
        color = 'green' if obj.points > 0 else 'orange'
        sign = '+' if obj.points > 0 else ''
        value = obj.points if obj.points > 0 else abs(obj.points)
        return format_html(
            '<span style="color: {}; font-size: 16px; font-weight: bold;">{} {} points</span>',
            color, sign, value
        )
    points_display_detail.short_description = "Points"
    
    def transaction_type_badge(self, obj):
        colors = {
            'earned': '#28a745',
            'redeemed': '#ffc107',
            'expired': '#6c757d',
            'adjusted': '#17a2b8'
        }
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; '
            'border-radius: 20px; font-size: 11px;">{}</span>',
            colors.get(obj.transaction_type, '#6c757d'),
            'white' if obj.transaction_type in ['earned', 'expired', 'adjusted'] else 'black',
            obj.get_transaction_type_display()
        )
    transaction_type_badge.short_description = "Type"
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


# ============================================
# LOYALTY SETTINGS ADMIN
# ============================================
@admin.register(LoyaltySettings)
class LoyaltySettingsAdmin(admin.ModelAdmin):
    list_display = ['id', 'points_per_unit', 'min_purchase_for_points', 
                   'max_points_per_transaction', 'min_redeem_points', 
                   'max_redeem_percentage', 'welcome_points']
    
    fieldsets = (
        ('Points Earning', {
            'fields': ('min_purchase_for_points', 'points_per_unit', 'max_points_per_transaction')
        }),
        ('Points Redemption', {
            'fields': ('min_redeem_points', 'max_redeem_percentage')
        }),
        ('Points Expiration', {
            'fields': ('points_expiry_days',)
        }),
        ('Registration', {
            'fields': ('welcome_points', 'require_id_for_registration', 'require_email_for_registration')
        }),
    )
    
    def has_add_permission(self, request):
        # Prevent creating multiple settings instances
        if LoyaltySettings.objects.exists():
            return False
        return True
    
    def has_delete_permission(self, request, obj=None):
        return False