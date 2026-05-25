from datetime import timezone
from datetime import timedelta
from django.utils import timezone 
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from decimal import Decimal

# ==================== DYNAMIC CHOICES MODEL ====================

class DynamicChoice(models.Model):
    """Base model for dynamic choices that can be added via frontend"""
    CHOICE_TYPES = [
        ('bank_name', 'Bank Name'),
        ('mpesa_account_type', 'M-Pesa Account Type'),
        ('expense_category', 'Expense Category'),
        ('payment_method', 'Payment Method'),
    ]
    
    choice_type = models.CharField(max_length=50, choices=CHOICE_TYPES)
    value = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['choice_type', 'value']
        ordering = ['choice_type', 'value']
    
    def __str__(self):
        return f"{self.get_choice_type_display()}: {self.value}"


# ==================== SHOP BRANCH MODEL ====================

class ShopBranch(models.Model):
    """Shop branches across different locations"""
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    location = models.CharField(max_length=200)
    manager = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    email = models.EmailField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    opening_date = models.DateField(auto_now_add=True)
    
    class Meta:
        ordering = ['name']
        verbose_name_plural = "Shop Branches"
    
    def __str__(self):
        return f"{self.name} ({self.code})"


# ==================== MPESA ACCOUNT MODEL ====================

class MpesaAccount(models.Model):
    """M-Pesa accounts for each shop (Till, Paybill, Agent, Merchant)"""
    
    ACCOUNT_TYPE_CHOICES = [
        ('till', 'Till Number'),
        ('paybill', 'Paybill Number'),
        ('agent', 'Agent Number'),
        ('merchant', 'Merchant Account'),
    ]
    
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('suspended', 'Suspended'),
    ]
    
    shop = models.ForeignKey(ShopBranch, on_delete=models.CASCADE, related_name='mpesa_accounts')
    account_name = models.CharField(max_length=100, help_text="Name to identify this account")
    account_number = models.CharField(max_length=50, unique=True, db_index=True)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES, default='till')
    store_number = models.CharField(max_length=50, blank=True, null=True, verbose_name="Store Number")
    # Simple counters
    total_deposit_count = models.PositiveIntegerField(default=0, verbose_name="Total Deposits Count")
    total_withdrawal_count = models.PositiveIntegerField(default=0, verbose_name="Total Withdrawals Count")
    total_sale_count = models.PositiveIntegerField(default=0, verbose_name="Total Sales Count")
    
    total_deposit_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_withdrawal_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_sale_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    # User assignment (optional)
    assigned_user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='assigned_mpesa_accounts',
        verbose_name="Assigned User/Cashier"
    )
    
    phone_number = models.CharField(max_length=12, blank=True, null=True, help_text="Registered M-Pesa phone number")
    
    # Financial Information
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Initial float amount")
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Current available balance")
    
    # Limits
    daily_limit = models.DecimalField(max_digits=12, decimal_places=2, default=500000, help_text="Daily transaction limit")
    per_transaction_limit = models.DecimalField(max_digits=12, decimal_places=2, default=150000, help_text="Per transaction limit")
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', db_index=True)
    is_active = models.BooleanField(default=True)
    
    # Business Hours
    business_hours_start = models.TimeField(default="08:00", null=True, blank=True)
    business_hours_end = models.TimeField(default="22:00", null=True, blank=True)
    
    # Additional Info
    notes = models.TextField(blank=True, null=True)
    
    # Audit Fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_mpesa_accounts')
    last_modified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='modified_mpesa_accounts')

    # New fields for tracking manual adjustments
    total_injections_count = models.PositiveIntegerField(default=0, verbose_name="Manual Injections Count")
    total_injections_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_manual_withdrawals_count = models.PositiveIntegerField(default=0, verbose_name="Manual Withdrawals Count")
    total_manual_withdrawals_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        ordering = ['shop__name', 'account_name']
        indexes = [
            models.Index(fields=['account_number']),
            models.Index(fields=['shop', 'status']),
            models.Index(fields=['account_type']),
        ]
        verbose_name = "M-Pesa Account"
        verbose_name_plural = "M-Pesa Accounts"
    
    def __str__(self):
        return f"{self.shop.name} - {self.account_name} ({self.get_account_type_display()}: {self.account_number})"

    
    def add_deposit(self, amount):
        """Add a deposit transaction"""
        self.total_deposit_count += 1
        self.total_deposit_amount += amount
        self.current_balance += amount
        self.save()
    
    def add_withdrawal(self, amount):
        """Add a withdrawal transaction"""
        self.total_withdrawal_count += 1
        self.total_withdrawal_amount += amount
        self.current_balance -= amount
        self.save()
    
    def add_sale(self, amount):
        """Add a sale transaction"""
        self.total_sale_count += 1
        self.total_sale_amount += amount
        self.current_balance -= amount
        self.save()

