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


# ==================== BANK ACCOUNT MODEL ====================

class BankAccount(models.Model):
    """Bank accounts - bank names can be added dynamically via frontend"""
    shop = models.ForeignKey(ShopBranch, on_delete=models.CASCADE, related_name='bank_accounts')
    bank_name = models.CharField(max_length=100)  # Dynamic - added via frontend
    account_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['shop', 'bank_name', 'account_number']
        ordering = ['bank_name']
    
    def __str__(self):
        return f"{self.shop.name} - {self.bank_name}"


# ==================== M-PESA ACCOUNT MODEL ====================

class MpesaAccount(models.Model):
    """M-Pesa accounts - account types can be added dynamically via frontend"""
    shop = models.ForeignKey(ShopBranch, on_delete=models.CASCADE, related_name='mpesa_accounts')
    account_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=50, unique=True)
    account_type = models.CharField(max_length=50)  # Dynamic - added via frontend (Till, Paybill, Agent, etc.)
    phone_number = models.CharField(max_length=12, help_text="Registered M-Pesa phone number")
    is_active = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.shop.name} - {self.account_name} ({self.account_number})"


# ==================== DAILY SHOP REPORT MODEL ====================

class DailyShopReport(models.Model):
    """Main daily report for each shop"""
    shop = models.ForeignKey(ShopBranch, on_delete=models.CASCADE, related_name='daily_reports')
    report_date = models.DateField()
    submitted_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='submitted_reports')
    submission_time = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)
    
    # Add these new fields for finalization tracking
    finalized_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='finalized_reports'
    )
    finalized_at = models.DateTimeField(null=True, blank=True)
    
    # M-Pesa closing balances
    closing_mpesa_float = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Closing M-Pesa Float")
    closing_mpesa_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Closing M-Pesa Cash")
    
    # Shop transactions
    shop_sales = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=0, 
        verbose_name="Total M-Pesa Transactions" 
    )
    
    # Totals (auto-calculated)
    total_closing_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    total_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    
    # Additional Info
    notes = models.TextField(blank=True, null=True)
    is_finalized = models.BooleanField(default=False)
    
    class Meta:
        unique_together = ['shop', 'report_date']
        ordering = ['-report_date']
        verbose_name_plural = "Daily Shop Reports"
    
    def __str__(self):
        return f"{self.shop.name} - {self.report_date}"
    
    def calculate_totals(self):
        """Calculate total closing balance from all bank accounts"""
        try:
            bank_closings = self.bank_closings.filter(is_active=True)
            bank_total = sum([float(bc.closing_balance) for bc in bank_closings])
            self.total_closing_balance = float(self.closing_mpesa_float or 0) + float(self.closing_mpesa_cash or 0) + bank_total
        except:
            self.total_closing_balance = 0
        return self.total_closing_balance

    def save(self, *args, **kwargs):
        self.calculate_totals()
        super().save(*args, **kwargs)

    def get_shop_previous_closing_balance(self):
        """
        Get the previous closing balance for the SHOP (not user-specific)
        This is used for opening balance calculations
        """
        previous_report = DailyShopReport.objects.filter(
            shop=self.shop,
            report_date__lt=self.report_date
        ).order_by('-report_date').first()
    
        return previous_report.total_closing_balance if previous_report else Decimal('0.00')

    def get_previous_day_report(self):
        """Get the report for the previous day for the same shop"""
        from datetime import timedelta
        previous_date = self.report_date - timedelta(days=1)
        return DailyShopReport.objects.filter(
            shop=self.shop,
            report_date=previous_date
        ).first()

    def get_opening_balance(self):
        """Get the opening balance (previous day's closing balance)"""
        previous_report = self.get_previous_day_report()
        if previous_report:
            return previous_report.total_closing_balance
        return Decimal('0.00')  # First day, no previous balance
    
    @property
    def total_mpesa_closing(self):
        """Get total M-PESA closing balance (float + cash)"""
        return (self.closing_mpesa_float or 0) + (self.closing_mpesa_cash or 0)
    
    @property
    def total_bank_closing(self):
        """Get total bank closing balance"""
        return self.bank_closings.filter(is_active=True).aggregate(
            total=models.Sum('closing_balance')
        )['total'] or 0
    
    @property
    def net_position(self):
        """Net Position = Current Day (M-PESA Float + M-PESA Cash + All Bank Balances)"""
        return self.total_mpesa_closing + self.total_bank_closing


# ==================== BANK CLOSING BALANCE MODEL ====================

class BankClosingBalance(models.Model):
    """Closing balance for each bank account in a daily report"""
    daily_report = models.ForeignKey(DailyShopReport, on_delete=models.CASCADE, related_name='bank_closings')
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE)
    closing_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ['daily_report', 'bank_account']
        verbose_name_plural = "Bank Closing Balances"
    
    def __str__(self):
        return f"{self.daily_report} - {self.bank_account.bank_name}: {self.closing_balance}"


class ShopExpense(models.Model):
    """Individual expenses for a daily report"""
    daily_report = models.ForeignKey(DailyShopReport, on_delete=models.CASCADE, related_name='expenses')
    expense_category = models.CharField(max_length=100, blank=True, null=True)
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    payment_method = models.CharField(max_length=50, default='cash', blank=True)
    receipt_number = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        if self.description:
            return f"{self.daily_report} - {self.description}: {self.amount}"
        return f"{self.daily_report} - Expense: {self.amount}"


# ==================== M-PESA DAILY SUMMARY MODEL ====================

class MpesaDailySummary(models.Model):
    """Daily M-Pesa summary for each shop"""
    shop = models.ForeignKey(ShopBranch, on_delete=models.CASCADE, related_name='mpesa_summaries')
    report_date = models.DateField()
    daily_report = models.OneToOneField(DailyShopReport, on_delete=models.CASCADE, related_name='mpesa_summary', null=True, blank=True)
    
    # Float balance
    opening_float = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    float_added = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    float_withdrawn = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    customer_payments = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cash_out_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_float = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Cash balance (physical cash from M-Pesa cash out)
    opening_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cash_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cash_expenses = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cash_withdrawn = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    closing_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Reconciliation
    expected_float = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    float_variance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cash_variance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    is_reconciled = models.BooleanField(default=False)
    reconciled_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='mpesa_reconciliations')
    reconciliation_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        unique_together = ['shop', 'report_date']
        ordering = ['-report_date']
    
    def __str__(self):
        return f"{self.shop.name} - M-Pesa {self.report_date}"
    
    def calculate_closing_float(self):
        self.closing_float = self.opening_float + self.float_added - self.float_withdrawn + self.customer_payments - self.cash_out_amount
        return self.closing_float
    
    def calculate_closing_cash(self):
        self.closing_cash = self.opening_cash + self.cash_sales - self.cash_expenses + self.cash_withdrawn
        return self.closing_cash
    
    def calculate_variances(self):
        self.float_variance = self.expected_float - self.closing_float
        self.cash_variance = self.expected_cash - self.closing_cash
        return self.float_variance, self.cash_variance
    
    def save(self, *args, **kwargs):
        self.calculate_closing_float()
        self.calculate_closing_cash()
        super().save(*args, **kwargs)


# ==================== SHOP CONFIGURATION MODEL ====================

class ShopConfiguration(models.Model):
    """Shop-specific configurations"""
    shop = models.ForeignKey(ShopBranch, on_delete=models.CASCADE, related_name='configurations')
    config_key = models.CharField(max_length=100)
    config_value = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['shop', 'config_key']
    
    def __str__(self):
        return f"{self.shop.name} - {self.config_key}"