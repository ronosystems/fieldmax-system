from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from django.db.models import Sum  
import logging





logger = logging.getLogger(__name__)





# ============================================
# FINANCE  SAMMARY MODELS
# ============================================
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
            # Add composite index for duplicate detection
            models.Index(fields=['transaction_type', 'amount', 'transaction_date']),
        ]
        # Add unique constraint to prevent exact duplicates
        unique_together = [['transaction_type', 'amount', 'description', 'transaction_date']]
    
    def save(self, *args, **kwargs):
        """Prevent duplicate transactions before saving"""
        # Skip duplicate check for existing records
        if not self.pk:
            # Check for duplicate within the same day
            duplicate_exists = FinancialTransaction.objects.filter(
                transaction_type=self.transaction_type,
                amount=self.amount,
                description=self.description,
                transaction_date__date=self.transaction_date.date()
            ).exists()
            
            if duplicate_exists:
                logger.warning(f"⚠️ DUPLICATE FINANCIAL TRANSACTION BLOCKED: {self.description[:50]} - KES {self.amount}")
                return  # Don't save duplicate
        
        super().save(*args, **kwargs)


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
            import uuid

            # Safe slicing with fallback
            short_id = self.checkout_request_id[-8:] if len(self.checkout_request_id) >= 8 else self.checkout_request_id
            payment_ref = f"MPESA-{short_id}-{uuid.uuid4().hex[:4]}"
            
            # Create corresponding financial transaction
            self.financial_transaction = FinancialTransaction.objects.create(
                transaction_type='income',
                category='other',
                amount=self.amount,
                description=f"M-Pesa Payment - {self.transaction_desc} - Ref: {self.mpesa_receipt_number}",
                payment_method='mpesa',
                payment_reference=self.mpesa_receipt_number or payment_ref, 
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


class StockPurchase(models.Model):
    """Track stock purchases (inventory expenses)"""
    
    stock_entry = models.ForeignKey(
        'inventory.StockEntry',
        on_delete=models.CASCADE,
        related_name='finance_transactions'
    )
    
    # Product info
    product_name = models.CharField(max_length=255)
    sku_code = models.CharField(max_length=50)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Purchase details
    purchase_date = models.DateTimeField(default=timezone.now)
    reference_id = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    
    # Financial link
    financial_transaction = models.ForeignKey(
        'FinancialTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_purchases'
    )
    
    # Account tracking
    account_transaction = models.ForeignKey(
        'AccountTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_purchases'
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='stock_purchases'
    )
    
    class Meta:
        ordering = ['-purchase_date']
        indexes = [
            models.Index(fields=['sku_code']),
            models.Index(fields=['-purchase_date']),
        ]
        verbose_name = 'Stock Purchase'
        verbose_name_plural = 'Stock Purchases'
    
    def __str__(self):
        return f"Stock Purchase: {self.sku_code} - {self.quantity} units @ KES {self.unit_price}"


class MoneyTransfer(models.Model):
    """Track money transfers between accounts - INTERNAL TRANSFERS ONLY"""
    
    ACCOUNT_CHOICES = [
        ('cash', 'Cash Account'),
        ('bank', 'Bank Account'),
        ('mpesa', 'M-Pesa Account'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    from_account = models.CharField(max_length=10, choices=ACCOUNT_CHOICES)
    to_account = models.CharField(max_length=10, choices=ACCOUNT_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255)
    transfer_reference = models.CharField(max_length=100, unique=True, blank=True)
    
    # Optional details
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_number = models.CharField(max_length=50, blank=True)
    bank_account_name = models.CharField(max_length=200, blank=True)
    mpesa_phone = models.CharField(max_length=15, blank=True)
    mpesa_receipt = models.CharField(max_length=50, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Audit
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='transfers_requested')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_approved')
    notes = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['from_account', 'to_account']),
            models.Index(fields=['status']),
            models.Index(fields=['transfer_reference']),
        ]
    
    def __str__(self):
        return f"Transfer {self.amount} from {self.get_from_account_display()} to {self.get_to_account_display()}"
    
    def save(self, *args, **kwargs):
        if not self.transfer_reference:
            self.transfer_reference = self._generate_reference()
        super().save(*args, **kwargs)
    
    def _generate_reference(self):
        from django.utils import timezone
        today = timezone.now().strftime('%Y%m%d')
        last = MoneyTransfer.objects.filter(
            transfer_reference__startswith=f'TR-{today}'
        ).order_by('-transfer_reference').first()
        
        if last and last.transfer_reference:
            try:
                last_num = int(last.transfer_reference.split('-')[-1])
                new_num = last_num + 1
            except:
                new_num = 1
        else:
            new_num = 1
        
        return f"TR-{today}-{str(new_num).zfill(3)}"
    
    def complete_transfer(self, approved_by=None):
        """Complete internal transfer - updates balances only, no income/expense"""
        from django.db import transaction
        
        with transaction.atomic():
            if not self._has_sufficient_balance():
                self.status = 'failed'
                self.notes = f"{self.notes}\nFailed: Insufficient balance".strip()
                self.save()
                return False
            
            self._transfer_balances()
            self.status = 'completed'
            self.completed_at = timezone.now()
            self.approved_by = approved_by or self.requested_by
            self.save()
            return True
    
    def _has_sufficient_balance(self):
        """Check if source has enough balance"""
        from .models import CashAccount, BankAccount
        
        if self.from_account == 'cash':
            cash = CashAccount.objects.first()
            return cash and cash.balance >= self.amount
        elif self.from_account == 'bank':
            bank = BankAccount.objects.first()
            return bank and bank.balance >= self.amount
        elif self.from_account == 'mpesa':
            mpesa = CashAccount.objects.filter(id=2).first()
            if not mpesa:
                mpesa = CashAccount.objects.create(id=2, balance=0)
            return mpesa.balance >= self.amount
        return False
    
    def _transfer_balances(self):
        """
        CORRECT BALANCE TRANSFER:
        - Cash to Bank: Subtract from Cash, Add to Bank
        - Bank to Cash: Subtract from Bank, Add to Cash
        - Cash to M-Pesa: Subtract from Cash, Add to M-Pesa
        etc.
        """
        from .models import CashAccount, BankAccount
        
        # STEP 1: SUBTRACT from source (debit)
        if self.from_account == 'cash':
            cash = CashAccount.objects.first()
            if cash:
                cash.balance -= self.amount
                cash.save()
                print(f"💰 Cash: -{self.amount} = {cash.balance}")
                
        elif self.from_account == 'bank':
            bank = BankAccount.objects.first()
            if bank:
                bank.balance -= self.amount
                bank.save()
                print(f"🏦 Bank: -{self.amount} = {bank.balance}")
                
        elif self.from_account == 'mpesa':
            mpesa = CashAccount.objects.filter(id=2).first()
            if not mpesa:
                mpesa = CashAccount.objects.create(id=2, balance=0)
            mpesa.balance -= self.amount
            mpesa.save()
            print(f"📱 M-Pesa: -{self.amount} = {mpesa.balance}")
        
        # STEP 2: ADD to destination (credit)
        if self.to_account == 'cash':
            cash = CashAccount.objects.first()
            if cash:
                cash.balance += self.amount
                cash.save()
                print(f"💰 Cash: +{self.amount} = {cash.balance}")
                
        elif self.to_account == 'bank':
            bank = BankAccount.objects.first()
            if bank:
                bank.balance += self.amount
                bank.save()
                print(f"🏦 Bank: +{self.amount} = {bank.balance}")
                
        elif self.to_account == 'mpesa':
            mpesa = CashAccount.objects.filter(id=2).first()
            if not mpesa:
                mpesa = CashAccount.objects.create(id=2, balance=0)
            mpesa.balance += self.amount
            mpesa.save()
            print(f"📱 M-Pesa: +{self.amount} = {mpesa.balance}")
    
    def cancel(self, cancelled_by=None, reason=""):
        self.status = 'cancelled'
        if reason:
            self.notes = f"{self.notes}\nCancelled: {reason}".strip()
        self.save()







# ============================================
# SAVINGS ACCOUNT (Only Profits)
# ============================================

class SavingsAccount(models.Model):
    """SAVINGS ACCOUNT - ONLY TRACKS PROFITS"""
    
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_profits_earned = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_profits_taken = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))  # ← ADD THIS
    
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = 'Savings Account'
        verbose_name_plural = 'Savings Accounts'
    
    def __str__(self):
        return f"Savings Account: KES {self.balance:,.2f} (Total Profits: KES {self.total_profits_earned:,.2f})"
    
    @classmethod
    def get_account(cls):
        """Get or create the single savings account"""
        account, created = cls.objects.get_or_create(id=1)
        if created:
            account.save()
        return account
    
    def add_profit(self, amount, sale_reference="", user=None):
        """Add profit to savings account from a sale"""
        if amount <= 0:
            return self.balance
    
        self.balance += amount
        self.total_profits_earned += amount
        self.updated_by = user
        self.save()
        
        SavingsTransaction.objects.create(
            savings_account=self,
            amount=amount,
            transaction_type='profit',
            sale_reference=sale_reference,
            description=f"Profit from sale {sale_reference}",
            created_by=user
        )
        
        logger.info(f"💰 SAVINGS: +{amount} profit from sale {sale_reference}")
        return self.balance

    # ============================================
    # SAVINGS TO INJECTION
    # ============================================   
    def transfer_to_injection(self, amount, user=None):
        """
        Transfer money from Savings Account to Injection Account
        This REDUCES savings (profits available) and INCREASES injection (capital history)
        """
        if amount <= 0:
            return False, "Amount must be greater than 0"
        
        if self.balance < amount:
            return False, f"Insufficient savings. Available: KES {self.balance:,.2f}"
        
        with transaction.atomic():
            # 1. Subtract from Savings
            self.balance -= amount
            self.updated_by = user
            self.save()
            
            # 2. Record transaction in SavingsTransaction
            SavingsTransaction.objects.create(
                savings_account=self,
                amount=amount,
                transaction_type='transfer_to_injection',  # This matches your TRANSACTION_TYPES
                description=f"Transferred to Injection Account: KES {amount:,.2f}",
                created_by=user
            )
            
            # 3. Add to Injection Account
            injection_account = InjectionAccount.get_account()
            injection_account.receive_from_savings(amount, user=user)
            
            # 4. Optional: Record transfer in InjectionTransaction
            # The receive_from_savings method already does this
            
            logger.info(f"💸 TRANSFER: KES {amount:,.2f} from Savings to Injection")
            
        return True, f"Successfully transferred KES {amount:,.2f} to Injection Account"


    # ============================================
    # ADD THIS NEW METHOD - ONE CLICK PROFIT TAKING
    # ============================================
    
    def take_profit(self, amount=None, user=None):
        """
        ONE CLICK PROFIT TAKING - Move profit from business to owner
        This REDUCES business assets (money leaves the business)
        """
        if amount is None:
            amount = self.balance
        
        if amount <= 0:
            return False, "No profit to take", Decimal('0.00')
        
        if self.balance < amount:
            return False, f"Insufficient savings. Available: KES {self.balance:,.2f}", Decimal('0.00')
        
        with transaction.atomic():
            # Record that profit is being taken
            self.balance -= amount
            self.total_profits_taken += amount
            self.updated_by = user
            self.save()
            
            # Create transaction record
            SavingsTransaction.objects.create(
                savings_account=self,
                amount=amount,
                transaction_type='profit_taken',  # ← NEW TYPE
                description=f"Profit taken by owner: KES {amount:,.2f}",
                created_by=user
            )
            
            # Optional: Create a financial transaction record
            FinancialTransaction.objects.create(
                transaction_type='expense',
                category='other',
                amount=amount,
                description=f"Owner profit withdrawal",
                payment_method='cash',
                payment_reference=f"PROFIT-TAKE-{timezone.now().strftime('%Y%m%d%H%M%S')}",
                recipient_name=user.get_full_name() if user else "Owner",
                created_by=user,
                notes=f"Profit taken from business. Assets decreased by KES {amount:,.2f}"
            )
            
            logger.info(f"💸 OWNER TOOK PROFIT: KES {amount:,.2f} from Savings")
            
        return True, f"Successfully took KES {amount:,.2f} profit", amount
    
    @property
    def available_profit_to_take(self):
        """Profit available to take home"""
        return self.balance
    
    @property
    def total_profit_ever_earned(self):
        return self.total_profits_earned
    
    @property
    def total_profit_ever_taken(self):
        return self.total_profits_taken
    
    @property
    def profit_remaining_in_business(self):
        return self.balance