# ==================== MPESA OPENING/CLOSING BALANCE MODEL ====================

class MpesaDailyBalance(models.Model):
    """Daily opening and closing balances for M-Pesa accounts"""
    
    mpesa_account = models.ForeignKey(MpesaAccount, on_delete=models.CASCADE, related_name='daily_balances')
    report_date = models.DateField()
    
    # Opening balances (from previous day's closing)
    opening_mpesa_float = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    opening_airtel_float = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    opening_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Closing balances
    closing_mpesa_float = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_airtel_float = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Daily transaction summary
    total_deposits = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_withdrawals = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transaction_count = models.PositiveIntegerField(default=0)
    
    # Variances
    mpesa_variance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    airtel_variance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cash_variance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    is_reconciled = models.BooleanField(default=False)
    reconciled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['mpesa_account', 'report_date']
        ordering = ['-report_date']
    
    def __str__(self):
        return f"{self.mpesa_account.account_name} - {self.report_date}"
    
    @property
    def total_opening(self):
        return self.opening_mpesa_float + self.opening_airtel_float + self.opening_cash
    
    @property
    def total_closing(self):
        return self.closing_mpesa_float + self.closing_airtel_float + self.closing_cash
    
    @property
    def net_change(self):
        return self.total_closing - self.total_opening


# ==================== BANK ACCOUNT MODEL ====================

class BankAccount(models.Model):
    """Bank accounts for each shop"""
    shop = models.ForeignKey(ShopBranch, on_delete=models.CASCADE, related_name='bank_accounts')
    bank_name = models.CharField(max_length=100)
    account_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['shop', 'bank_name', 'account_number']
        ordering = ['bank_name']
    
    def __str__(self):
        return f"{self.shop.name} - {self.bank_name} ({self.account_number})"


# ==================== BANK OPENING/CLOSING BALANCE MODEL ====================

class BankDailyBalance(models.Model):
    """Daily opening and closing balances for bank accounts"""
    
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name='daily_balances')
    report_date = models.DateField()
    
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    total_deposits = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_withdrawals = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transaction_count = models.PositiveIntegerField(default=0)
    
    variance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_reconciled = models.BooleanField(default=False)
    reconciled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['bank_account', 'report_date']
        ordering = ['-report_date']
    
    def __str__(self):
        return f"{self.bank_account.bank_name} - {self.report_date}"
    
    @property
    def net_change(self):
        return self.closing_balance - self.opening_balance


# ==================== CASH ACCOUNT MODEL ====================

class CashAccount(models.Model):
    """Physical cash accounts for each shop"""
    
    shop = models.ForeignKey(ShopBranch, on_delete=models.CASCADE, related_name='cash_accounts')
    account_name = models.CharField(max_length=100, default="Main Cash", help_text="e.g., Main Cash, Petty Cash")
    currency = models.CharField(max_length=3, default="KES")
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['shop', 'account_name']
        ordering = ['account_name']
    
    def __str__(self):
        return f"{self.shop.name} - {self.account_name}"
    
    def update_balance(self, amount, transaction_type='credit'):
        if transaction_type == 'credit':
            self.current_balance += amount
        else:
            self.current_balance -= amount
        self.save(update_fields=['current_balance', 'updated_at'])
        return self.current_balance


# ==================== CASH OPENING/CLOSING BALANCE MODEL ====================

