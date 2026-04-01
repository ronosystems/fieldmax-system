from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class Salary(models.Model):
    """Staff salary records"""
    
    MONTH_CHOICES = [
        (1, 'January'), (2, 'February'), (3, 'March'),
        (4, 'April'), (5, 'May'), (6, 'June'),
        (7, 'July'), (8, 'August'), (9, 'September'),
        (10, 'October'), (11, 'November'), (12, 'December')
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ]
    
    staff = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='salaries'
    )
    
    # Salary details
    month = models.IntegerField(choices=MONTH_CHOICES)
    year = models.IntegerField()
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    bonus = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Payment details
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_reference = models.CharField(max_length=100, blank=True)
    paid_date = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='salaries_paid'
    )
    
    # Notes
    notes = models.TextField(blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='salaries_created'
    )
    
    class Meta:
        ordering = ['-year', '-month']
        unique_together = ['staff', 'month', 'year']
        indexes = [
            models.Index(fields=['staff', 'status']),
            models.Index(fields=['status']),
            models.Index(fields=['-year', '-month']),
        ]
    
    def __str__(self):
        return f"{self.staff.username} - {self.get_month_display()} {self.year} - KSH {self.total_amount}"
    
    def save(self, *args, **kwargs):
        # Calculate total amount
        self.total_amount = self.base_salary + self.bonus - self.deductions
        super().save(*args, **kwargs)
    
    def approve(self, approved_by=None, notes=""):
        """Approve salary"""
        self.status = 'approved'
        if notes:
            self.notes = f"{self.notes}\nApproved: {notes}".strip()
        self.save()
        
        logger.info(f"Salary approved for {self.staff.username} - {self.get_month_display()} {self.year}")
    
    def mark_as_paid(self, paid_by=None, payment_reference="", notes=""):
        """Mark salary as paid"""
        self.status = 'paid'
        self.paid_date = timezone.now()
        self.paid_by = paid_by
        self.payment_reference = payment_reference
        if notes:
            self.notes = f"{self.notes}\nPaid: {notes}".strip()
        self.save()
        
        logger.info(f"Salary paid to {self.staff.username} - KSH {self.total_amount}")
    
    @property
    def is_pending(self):
        return self.status == 'pending'
    
    @property
    def is_approved(self):
        return self.status == 'approved'
    
    @property
    def is_paid(self):
        return self.status == 'paid'


class FinancialTransaction(models.Model):
    """Track all financial transactions"""
    
    TRANSACTION_TYPES = [
        ('salary', 'Salary Payment'),
        ('commission', 'Commission Payment'),
        ('expense', 'Expense'),
        ('income', 'Income'),
        ('refund', 'Refund'),
    ]
    
    CATEGORY_CHOICES = [
        ('staff', 'Staff'),
        ('commission', 'Commission'),
        ('operational', 'Operational'),
        ('rent', 'Rent'),
        ('utilities', 'Utilities'),
        ('other', 'Other'),
    ]
    
    PAYMENT_METHODS = [
        ('cash', 'Cash'),
        ('bank', 'Bank Transfer'),
        ('mpesa', 'M-Pesa'),
        ('cheque', 'Cheque'),
    ]
    
    # Transaction details
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255)
    
    # Related objects
    salary = models.ForeignKey(
        Salary,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='financial_transactions'
    )
    
    # Commission reference (from credit app)
    commission_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Reference to commission from credit app"
    )
    
    # Payment details
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='cash')
    payment_reference = models.CharField(max_length=100, blank=True)
    
    # Recipient/Receiver
    recipient_name = models.CharField(max_length=200, blank=True)
    recipient_account = models.CharField(max_length=100, blank=True)
    
    # Metadata
    transaction_date = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='financial_transactions'
    )
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-transaction_date']
        indexes = [
            models.Index(fields=['transaction_type']),
            models.Index(fields=['-transaction_date']),
        ]
    
    def __str__(self):
        return f"{self.get_transaction_type_display()} - KSH {self.amount} - {self.transaction_date.date()}"