class SavingsTransaction(models.Model):
    """Track all savings account transactions"""
    
    TRANSACTION_TYPES = [
        ('profit', 'Profit Added'),
        ('transfer_out', 'Transfer to Injection'),
        ('transfer_to_injection', 'Transfer to Injection Account'), 
        ('profit_taken', 'Profit Taken by Owner'), 
        ('expense', 'Expense Deduction'),
    ]
    
    savings_account = models.ForeignKey(SavingsAccount, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    sale_reference = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    transaction_date = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    
    class Meta:
        ordering = ['-transaction_date']
        unique_together = [['transaction_type', 'amount', 'sale_reference']]
    
    def save(self, *args, **kwargs):
        """Prevent duplicate Savings transactions"""
        if not self.pk and self.sale_reference:
            duplicate_exists = SavingsTransaction.objects.filter(
                transaction_type=self.transaction_type,
                amount=self.amount,
                sale_reference=self.sale_reference
            ).exists()
            
            if duplicate_exists:
                logger.warning(f"⚠️ DUPLICATE SAVINGS TRANSACTION BLOCKED: {self.description[:50]} - KES {self.amount}")
                return
        
        super().save(*args, **kwargs)




# ============================================
# NET ACCOUNT (Main Operating Account)
# ============================================

class NetAccount(models.Model):
    """
    NET ACCOUNT - Main operating account
    
    DEDUCTIONS (-):
    - Inventory purchases
    - Salaries
    - Rent, bills, operational expenses
    
    ADDITIONS (+):
    - Cost of Goods Sold (buying price of sold items)
    - Injections from Injection Account
    """
    
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Deductions tracking (Money OUT)
    total_inventory_purchases = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_salaries = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_operational_expenses = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Additions tracking (Money IN)
    total_cogs_added = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_injections_received = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = 'Net Account'
        verbose_name_plural = 'Net Accounts'
    
    def __str__(self):
        return f"Net Account Balance: KES {self.balance:,.2f}"
    
    @classmethod
    def get_account(cls):
        account, created = cls.objects.get_or_create(id=1)
        if created:
            account.save()
        return account
    
    # ADDITIONS (+) - Money INTO Net Account
    
    def add_cogs(self, amount, sale_reference="", user=None):
        """ADD COGS (Cost of Goods Sold) - Buying price of sold items"""
        if amount <= 0:
            return self.balance
        
        self.balance += amount
        self.total_cogs_added += amount
        self.updated_by = user
        self.save()
        
        NetTransaction.objects.create(
            net_account=self,
            amount=amount,
            transaction_type='addition',
            category='cogs',
            reference=sale_reference,
            description=f"COGS added from sale {sale_reference}",
            created_by=user
        )
        
        logger.info(f"📈 NET: +{amount} COGS from sale {sale_reference}")
        return self.balance
    
    def receive_injection(self, amount, user=None):
        """RECEIVE INJECTION from Injection Account"""
        if amount <= 0:
            return self.balance
        
        self.balance += amount
        self.total_injections_received += amount
        self.updated_by = user
        self.save()
        
        NetTransaction.objects.create(
            net_account=self,
            amount=amount,
            transaction_type='addition',
            category='injection',
            reference="Injection Transfer",
            description=f"Injection received from Injection Account",
            created_by=user
        )
        
        logger.info(f"📈 NET: +{amount} injection received")
        return self.balance
    
    
    def deduct_inventory_purchase(self, amount, sku_ref="", user=None):
        """DEDUCT inventory purchase when buying stock"""
        if amount <= 0:
            return self.balance
        
        self.balance -= amount
        self.total_inventory_purchases += amount
        self.updated_by = user
        self.save()
        
        NetTransaction.objects.create(
            net_account=self,
            amount=amount,
            transaction_type='deduction',
            category='inventory',
            reference=sku_ref,
            description=f"Inventory Purchase: {sku_ref}",
            created_by=user
        )
        
        logger.info(f"📉 NET: -{amount} inventory purchase")
        return self.balance
    
    def deduct_salary(self, amount, staff_name="", user=None):
        """DEDUCT salary payment"""
        if amount <= 0:
            return self.balance
        
        self.balance -= amount
        self.total_salaries += amount
        self.updated_by = user
        self.save()
        
        NetTransaction.objects.create(
            net_account=self,
            amount=amount,
            transaction_type='deduction',
            category='salary',
            reference=staff_name,
            description=f"Salary: {staff_name}",
            created_by=user
        )
        
        logger.info(f"📉 NET: -{amount} salary payment")
        return self.balance
    
    def deduct_operational_expense(self, amount, expense_type="", reference="", user=None):
        """DEDUCT operational expense (rent, utilities, bills, etc.)"""
        if amount <= 0:
            return self.balance
        
        self.balance -= amount
        self.total_operational_expenses += amount
        self.updated_by = user
        self.save()
        
        NetTransaction.objects.create(
            net_account=self,
            amount=amount,
            transaction_type='deduction',
            category='operational',
            reference=reference,
            description=f"{expense_type}: {reference}" if expense_type else reference,
            created_by=user
        )
        
        logger.info(f"📉 NET: -{amount} operational expense ({expense_type})")
        return self.balance
    
    @property
    def total_deductions(self):
        return self.total_inventory_purchases + self.total_salaries + self.total_operational_expenses
    
    @property
    def total_additions(self):
        return self.total_cogs_added + self.total_injections_received

    @property
    def total_cash_outflow(self):
        """Total money that left Net Account (purchases, salaries, expenses)"""
        return self.total_inventory_purchases + self.total_salaries + self.total_operational_expenses

    @property
    def total_cash_inflow(self):
        """Total money that entered Net Account (COGS, injections)"""
        return self.total_cogs_added + self.total_injections_received


class NetTransaction(models.Model):
    """Track all net account transactions"""
    
    TRANSACTION_TYPES = [
        ('addition', 'Addition (+) - Money In'),
        ('deduction', 'Deduction (-) - Money Out'),
    ]
    
    CATEGORIES = [
        ('cogs', 'COGS Added (Buying Price)'),
        ('injection', 'Injection Received'),
        ('inventory', 'Inventory Purchase'),
        ('salary', 'Salary Payment'),
        ('operational', 'Operational Expense'),
        ('other', 'Other'),
    ]
    
    net_account = models.ForeignKey(NetAccount, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    category = models.CharField(max_length=20, choices=CATEGORIES)
    reference = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    transaction_date = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-transaction_date']
        indexes = [
            models.Index(fields=['category']),
            models.Index(fields=['-transaction_date']),
            models.Index(fields=['transaction_type']),
            # Add composite index for duplicate detection
            models.Index(fields=['category', 'amount', 'transaction_date']),
        ]
        # Add unique constraint
        unique_together = [['category', 'amount', 'description', 'transaction_date']]
    
    def save(self, *args, **kwargs):
        """Prevent duplicate Net transactions"""
        if not self.pk:
            duplicate_exists = NetTransaction.objects.filter(
                category=self.category,
                amount=self.amount,
                description=self.description,
                transaction_date__date=self.transaction_date.date()
            ).exists()
            
            if duplicate_exists:
                logger.warning(f"⚠️ DUPLICATE NET TRANSACTION BLOCKED: {self.description[:50]} - KES {self.amount}")
                return
        
        super().save(*args, **kwargs)







# ============================================
# INJECTION ACCOUNT (Money Entry Point)
# ============================================

class InjectionAccount(models.Model):
    """
    INJECTION ACCOUNT - Tracks TOTAL all-time injected money (never decreases)
    
    This is a CUMULATIVE account - only increases, never decreases.
    Shows total capital ever injected into the business.
    """
    
    total_injected_all_time = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_from_savings = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_external_injection = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = 'Injection Account'
        verbose_name_plural = 'Injection Accounts'
    
    def __str__(self):
        return f"Injection Account: Total Injected KES {self.total_injected_all_time:,.2f}"
    
    @classmethod
    def get_account(cls):
        """Get or create the single injection account"""
        account, created = cls.objects.get_or_create(id=1)
        if created:
            account.save()
        return account
    
    @property
    def balance(self):
        """For compatibility - returns total injected all time"""
        return self.total_injected_all_time
    
    def receive_from_savings(self, amount, user=None):
        """Record money transferred from Savings Account"""
        if amount <= 0:
            return
        
        self.total_injected_all_time += amount
        self.total_from_savings += amount
        self.updated_by = user
        self.save()
        
        InjectionTransaction.objects.create(
            injection_account=self,
            amount=amount,
            transaction_type='from_savings',
            source_detail="Transfer from Savings",
            created_by=user
        )
        
        logger.info(f"💉 INJECTION: +{amount} from Savings (Total: {self.total_injected_all_time})")
    
    def add_external_injection(self, amount, source_type="capital", source_name="", reference="", user=None):
        """Add external money (capital, loans, investments) - INCREASES total only"""
        if amount <= 0:
            return False, "Amount must be greater than 0"
        
        self.total_injected_all_time += amount
        self.total_external_injection += amount
        self.updated_by = user
        self.save()
        
        InjectionTransaction.objects.create(
            injection_account=self,
            amount=amount,
            transaction_type='external',
            source_type=source_type,
            source_name=source_name,
            source_detail=f"{source_name or source_type}",
            reference=reference,
            created_by=user
        )
        
        logger.info(f"💉 INJECTION: +{amount} external (Total: {self.total_injected_all_time})")
        return True, f"Successfully added KES {amount:,.2f} to Injection Account"
    
    def record_transfer_to_net(self, amount, user=None):
        """RECORD that money was transferred to Net Account - does NOT decrease balance"""
        if amount <= 0:
            return False, "Amount must be greater than 0"
        
        InjectionTransaction.objects.create(
            injection_account=self,
            amount=amount,
            transaction_type='transfer_to_net',
            source_detail=f"Transferred to Net Account",
            created_by=user
        )
        
        logger.info(f"💉 INJECTION: Recorded transfer of {amount} to Net")
        return True, f"Recorded transfer of KES {amount:,.2f} to Net Account"
    

class InjectionTransaction(models.Model):
    """Track all injection account transactions"""
    
    TRANSACTION_TYPES = [
        ('from_savings', 'From Savings Account'),
        ('external', 'External Injection'),
        ('transfer_to_net', 'Transfer to Net Account'),
    ]
    
    injection_account = models.ForeignKey(InjectionAccount, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    source_type = models.CharField(max_length=30, blank=True)
    source_name = models.CharField(max_length=200, blank=True)
    source_detail = models.CharField(max_length=200, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    transaction_date = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-transaction_date']
    
    def __str__(self):
        return f"{self.get_transaction_type_display()}: KES {self.amount}"







# ============================================
# SALES ACCOUNTING MODELS
# ============================================

class IncomeAccount(models.Model):
    """Track all income from sales"""
    
    # Account balance
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_income = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Tracking
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='income_updates'
    )
    
    class Meta:
        verbose_name = 'Income Account'
        verbose_name_plural = 'Income Accounts'
    
    def __str__(self):
        return f"Income Account - Balance: KES {self.balance} | Total Income: KES {self.total_income}"
    
    def add_income(self, amount, sale_reference="", user=None):
        """Add income from a sale"""
        from .models import IncomeTransaction
        
        self.balance += amount
        self.total_income += amount
        self.updated_by = user
        self.save()
        
        # Record the transaction
        IncomeTransaction.objects.create(
            income_account=self,
            amount=amount,
            transaction_type='sale',
            reference=sale_reference,
            created_by=user
        )
        
        return self.balance
    
    @classmethod
    def get_or_create_account(cls):
        """Get or create the single income account"""
        account, created = cls.objects.get_or_create(id=1)
        if created:
            account.save()
        return account


class PurchaseAccount(models.Model):
    """Track all purchase costs (cost of goods sold)"""
    
    # Account balance
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_purchases = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Tracking
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='purchase_updates'
    )
    
    class Meta:
        verbose_name = 'Purchase Account'
        verbose_name_plural = 'Purchase Accounts'
    
    def __str__(self):
        return f"Purchase Account - Balance: KES {self.balance} | Total Purchases: KES {self.total_purchases}"
    
    def add_purchase_cost(self, amount, product_reference="", user=None):
        """Add purchase cost (cost of goods sold)"""
        from .models import PurchaseTransaction
        
        self.balance += amount
        self.total_purchases += amount
        self.updated_by = user
        self.save()
        
        # Record the transaction
        PurchaseTransaction.objects.create(
            purchase_account=self,
            amount=amount,
            transaction_type='cogs',
            reference=product_reference,
            created_by=user
        )
        
        return self.balance
    
    @classmethod
    def get_or_create_account(cls):
        """Get or create the single purchase account"""
        account, created = cls.objects.get_or_create(id=1)
        if created:
            account.save()
        return account


class ProfitAccount(models.Model):
    """Track profits from sales (Income - Cost)"""
    
    # Account balance
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_profit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Tracking
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='profit_updates'
    )
    
    class Meta:
        verbose_name = 'Profit Account'
        verbose_name_plural = 'Profit Accounts'
    
    def __str__(self):
        return f"Profit Account - Balance: KES {self.balance} | Total Profit: KES {self.total_profit}"
    
    def add_profit(self, amount, sale_reference="", user=None):
        """Add profit from a sale"""
        from .models import ProfitTransaction
        
        self.balance += amount
        self.total_profit += amount
        self.updated_by = user
        self.save()
        
        # Record the transaction
        ProfitTransaction.objects.create(
            profit_account=self,
            amount=amount,
            transaction_type='sale_profit',
            reference=sale_reference,
            created_by=user
        )
        
        return self.balance
    
    @classmethod
    def get_or_create_account(cls):
        """Get or create the single profit account"""
        account, created = cls.objects.get_or_create(id=1)
        if created:
            account.save()
        return account






# ============================================
# TRANSACTION RECORDS
# ============================================

class IncomeTransaction(models.Model):
    """Individual income transactions"""
    
    INCOME_TYPES = [
        ('sale', 'Product Sale'),
        ('credit', 'Credit Payment'),
        ('refund', 'Refund'),
        ('other', 'Other Income'),
    ]
    
    income_account = models.ForeignKey(
        IncomeAccount, 
        on_delete=models.CASCADE, 
        related_name='transactions'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=INCOME_TYPES)
    reference = models.CharField(max_length=100, blank=True)  # Sale ID, Credit ID, etc.
    description = models.TextField(blank=True)
    transaction_date = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-transaction_date']
        indexes = [
            models.Index(fields=['-transaction_date']),
            models.Index(fields=['transaction_type']),
        ]
    
    def __str__(self):
        return f"Income: KES {self.amount} - {self.get_transaction_type_display()}"


class PurchaseTransaction(models.Model):
    """Individual purchase transactions (Cost of Goods Sold)"""
    
    PURCHASE_TYPES = [
        ('cogs', 'Cost of Goods Sold'),
        ('stock', 'Stock Purchase'),
        ('supplies', 'Supplies'),
        ('other', 'Other Purchase'),
    ]
    
    purchase_account = models.ForeignKey(
        PurchaseAccount, 
        on_delete=models.CASCADE, 
        related_name='transactions'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=PURCHASE_TYPES)
    reference = models.CharField(max_length=100, blank=True)  # Product SKU, Stock Entry ID
    description = models.TextField(blank=True)
    transaction_date = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-transaction_date']
        indexes = [
            models.Index(fields=['-transaction_date']),
            models.Index(fields=['transaction_type']),
        ]
    
    def __str__(self):
        return f"Purchase: KES {self.amount} - {self.get_transaction_type_display()}"


class ProfitTransaction(models.Model):
    """Individual profit transactions"""
    
    PROFIT_TYPES = [
        ('sale_profit', 'Sale Profit'),
        ('adjustment', 'Profit Adjustment'),
    ]
    
    profit_account = models.ForeignKey(
        ProfitAccount, 
        on_delete=models.CASCADE, 
        related_name='transactions'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=PROFIT_TYPES)
    reference = models.CharField(max_length=100, blank=True)  # Sale ID
    description = models.TextField(blank=True)
    transaction_date = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-transaction_date']
        indexes = [
            models.Index(fields=['-transaction_date']),
            models.Index(fields=['transaction_type']),
        ]
    
    def __str__(self):
        return f"Profit: KES {self.amount} - {self.get_transaction_type_display()}"







# ============================================
# SALE ACCOUNTING HELPER
# ============================================

class SaleAccountingHelper:
    """Helper to process sale accounting"""
    
    @staticmethod
    def process_sale(sale, user=None):
        """
        Process accounting for a sale:
        1. Record income (selling price) - CREDIT IncomeAccount
        2. Record purchase cost (buying price) - DEBIT PurchaseAccount  
        3. Record profit (selling price - buying price) - CREDIT ProfitAccount
        """
        from decimal import Decimal
        
        # Get or create accounts
        income_account = IncomeAccount.get_or_create_account()
        purchase_account = PurchaseAccount.get_or_create_account()
        profit_account = ProfitAccount.get_or_create_account()
        
        total_income = Decimal('0')
        total_cost = Decimal('0')
        
        # Get sale items
        if hasattr(sale, 'items'):
            items = sale.items.all()
        elif hasattr(sale, 'sale_items'):
            items = sale.sale_items.all()
        else:
            items = []
        
        for item in items:
            # Calculate selling price total - FIXED: use unit_price, not price
            selling_price = Decimal(str(item.unit_price)) * Decimal(str(item.quantity))
            
            # Get buying price from product
            if hasattr(item, 'product') and item.product:
                buying_price = Decimal(str(item.product.buying_price)) * Decimal(str(item.quantity))
            else:
                buying_price = Decimal('0')
            
            profit = selling_price - buying_price
            
            total_income += selling_price
            total_cost += buying_price
        
        # Only record if there are items
        if total_income > 0:
            # Add total income to IncomeAccount
            income_account.add_income(
                amount=total_income,
                sale_reference=getattr(sale, 'sale_id', str(sale.id)),
                user=user or getattr(sale, 'seller', None)
            )
            
            # Add total purchase cost to PurchaseAccount
            purchase_account.add_purchase_cost(
                amount=total_cost,
                product_reference=getattr(sale, 'sale_id', str(sale.id)),
                user=user or getattr(sale, 'seller', None)
            )
            
            # Record profit
            profit_account.add_profit(
                amount=total_income - total_cost,
                sale_reference=getattr(sale, 'sale_id', str(sale.id)),
                user=user or getattr(sale, 'seller', None)
            )
        
        return {
            'income': total_income,
            'cost': total_cost,
            'profit': total_income - total_cost
    }




# ============================================
# CAPITAL INJECTION MODELS (External Funding)
# ============================================

class CapitalInjection(models.Model):
    """Track external capital injected into the business"""
    
    SOURCE_CHOICES = [
        ('investor', 'Investor'),
        ('loan', 'Bank Loan'),
        ('personal', 'Personal Savings'),
        ('grant', 'Grant'),
        ('partner', 'Business Partner'),
        ('other', 'Other Source'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    # Basic info
    injection_id = models.CharField(max_length=50, unique=True, editable=False)
    source_type = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    source_name = models.CharField(max_length=200, help_text="Name of investor, bank, or source")
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Payment details
    payment_method = models.CharField(max_length=20, choices=FinancialTransaction.PAYMENT_METHODS, default='bank')
    payment_reference = models.CharField(max_length=100, blank=True)
    transaction_date = models.DateTimeField(default=timezone.now)
    
    # Account allocation (where the money goes)
    target_account = models.CharField(max_length=20, choices=[
        ('cash', 'Cash Account'),
        ('bank', 'Bank Account'),
        ('mpesa', 'M-Pesa Account'),
    ], default='bank')
    
    # For loans tracking
    is_loan = models.BooleanField(default=False, help_text="Is this a loan that needs repayment?")
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text="Annual interest rate %")
    repayment_term_months = models.PositiveIntegerField(default=0, help_text="Repayment period in months")
    monthly_repayment = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='completed')
    notes = models.TextField(blank=True)
    
    # Audit
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='capital_injections')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Financial links
    financial_transaction = models.ForeignKey(
        'FinancialTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='capital_injections'
    )
    account_transaction = models.ForeignKey(
        'AccountTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='capital_injections'
    )
    
    class Meta:
        ordering = ['-transaction_date']
        verbose_name = 'Capital Injection'
        verbose_name_plural = 'Capital Injections'
        indexes = [
            models.Index(fields=['source_type']),
            models.Index(fields=['status']),
            models.Index(fields=['-transaction_date']),
        ]
    
    def __str__(self):
        return f"{self.source_type.title()} - KES {self.amount:,.2f} from {self.source_name}"
    
    def save(self, *args, **kwargs):
        if not self.injection_id:
            self.injection_id = self._generate_injection_id()
        super().save(*args, **kwargs)
    
    def _generate_injection_id(self):
        """Generate sequential injection ID: CAP-001"""
        from django.db import transaction
        
        prefix = "CAP-"
        with transaction.atomic():
            last = CapitalInjection.objects.filter(
                injection_id__startswith=prefix
            ).order_by('-injection_id').first()
            
            if last and last.injection_id:
                try:
                    last_num = int(last.injection_id.replace(prefix, ""))
                    new_num = last_num + 1
                except (ValueError, IndexError):
                    new_num = 1
            else:
                new_num = 1
            
            return f"{prefix}{str(new_num).zfill(3)}"
    
    def process_injection(self, user=None):
        """Process the capital injection and update accounts"""
        from django.db import transaction
        from decimal import Decimal
        
        with transaction.atomic():
            # 1. Create FinancialTransaction
            fin_trans = FinancialTransaction.objects.create(
                transaction_type='income',
                category='other',
                amount=self.amount,
                description=f"Capital Injection: {self.get_source_type_display()} from {self.source_name}",
                payment_method=self.payment_method,
                payment_reference=self.payment_reference or self.injection_id,
                recipient_name=self.source_name,
                created_by=user or self.created_by,
                notes=f"Injection ID: {self.injection_id}\n{self.notes}"
            )
            self.financial_transaction = fin_trans
            
            # 2. Create AccountTransaction
            acc_trans = AccountTransaction.objects.create(
                account_type=self.target_account,
                transaction_type='income',
                amount=self.amount,
                description=f"Capital Injection: {self.source_name}",
                reference=self.injection_id,
                created_by=user or self.created_by,
                notes=f"Injection from {self.source_type}"
            )
            self.account_transaction = acc_trans
            
            # 3. Update target account balance
            if self.target_account == 'cash':
                cash_account, _ = CashAccount.objects.get_or_create(id=1)
                cash_account.update_balance(self.amount, 'income', user or self.created_by)
            elif self.target_account == 'bank':
                bank_account, _ = BankAccount.objects.get_or_create(id=1)
                bank_account.update_balance(self.amount, 'income', user or self.created_by)
            elif self.target_account == 'mpesa':
                mpesa_account, _ = CashAccount.objects.get_or_create(id=2, defaults={'balance': 0})
                mpesa_account.update_balance(self.amount, 'income', user or self.created_by)
            
            # 4. Update status
            self.status = 'completed'
            self.save()
            
            return True
    
    @property
    def is_repayable(self):
        return self.is_loan and self.status == 'completed'