class CashDailyBalance(models.Model):
    """Daily opening and closing balances for cash accounts"""
    
    cash_account = models.ForeignKey(CashAccount, on_delete=models.CASCADE, related_name='daily_balances')
    report_date = models.DateField()
    
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    cash_in = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cash_out = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transaction_count = models.PositiveIntegerField(default=0)
    
    variance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_reconciled = models.BooleanField(default=False)
    reconciled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['cash_account', 'report_date']
        ordering = ['-report_date']
    
    def __str__(self):
        return f"{self.cash_account.account_name} - {self.report_date}"
    
    @property
    def net_change(self):
        return self.closing_balance - self.opening_balance


# ==================== SHOP EXPENSES MODEL ====================

class ShopExpense(models.Model):
    """Individual expenses for a daily report"""
    
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('mpesa', 'M-Pesa'),
        ('bank', 'Bank Transfer'),
        ('cheque', 'Cheque'),
    ]
    
    daily_report = models.ForeignKey('DailyShopReport', on_delete=models.CASCADE, related_name='expenses')
    expense_category = models.CharField(max_length=100, blank=True, null=True)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    payment_method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES, default='cash')
    
    # For tracking which account was used for payment
    mpesa_account = models.ForeignKey(MpesaAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses')
    bank_account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses')
    cash_account = models.ForeignKey(CashAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses')
    
    receipt_number = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.daily_report} - {self.description}: KES {self.amount}"


# ==================== DAILY SHOP REPORT MODEL ====================

class DailyShopReport(models.Model):
    """Main daily report for each shop"""
    shop = models.ForeignKey(ShopBranch, on_delete=models.CASCADE, related_name='daily_reports')
    report_date = models.DateField()
    submitted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='submitted_reports')
    submission_time = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)
    
    finalized_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='finalized_reports')
    finalized_at = models.DateTimeField(null=True, blank=True)
    
    total_mpesa_transactions = models.PositiveIntegerField(default=0)
    total_mpesa_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    total_closing_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    total_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    cash_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Cash Balance")
    
    notes = models.TextField(blank=True, null=True)
    is_finalized = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ['shop', 'report_date']
        ordering = ['-report_date']
    
    def __str__(self):
        return f"{self.shop.name} - {self.report_date}"
    
    def update_totals(self):
        """Update totals after the report has been saved (with a primary key)"""
        # Calculate totals from related models
        mpesa_total = self.mpesa_balances.aggregate(
            total=models.Sum('closing_balance')
        )['total'] or 0
        
        bank_total = self.bank_closings.aggregate(
            total=models.Sum('closing_balance')
        )['total'] or 0
        
        self.total_closing_balance = float(mpesa_total) + float(bank_total)
        self.save(update_fields=['total_closing_balance'])
        return self.total_closing_balance

    @property
    def total_mpesa_balance(self):
        """Get total M-Pesa closing balance from all M-Pesa accounts in this report"""
        return self.mpesa_balances.aggregate(
            total=models.Sum('closing_mpesa_float')
        )['total'] or 0

# ==================== DAILY MPESA ACCOUNT REPORT MODEL ====================

