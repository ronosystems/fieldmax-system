from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from .models import (
    Salary, 
    FinancialTransaction, 
    FinancialSummary,
    AccountTransaction,
    CashAccount,
    BankAccount,
    CreditAccount,
    MpesaTransaction,
    MpesaCallbackLog,
    StockPurchase,
    MoneyTransfer,
    SavingsAccount,
    SavingsTransaction,
    InjectionAccount,
    InjectionTransaction,
    NetAccount,
    NetTransaction,
    IncomeAccount,
    PurchaseAccount,
    ProfitAccount,
    IncomeTransaction,
    PurchaseTransaction,
    ProfitTransaction,
    CapitalInjection,
    CapitalInjectionRepayment,
    CapitalAccount,
    InventoryAsset,
    InventoryTransaction,
)


@admin.register(Salary)
class SalaryAdmin(admin.ModelAdmin):
    list_display = [
        'id', 
        'staff_link', 
        'get_month_display', 
        'year', 
        'base_salary', 
        'bonus', 
        'deductions',
        'total_amount', 
        'status_badge', 
        'created_at'
    ]
    list_filter = ['status', 'month', 'year', 'created_at']
    search_fields = ['staff__username', 'staff__first_name', 'staff__last_name', 'payment_reference']
    readonly_fields = ['total_amount', 'created_at', 'updated_at']
    list_per_page = 50
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Staff Information', {
            'fields': ('staff', 'month', 'year')
        }),
        ('Salary Details', {
            'fields': ('base_salary', 'bonus', 'deductions', 'total_amount')
        }),
        ('Payment Status', {
            'fields': ('status', 'payment_reference', 'paid_date', 'paid_by')
        }),
        ('Additional Information', {
            'fields': ('notes', 'created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def staff_link(self, obj):
        url = reverse('admin:auth_user_change', args=[obj.staff.id])
        return format_html('<a href="{}">{}</a>', url, obj.staff.get_full_name() or obj.staff.username)
    staff_link.short_description = 'Staff'
    
    def status_badge(self, obj):
        colors = {
            'pending': 'orange',
            'approved': 'blue',
            'paid': 'green',
            'cancelled': 'red',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    actions = ['approve_selected', 'mark_as_paid_selected']
    
    def approve_selected(self, request, queryset):
        updated = 0
        for salary in queryset.filter(status='pending'):
            salary.approve(approved_by=request.user)
            updated += 1
        self.message_user(request, f'{updated} salaries approved successfully.')
    approve_selected.short_description = 'Approve selected salaries'
    
    def mark_as_paid_selected(self, request, queryset):
        updated = 0
        for salary in queryset.filter(status='approved'):
            salary.mark_as_paid(paid_by=request.user)
            updated += 1
        self.message_user(request, f'{updated} salaries marked as paid.')
    mark_as_paid_selected.short_description = 'Mark selected as paid'


@admin.register(FinancialTransaction)
class FinancialTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 
        'transaction_type_badge', 
        'category', 
        'amount_display', 
        'description', 
        'transaction_date', 
        'payment_method', 
        'created_by_link'
    ]
    list_filter = ['transaction_type', 'category', 'payment_method', 'transaction_date']
    search_fields = ['description', 'payment_reference', 'recipient_name']
    readonly_fields = []
    list_per_page = 50
    date_hierarchy = 'transaction_date'
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('transaction_type', 'category', 'amount', 'description')
        }),
        ('Payment Information', {
            'fields': ('payment_method', 'payment_reference', 'recipient_name', 'recipient_account')
        }),
        ('Related Records', {
            'fields': ('salary', 'commission_id'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('transaction_date', 'created_by', 'notes'),
            'classes': ('collapse',)
        }),
    )
    
    def amount_display(self, obj):
        color = 'green' if obj.transaction_type == 'income' else 'red'
        prefix = '+' if obj.transaction_type == 'income' else '-'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} KES {}</span>',
            color, prefix, f'{obj.amount:,.2f}'
        )
    amount_display.short_description = 'Amount'
    
    def transaction_type_badge(self, obj):
        colors = {
            'salary': 'blue',
            'commission': 'purple',
            'expense': 'red',
            'income': 'green',
            'refund': 'orange',
        }
        color = colors.get(obj.transaction_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_transaction_type_display()
        )
    transaction_type_badge.short_description = 'Type'
    
    def created_by_link(self, obj):
        if obj.created_by:
            url = reverse('admin:auth_user_change', args=[obj.created_by.id])
            return format_html('<a href="{}">{}</a>', url, obj.created_by.username)
        return '-'
    created_by_link.short_description = 'Created By'


