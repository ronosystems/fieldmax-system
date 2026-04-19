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







# ============================================
# M-PESA PAYMENT MODELS
# ============================================

class MpesaTransaction(models.Model):
    """Track M-Pesa payment transactions"""
    
    TRANSACTION_STATUS = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Transaction identifiers from M-Pesa
    merchant_request_id = models.CharField(max_length=100, unique=True, db_index=True)
    checkout_request_id = models.CharField(max_length=100, unique=True, db_index=True)
    
    # Transaction results
    result_code = models.IntegerField(null=True, blank=True)
    result_desc = models.CharField(max_length=255, null=True, blank=True)
    
    # Payment details
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    phone_number = models.CharField(max_length=15, db_index=True)
    account_reference = models.CharField(max_length=50, db_index=True)  # Will store Sale ID
    transaction_desc = models.CharField(max_length=100)
    
    # M-Pesa response data
    mpesa_receipt_number = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    transaction_date = models.DateTimeField(null=True, blank=True)
    
    # Status tracking
    status = models.CharField(max_length=20, choices=TRANSACTION_STATUS, default='pending', db_index=True)
    
    # Link to sale
    sale = models.ForeignKey(
        'sales.Sale',  # Link to your Sale model
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mpesa_transactions',
        to_field='sale_id' 
    )
    
    # Link to financial transaction
    financial_transaction = models.ForeignKey(
        'FinancialTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mpesa_transactions'
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='mpesa_transactions'
    )
    
    # Callback data (raw JSON for debugging)
    callback_raw_data = models.JSONField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['merchant_request_id']),
            models.Index(fields=['checkout_request_id']),
            models.Index(fields=['mpesa_receipt_number']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['phone_number', 'status']),
        ]
        verbose_name = 'M-Pesa Transaction'
        verbose_name_plural = 'M-Pesa Transactions'
    
    def __str__(self):
        return f"M-Pesa {self.amount} - {self.phone_number} - {self.status}"
    
    def save(self, *args, **kwargs):
        # Auto-create FinancialTransaction when payment is completed
        if self.status == 'completed' and not self.financial_transaction:
            from decimal import Decimal
            
            # Create corresponding financial transaction
            self.financial_transaction = FinancialTransaction.objects.create(
                transaction_type='income',
                category='other',
                amount=self.amount,
                description=f"M-Pesa Payment - {self.transaction_desc} - Ref: {self.mpesa_receipt_number}",
                payment_method='mpesa',
                payment_reference=self.mpesa_receipt_number,
                recipient_name=f"Customer {self.phone_number}",
                transaction_date=self.transaction_date or timezone.now(),
                created_by=self.created_by,
                notes=f"M-Pesa Transaction ID: {self.checkout_request_id}\nAccount Ref: {self.account_reference}"
            )
        
        super().save(*args, **kwargs)
    
    @property
    def is_completed(self):
        return self.status == 'completed'
    
    @property
    def is_pending(self):
        return self.status == 'pending'
    
    @property
    def is_failed(self):
        return self.status == 'failed'


class MpesaCallbackLog(models.Model):
    """Log all M-Pesa callbacks for debugging"""
    
    transaction = models.ForeignKey(
        MpesaTransaction,
        on_delete=models.CASCADE,
        related_name='callback_logs',
        null=True,
        blank=True
    )
    
    # Callback data
    checkout_request_id = models.CharField(max_length=100, db_index=True)
    result_code = models.IntegerField()
    result_desc = models.CharField(max_length=255)
    
    # Raw data
    raw_payload = models.JSONField()
    
    # Processing info
    processed = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['checkout_request_id']),
            models.Index(fields=['-created_at']),
        ]
        verbose_name = 'M-Pesa Callback Log'
        verbose_name_plural = 'M-Pesa Callback Logs'
    
    def __str__(self):
        return f"Callback {self.checkout_request_id} - Code: {self.result_code}"