class DailyMpesaAccountReport(models.Model):
    """Daily report for M-Pesa accounts - linked to DailyShopReport"""
    
    daily_report = models.ForeignKey(DailyShopReport, on_delete=models.CASCADE, related_name='mpesa_balances')
    mpesa_account = models.ForeignKey(MpesaAccount, on_delete=models.CASCADE, related_name='daily_reports')
    
    # Closing balances for the day
    closing_mpesa_float = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_airtel_float = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Daily activity
    transaction_count = models.PositiveIntegerField(default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['daily_report', 'mpesa_account']
        ordering = ['mpesa_account__account_name']
    
    def __str__(self):
        return f"{self.mpesa_account.account_name} - {self.daily_report.report_date}"
    
    @property
    def total_closing(self):
        return self.closing_mpesa_float + self.closing_airtel_float + self.closing_cash


# ==================== SHOP CONFIGURATION MODEL ====================

class ShopConfiguration(models.Model):
    """Shop-specific configurations"""
    
    CONFIG_TYPES = [
        ('general', 'General Settings'),
        ('reporting', 'Reporting Settings'),
        ('notifications', 'Notification Settings'),
        ('limits', 'Limit Settings'),
    ]
    
    shop = models.ForeignKey(ShopBranch, on_delete=models.CASCADE, related_name='configurations')
    config_type = models.CharField(max_length=50, choices=CONFIG_TYPES, default='general')
    config_key = models.CharField(max_length=100)
    config_value = models.TextField()
    description = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        unique_together = ['shop', 'config_key']
        ordering = ['config_type', 'config_key']
    
    def __str__(self):
        return f"{self.shop.name} - {self.config_key}"
    
    @classmethod
    def get_value(cls, shop, key, default=None):
        """Get configuration value for a shop"""
        try:
            config = cls.objects.get(shop=shop, config_key=key)
            return config.config_value
        except cls.DoesNotExist:
            return default


# ==================== BANK CLOSING BALANCE  ====================

class BankClosingBalance(models.Model):
    """Legacy model - use BankDailyBalance instead"""
    daily_report = models.ForeignKey(DailyShopReport, on_delete=models.CASCADE, related_name='bank_closings')
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE)
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['daily_report', 'bank_account']
        verbose_name_plural = "Bank Closing Balances"
    
    def __str__(self):
        return f"{self.daily_report} - {self.bank_account.bank_name}: {self.closing_balance}"


# ==================== MPESA ADJUSTMENT ==============================

class MpesaAdjustment(models.Model):
    """Track manual adjustments (injections/withdrawals) to M-Pesa accounts"""
    
    ADJUSTMENT_TYPE_CHOICES = [
        ('injection', 'Injection (Add Money)'),
        ('withdrawal', 'Withdrawal (Take Money Out)'),
    ]
    
    mpesa_account = models.ForeignKey(MpesaAccount, on_delete=models.CASCADE, related_name='adjustments')
    adjustment_type = models.CharField(max_length=20, choices=ADJUSTMENT_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    
    # Reference info
    reference_number = models.CharField(max_length=100, blank=True, null=True, help_text="Transaction reference or receipt number")
    reason = models.TextField(help_text="Reason for this adjustment (e.g., 'Extra cash injection from owner', 'Cash taken for expenses')")
    
    # Balance tracking
    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Audit fields
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='mpesa_adjustments')
    created_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_mpesa_adjustments')
    approved_at = models.DateTimeField(null=True, blank=True)
    is_approved = models.BooleanField(default=False)
    
    # Optional: link to a daily report if adjustment is part of end-of-day
    daily_report = models.ForeignKey('DailyShopReport', on_delete=models.SET_NULL, null=True, blank=True, related_name='mpesa_adjustments')
    
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "M-Pesa Adjustment"
        verbose_name_plural = "M-Pesa Adjustments"
    
    def __str__(self):
        return f"{self.get_adjustment_type_display()} - {self.mpesa_account.account_name}: KES {self.amount}"
    
    def save(self, *args, **kwargs):
        # Calculate balance after adjustment
        self.balance_before = self.mpesa_account.current_balance
        
        if self.adjustment_type == 'injection':
            self.balance_after = self.balance_before + self.amount
            self.mpesa_account.current_balance = self.balance_after
            # Also update total deposit count/amount as injection
            self.mpesa_account.total_deposit_count += 1
            self.mpesa_account.total_deposit_amount += self.amount
        else:  # withdrawal
            self.balance_after = self.balance_before - self.amount
            self.mpesa_account.current_balance = self.balance_after
            # Update withdrawal counts
            self.mpesa_account.total_withdrawal_count += 1
            self.mpesa_account.total_withdrawal_amount += self.amount
        
        self.mpesa_account.save()
        super().save(*args, **kwargs)


# ==================== ACCOUNT  TRANSACTIONS ===========================