class FinancialSummary(models.Model):
    """Monthly financial summary"""
    
    MONTH_CHOICES = Salary.MONTH_CHOICES
    
    month = models.IntegerField(choices=MONTH_CHOICES)
    year = models.IntegerField()
    
    # Income
    total_sales_income = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_credit_income = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_income = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Expenses
    total_salaries = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_commissions = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_operational_expenses = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_expenses = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Profit
    net_profit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    profit_margin = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Metadata
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['month', 'year']
        ordering = ['-year', '-month']
    
    def __str__(self):
        return f"{self.get_month_display()} {self.year} - Profit: KSH {self.net_profit}"
    
    def calculate(self):
        """Calculate summary totals"""
        self.net_profit = self.total_income - self.total_expenses
        if self.total_income > 0:
            self.profit_margin = (self.net_profit / self.total_income) * 100
        self.save()



        # ============================================
# FINANCE ACCOUNTS MODELS
# ============================================

class AccountTransaction(models.Model):
    """Base model for all account transactions"""
    
    TRANSACTION_TYPES = [
        ('income', 'Income'),
        ('expense', 'Expense'),
        ('transfer', 'Transfer'),
        ('adjustment', 'Adjustment'),
    ]
    
    ACCOUNT_TYPES = [
        ('cash', 'Cash Account'),
        ('bank', 'Bank Account'),
        ('credit', 'Credit Account'),
    ]
    
    account_type = models.CharField(max_length=10, choices=ACCOUNT_TYPES)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255)
    reference = models.CharField(max_length=100, blank=True)
    transaction_date = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    notes = models.TextField(blank=True)
    
    # For transfers between accounts
    from_account = models.CharField(max_length=10, blank=True)
    to_account = models.CharField(max_length=10, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-transaction_date']
        indexes = [
            models.Index(fields=['account_type']),
            models.Index(fields=['-transaction_date']),
        ]
    
    def __str__(self):
        return f"{self.get_account_type_display()} - {self.get_transaction_type_display()} - KES {self.amount}"


class CashAccount(models.Model):
    """Cash account balance tracking"""
    
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        verbose_name = 'Cash Account'
        verbose_name_plural = 'Cash Accounts'
    
    def __str__(self):
        return f"Cash Account Balance: KES {self.balance}"
    
    def update_balance(self, amount, transaction_type, user=None):
        """Update cash balance"""
        if transaction_type == 'income':
            self.balance += amount
        elif transaction_type == 'expense':
            self.balance -= amount
        self.updated_by = user
        self.save()
        return self.balance


class BankAccount(models.Model):
    """Bank account balance tracking"""
    
    bank_name = models.CharField(max_length=100, default='Default Bank')
    account_number = models.CharField(max_length=50, blank=True)
    account_name = models.CharField(max_length=200, blank=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        verbose_name = 'Bank Account'
        verbose_name_plural = 'Bank Accounts'
    
    def __str__(self):
        return f"{self.bank_name} Account: KES {self.balance}"
    
    def update_balance(self, amount, transaction_type, user=None):
        """Update bank balance"""
        if transaction_type == 'income':
            self.balance += amount
        elif transaction_type == 'expense':
            self.balance -= amount
        self.updated_by = user
        self.save()
        return self.balance


class CreditAccount(models.Model):
    """Credit account balance tracking"""
    
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        verbose_name = 'Credit Account'
        verbose_name_plural = 'Credit Accounts'
    
    def __str__(self):
        return f"Credit Account Balance: KES {self.balance} (Limit: KES {self.credit_limit})"
    
    @property
    def available_credit(self):
        return self.credit_limit - self.balance
    
    def update_balance(self, amount, transaction_type, user=None):
        """Update credit balance"""
        if transaction_type == 'income':
            self.balance -= amount
        elif transaction_type == 'expense':
            self.balance += amount
        self.updated_by = user
        self.save()
        return self.balance