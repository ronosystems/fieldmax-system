from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Sum
from django.utils import timezone
from .models import (
    DynamicChoice, ShopBranch, MpesaAccount, MpesaDailyBalance,
    BankAccount, BankDailyBalance, CashAccount, CashDailyBalance,
    ShopExpense, DailyShopReport, DailyMpesaAccountReport,
    ShopConfiguration, BankClosingBalance
)


@admin.register(DynamicChoice)
class DynamicChoiceAdmin(admin.ModelAdmin):
    list_display = ['choice_type', 'value', 'is_active', 'created_by', 'created_at']
    list_filter = ['choice_type', 'is_active', 'created_at']
    search_fields = ['value', 'choice_type']
    list_editable = ['is_active']
    list_per_page = 50
    
    fieldsets = (
        ('Choice Information', {
            'fields': ('choice_type', 'value', 'is_active')
        }),
        ('Audit Information', {
            'fields': ('created_by',),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not obj.pk:  # Only set created_by on creation
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ShopBranch)
class ShopBranchAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'location', 'manager', 'phone', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'code', 'location', 'manager', 'phone']
    list_editable = ['is_active']
    list_per_page = 50
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'code', 'location', 'is_active')
        }),
        ('Contact Information', {
            'fields': ('manager', 'phone', 'email')
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('mpesa_accounts', 'bank_accounts')
    
    def mpesa_accounts_count(self, obj):
        return obj.mpesa_accounts.count()
    mpesa_accounts_count.short_description = 'M-Pesa Accounts'


@admin.register(MpesaAccount)
class MpesaAccountAdmin(admin.ModelAdmin):
    list_display = [
        'shop', 'account_name', 'account_number', 'account_type', 
        'current_balance', 'status', 'assigned_user', 'is_active'
    ]
    list_filter = ['shop', 'account_type', 'status', 'is_active', 'created_at']
    search_fields = ['account_name', 'account_number', 'phone_number', 'shop__name']
    list_editable = ['status', 'is_active']
    list_select_related = ['shop', 'assigned_user', 'created_by', 'last_modified_by']
    list_per_page = 50
    readonly_fields = [
        'total_deposit_count', 'total_withdrawal_count', 'total_sale_count',
        'total_deposit_amount', 'total_withdrawal_amount', 'total_sale_amount',
        'created_at', 'updated_at'
    ]
    
    fieldsets = (
        ('Account Information', {
            'fields': ('shop', 'account_name', 'account_number', 'account_type', 'store_number')
        }),
        ('Balance Information', {
            'fields': ('opening_balance', 'current_balance', 'daily_limit', 'per_transaction_limit')
        }),
        ('Contact & Assignment', {
            'fields': ('assigned_user', 'phone_number')
        }),
        ('Business Hours', {
            'fields': ('business_hours_start', 'business_hours_end'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('status', 'is_active')
        }),
        ('Transaction Counters', {
            'fields': (
                'total_deposit_count', 'total_deposit_amount',
                'total_withdrawal_count', 'total_withdrawal_amount',
                'total_sale_count', 'total_sale_amount'
            ),
            'classes': ('collapse',)
        }),
        ('Additional Information', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Audit Information', {
            'fields': ('created_by', 'last_modified_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not obj.pk:  # Only set created_by on creation
            obj.created_by = request.user
        else:
            obj.last_modified_by = request.user
        super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('shop', 'assigned_user')


@admin.register(MpesaDailyBalance)
class MpesaDailyBalanceAdmin(admin.ModelAdmin):
    list_display = [
        'mpesa_account', 'report_date', 'total_opening', 'total_closing', 
        'net_change', 'is_reconciled', 'reconciled_by'
    ]
    list_filter = ['is_reconciled', 'report_date', 'mpesa_account__shop']
    search_fields = ['mpesa_account__account_name', 'notes']
    readonly_fields = ['created_at', 'total_opening', 'total_closing', 'net_change']
    list_select_related = ['mpesa_account', 'reconciled_by']
    list_per_page = 50
    
    fieldsets = (
        ('Account Information', {
            'fields': ('mpesa_account', 'report_date')
        }),
        ('Opening Balances', {
            'fields': ('opening_mpesa_float', 'opening_airtel_float', 'opening_cash')
        }),
        ('Closing Balances', {
            'fields': ('closing_mpesa_float', 'closing_airtel_float', 'closing_cash')
        }),
        ('Transaction Summary', {
            'fields': ('total_deposits', 'total_withdrawals', 'transaction_count')
        }),
        ('Variances', {
            'fields': ('mpesa_variance', 'airtel_variance', 'cash_variance')
        }),
        ('Reconciliation', {
            'fields': ('is_reconciled', 'reconciled_by', 'reconciled_at')
        }),
        ('Additional Information', {
            'fields': ('notes', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if obj.is_reconciled and not obj.reconciled_by:
            obj.reconciled_by = request.user
            obj.reconciled_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ['shop', 'bank_name', 'account_name', 'account_number', 'current_balance', 'is_active']
    list_filter = ['shop', 'bank_name', 'is_active']
    search_fields = ['bank_name', 'account_name', 'account_number', 'shop__name']
    list_editable = ['is_active']
    list_select_related = ['shop']
    list_per_page = 50
    
    fieldsets = (
        ('Account Information', {
            'fields': ('shop', 'bank_name', 'account_name', 'account_number')
        }),
        ('Balance Information', {
            'fields': ('opening_balance', 'current_balance')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Audit Information', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(BankDailyBalance)
class BankDailyBalanceAdmin(admin.ModelAdmin):
    list_display = [
        'bank_account', 'report_date', 'opening_balance', 'closing_balance', 
        'net_change', 'variance', 'is_reconciled'
    ]
    list_filter = ['is_reconciled', 'report_date', 'bank_account__shop']
    search_fields = ['bank_account__bank_name', 'bank_account__account_number', 'notes']
    list_select_related = ['bank_account', 'reconciled_by']
    readonly_fields = ['created_at', 'net_change']
    list_per_page = 50
    
    fieldsets = (
        ('Account Information', {
            'fields': ('bank_account', 'report_date')
        }),
        ('Balance Information', {
            'fields': ('opening_balance', 'closing_balance')
        }),
        ('Transaction Summary', {
            'fields': ('total_deposits', 'total_withdrawals', 'transaction_count')
        }),
        ('Reconciliation', {
            'fields': ('variance', 'is_reconciled', 'reconciled_by', 'reconciled_at')
        }),
        ('Additional Information', {
            'fields': ('notes', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if obj.is_reconciled and not obj.reconciled_by:
            obj.reconciled_by = request.user
            obj.reconciled_at = timezone.now()
        super().save_model(request, obj, form, change)


@admin.register(CashAccount)
class CashAccountAdmin(admin.ModelAdmin):
    list_display = ['shop', 'account_name', 'currency', 'current_balance', 'is_active']
    list_filter = ['shop', 'is_active', 'currency']
    search_fields = ['account_name', 'shop__name']
    list_editable = ['is_active']
    list_select_related = ['shop']
    list_per_page = 50
    
    fieldsets = (
        ('Account Information', {
            'fields': ('shop', 'account_name', 'currency')
        }),
        ('Balance Information', {
            'fields': ('opening_balance', 'current_balance')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Audit Information', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(CashDailyBalance)
class CashDailyBalanceAdmin(admin.ModelAdmin):
    list_display = [
        'cash_account', 'report_date', 'opening_balance', 'closing_balance', 
        'net_change', 'cash_in', 'cash_out', 'variance', 'is_reconciled'
    ]
    list_filter = ['is_reconciled', 'report_date', 'cash_account__shop']
    search_fields = ['cash_account__account_name', 'notes']
    list_select_related = ['cash_account', 'reconciled_by']
    readonly_fields = ['created_at', 'net_change']
    list_per_page = 50
    
    fieldsets = (
        ('Account Information', {
            'fields': ('cash_account', 'report_date')
        }),
        ('Balance Information', {
            'fields': ('opening_balance', 'closing_balance')
        }),
        ('Transaction Summary', {
            'fields': ('cash_in', 'cash_out', 'transaction_count')
        }),
        ('Reconciliation', {
            'fields': ('variance', 'is_reconciled', 'reconciled_by', 'reconciled_at')
        }),
        ('Additional Information', {
            'fields': ('notes', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if obj.is_reconciled and not obj.reconciled_by:
            obj.reconciled_by = request.user
            obj.reconciled_at = timezone.now()
        super().save_model(request, obj, form, change)


class ShopExpenseInline(admin.TabularInline):
    model = ShopExpense
    extra = 1
    fields = ['expense_category', 'description', 'amount', 'payment_method', 'receipt_number']
    raw_id_fields = ['mpesa_account', 'bank_account', 'cash_account']


class DailyMpesaAccountReportInline(admin.TabularInline):
    model = DailyMpesaAccountReport
    extra = 1
    fields = ['mpesa_account', 'closing_mpesa_float', 'closing_airtel_float', 'closing_cash', 'transaction_count', 'total_amount']
    raw_id_fields = ['mpesa_account']
    show_change_link = True


class BankClosingBalanceInline(admin.TabularInline):
    model = BankClosingBalance
    extra = 1
    fields = ['bank_account', 'closing_balance']
    raw_id_fields = ['bank_account']


@admin.register(DailyShopReport)
class DailyShopReportAdmin(admin.ModelAdmin):
    list_display = [
        'shop', 'report_date', 'submitted_by', 'total_mpesa_amount', 
        'total_expenses', 'total_closing_balance', 'is_finalized', 
        'finalized_by', 'submission_time'
    ]
    list_filter = ['is_finalized', 'report_date', 'shop', 'submission_time']
    search_fields = ['shop__name', 'notes', 'submitted_by__username']
    readonly_fields = [
        'submission_time', 'last_modified', 'total_mpesa_amount', 
        'total_expenses', 'total_closing_balance', 'cash_balance'
    ]
    list_select_related = ['shop', 'submitted_by', 'finalized_by']
    list_per_page = 50
    inlines = [ShopExpenseInline, DailyMpesaAccountReportInline, BankClosingBalanceInline]
    
    fieldsets = (
        ('Report Information', {
            'fields': ('shop', 'report_date', 'submitted_by')
        }),
        ('Financial Summary', {
            'fields': (
                'total_mpesa_transactions', 'total_mpesa_amount',
                'total_expenses', 'cash_balance', 'total_closing_balance'
            )
        }),
        ('Finalization', {
            'fields': ('is_finalized', 'finalized_by', 'finalized_at')
        }),
        ('Additional Information', {
            'fields': ('notes', 'submission_time', 'last_modified'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not obj.pk:  # Only set submitted_by on creation
            obj.submitted_by = request.user
        if obj.is_finalized and not obj.finalized_by:
            obj.finalized_by = request.user
            obj.finalized_at = timezone.now()
        super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('shop', 'submitted_by', 'finalized_by')
    
    def get_readonly_fields(self, request, obj=None):
        if obj and obj.is_finalized:
            # Make all fields readonly if report is finalized
            return [f.name for f in self.model._meta.fields] + ['total_mpesa_amount', 'total_expenses', 'total_closing_balance', 'cash_balance']
        return self.readonly_fields


@admin.register(DailyMpesaAccountReport)
class DailyMpesaAccountReportAdmin(admin.ModelAdmin):
    list_display = [
        'daily_report', 'mpesa_account', 'total_closing', 
        'transaction_count', 'total_amount', 'created_at'
    ]
    list_filter = ['daily_report__shop', 'daily_report__report_date', 'created_at']
    search_fields = ['mpesa_account__account_name', 'notes']
    list_select_related = ['daily_report', 'daily_report__shop', 'mpesa_account']
    readonly_fields = ['created_at', 'total_closing']
    list_per_page = 50
    
    fieldsets = (
        ('Report Information', {
            'fields': ('daily_report', 'mpesa_account')
        }),
        ('Closing Balances', {
            'fields': ('closing_mpesa_float', 'closing_airtel_float', 'closing_cash')
        }),
        ('Transaction Summary', {
            'fields': ('transaction_count', 'total_amount')
        }),
        ('Additional Information', {
            'fields': ('notes', 'created_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(ShopConfiguration)
class ShopConfigurationAdmin(admin.ModelAdmin):
    list_display = ['shop', 'config_type', 'config_key', 'config_value', 'updated_at']
    list_filter = ['config_type', 'shop', 'updated_at']
    search_fields = ['config_key', 'config_value', 'shop__name']
    list_editable = ['config_value']
    list_select_related = ['shop', 'updated_by']
    list_per_page = 50
    
    fieldsets = (
        ('Configuration Information', {
            'fields': ('shop', 'config_type', 'config_key', 'config_value')
        }),
        ('Additional Information', {
            'fields': ('description', 'updated_by'),
            'classes': ('collapse',)
        }),
        ('Audit Information', {
            'fields': ('updated_at',),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(BankClosingBalance)
class BankClosingBalanceAdmin(admin.ModelAdmin):
    list_display = ['daily_report', 'bank_account', 'closing_balance', 'is_active']
    list_filter = ['is_active', 'daily_report__shop', 'daily_report__report_date']
    search_fields = ['bank_account__bank_name', 'bank_account__account_number']
    list_select_related = ['daily_report', 'daily_report__shop', 'bank_account']
    list_editable = ['is_active']
    list_per_page = 50
    
    fieldsets = (
        ('Report Information', {
            'fields': ('daily_report', 'bank_account')
        }),
        ('Balance Information', {
            'fields': ('closing_balance', 'is_active')
        }),
    )


# Custom admin site header
admin.site.site_header = 'Shop Management System Administration'
admin.site.site_title = 'Shop Management Admin'
admin.site.index_title = 'Welcome to Shop Management System'