class AccountTransaction(models.Model):
    """Generic transaction model for all account types (M-Pesa, Bank, Cash)"""
    
    ACCOUNT_TYPE_CHOICES = [
        ('mpesa', 'M-Pesa Account'),
        ('bank', 'Bank Account'),
        ('cash', 'Cash Account'),
    ]
    
    TRANSACTION_TYPE_CHOICES = [
        ('injection', 'Injection (Add Money)'),
        ('withdrawal', 'Withdrawal (Take Money Out)'),
        ('transfer', 'Transfer Between Accounts'),
    ]
    
    # Account identification
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    mpesa_account = models.ForeignKey(MpesaAccount, on_delete=models.CASCADE, null=True, blank=True, related_name='transactions')
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, null=True, blank=True, related_name='transactions')
    cash_account = models.ForeignKey(CashAccount, on_delete=models.CASCADE, null=True, blank=True, related_name='transactions')
    
    # Transaction details
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    
    # For transfers (source and destination)
    from_account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES, null=True, blank=True)
    from_mpesa_account = models.ForeignKey(MpesaAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_out')
    from_bank_account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_out')
    from_cash_account = models.ForeignKey(CashAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_out')
    
    to_account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES, null=True, blank=True)
    to_mpesa_account = models.ForeignKey(MpesaAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_in')
    to_bank_account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_in')
    to_cash_account = models.ForeignKey(CashAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_in')
    
    # Reference info
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    reason = models.TextField()
    notes = models.TextField(blank=True, null=True)
    
    # Balance tracking
    balance_before = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Audit fields
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='transactions')
    created_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_transactions')
    approved_at = models.DateTimeField(null=True, blank=True)
    is_approved = models.BooleanField(default=False)
    
    # Link to daily report
    daily_report = models.ForeignKey('DailyShopReport', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Account Transaction"
        verbose_name_plural = "Account Transactions"
    
    def __str__(self):
        account_name = ""
        if self.account_type == 'mpesa' and self.mpesa_account:
            account_name = self.mpesa_account.account_name
        elif self.account_type == 'bank' and self.bank_account:
            account_name = f"{self.bank_account.bank_name} - {self.bank_account.account_name}"
        elif self.account_type == 'cash' and self.cash_account:
            account_name = self.cash_account.account_name
        
        return f"{self.get_transaction_type_display()} - {account_name}: KES {self.amount}"
    
    def get_account(self):
        """Return the actual account object"""
        if self.account_type == 'mpesa' and self.mpesa_account:
            return self.mpesa_account
        elif self.account_type == 'bank' and self.bank_account:
            return self.bank_account
        elif self.account_type == 'cash' and self.cash_account:
            return self.cash_account
        return None
    
    def get_balance_field(self):
        """Return the balance field name for the account"""
        if self.account_type == 'mpesa':
            return 'current_balance'
        elif self.account_type == 'bank':
            return 'current_balance'
        elif self.account_type == 'cash':
            return 'current_balance'
        return 'current_balance'
    
    def save(self, *args, **kwargs):
        """Save transaction and update account balance"""
        account = self.get_account()
        
        if account:
            # Get current balance
            self.balance_before = account.current_balance
            
            if self.transaction_type == 'injection':
                # Add money
                self.balance_after = self.balance_before + self.amount
                account.current_balance = self.balance_after
                
                # Update specific account counters
                if self.account_type == 'mpesa':
                    account.total_injections_count += 1
                    account.total_injections_amount += self.amount
                    account.total_deposit_count += 1
                    account.total_deposit_amount += self.amount
                elif self.account_type == 'bank':
                    # For bank accounts, you may want to add similar counters
                    pass
                elif self.account_type == 'cash':
                    # For cash accounts, you may want to add similar counters
                    pass
                    
            elif self.transaction_type == 'withdrawal':
                # Subtract money
                self.balance_after = self.balance_before - self.amount
                account.current_balance = self.balance_after
                
                # Update specific account counters
                if self.account_type == 'mpesa':
                    account.total_manual_withdrawals_count += 1
                    account.total_manual_withdrawals_amount += self.amount
                    account.total_withdrawal_count += 1
                    account.total_withdrawal_amount += self.amount
                    
            # Save the account
            account.save()
        
        super().save(*args, **kwargs)

