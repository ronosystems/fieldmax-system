# credit/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Sum, Q
from .models import (
    CreditCompany, CreditCustomer, CreditTransaction,
    CompanyPayment, CreditTransactionLog, SellerCommission,
    SellerCommissionSummary
)

@admin.register(CreditCompany)
class CreditCompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'email', 'phone', 'pending_amount', 'paid_amount', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'code', 'email', 'phone']
    readonly_fields = ['code', 'created_at', 'updated_at', 'pending_amount', 'paid_amount']
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'code', 'email', 'phone', 'contact_person')
        }),
        ('Address & Terms', {
            'fields': ('address', 'payment_terms')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Statistics', {
            'fields': ('pending_amount', 'paid_amount'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(CreditCustomer)
class CreditCustomerAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'id_number', 'phone_number', 'transaction_count', 'total_credit', 'is_active']
    list_filter = ['is_active', 'created_at', 'county']
    search_fields = ['full_name', 'id_number', 'phone_number', 'email']
    readonly_fields = ['created_at', 'updated_at', 'total_credit', 'transaction_count']
    fieldsets = (
        ('Personal Information', {
            'fields': ('full_name', 'id_number', 'phone_number', 'alternate_phone', 'email')
        }),
        ('Address', {
            'fields': ('county', 'town', 'physical_address')
        }),
        ('Next of Kin', {
            'fields': ('nok_name', 'nok_phone'),
            'classes': ('collapse',)
        }),
        ('Documents', {
            'fields': ('passport_photo', 'id_front_photo', 'id_back_photo', 'additional_document'),
            'classes': ('wide',)
        }),
        ('Status & Notes', {
            'fields': ('is_active', 'notes')
        }),
        ('Statistics', {
            'fields': ('total_credit', 'transaction_count'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

class CreditTransactionLogInline(admin.TabularInline):
    model = CreditTransactionLog
    extra = 0
    readonly_fields = ['action', 'performed_by', 'notes', 'created_at']
    can_delete = False

@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'transaction_id', 'customer_link', 'credit_company_link',
        'product_name', 'ceiling_price', 'commission_amount_display',
        'payment_status_colored', 'commission_status_colored',
        'transaction_date'
    ]
    list_filter = [
        'payment_status', 'commission_status', 'commission_type',
        'credit_company', 'transaction_date', 'paid_date'
    ]
    search_fields = [
        'transaction_id', 'customer__full_name', 'customer__id_number',
        'product_name', 'product_code', 'imei', 'etr_receipt_number'
    ]
    readonly_fields = [
        'transaction_id', 'etr_receipt_number', 'created_at', 'updated_at',
        'commission_amount', 'reversed_at', 'reversal_reason'
    ]
    raw_id_fields = ['customer', 'product', 'dealer', 'reversed_by', 'commission_paid_by']
    autocomplete_lookup_fields = {
        'fk': ['customer', 'product', 'dealer', 'reversed_by', 'commission_paid_by'],
    }
    inlines = [CreditTransactionLogInline]
    
    fieldsets = (
        ('Transaction Information', {
            'fields': ('transaction_id', 'etr_receipt_number', 'credit_company', 'customer', 'dealer')
        }),
        ('Product Details', {
            'fields': ('product', 'product_name', 'product_code', 'imei')
        }),
        ('Financial Details', {
            'fields': ('ceiling_price', ('commission_type', 'commission_value'), 'commission_amount')
        }),
        ('Payment Status', {
            'fields': ('payment_status', 'paid_date', 'payment_reference', 'company_reference')
        }),
        ('Commission Status', {
            'fields': ('commission_status', 'commission_paid_date', 'commission_paid_by', 'commission_notes')
        }),
        ('Reversal Information', {
            'fields': ('reversed_at', 'reversed_by', 'reversal_reason'),
            'classes': ('collapse',)
        }),
        ('Additional Info', {
            'fields': ('notes', 'transaction_date')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['mark_as_paid', 'mark_commission_paid']
    
    def customer_link(self, obj):
        url = reverse('admin:credit_creditcustomer_change', args=[obj.customer.id])
        return format_html('<a href="{}">{}</a>', url, obj.customer.full_name)
    customer_link.short_description = 'Customer'
    
    def credit_company_link(self, obj):
        url = reverse('admin:credit_creditcompany_change', args=[obj.credit_company.id])
        return format_html('<a href="{}">{}</a>', url, obj.credit_company.name)
    credit_company_link.short_description = 'Company'
    
    def commission_amount_display(self, obj):
        # FIXED: Convert to float and handle Decimal/SafeString
        try:
            amount = float(obj.commission_amount) if obj.commission_amount else 0
            return format_html('KSH {:.2f}', amount)
        except (TypeError, ValueError):
            return format_html('KSH {}', obj.commission_amount or 0)
    commission_amount_display.short_description = 'Commission'
    
    def payment_status_colored(self, obj):
        colors = {
            'pending': 'orange',
            'paid': 'green',
            'cancelled': 'red',
            'reversed': 'gray'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.payment_status, 'black'),
            obj.get_payment_status_display()
        )
    payment_status_colored.short_description = 'Payment Status'
    
    def commission_status_colored(self, obj):
        colors = {
            'pending': 'orange',
            'paid': 'green',
            'cancelled': 'red'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.commission_status, 'black'),
            obj.get_commission_status_display()
        )
    commission_status_colored.short_description = 'Commission Status'
    
    def mark_as_paid(self, request, queryset):
        for transaction in queryset.filter(payment_status='pending'):
            transaction.mark_as_paid(paid_by=request.user)
        self.message_user(request, f"{queryset.count()} transactions marked as paid.")
    mark_as_paid.short_description = "Mark selected as paid by company"
    
    def mark_commission_paid(self, request, queryset):
        for transaction in queryset.filter(commission_status='pending'):
            transaction.mark_commission_as_paid(paid_by=request.user)
        self.message_user(request, f"{queryset.count()} commissions marked as paid.")
    mark_commission_paid.short_description = "Mark selected commissions as paid"

@admin.register(SellerCommission)
class SellerCommissionAdmin(admin.ModelAdmin):
    list_display = ['seller', 'transaction_link', 'amount_display', 'status_colored', 'paid_date']
    list_filter = ['status', 'created_at', 'paid_date']
    search_fields = ['seller__username', 'seller__email', 'transaction__transaction_id']
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['seller', 'transaction', 'paid_by']
    
    def amount_display(self, obj):
        # FIXED: Add this method to display amount properly
        try:
            amount = float(obj.amount) if obj.amount else 0
            return format_html('KSH {:.2f}', amount)
        except (TypeError, ValueError):
            return format_html('KSH {}', obj.amount or 0)
    amount_display.short_description = 'Amount'
    
    def transaction_link(self, obj):
        url = reverse('admin:credit_credittransaction_change', args=[obj.transaction.id])
        return format_html('<a href="{}">{}</a>', url, obj.transaction.transaction_id)
    transaction_link.short_description = 'Transaction'
    
    def status_colored(self, obj):
        colors = {
            'pending': 'orange',
            'paid': 'green',
            'cancelled': 'red'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.status, 'black'),
            obj.get_status_display()
        )
    status_colored.short_description = 'Status'
    
    actions = ['mark_as_paid']
    
    def mark_as_paid(self, request, queryset):
        for commission in queryset.filter(status='pending'):
            commission.mark_as_paid(paid_by=request.user)
        self.message_user(request, f"{queryset.count()} commissions marked as paid.")
    mark_as_paid.short_description = "Mark selected as paid"

@admin.register(SellerCommissionSummary)
class SellerCommissionSummaryAdmin(admin.ModelAdmin):
    list_display = [
        'seller', 'total_earned', 'total_paid', 'total_pending',
        'transactions_count', 'last_paid_date'
    ]
    list_filter = ['updated_at']
    search_fields = ['seller__username', 'seller__email']
    readonly_fields = ['total_earned', 'total_paid', 'total_pending', 'updated_at']
    
    actions = ['refresh_summaries']
    
    def refresh_summaries(self, request, queryset):
        for summary in queryset:
            summary.update_from_transactions()
        self.message_user(request, f"{queryset.count()} summaries refreshed.")
    refresh_summaries.short_description = "Refresh selected summaries"

@admin.register(CompanyPayment)
class CompanyPaymentAdmin(admin.ModelAdmin):
    list_display = ['payment_id', 'credit_company', 'amount_display', 'payment_method', 'payment_date']
    list_filter = ['payment_method', 'payment_date', 'credit_company']
    search_fields = ['payment_id', 'payment_reference', 'credit_company__name']
    readonly_fields = ['payment_id', 'created_at']
    filter_horizontal = ['transactions']
    
    def amount_display(self, obj):
        # FIXED: Add this method to display amount properly
        try:
            amount = float(obj.amount) if obj.amount else 0
            return format_html('KSH {:.2f}', amount)
        except (TypeError, ValueError):
            return format_html('KSH {}', obj.amount or 0)
    amount_display.short_description = 'Amount'
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('payment_id', 'credit_company', 'amount', 'payment_method', 'payment_reference', 'payment_date')
        }),
        ('Transactions', {
            'fields': ('transactions',)
        }),
        ('Bank Details', {
            'fields': ('bank_name', 'account_number'),
            'classes': ('collapse',)
        }),
        ('Additional Info', {
            'fields': ('notes', 'created_by', 'created_at')
        }),
    )
    
    actions = ['process_payment']
    
    def process_payment(self, request, queryset):
        for payment in queryset:
            payment.process_payment()
        self.message_user(request, f"{queryset.count()} payments processed.")
    process_payment.short_description = "Process selected payments"

@admin.register(CreditTransactionLog)
class CreditTransactionLogAdmin(admin.ModelAdmin):
    list_display = ['transaction', 'action', 'performed_by', 'created_at']
    list_filter = ['action', 'created_at']
    search_fields = ['transaction__transaction_id', 'notes']
    readonly_fields = ['transaction', 'action', 'performed_by', 'notes', 'created_at']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False