@admin.register(FinancialSummary)
class FinancialSummaryAdmin(admin.ModelAdmin):
    list_display = [
        'get_month_display', 
        'year', 
        'total_income_display', 
        'total_expenses_display', 
        'net_profit_display', 
        'profit_margin_display',
        'updated_at'
    ]
    list_filter = ['year', 'month']
    readonly_fields = ['updated_at']
    list_per_page = 20
    
    fieldsets = (
        ('Period', {
            'fields': ('month', 'year')
        }),
        ('Income', {
            'fields': ('total_sales_income', 'total_credit_income', 'total_income')
        }),
        ('Expenses', {
            'fields': ('total_salaries', 'total_commissions', 'total_operational_expenses', 'total_expenses')
        }),
        ('Profit', {
            'fields': ('net_profit', 'profit_margin')
        }),
    )
    
    def total_income_display(self, obj):
        return format_html('<span style="color: green; font-weight: bold;">KES {}</span>', f'{obj.total_income:,.2f}')
    total_income_display.short_description = 'Total Income'
    
    def total_expenses_display(self, obj):
        return format_html('<span style="color: red; font-weight: bold;">KES {}</span>', f'{obj.total_expenses:,.2f}')
    total_expenses_display.short_description = 'Total Expenses'
    
    def net_profit_display(self, obj):
        color = 'green' if obj.net_profit >= 0 else 'red'
        return format_html('<span style="color: {}; font-weight: bold;">KES {}</span>', color, f'{obj.net_profit:,.2f}')
    net_profit_display.short_description = 'Net Profit'
    
    def profit_margin_display(self, obj):
        color = 'green' if obj.profit_margin >= 0 else 'red'
        return format_html('<span style="color: {};">{}%</span>', color, f'{obj.profit_margin:.2f}')
    profit_margin_display.short_description = 'Profit Margin'


@admin.register(AccountTransaction)
class AccountTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 
        'account_type_badge', 
        'transaction_type_badge', 
        'amount_display', 
        'description', 
        'transaction_date', 
        'reference'
    ]
    list_filter = ['account_type', 'transaction_type', 'transaction_date']
    search_fields = ['description', 'reference', 'notes']
    readonly_fields = []
    list_per_page = 50
    date_hierarchy = 'transaction_date'
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('account_type', 'transaction_type', 'amount', 'description')
        }),
        ('Reference Information', {
            'fields': ('reference', 'notes')
        }),
        ('Transfer Information', {
            'fields': ('from_account', 'to_account'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('transaction_date', 'created_by'),
            'classes': ('collapse',)
        }),
    )
    
    def account_type_badge(self, obj):
        colors = {
            'cash': 'green',
            'bank': 'blue',
            'credit': 'orange',
        }
        color = colors.get(obj.account_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_account_type_display()
        )
    account_type_badge.short_description = 'Account'
    
    def transaction_type_badge(self, obj):
        colors = {
            'income': 'green',
            'expense': 'red',
            'transfer': 'blue',
            'adjustment': 'orange',
        }
        color = colors.get(obj.transaction_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_transaction_type_display()
        )
    transaction_type_badge.short_description = 'Type'
    
    def amount_display(self, obj):
        if obj.transaction_type == 'income':
            color = 'green'
            prefix = '+'
        elif obj.transaction_type == 'expense':
            color = 'red'
            prefix = '-'
        else:
            color = 'blue'
            prefix = '~'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} KES {}</span>',
            color, prefix, f'{obj.amount:,.2f}'
        )
    amount_display.short_description = 'Amount'


