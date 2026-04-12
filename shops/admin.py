# shops/admin.py
from django.contrib import admin
from django import forms
from django.contrib import messages
from django.utils import timezone
from .models import (
    ShopBranch, BankAccount, MpesaAccount, DailyShopReport,
    BankClosingBalance, ShopExpense, MpesaDailySummary, DynamicChoice, ShopConfiguration
)


# ==================== DYNAMIC CHOICES ADMIN ====================
@admin.register(DynamicChoice)
class DynamicChoiceAdmin(admin.ModelAdmin):
    list_display = ['choice_type', 'value', 'is_active', 'created_by', 'created_at']
    list_filter = ['choice_type', 'is_active']
    search_fields = ['value']
    list_editable = ['is_active']
    list_per_page = 25
    readonly_fields = ['created_at']  # Make created_at readonly
    
    fieldsets = (
        ('Choice Information', {
            'fields': ('choice_type', 'value')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:  # Only set created_by on creation
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


# ==================== SHOP BRANCH ADMIN ====================
@admin.register(ShopBranch)
class ShopBranchAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'location', 'manager', 'phone', 'is_active', 'opening_date']
    list_filter = ['is_active', 'opening_date']
    search_fields = ['name', 'code', 'location', 'manager', 'phone']
    list_editable = ['is_active']
    list_per_page = 25
    readonly_fields = ['opening_date']  # Make opening_date readonly
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'code', 'location')
        }),
        ('Contact Information', {
            'fields': ('manager', 'phone', 'email')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('System', {
            'fields': ('opening_date',),
            'classes': ('collapse',)
        }),
    )


# ==================== BANK ACCOUNT ADMIN ====================
@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ['shop', 'bank_name', 'account_name', 'account_number', 'is_active', 'created_at']
    list_filter = ['shop', 'bank_name', 'is_active']
    search_fields = ['bank_name', 'account_name', 'account_number']
    list_editable = ['is_active']
    list_per_page = 25
    readonly_fields = ['created_at']  # Make created_at readonly
    
    fieldsets = (
        ('Bank Details', {
            'fields': ('shop', 'bank_name', 'account_name', 'account_number')
        }),
        ('Financial', {
            'fields': ('opening_balance',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('System', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


# ==================== M-PESA ACCOUNT ADMIN ====================
@admin.register(MpesaAccount)
class MpesaAccountAdmin(admin.ModelAdmin):
    list_display = ['shop', 'account_name', 'account_number', 'account_type', 'phone_number', 'is_active', 'created_date']
    list_filter = ['shop', 'account_type', 'is_active']
    search_fields = ['account_name', 'account_number', 'phone_number']
    list_editable = ['is_active']
    list_per_page = 25
    readonly_fields = ['created_date']  # Make created_date readonly
    
    fieldsets = (
        ('Account Details', {
            'fields': ('shop', 'account_name', 'account_number', 'account_type')
        }),
        ('Contact', {
            'fields': ('phone_number',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('System', {
            'fields': ('created_date',),
            'classes': ('collapse',)
        }),
    )


# ==================== BANK CLOSING BALANCE INLINE ====================
class BankClosingBalanceInline(admin.TabularInline):
    model = BankClosingBalance
    extra = 1
    fields = ['bank_account', 'closing_balance', 'is_active']
    show_change_link = True
    classes = ['collapse']


# ==================== SHOP EXPENSE INLINE ====================
class ShopExpenseInline(admin.TabularInline):
    model = ShopExpense
    extra = 1
    fields = ['description', 'amount', 'payment_method', 'receipt_number']
    show_change_link = True
    classes = ['collapse']


# ==================== DAILY SHOP REPORT ADMIN ====================
@admin.register(DailyShopReport)
class DailyShopReportAdmin(admin.ModelAdmin):
    list_display = ['shop', 'report_date', 'submitted_by', 'shop_sales', 'total_expenses', 'total_closing_balance', 'is_finalized', 'submission_time']
    list_filter = ['shop', 'is_finalized', 'report_date', 'submission_time']
    search_fields = ['shop__name', 'submitted_by__username', 'notes']
    list_per_page = 25
    readonly_fields = ['submission_time', 'last_modified', 'total_closing_balance', 'total_expenses', 'finalized_at']  # Add readonly fields
    
    inlines = [BankClosingBalanceInline, ShopExpenseInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('shop', 'report_date', 'submitted_by')
        }),
        ('M-Pesa Balances', {
            'fields': ('closing_mpesa_float', 'closing_mpesa_cash')
        }),
        ('Transactions', {
            'fields': ('shop_sales',)
        }),
        ('Financial Summary', {
            'fields': ('total_expenses', 'total_closing_balance')
        }),
        ('Status', {
            'fields': ('is_finalized', 'finalized_by', 'finalized_at')
        }),
        ('Additional Info', {
            'fields': ('notes',)
        }),
        ('Timestamps', {
            'fields': ('submission_time', 'last_modified'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            return qs.filter(submitted_by=request.user)
        return qs
    
    def save_model(self, request, obj, form, change):
        if not change:  # Only set submitted_by on creation
            obj.submitted_by = request.user
        super().save_model(request, obj, form, change)
    
    actions = ['finalize_reports', 'unfinalize_reports']
    
    def finalize_reports(self, request, queryset):
        updated = queryset.update(is_finalized=True, finalized_by=request.user, finalized_at=timezone.now())
        self.message_user(request, f'{updated} report(s) finalized successfully.', messages.SUCCESS)
    finalize_reports.short_description = "Finalize selected reports"
    
    def unfinalize_reports(self, request, queryset):
        updated = queryset.update(is_finalized=False, finalized_by=None, finalized_at=None)
        self.message_user(request, f'{updated} report(s) unfinalized successfully.', messages.SUCCESS)
    unfinalize_reports.short_description = "Unfinalize selected reports"


# ==================== BANK CLOSING BALANCE ADMIN ====================
@admin.register(BankClosingBalance)
class BankClosingBalanceAdmin(admin.ModelAdmin):
    list_display = ['daily_report', 'bank_account', 'closing_balance', 'is_active']
    list_filter = ['daily_report__shop', 'bank_account', 'is_active']
    search_fields = ['daily_report__shop__name', 'bank_account__bank_name']
    list_per_page = 25
    
    fieldsets = (
        ('Report Information', {
            'fields': ('daily_report',)
        }),
        ('Bank Details', {
            'fields': ('bank_account',)
        }),
        ('Balance', {
            'fields': ('closing_balance',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )


# ==================== SHOP EXPENSE ADMIN ====================
@admin.register(ShopExpense)
class ShopExpenseAdmin(admin.ModelAdmin):
    list_display = ['daily_report', 'description', 'amount', 'payment_method', 'created_at']
    list_filter = ['daily_report__shop', 'payment_method', 'created_at']
    search_fields = ['description', 'receipt_number']
    list_per_page = 25
    readonly_fields = ['created_at']  # Make created_at readonly
    
    fieldsets = (
        ('Report Information', {
            'fields': ('daily_report',)
        }),
        ('Expense Details', {
            'fields': ('expense_category', 'description', 'amount')
        }),
        ('Payment Information', {
            'fields': ('payment_method', 'receipt_number')
        }),
        ('System', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


# ==================== M-PESA DAILY SUMMARY ADMIN ====================
@admin.register(MpesaDailySummary)
class MpesaDailySummaryAdmin(admin.ModelAdmin):
    list_display = ['shop', 'report_date', 'closing_float', 'closing_cash', 'is_reconciled']
    list_filter = ['shop', 'is_reconciled', 'report_date']
    search_fields = ['shop__name']
    list_per_page = 25
    readonly_fields = ['float_variance', 'cash_variance', 'reconciliation_date']  # Add readonly fields
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('shop', 'report_date', 'daily_report')
        }),
        ('Float Summary', {
            'fields': ('opening_float', 'float_added', 'float_withdrawn', 'customer_payments', 'cash_out_amount', 'closing_float')
        }),
        ('Cash Summary', {
            'fields': ('opening_cash', 'cash_sales', 'cash_expenses', 'cash_withdrawn', 'closing_cash')
        }),
        ('Reconciliation', {
            'fields': ('expected_float', 'float_variance', 'expected_cash', 'cash_variance', 'is_reconciled', 'reconciled_by', 'reconciliation_date')
        }),
        ('Additional Info', {
            'fields': ('notes',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if 'is_reconciled' in form.changed_data and obj.is_reconciled and not obj.reconciled_by:
            obj.reconciled_by = request.user
            obj.reconciliation_date = timezone.now()
        super().save_model(request, obj, form, change)


# ==================== SHOP CONFIGURATION ADMIN ====================
@admin.register(ShopConfiguration)
class ShopConfigurationAdmin(admin.ModelAdmin):
    list_display = ['shop', 'config_key', 'updated_at']
    list_filter = ['shop']
    search_fields = ['shop__name', 'config_key']
    list_per_page = 25
    readonly_fields = ['updated_at']  # Make updated_at readonly
    
    fieldsets = (
        ('Configuration', {
            'fields': ('shop', 'config_key', 'config_value')
        }),
        ('System', {
            'fields': ('updated_at',),
            'classes': ('collapse',)
        }),
    )