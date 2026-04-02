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
    CreditAccount
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
    readonly_fields = []  # Removed created_at since it doesn't exist
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
    readonly_fields = []  # Removed created_at since it doesn't exist
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
        # Only allow one bank account record
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
        # Only allow one credit account record
        if CreditAccount.objects.exists():
            return False
        return True
    
    def has_delete_permission(self, request, obj=None):
        return False