@admin.register(CashAccount)
class CashAccountAdmin(admin.ModelAdmin):
    list_display = ['balance_display', 'last_updated', 'updated_by_link']
    readonly_fields = ['balance', 'last_updated']
    
    def balance_display(self, obj):
        return format_html(
            '<span style="color: green; font-weight: bold; font-size: 1.2rem;">KES {}</span>',
            f'{obj.balance:,.2f}'
        )
    balance_display.short_description = 'Current Balance'
    
    def updated_by_link(self, obj):
        if obj.updated_by:
            url = reverse('admin:auth_user_change', args=[obj.updated_by.id])
            return format_html('<a href="{}">{}</a>', url, obj.updated_by.username)
        return '-'
    updated_by_link.short_description = 'Updated By'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ['bank_name', 'account_number', 'balance_display', 'last_updated', 'updated_by_link']
    readonly_fields = ['balance', 'last_updated']
    search_fields = ['bank_name', 'account_number', 'account_name']
    
    fieldsets = (
        ('Bank Information', {
            'fields': ('bank_name', 'account_number', 'account_name')
        }),
        ('Balance', {
            'fields': ('balance', 'last_updated', 'updated_by')
        }),
    )
    
    def balance_display(self, obj):
        return format_html(
            '<span style="color: blue; font-weight: bold; font-size: 1.2rem;">KES {}</span>',
            f'{obj.balance:,.2f}'
        )
    balance_display.short_description = 'Current Balance'
    
    def updated_by_link(self, obj):
        if obj.updated_by:
            url = reverse('admin:auth_user_change', args=[obj.updated_by.id])
            return format_html('<a href="{}">{}</a>', url, obj.updated_by.username)
        return '-'
    updated_by_link.short_description = 'Updated By'
    
    def has_add_permission(self, request):
        if BankAccount.objects.exists():
            return False
        return True
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CreditAccount)
class CreditAccountAdmin(admin.ModelAdmin):
    list_display = ['credit_limit_display', 'balance_display', 'available_credit_display', 'interest_rate', 'last_updated']
    readonly_fields = ['balance', 'last_updated']
    
    fieldsets = (
        ('Credit Information', {
            'fields': ('credit_limit', 'balance', 'interest_rate')
        }),
        ('Metadata', {
            'fields': ('last_updated', 'updated_by')
        }),
    )
    
    def credit_limit_display(self, obj):
        return format_html('<span style="color: orange;">KES {}</span>', f'{obj.credit_limit:,.2f}')
    credit_limit_display.short_description = 'Credit Limit'
    
    def balance_display(self, obj):
        color = 'red' if obj.balance > 0 else 'green'
        return format_html(
            '<span style="color: {}; font-weight: bold;">KES {}</span>',
            color, f'{obj.balance:,.2f}'
        )
    balance_display.short_description = 'Current Balance'
    
    def available_credit_display(self, obj):
        available = obj.available_credit
        color = 'green' if available > 0 else 'red'
        return format_html(
            '<span style="color: {}; font-weight: bold;">KES {}</span>',
            color, f'{available:,.2f}'
        )
    available_credit_display.short_description = 'Available Credit'
    
    def has_add_permission(self, request):
        if CreditAccount.objects.exists():
            return False
        return True
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MpesaTransaction)
class MpesaTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'amount_display', 'phone_number', 'account_reference', 
        'status_badge', 'mpesa_receipt_number', 'created_at'
    ]
    list_filter = ['status', 'created_at', 'result_code']
    search_fields = ['phone_number', 'account_reference', 'mpesa_receipt_number', 'checkout_request_id']
    readonly_fields = ['merchant_request_id', 'checkout_request_id', 'callback_raw_data']
    list_per_page = 50
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('amount', 'phone_number', 'account_reference', 'transaction_desc')
        }),
        ('M-Pesa Identifiers', {
            'fields': ('merchant_request_id', 'checkout_request_id', 'mpesa_receipt_number')
        }),
        ('Status', {
            'fields': ('status', 'result_code', 'result_desc', 'transaction_date')
        }),
        ('Related Records', {
            'fields': ('sale', 'financial_transaction', 'created_by')
        }),
        ('Raw Data', {
            'fields': ('callback_raw_data',),
            'classes': ('collapse',)
        }),
    )
    
    def amount_display(self, obj):
        return format_html('<span style="color: green; font-weight: bold;">KES {}</span>', f'{obj.amount:,.2f}')
    amount_display.short_description = 'Amount'
    
    def status_badge(self, obj):
        colors = {
            'pending': 'orange',
            'completed': 'green',
            'failed': 'red',
            'cancelled': 'gray',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'


@admin.register(MpesaCallbackLog)
class MpesaCallbackLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'checkout_request_id', 'result_code', 'result_desc', 'processed', 'created_at']
    list_filter = ['processed', 'result_code', 'created_at']
    search_fields = ['checkout_request_id', 'result_desc']
    readonly_fields = ['raw_payload', 'created_at']
    list_per_page = 50
    
    def has_add_permission(self, request):
        return False


@admin.register(StockPurchase)
class StockPurchaseAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'sku_code', 'quantity', 'unit_price', 'total_amount_display', 
        'purchase_date', 'has_financial_transaction'
    ]
    list_filter = ['purchase_date', 'created_at']
    search_fields = ['sku_code', 'product_name', 'reference_id']
    readonly_fields = ['total_amount', 'created_at']
    list_per_page = 50
    date_hierarchy = 'purchase_date'
    
    fieldsets = (
        ('Product Information', {
            'fields': ('product_name', 'sku_code', 'quantity', 'unit_price', 'total_amount')
        }),
        ('Purchase Details', {
            'fields': ('purchase_date', 'reference_id', 'notes')
        }),
        ('Related Records', {
            'fields': ('stock_entry', 'financial_transaction', 'account_transaction', 'created_by')
        }),
    )
    
    def total_amount_display(self, obj):
        return format_html('<span style="color: red; font-weight: bold;">KES {}</span>', f'{obj.total_amount:,.2f}')
    total_amount_display.short_description = 'Total Amount'
    
    def has_financial_transaction(self, obj):
        return obj.financial_transaction is not None
    has_financial_transaction.boolean = True
    has_financial_transaction.short_description = 'Has Financial Transaction'


