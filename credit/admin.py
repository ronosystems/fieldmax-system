from django.db import models
from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.contrib.auth import get_user_model
from inventory.models import Product
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.db.models import Sum, Count, Q
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.db import transaction as db_transaction
from django.contrib import messages
from django.http import HttpResponseRedirect
from .models import (
    CreditCompany, CreditCustomer, CreditTransaction, 
    CompanyPayment, CreditTransactionLog
)

@admin.register(CreditCompany)
class CreditCompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'phone', 'email', 'pending_amount_display', 'transaction_count', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'code', 'email', 'phone']
    readonly_fields = ['code', 'created_at', 'updated_at', 'pending_amount', 'paid_amount']
    
    fieldsets = (
        ('Company Information', {
            'fields': ('name', 'code', 'email', 'phone', 'contact_person', 'address')
        }),
        ('Business Details', {
            'fields': ('payment_terms', 'is_active')
        }),
        ('Financial Summary', {
            'fields': ('pending_amount', 'paid_amount'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at', 'created_by'),
            'classes': ('collapse',)
        }),
    )
    
    def pending_amount_display(self, obj):
        return format_html(
            '<span style="color: {}; font-weight: bold;">KSH {}</span>',
            '#e74c3c' if obj.pending_amount > 0 else '#2ecc71',
            obj.pending_amount
        )
    pending_amount_display.short_description = 'Pending Amount'
    
    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(CreditCustomer)
class CreditCustomerAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'id_number', 'phone_number', 'total_credit_display', 'transaction_count', 'created_at']
    list_filter = ['is_active', 'county']
    search_fields = ['full_name', 'id_number', 'phone_number', 'email']
    readonly_fields = ['created_at', 'updated_at', 'total_credit']
    
    fieldsets = (
        ('Personal Information', {
            'fields': ('full_name', 'id_number', 'phone_number', 'email', 'alternate_phone')
        }),
        ('Address', {
            'fields': ('county', 'town', 'physical_address')
        }),
        ('Next of Kin', {
            'fields': ('nok_name', 'nok_phone')
        }),
        ('Status', {
            'fields': ('is_active', 'notes')
        }),
        ('Financial Summary', {
            'fields': ('total_credit',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at', 'created_by'),
            'classes': ('collapse',)
        }),
    )
    
    def total_credit_display(self, obj):
        return format_html(
            '<span style="color: #e67e22; font-weight: bold;">KSH {}</span>',
            obj.total_credit
        )
    total_credit_display.short_description = 'Total Credit'


class CreditTransactionLogInline(admin.TabularInline):
    model = CreditTransactionLog
    extra = 0
    readonly_fields = ['action', 'performed_by', 'notes', 'created_at']
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = ['transaction_id', 'customer_link', 'credit_company_link', 'product_link', 
                    'ceiling_price_display', 'payment_status_badge', 'transaction_date']
    list_filter = ['payment_status', 'credit_company', 'transaction_date']
    search_fields = ['transaction_id', 'customer__full_name', 'customer__id_number', 
                    'product__product_code', 'imei']
    readonly_fields = ['transaction_id', 'etr_receipt_number', 'created_at', 'updated_at', 
                       'days_since_given_display']
    inlines = [CreditTransactionLogInline]
    
    fieldsets = (
        ('Transaction Information', {
            'fields': ('transaction_id', 'etr_receipt_number', 'credit_company', 'customer', 'dealer')
        }),
        ('Product Details', {
            'fields': ('product', 'product_name', 'product_code', 'imei')
        }),
        ('Financial Details', {
            'fields': ('ceiling_price', 'payment_status', 'paid_date', 'payment_reference')
        }),
        ('References', {
            'fields': ('company_reference', 'notes')
        }),
        ('Dates', {
            'fields': ('transaction_date', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def customer_link(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            f'/admin/credit/creditcustomer/{obj.customer.id}/change/',
            obj.customer.full_name
        )
    customer_link.short_description = 'Customer'
    
    def credit_company_link(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            f'/admin/credit/creditcompany/{obj.credit_company.id}/change/',
            obj.credit_company.name
        )
    credit_company_link.short_description = 'Company'
    
    def product_link(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            f'/admin/inventory/product/{obj.product.id}/change/',
            obj.product.product_code
        )
    product_link.short_description = 'Product'
    
    def ceiling_price_display(self, obj):
        return f"KSH {obj.ceiling_price:,.0f}"
    ceiling_price_display.short_description = 'Ceiling Price'
    
    def payment_status_badge(self, obj):
        colors = {
            'pending': '#e74c3c',
            'paid': '#2ecc71',
            'cancelled': '#95a5a6',
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 10px;">{}</span>',
            colors.get(obj.payment_status, '#95a5a6'),
            obj.get_payment_status_display()
        )
    payment_status_badge.short_description = 'Status'
    
    def days_since_given_display(self, obj):
        days = obj.days_since_given
        if days > 90:
            color = '#e74c3c'
        elif days > 60:
            color = '#e67e22'
        elif days > 30:
            color = '#f39c12'
        else:
            color = '#27ae60'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} days</span>',
            color, days
        )
    days_since_given_display.short_description = 'Days Since Given'
    
    actions = ['mark_as_paid', 'cancel_transactions']
    
    def mark_as_paid(self, request, queryset):
        count = 0
        for transaction in queryset.filter(payment_status='pending'):
            transaction.mark_as_paid(paid_by=request.user)
            count += 1
        self.message_user(request, f'{count} transactions marked as paid.')
    mark_as_paid.short_description = "Mark selected as Paid"
    
    def cancel_transactions(self, request, queryset):
        count = 0
        for transaction in queryset.filter(payment_status='pending'):
            transaction.cancel(cancelled_by=request.user)
            count += 1
        self.message_user(request, f'{count} transactions cancelled.')
    cancel_transactions.short_description = "Cancel selected transactions"


@admin.register(CompanyPayment)
class CompanyPaymentAdmin(admin.ModelAdmin):
    list_display = ['payment_id', 'credit_company', 'amount_display', 'payment_method', 
                    'payment_date', 'transaction_count', 'created_at']
    list_filter = ['payment_method', 'payment_date', 'credit_company']
    search_fields = ['payment_id', 'payment_reference', 'credit_company__name']
    readonly_fields = ['payment_id', 'created_at']
    filter_horizontal = ['transactions']
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('payment_id', 'credit_company', 'amount', 'payment_method', 'payment_reference', 'payment_date')
        }),
        ('Bank Details', {
            'fields': ('bank_name', 'account_number'),
            'classes': ('collapse',)
        }),
        ('Transactions', {
            'fields': ('transactions',),
            'description': 'Select the credit transactions included in this payment'
        }),
        ('Additional Info', {
            'fields': ('notes', 'created_by', 'created_at')
        }),
    )
    
    def amount_display(self, obj):
        return f"KSH {obj.amount:,.0f}"
    amount_display.short_description = 'Amount'
    
    def transaction_count(self, obj):
        return obj.transactions.count()
    transaction_count.short_description = 'Transactions'
    
    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    def response_add(self, request, obj, post_url_continue=None):
        if '_process' in request.POST:
            obj.process_payment()
            self.message_user(request, f'Payment processed! {obj.transactions.count()} transactions marked as paid.')
        return super().response_add(request, obj, post_url_continue)
    
    actions = ['process_payments']
    
    def process_payments(self, request, queryset):
        count = 0
        for payment in queryset:
            payment.process_payment()
            count += payment.transactions.count()
        self.message_user(request, f'Processed {queryset.count()} payments, marking {count} transactions as paid.')
    process_payments.short_description = "Process selected payments"


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