class CapitalInjectionRepayment(models.Model):
    """Track repayments for loans taken as capital injection"""
    
    capital_injection = models.ForeignKey(
        CapitalInjection,
        on_delete=models.CASCADE,
        related_name='repayments'
    )
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_date = models.DateTimeField(default=timezone.now)
    payment_reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Financial links
    financial_transaction = models.ForeignKey(
        'FinancialTransaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loan_repayments'
    )
    
    class Meta:
        ordering = ['payment_date']
        verbose_name = 'Capital Injection Repayment'
        verbose_name_plural = 'Capital Injection Repayments'
    
    def __str__(self):
        return f"Repayment of {self.amount} for {self.capital_injection.injection_id}"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update remaining balance on the capital injection
        self.capital_injection.refresh_from_db()


class CapitalAccount(models.Model):
    """Track overall capital position of the business"""
    
    total_capital_injected = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_loan_repayments = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_purchases = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_sales_revenue = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    net_capital = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = 'Capital Account'
        verbose_name_plural = 'Capital Accounts'
    
    def __str__(self):
        return f"Capital Account - Net: KES {self.net_capital:,.2f}"
    
    @classmethod
    def get_or_create_account(cls):
        account, created = cls.objects.get_or_create(id=1)
        if created:
            account.save()
        return account
    
    def refresh_from_db(self, using=None, fields=None):
        """Refresh capital account by recalculating from all transactions"""
        from django.db import models
        from decimal import Decimal
        
        total_injected = CapitalInjection.objects.filter(status='completed').aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0')
        
        total_repaid = CapitalInjectionRepayment.objects.aggregate(
            total=models.Sum('amount')
        )['total'] or Decimal('0')
        
        total_purchases = StockPurchase.objects.aggregate(
            total=models.Sum('total_amount')
        )['total'] or Decimal('0')
        
        total_sales = IncomeTransaction.objects.filter(
            transaction_type='sale'
        ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
        
        self.total_capital_injected = total_injected
        self.total_loan_repayments = total_repaid
        self.total_purchases = total_purchases
        self.total_sales_revenue = total_sales
        self.net_capital = total_injected - total_repaid - total_purchases + total_sales
        self.save(update_fields=[
            'total_capital_injected', 'total_loan_repayments', 
            'total_purchases', 'total_sales_revenue', 'net_capital'
        ])
        return self
    
    def deduct_for_purchase(self, amount, user=None):
        """Deduct from capital for inventory purchase"""
        self.refresh_from_db()
        return self.net_capital
    
    def add_sales_revenue(self, amount, user=None):
        """Add sales revenue to capital"""
        self.refresh_from_db()
        return self.net_capital
    

# ============================================
# INVENTORY ASSET MODEL (Track inventory value)
# ============================================

class InventoryAsset(models.Model):
    """
    Track inventory as an ASSET (not expense)
    This shows the value of your current stock
    """
    
    # Current inventory value at cost (what you paid)
    current_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Total purchases all time
    total_purchased = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Total COGS all time (items sold)
    total_cogs = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Last updated timestamp
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        verbose_name = 'Inventory Asset'
        verbose_name_plural = 'Inventory Assets'
    
    def __str__(self):
        return f"Inventory Asset: KES {self.current_value:,.2f}"
    
    @classmethod
    def get_account(cls):
        """Get or create the single inventory asset account"""
        account, created = cls.objects.get_or_create(id=1)
        if created:
            account.save()
        return account
    
    def add_purchase(self, amount, sku_code="", quantity=0, unit_price=0, user=None):
        """
        Add inventory purchase (ASSET increases)
        Called when you restock/buy products
        """
        if amount <= 0:
            return self.current_value
        
        self.current_value += amount
        self.total_purchased += amount
        self.updated_by = user
        self.save()
        
        InventoryTransaction.objects.create(
            inventory_asset=self,
            amount=amount,
            transaction_type='purchase',
            sku_code=sku_code,
            quantity=quantity,
            unit_price=unit_price,
            description=f"Stock purchase: {sku_code} - {quantity} units @ KES {unit_price}",
            created_by=user
        )
        
        logger.info(f"📦 INVENTORY ASSET: +{amount} (Purchase) | Total: {self.current_value:,.2f}")
        return self.current_value
    
    def deduct_cogs(self, amount, sku_code="", quantity=0, unit_price=0, sale_reference="", user=None):
        """
        Deduct COGS when items are sold (ASSET decreases)
        Called when you sell products
        """
        if amount <= 0:
            return self.current_value
        
        self.current_value -= amount
        self.total_cogs += amount
        self.updated_by = user
        self.save()
        
        InventoryTransaction.objects.create(
            inventory_asset=self,
            amount=amount,
            transaction_type='cogs',
            sku_code=sku_code,
            quantity=quantity,
            unit_price=unit_price,
            sale_reference=sale_reference,
            description=f"COGS for sale {sale_reference}: {sku_code} - {quantity} units @ KES {unit_price}",
            created_by=user
        )
        
        logger.info(f"📦 INVENTORY ASSET: -{amount} (COGS) | Remaining: {self.current_value:,.2f}")
        return self.current_value
    
    def adjust_inventory(self, amount, reason="", user=None):
        """
        Manual adjustment for inventory (e.g., damaged, stolen, found)
        """
        if amount == 0:
            return self.current_value
        
        self.current_value += amount
        self.updated_by = user
        self.save()
        
        trans_type = 'adjustment_increase' if amount > 0 else 'adjustment_decrease'
        
        InventoryTransaction.objects.create(
            inventory_asset=self,
            amount=abs(amount),
            transaction_type=trans_type,
            description=f"Manual adjustment: {reason}",
            created_by=user
        )
        
        logger.info(f"📦 INVENTORY ASSET: Adjustment {amount:+,.2f} | New value: {self.current_value:,.2f}")
        return self.current_value
    
    def refresh_from_inventory(self):
        """
        Refresh inventory value by calculating from actual products
        This syncs with your actual inventory data
        """
        from inventory.models import Product
        from decimal import Decimal
        
        total_value = Decimal('0.00')
        
        for product in Product.objects.filter(is_active=True, is_discontinued=False):
            current_stock = product.current_stock
            total_value += current_stock * product.buying_price
        
        self.current_value = total_value
        self.save()
        
        logger.info(f"📊 Inventory asset refreshed to KES {total_value:,.2f}")
        return total_value
    
    @property
    def profit_realized_from_inventory(self):
        """Profit you've made from sold inventory (Revenue - COGS)"""
        # This matches your Savings account
        from sales.models import Sale
        total_revenue = Sale.objects.filter(is_reversed=False).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        return total_revenue - self.total_cogs


class InventoryTransaction(models.Model):
    """Track all inventory asset transactions"""
    
    TRANSACTION_TYPES = [
        ('purchase', 'Stock Purchase (Asset Increase)'),
        ('cogs', 'Cost of Goods Sold (Asset Decrease)'),
        ('adjustment_increase', 'Manual Increase'),
        ('adjustment_decrease', 'Manual Decrease'),
    ]
    
    inventory_asset = models.ForeignKey(InventoryAsset, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    
    # Product details
    sku_code = models.CharField(max_length=50, blank=True, db_index=True)
    quantity = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    sale_reference = models.CharField(max_length=100, blank=True)
    
    description = models.TextField(blank=True)
    transaction_date = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-transaction_date']
        indexes = [
            models.Index(fields=['-transaction_date']),
            models.Index(fields=['transaction_type']),
            models.Index(fields=['sku_code']),
        ]
    
    def __str__(self):
        sign = "+" if self.amount > 0 else "-"
        return f"{self.get_transaction_type_display()}: {sign} KES {abs(self.amount):,.2f}"



__all__ = [
    'Salary',
    'FinancialTransaction',
    'FinancialSummary',
    'AccountTransaction',
    'CashAccount',
    'BankAccount',
    'CreditAccount',
    'MpesaTransaction',
    'MpesaCallbackLog',
    'StockPurchase',
    'MoneyTransfer',
    'SavingsAccount',
    'SavingsTransaction',
    'InjectionAccount',
    'InjectionTransaction',
    'NetAccount',
    'NetTransaction',
    'IncomeAccount',
    'PurchaseAccount',
    'ProfitAccount',
    'IncomeTransaction',
    'PurchaseTransaction',
    'ProfitTransaction',
    'SaleAccountingHelper',
    'CapitalInjection',
    'CapitalInjectionRepayment',
    'CapitalAccount',
]