@admin.register(MoneyTransfer)
class MoneyTransferAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'from_account_badge', 'to_account_badge', 'amount_display', 
        'description', 'status_badge', 'created_at'
    ]
    list_filter = ['from_account', 'to_account', 'status', 'created_at']
    search_fields = ['transfer_reference', 'description', 'notes']
    readonly_fields = ['transfer_reference', 'created_at', 'updated_at']
    list_per_page = 50
    
    fieldsets = (
        ('Transfer Details', {
            'fields': ('from_account', 'to_account', 'amount', 'description')
        }),
        ('Reference', {
            'fields': ('transfer_reference',)
        }),
        ('Bank Details (if applicable)', {
            'fields': ('bank_name', 'bank_account_number', 'bank_account_name'),
            'classes': ('collapse',)
        }),
        ('M-Pesa Details (if applicable)', {
            'fields': ('mpesa_phone', 'mpesa_receipt'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('status', 'completed_at', 'requested_by', 'approved_by', 'notes')
        }),
    )
    
    def from_account_badge(self, obj):
        colors = {'cash': 'green', 'bank': 'blue', 'mpesa': 'orange'}
        color = colors.get(obj.from_account, 'gray')
        return format_html('<span style="color: {};">{}</span>', color, obj.get_from_account_display())
    from_account_badge.short_description = 'From'
    
    def to_account_badge(self, obj):
        colors = {'cash': 'green', 'bank': 'blue', 'mpesa': 'orange'}
        color = colors.get(obj.to_account, 'gray')
        return format_html('<span style="color: {};">{}</span>', color, obj.get_to_account_display())
    to_account_badge.short_description = 'To'
    
    def amount_display(self, obj):
        return format_html('<span style="color: blue; font-weight: bold;">KES {}</span>', f'{obj.amount:,.2f}')
    amount_display.short_description = 'Amount'
    
    def status_badge(self, obj):
        colors = {
            'pending': 'orange',
            'completed': 'green',
            'failed': 'red',
            'cancelled': 'gray',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    actions = ['complete_transfers', 'cancel_transfers']
    
    def complete_transfers(self, request, queryset):
        updated = 0
        for transfer in queryset.filter(status='pending'):
            if transfer.complete_transfer(approved_by=request.user):
                updated += 1
        self.message_user(request, f'{updated} transfers completed successfully.')
    complete_transfers.short_description = 'Complete selected transfers'
    
    def cancel_transfers(self, request, queryset):
        updated = 0
        for transfer in queryset.filter(status='pending'):
            transfer.cancel(cancelled_by=request.user, reason="Cancelled via admin")
            updated += 1
        self.message_user(request, f'{updated} transfers cancelled.')
    cancel_transfers.short_description = 'Cancel selected transfers'


@admin.register(SavingsAccount)
class SavingsAccountAdmin(admin.ModelAdmin):
    list_display = ['balance_display', 'total_profits_earned_display', 'total_profits_taken_display', 'available_profit_display', 'last_updated']
    readonly_fields = ['balance', 'total_profits_earned', 'total_profits_taken', 'last_updated']
    
    fieldsets = (
        ('Savings Summary', {
            'fields': ('balance', 'total_profits_earned', 'total_profits_taken')
        }),
        ('Metadata', {
            'fields': ('last_updated', 'updated_by')
        }),
    )
    
    def balance_display(self, obj):
        return format_html(
            '<span style="color: green; font-weight: bold; font-size: 1.2rem;">KES {}</span>',
            f'{obj.balance:,.2f}'
        )
    balance_display.short_description = 'Current Balance'
    
    def total_profits_earned_display(self, obj):
        return format_html('<span style="color: blue;">KES {}</span>', f'{obj.total_profits_earned:,.2f}')
    total_profits_earned_display.short_description = 'Total Profits Earned'
    
    def total_profits_taken_display(self, obj):
        return format_html('<span style="color: orange;">KES {}</span>', f'{obj.total_profits_taken:,.2f}')
    total_profits_taken_display.short_description = 'Total Profits Taken'
    
    def available_profit_display(self, obj):
        return format_html(
            '<span style="color: purple; font-weight: bold;">KES {}</span>',
            f'{obj.available_profit_to_take:,.2f}'
        )
    available_profit_display.short_description = 'Available to Take'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    actions = ['take_profit_action']
    
    def take_profit_action(self, request, queryset):
        for savings in queryset:
            success, message, amount = savings.take_profit(user=request.user)
            self.message_user(request, message)
    take_profit_action.short_description = 'Take profit from selected savings account'


@admin.register(SavingsTransaction)
class SavingsTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'amount_display', 'transaction_type_badge', 'sale_reference', 'description', 'transaction_date']
    list_filter = ['transaction_type', 'transaction_date', 'created_at']
    search_fields = ['sale_reference', 'description']
    readonly_fields = ['created_at']
    list_per_page = 50
    date_hierarchy = 'transaction_date'
    
    def amount_display(self, obj):
        if obj.transaction_type == 'profit':
            color = 'green'
            prefix = '+'
        else:
            color = 'red'
            prefix = '-'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} KES {}</span>',
            color, prefix, f'{obj.amount:,.2f}'
        )
    amount_display.short_description = 'Amount'
    
    def transaction_type_badge(self, obj):
        colors = {
            'profit': 'green',
            'transfer_out': 'orange',
            'profit_taken': 'purple',
            'expense': 'red',
        }
        color = colors.get(obj.transaction_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_transaction_type_display()
        )
    transaction_type_badge.short_description = 'Type'


@admin.register(InjectionAccount)
class InjectionAccountAdmin(admin.ModelAdmin):
    list_display = ['total_injected_display', 'total_from_savings_display', 'total_external_display', 'last_updated']
    readonly_fields = ['total_injected_all_time', 'total_from_savings', 'total_external_injection', 'last_updated']
    
    fieldsets = (
        ('Injection Summary', {
            'fields': ('total_injected_all_time', 'total_from_savings', 'total_external_injection')
        }),
        ('Metadata', {
            'fields': ('last_updated', 'updated_by')
        }),
    )
    
    def total_injected_display(self, obj):
        return format_html(
            '<span style="color: green; font-weight: bold; font-size: 1.2rem;">KES {}</span>',
            f'{obj.total_injected_all_time:,.2f}'
        )
    total_injected_display.short_description = 'Total Injected All Time'
    
    def total_from_savings_display(self, obj):
        return format_html('<span style="color: blue;">KES {}</span>', f'{obj.total_from_savings:,.2f}')
    total_from_savings_display.short_description = 'From Savings'
    
    def total_external_display(self, obj):
        return format_html('<span style="color: orange;">KES {}</span>', f'{obj.total_external_injection:,.2f}')
    total_external_display.short_description = 'External Injections'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InjectionTransaction)
class InjectionTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'amount_display', 'transaction_type_badge', 'source_name', 'source_detail', 'transaction_date']
    list_filter = ['transaction_type', 'transaction_date', 'source_type']
    search_fields = ['source_name', 'source_detail', 'reference']
    readonly_fields = ['created_at']
    list_per_page = 50
    date_hierarchy = 'transaction_date'
    
    def amount_display(self, obj):
        return format_html('<span style="color: green; font-weight: bold;">+ KES {}</span>', f'{obj.amount:,.2f}')
    amount_display.short_description = 'Amount'
    
    def transaction_type_badge(self, obj):
        colors = {
            'from_savings': 'blue',
            'external': 'green',
            'transfer_to_net': 'orange',
        }
        color = colors.get(obj.transaction_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_transaction_type_display()
        )
    transaction_type_badge.short_description = 'Type'


@admin.register(NetAccount)
class NetAccountAdmin(admin.ModelAdmin):
    list_display = [
        'balance_display', 'total_additions_display', 'total_deductions_display', 
        'cash_inflow_display', 'cash_outflow_display', 'last_updated'
    ]
    readonly_fields = [
        'balance', 'total_inventory_purchases', 'total_salaries', 'total_operational_expenses',
        'total_cogs_added', 'total_injections_received', 'last_updated'
    ]
    
    fieldsets = (
        ('Net Account Balance', {
            'fields': ('balance',)
        }),
        ('Additions (Money IN)', {
            'fields': ('total_cogs_added', 'total_injections_received')
        }),
        ('Deductions (Money OUT)', {
            'fields': ('total_inventory_purchases', 'total_salaries', 'total_operational_expenses')
        }),
        ('Metadata', {
            'fields': ('last_updated', 'updated_by')
        }),
    )
    
    def balance_display(self, obj):
        color = 'green' if obj.balance >= 0 else 'red'
        return format_html(
            '<span style="color: {}; font-weight: bold; font-size: 1.2rem;">KES {}</span>',
            color, f'{obj.balance:,.2f}'
        )
    balance_display.short_description = 'Current Balance'
    
    def total_additions_display(self, obj):
        return format_html('<span style="color: green;">KES {}</span>', f'{obj.total_additions:,.2f}')
    total_additions_display.short_description = 'Total Additions'
    
    def total_deductions_display(self, obj):
        return format_html('<span style="color: red;">KES {}</span>', f'{obj.total_deductions:,.2f}')
    total_deductions_display.short_description = 'Total Deductions'
    
    def cash_inflow_display(self, obj):
        return format_html('<span style="color: blue;">KES {}</span>', f'{obj.total_cash_inflow:,.2f}')
    cash_inflow_display.short_description = 'Cash Inflow'
    
    def cash_outflow_display(self, obj):
        return format_html('<span style="color: orange;">KES {}</span>', f'{obj.total_cash_outflow:,.2f}')
    cash_outflow_display.short_description = 'Cash Outflow'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NetTransaction)
class NetTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'amount_display', 'transaction_type_badge', 'category_badge', 'reference', 'description', 'transaction_date']
    list_filter = ['transaction_type', 'category', 'transaction_date']
    search_fields = ['reference', 'description']
    readonly_fields = ['created_at']
    list_per_page = 50
    date_hierarchy = 'transaction_date'
    
    def amount_display(self, obj):
        if obj.transaction_type == 'addition':
            color = 'green'
            prefix = '+'
        else:
            color = 'red'
            prefix = '-'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} KES {}</span>',
            color, prefix, f'{obj.amount:,.2f}'
        )
    amount_display.short_description = 'Amount'
    
    def transaction_type_badge(self, obj):
        colors = {
            'addition': 'green',
            'deduction': 'red',
        }
        color = colors.get(obj.transaction_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_transaction_type_display()
        )
    transaction_type_badge.short_description = 'Type'
    
    def category_badge(self, obj):
        colors = {
            'cogs': 'green',
            'injection': 'blue',
            'inventory': 'orange',
            'salary': 'purple',
            'operational': 'red',
            'other': 'gray',
        }
        color = colors.get(obj.category, 'gray')
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_category_display()
        )
    category_badge.short_description = 'Category'


@admin.register(IncomeAccount)
class IncomeAccountAdmin(admin.ModelAdmin):
    list_display = ['balance_display', 'total_income_display', 'last_updated']
    readonly_fields = ['balance', 'total_income', 'last_updated']
    
    def balance_display(self, obj):
        return format_html(
            '<span style="color: green; font-weight: bold; font-size: 1.2rem;">KES {}</span>',
            f'{obj.balance:,.2f}'
        )
    balance_display.short_description = 'Current Balance'
    
    def total_income_display(self, obj):
        return format_html('<span style="color: blue;">KES {}</span>', f'{obj.total_income:,.2f}')
    total_income_display.short_description = 'Total Income All Time'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PurchaseAccount)
class PurchaseAccountAdmin(admin.ModelAdmin):
    list_display = ['balance_display', 'total_purchases_display', 'last_updated']
    readonly_fields = ['balance', 'total_purchases', 'last_updated']
    
    def balance_display(self, obj):
        return format_html(
            '<span style="color: orange; font-weight: bold; font-size: 1.2rem;">KES {}</span>',
            f'{obj.balance:,.2f}'
        )
    balance_display.short_description = 'Current Balance'
    
    def total_purchases_display(self, obj):
        return format_html('<span style="color: red;">KES {}</span>', f'{obj.total_purchases:,.2f}')
    total_purchases_display.short_description = 'Total Purchases All Time'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProfitAccount)
class ProfitAccountAdmin(admin.ModelAdmin):
    list_display = ['balance_display', 'total_profit_display', 'last_updated']
    readonly_fields = ['balance', 'total_profit', 'last_updated']
    
    def balance_display(self, obj):
        color = 'green' if obj.balance >= 0 else 'red'
        return format_html(
            '<span style="color: {}; font-weight: bold; font-size: 1.2rem;">KES {}</span>',
            color, f'{obj.balance:,.2f}'
        )
    balance_display.short_description = 'Current Balance'
    
    def total_profit_display(self, obj):
        color = 'green' if obj.total_profit >= 0 else 'red'
        return format_html('<span style="color: {};">KES {}</span>', color, f'{obj.total_profit:,.2f}')
    total_profit_display.short_description = 'Total Profit All Time'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IncomeTransaction)
class IncomeTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'amount_display', 'transaction_type_badge', 'reference', 'description', 'transaction_date']
    list_filter = ['transaction_type', 'transaction_date']
    search_fields = ['reference', 'description']
    readonly_fields = ['created_at']
    list_per_page = 50
    date_hierarchy = 'transaction_date'
    
    def amount_display(self, obj):
        return format_html('<span style="color: green; font-weight: bold;">+ KES {}</span>', f'{obj.amount:,.2f}')
    amount_display.short_description = 'Amount'
    
    def transaction_type_badge(self, obj):
        colors = {
            'sale': 'green',
            'credit': 'blue',
            'refund': 'orange',
            'other': 'gray',
        }
        color = colors.get(obj.transaction_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_transaction_type_display()
        )
    transaction_type_badge.short_description = 'Type'


@admin.register(PurchaseTransaction)
class PurchaseTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'amount_display', 'transaction_type_badge', 'reference', 'description', 'transaction_date']
    list_filter = ['transaction_type', 'transaction_date']
    search_fields = ['reference', 'description']
    readonly_fields = ['created_at']
    list_per_page = 50
    date_hierarchy = 'transaction_date'
    
    def amount_display(self, obj):
        return format_html('<span style="color: red; font-weight: bold;">- KES {}</span>', f'{obj.amount:,.2f}')
    amount_display.short_description = 'Amount'
    
    def transaction_type_badge(self, obj):
        colors = {
            'cogs': 'orange',
            'stock': 'red',
            'supplies': 'blue',
            'other': 'gray',
        }
        color = colors.get(obj.transaction_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_transaction_type_display()
        )
    transaction_type_badge.short_description = 'Type'


@admin.register(ProfitTransaction)
class ProfitTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'amount_display', 'transaction_type_badge', 'reference', 'description', 'transaction_date']
    list_filter = ['transaction_type', 'transaction_date']
    search_fields = ['reference', 'description']
    readonly_fields = ['created_at']
    list_per_page = 50
    date_hierarchy = 'transaction_date'
    
    def amount_display(self, obj):
        color = 'green' if obj.amount >= 0 else 'red'
        prefix = '+' if obj.amount >= 0 else '-'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} KES {}</span>',
            color, prefix, f'{abs(obj.amount):,.2f}'
        )
    amount_display.short_description = 'Amount'
    
    def transaction_type_badge(self, obj):
        colors = {
            'sale_profit': 'green',
            'adjustment': 'orange',
        }
        color = colors.get(obj.transaction_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_transaction_type_display()
        )
    transaction_type_badge.short_description = 'Type'


@admin.register(CapitalInjection)
class CapitalInjectionAdmin(admin.ModelAdmin):
    list_display = [
        'injection_id', 'source_type_badge', 'source_name', 'amount_display', 
        'payment_method', 'status_badge', 'transaction_date'
    ]
    list_filter = ['source_type', 'status', 'payment_method', 'is_loan', 'transaction_date']
    search_fields = ['injection_id', 'source_name', 'payment_reference']
    readonly_fields = ['injection_id', 'created_at', 'updated_at']
    list_per_page = 50
    date_hierarchy = 'transaction_date'
    
    fieldsets = (
        ('Injection Information', {
            'fields': ('injection_id', 'source_type', 'source_name', 'amount')
        }),
        ('Payment Details', {
            'fields': ('payment_method', 'payment_reference', 'transaction_date', 'target_account')
        }),
        ('Loan Details (if applicable)', {
            'fields': ('is_loan', 'interest_rate', 'repayment_term_months', 'monthly_repayment'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('status', 'notes')
        }),
        ('Related Records', {
            'fields': ('financial_transaction', 'account_transaction', 'created_by'),
            'classes': ('collapse',)
        }),
    )
    
    def source_type_badge(self, obj):
        colors = {
            'investor': 'green',
            'loan': 'red',
            'personal': 'blue',
            'grant': 'purple',
            'partner': 'orange',
            'other': 'gray',
        }
        color = colors.get(obj.source_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_source_type_display()
        )
    source_type_badge.short_description = 'Source Type'
    
    def amount_display(self, obj):
        return format_html('<span style="color: green; font-weight: bold;">KES {}</span>', f'{obj.amount:,.2f}')
    amount_display.short_description = 'Amount'
    
    def status_badge(self, obj):
        colors = {
            'pending': 'orange',
            'completed': 'green',
            'cancelled': 'red',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    actions = ['process_injections']
    
    def process_injections(self, request, queryset):
        updated = 0
        for injection in queryset.filter(status='pending'):
            if injection.process_injection(user=request.user):
                updated += 1
        self.message_user(request, f'{updated} capital injections processed successfully.')
    process_injections.short_description = 'Process selected injections'


@admin.register(CapitalInjectionRepayment)
class CapitalInjectionRepaymentAdmin(admin.ModelAdmin):
    list_display = ['id', 'capital_injection_link', 'amount_display', 'payment_date', 'payment_reference']
    list_filter = ['payment_date', 'created_at']
    search_fields = ['payment_reference', 'notes']
    readonly_fields = ['created_at']
    list_per_page = 50
    date_hierarchy = 'payment_date'
    
    def capital_injection_link(self, obj):
        url = reverse('admin:finance_capitalinjection_change', args=[obj.capital_injection.id])
        return format_html('<a href="{}">{}</a>', url, obj.capital_injection.injection_id)
    capital_injection_link.short_description = 'Capital Injection'
    
    def amount_display(self, obj):
        return format_html('<span style="color: red; font-weight: bold;">KES {}</span>', f'{obj.amount:,.2f}')
    amount_display.short_description = 'Amount'


@admin.register(CapitalAccount)
class CapitalAccountAdmin(admin.ModelAdmin):
    list_display = [
        'net_capital_display', 'total_injected_display', 'total_repayments_display',
        'total_purchases_display', 'total_sales_display', 'last_updated'
    ]
    readonly_fields = [
        'total_capital_injected', 'total_loan_repayments', 'total_purchases',
        'total_sales_revenue', 'net_capital', 'last_updated'
    ]
    
    fieldsets = (
        ('Capital Summary', {
            'fields': ('net_capital',)
        }),
        ('Breakdown', {
            'fields': ('total_capital_injected', 'total_loan_repayments', 'total_purchases', 'total_sales_revenue')
        }),
        ('Metadata', {
            'fields': ('last_updated', 'updated_by')
        }),
    )
    
    def net_capital_display(self, obj):
        color = 'green' if obj.net_capital >= 0 else 'red'
        return format_html(
            '<span style="color: {}; font-weight: bold; font-size: 1.2rem;">KES {}</span>',
            color, f'{obj.net_capital:,.2f}'
        )
    net_capital_display.short_description = 'Net Capital'
    
    def total_injected_display(self, obj):
        return format_html('<span style="color: green;">KES {}</span>', f'{obj.total_capital_injected:,.2f}')
    total_injected_display.short_description = 'Total Injected'
    
    def total_repayments_display(self, obj):
        return format_html('<span style="color: red;">KES {}</span>', f'{obj.total_loan_repayments:,.2f}')
    total_repayments_display.short_description = 'Total Repayments'
    
    def total_purchases_display(self, obj):
        return format_html('<span style="color: orange;">KES {}</span>', f'{obj.total_purchases:,.2f}')
    total_purchases_display.short_description = 'Total Purchases'
    
    def total_sales_display(self, obj):
        return format_html('<span style="color: blue;">KES {}</span>', f'{obj.total_sales_revenue:,.2f}')
    total_sales_display.short_description = 'Total Sales Revenue'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    actions = ['refresh_capital']
    
    def refresh_capital(self, request, queryset):
        for capital in queryset:
            capital.refresh_from_db()
        self.message_user(request, 'Capital accounts refreshed successfully.')
    refresh_capital.short_description = 'Refresh capital calculations'


@admin.register(InventoryAsset)
class InventoryAssetAdmin(admin.ModelAdmin):
    list_display = [
        'current_value_display', 'total_purchased_display', 'total_cogs_display', 
        'profit_realized_display', 'last_updated'
    ]
    readonly_fields = ['current_value', 'total_purchased', 'total_cogs', 'last_updated']
    
    fieldsets = (
        ('Inventory Value', {
            'fields': ('current_value',)
        }),
        ('Summary', {
            'fields': ('total_purchased', 'total_cogs')
        }),
        ('Metadata', {
            'fields': ('last_updated', 'updated_by')
        }),
    )
    
    def current_value_display(self, obj):
        return format_html(
            '<span style="color: green; font-weight: bold; font-size: 1.2rem;">KES {}</span>',
            f'{obj.current_value:,.2f}'
        )
    current_value_display.short_description = 'Current Inventory Value'
    
    def total_purchased_display(self, obj):
        return format_html('<span style="color: blue;">KES {}</span>', f'{obj.total_purchased:,.2f}')
    total_purchased_display.short_description = 'Total Purchased (All Time)'
    
    def total_cogs_display(self, obj):
        return format_html('<span style="color: orange;">KES {}</span>', f'{obj.total_cogs:,.2f}')
    total_cogs_display.short_description = 'Total COGS (Sold)'
    
    def profit_realized_display(self, obj):
        profit = obj.profit_realized_from_inventory
        color = 'green' if profit >= 0 else 'red'
        return format_html(
            '<span style="color: {}; font-weight: bold;">KES {}</span>',
            color, f'{profit:,.2f}'
        )
    profit_realized_display.short_description = 'Profit Realized'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    actions = ['refresh_inventory_value']
    
    def refresh_inventory_value(self, request, queryset):
        for asset in queryset:
            asset.refresh_from_inventory()
        self.message_user(request, 'Inventory values refreshed successfully.')
    refresh_inventory_value.short_description = 'Refresh from actual inventory'


@admin.register(InventoryTransaction)
class InventoryTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'amount_display', 'transaction_type_badge', 'sku_code', 
        'quantity', 'unit_price', 'transaction_date'
    ]
    list_filter = ['transaction_type', 'transaction_date']
    search_fields = ['sku_code', 'sale_reference', 'description']
    readonly_fields = ['created_at']
    list_per_page = 50
    date_hierarchy = 'transaction_date'
    
    def amount_display(self, obj):
        if obj.transaction_type == 'purchase':
            color = 'green'
            prefix = '+'
        elif obj.transaction_type == 'cogs':
            color = 'red'
            prefix = '-'
        elif obj.transaction_type == 'adjustment_increase':
            color = 'blue'
            prefix = '+'
        else:
            color = 'orange'
            prefix = '-'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} KES {}</span>',
            color, prefix, f'{obj.amount:,.2f}'
        )
    amount_display.short_description = 'Amount'
    
    def transaction_type_badge(self, obj):
        colors = {
            'purchase': 'green',
            'cogs': 'red',
            'adjustment_increase': 'blue',
            'adjustment_decrease': 'orange',
        }
        color = colors.get(obj.transaction_type, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_transaction_type_display()
        )
    transaction_type_badge.short_description = 'Type'