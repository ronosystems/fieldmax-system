# ====================================
# CREDIT FINANCING MODELS
# You add companies, give phones to customers, companies pay you
# ====================================
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
from datetime import date, timedelta
from inventory.models import Product
from sales.models import Sale
from django.db.models import Q
from django.db.models import Sum, Count
from django.utils.text import slugify
from django.db import transaction as db_transaction
from django.utils.crypto import get_random_string
import random
import string
import logging

logger = logging.getLogger(__name__)

# ====================================
# CREDIT COMPANY 
# ====================================
class CreditCompany(models.Model):
    """
    Credit companies you work with - you add them manually
    Example: Company X, M-Kopa, Lipa Later, etc.
    """
    # Basic Info - YOU ENTER THESE
    name = models.CharField(max_length=200, unique=True)
    email = models.EmailField(help_text="Company email for communication")
    phone = models.CharField(max_length=20, blank=True)
    contact_person = models.CharField(max_length=200, blank=True)
    
    # Optional details
    code = models.CharField(
        max_length=50, 
        unique=True, 
        blank=True,
        help_text="Auto-generated if left blank"
    )
    address = models.TextField(blank=True)
    
    # Payment terms (optional - for your reference)
    payment_terms = models.CharField(
        max_length=255,
        blank=True,
        help_text="e.g., Net 30, Net 45, Weekly on Friday"
    )
    
    # Status
    is_active = models.BooleanField(default=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_companies'
    )
    
    class Meta:
        ordering = ['name']
        verbose_name = 'Credit Company'
        verbose_name_plural = 'Credit Companies'
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_unique_code()
        super().save(*args, **kwargs)
    
    def _generate_unique_code(self):
        """Generate a unique company code"""
        # Base code from name (first 4 letters, uppercase, remove special chars)
        base = ''.join([c for c in self.name[:4].upper() if c.isalnum()])
        if len(base) < 2:
            base = base + 'CO'  # Default if name is too short
        
        code = base
        counter = 1
        
        # Keep trying until we find a unique code
        while CreditCompany.objects.filter(code=code).exists():
            # Add random suffix
            import random
            import string
            suffix = ''.join(random.choices(string.digits, k=3))
            code = f"{base}{suffix}"
            counter += 1
            if counter > 100:  # Safety valve
                # Fallback to timestamp
                from datetime import datetime
                code = f"{base}{datetime.now().strftime('%y%m%d%H%M%S')}"
                break
        
        return code
    
    @property
    def pending_amount(self):
        """Total amount this company owes you (pending payments)"""
        return self.transactions.filter(
            payment_status='pending'
        ).aggregate(models.Sum('ceiling_price'))['ceiling_price__sum'] or Decimal('0.00')
    
    @property
    def paid_amount(self):
        """Total amount this company has paid you"""
        return self.transactions.filter(
            payment_status='paid'
        ).aggregate(models.Sum('ceiling_price'))['ceiling_price__sum'] or Decimal('0.00')
    
    @property
    def transaction_count(self):
        """Total number of transactions with this company"""
        return self.transactions.count()
    
    @property
    def pending_count(self):
        """Number of pending transactions"""
        return self.transactions.filter(payment_status='pending').count()
    
    @property
    def paid_count(self):
        """Number of paid transactions"""
        return self.transactions.filter(payment_status='paid').count()


# ====================================
# CREDIT CUSTOMER (Your customers)
# ====================================
class CreditCustomer(models.Model):
    """
    Customers who buy phones on credit through credit companies
    Now with photo uploads for passport and ID documents
    """
    # Basic Info - REQUIRED
    full_name = models.CharField(max_length=200)
    id_number = models.CharField(max_length=50, unique=True)
    phone_number = models.CharField(max_length=20)
    
    # Optional Info
    email = models.EmailField(blank=True)
    alternate_phone = models.CharField(max_length=20, blank=True)
    
    # Address
    county = models.CharField(max_length=100, blank=True)
    town = models.CharField(max_length=100, blank=True)
    physical_address = models.TextField(blank=True)
    
    # Next of kin (optional but recommended)
    nok_name = models.CharField(max_length=200, blank=True)
    nok_phone = models.CharField(max_length=20, blank=True)
    
    # ====================================
    # CUSTOMER PHOTOS / DOCUMENTS
    # ====================================
    passport_photo = models.ImageField(
        upload_to='customers/passports/',
        blank=True,
        null=True,
        help_text="Customer's passport photo"
    )
    
    id_front_photo = models.ImageField(
        upload_to='customers/id_front/',
        blank=True,
        null=True,
        help_text="Front side of national ID"
    )
    
    id_back_photo = models.ImageField(
        upload_to='customers/id_back/',
        blank=True,
        null=True,
        help_text="Back side of national ID"
    )
    
    # Additional documents (optional)
    additional_document = models.FileField(
        upload_to='customers/documents/',
        blank=True,
        null=True,
        help_text="Any additional supporting document"
    )
    
    # Status
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='credit_customers'
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['id_number']),
            models.Index(fields=['phone_number']),
            models.Index(fields=['full_name']),
        ]
    
    def __str__(self):
        return f"{self.full_name} ({self.id_number})"
    
    @property
    def has_photos(self):
        """Check if customer has uploaded photos"""
        return bool(self.passport_photo or self.id_front_photo or self.id_back_photo)
    
    @property
    def total_credit(self):
        """Total value of phones taken on credit"""
        return self.transactions.aggregate(
            total=models.Sum('ceiling_price')
        )['total'] or Decimal('0.00')
    
    @property
    def transaction_count(self):
        """Number of credit transactions"""
        return self.transactions.count()
    
    @property
    def pending_count(self):
        """Transactions where company hasn't paid yet"""
        return self.transactions.filter(
            payment_status='pending'
        ).count()
    
    @property
    def paid_count(self):
        """Transactions that have been paid"""
        return self.transactions.filter(
            payment_status='paid'
        ).count()


# ====================================
# SELLER COMMISSION (Track commissions earned by sellers)
# ====================================
class SellerCommission(models.Model):
    """
    Track commissions earned by sellers from credit transactions
    """
    seller = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='commissions_earned'
    )
    
    transaction = models.OneToOneField(
        'CreditTransaction',
        on_delete=models.CASCADE,
        related_name='seller_commission_record'
    )
    
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Commission amount earned"
    )
    
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('paid', 'Paid'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending'
    )
    
    paid_date = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='commission_payouts_made'
    )
    
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['seller', 'status']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.seller.username} - KSH {self.amount} - {self.status}"
    
    def mark_as_paid(self, paid_by=None, notes=""):
        """Mark commission as paid"""
        self.status = 'paid'
        self.paid_date = timezone.now()
        self.paid_by = paid_by
        if notes:
            self.notes = notes
        self.save()
        
        # Also update the transaction
        self.transaction.commission_status = 'paid'
        self.transaction.commission_paid_date = self.paid_date
        self.transaction.commission_paid_by = paid_by
        self.transaction.save()
        
        # Log commission payment
        CreditTransactionLog.objects.create(
            transaction=self.transaction,
            action='commission_paid',
            performed_by=paid_by,
            notes=f"Commission of KSH {self.amount} paid to seller. {notes}"
        )


# ====================================
# SELLER COMMISSION SUMMARY
# ====================================
class SellerCommissionSummary(models.Model):
    """
    Summary of commissions for each seller (updated periodically)
    """
    seller = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='commission_summary'
    )
    
    total_earned = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Total commissions earned (including paid and pending)"
    )
    
    total_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Total commissions paid out"
    )
    
    total_pending = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Total commissions pending payment"
    )
    
    last_paid_date = models.DateTimeField(null=True, blank=True)
    last_paid_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )
    
    transactions_count = models.IntegerField(default=0)
    paid_transactions_count = models.IntegerField(default=0)
    
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Seller Commission Summary'
        verbose_name_plural = 'Seller Commission Summaries'
    
    def __str__(self):
        return f"{self.seller.username} - Earned: KSH {self.total_earned}, Paid: KSH {self.total_paid}"
    
    def update_from_transactions(self):
        """Update summary from seller's transactions"""
        transactions = CreditTransaction.objects.filter(
            dealer=self.seller,
            payment_status='paid'  # Only count paid transactions
        )
        
        self.total_earned = transactions.aggregate(
            total=models.Sum('commission_amount')
        )['total'] or 0
        
        self.total_paid = transactions.filter(
            commission_status='paid'
        ).aggregate(
            total=models.Sum('commission_amount')
        )['total'] or 0
        
        self.total_pending = self.total_earned - self.total_paid
        
        self.transactions_count = transactions.count()
        self.paid_transactions_count = transactions.filter(
            commission_status='paid'
        ).count()
        
        last_paid = transactions.filter(
            commission_status='paid',
            commission_paid_date__isnull=False
        ).order_by('-commission_paid_date').first()
        
        if last_paid:
            self.last_paid_date = last_paid.commission_paid_date
            self.last_paid_amount = last_paid.commission_amount
        
        self.save()
        return self


# ====================================
# CREDIT TRANSACTION (Main - Phone given to customer)
# ====================================
class CreditTransaction(models.Model):
    """
    Records when you give a phone to customer under a credit company's plan
    Now with commission tracking for sellers
    """
    
    PAYMENT_STATUS = [
        ('pending', 'Pending Payment'),      # Company hasn't paid yet
        ('paid', 'Paid by Company'),         # Company has paid you
        ('cancelled', 'Cancelled'),          # Transaction cancelled
        ('reversed', 'Reversed'),            # Transaction reversed, product available
    ]
    
    COMMISSION_STATUS = [
        ('not_set', 'Not Set'),                # For transactions where company hasn't paid
        ('requested', 'Requested'),            # New status - commission requested but not approved
        ('approved', 'Approved'),              # Approved for payment
        ('paid', 'Paid to Seller'),            # Commission has been paid
        ('cancelled', 'Cancelled'),            # Commission cancelled
    ]
    
    # Transaction ID (auto-generated in Sale format: #SALE-XXXX)
    transaction_id = models.CharField(max_length=100, unique=True, db_index=True)
    
    # The credit company (you select from companies you added)
    credit_company = models.ForeignKey(
        CreditCompany,
        on_delete=models.PROTECT,
        related_name='transactions',
        help_text="Select the credit company"
    )
    
    # The customer
    customer = models.ForeignKey(
        CreditCustomer,
        on_delete=models.PROTECT,
        related_name='transactions'
    )
    
    # You (the dealer/seller)
    dealer = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='credit_transactions'
    )
    
    # The product (phone)
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='credit_transactions'
    )
    
    # Product details (snapshot)
    product_name = models.CharField(max_length=200, blank=True)
    product_code = models.CharField(max_length=100, blank=True)
    imei = models.CharField(
        max_length=100,
        blank=True,
        help_text="Phone IMEI number (if applicable)"
    )
    
    # Money - Ceiling price is what the company will pay you
    ceiling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Amount the credit company will pay you"
    )
    
    # ===== COMMISSION FIELDS =====
    commission_type = models.CharField(
        max_length=20,
        choices=[
            ('percentage', 'Percentage'),
            ('fixed', 'Fixed Amount'),
        ],
        default='percentage',
        help_text="How commission is calculated"
    )
    
    commission_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Percentage (e.g., 5 for 5%) or fixed amount in KSH"
    )
    
    commission_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Calculated commission amount (auto-filled)"
    )
    
    commission_status = models.CharField(
        max_length=20,
        choices=COMMISSION_STATUS,
        default='not_set' 
    )
    
    commission_paid_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When commission was paid to seller"
    )
    
    commission_paid_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='commission_payments_made'
    )
    
    commission_notes = models.TextField(
        blank=True,
        help_text="Notes about commission payment"
    )
    
    # Dates
    transaction_date = models.DateTimeField(default=timezone.now)
    paid_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the company paid you"
    )
    
    # Payment tracking
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS,
        default='pending'
    )
    payment_reference = models.CharField(
        max_length=200,
        blank=True,
        help_text="Company's payment reference (M-Pesa code, bank ref, etc.)"
    )
    
    # ETR Receipt Number (same format as sales)
    etr_receipt_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="ETR receipt number (e.g., 0501)"
    )
    
    # Any reference from the company
    company_reference = models.CharField(
        max_length=200,
        blank=True,
        help_text="Reference number from the credit company"
    )
    
    # Notes
    notes = models.TextField(blank=True)
    
    # Reversal tracking
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversed_credit_transactions'
    )
    reversal_reason = models.TextField(blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-transaction_date']
        indexes = [
            models.Index(fields=['transaction_id']),
            models.Index(fields=['payment_status']),
            models.Index(fields=['credit_company', 'payment_status']),
            models.Index(fields=['-transaction_date']),
            models.Index(fields=['etr_receipt_number']),
            models.Index(fields=['commission_status']),  # Added for commission queries
            models.Index(fields=['dealer', 'commission_status']),  # Added for seller queries
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['product'],
                condition=Q(payment_status='pending') | Q(payment_status='paid'),
                name='unique_product_per_active_transaction'
            )
        ]
    
    def __str__(self):
        return f"{self.transaction_id} - {self.customer.full_name} - {self.credit_company.name} - KSH {self.ceiling_price}"
    
    def save(self, *args, **kwargs):
        # Auto-generate transaction ID in Sale format if not set
        if not self.transaction_id:
            self.transaction_id, self.etr_receipt_number = self._generate_sale_id_and_etr()
        
        # Save product snapshot
        if self.product and not self.product_name:
            self.product_name = self.product.name
            self.product_code = self.product.product_code
        
        # Calculate commission amount if not set and ceiling_price exists
        if self.ceiling_price and self.commission_value and not self.commission_amount:
            self.calculate_commission()
        
        super().save(*args, **kwargs)
    
    def _generate_sale_id_and_etr(self):
        """
        Generate Sale ID in format #SALE-XXXX and ETR number (XXXX)
        Shares the same counter with regular sales
        """
        # Import here to avoid circular import
        try:
            from sales.models import Sale
        except ImportError:
            Sale = None
        
        today = date.today()
        
        # Get the highest sequence number from BOTH regular sales and credit transactions
        last_sequence = 0
        
        # Check regular sales if the model exists
        if Sale:
            last_sale = Sale.objects.filter(
                sale_id__startswith='#SALE-'
            ).order_by('-sale_id').first()
            
            if last_sale and last_sale.sale_id:
                try:
                    last_num = int(last_sale.sale_id.replace('#SALE-', ''))
                    last_sequence = max(last_sequence, last_num)
                except (ValueError, AttributeError):
                    pass
        
        # Check credit transactions
        last_credit = CreditTransaction.objects.filter(
            transaction_id__startswith='#SALE-'
        ).order_by('-transaction_id').first()
        
        if last_credit and last_credit.transaction_id:
            try:
                last_num = int(last_credit.transaction_id.replace('#SALE-', ''))
                last_sequence = max(last_sequence, last_num)
            except (ValueError, AttributeError):
                pass
        
        # Also check for any existing sequence numbers in the database
        # This handles case when there are no records yet
        if last_sequence == 0:
            # Check if there are any sales with numeric IDs
            all_sales = []
            if Sale:
                all_sales = Sale.objects.filter(
                    sale_id__startswith='#SALE-'
                ).values_list('sale_id', flat=True)
            
            all_credits = CreditTransaction.objects.filter(
                transaction_id__startswith='#SALE-'
            ).values_list('transaction_id', flat=True)
            
            all_ids = list(all_sales) + list(all_credits)
            
            for id_str in all_ids:
                try:
                    num = int(id_str.replace('#SALE-', ''))
                    last_sequence = max(last_sequence, num)
                except (ValueError, AttributeError):
                    pass
        
        # Increment for new transaction
        new_sequence = last_sequence + 1
        formatted_sequence = str(new_sequence).zfill(4)
        
        # Generate IDs
        transaction_id = f"#SALE-{formatted_sequence}"
        etr_number = formatted_sequence
        
        return transaction_id, etr_number
    
    def calculate_commission(self):
        """Calculate commission amount based on type and value"""
        if self.commission_type == 'percentage':
            # Percentage of ceiling price
            self.commission_amount = (self.ceiling_price * self.commission_value) / Decimal('100.00')
        else:
            # Fixed amount
            self.commission_amount = self.commission_value
        
        # Round to 2 decimal places
        self.commission_amount = round(self.commission_amount, 2)
        
        return self.commission_amount
    
    def mark_as_paid(self, payment_ref='', paid_by=None):
        """Mark as paid when the credit company sends money"""
        self.payment_status = 'paid'
        self.paid_date = timezone.now()
        if payment_ref:
            self.payment_reference = payment_ref
        self.save()
        
        # Create stock entry (record the sale)
        from inventory.models import StockEntry
        StockEntry.objects.create(
            product=self.product,
            quantity=-1,
            entry_type='sale',
            unit_price=self.ceiling_price,
            total_amount=self.ceiling_price,
            reference_id=self.transaction_id,
            notes=f'Credit sale - Paid by {self.credit_company.name}',
            created_by=paid_by or self.dealer
        )
        
        # Log the action
        CreditTransactionLog.objects.create(
            transaction=self,
            action='paid',
            performed_by=paid_by or self.dealer,
            notes=f'Paid - Ref: {payment_ref}'
        )
        
        # Update seller commission summary
        self._update_seller_commission_summary()
    
    def mark_commission_as_paid(self, paid_by=None, notes=""):
        """Mark commission as paid to seller"""
        self.commission_status = 'paid'
        self.commission_paid_date = timezone.now()
        self.commission_paid_by = paid_by
        if notes:
            self.commission_notes = notes
        self.save()
        
        # Update the SellerCommission record
        try:
            commission_record = self.seller_commission_record
            commission_record.mark_as_paid(paid_by=paid_by, notes=notes)
        except SellerCommission.DoesNotExist:
            # Create one if it doesn't exist (for backward compatibility)
            SellerCommission.objects.create(
                seller=self.dealer,
                transaction=self,
                amount=self.commission_amount,
                status='paid',
                paid_date=self.commission_paid_date,
                paid_by=paid_by,
                notes=notes
            )
        
        # Update summary
        self._update_seller_commission_summary()
        
        # Log commission payment
        CreditTransactionLog.objects.create(
            transaction=self,
            action='commission_paid',
            performed_by=paid_by,
            notes=f"Commission of KSH {self.commission_amount} paid to seller. {notes}"
        )
    
    def cancel(self, reason='', cancelled_by=None):
        """Cancel the transaction"""
        self.payment_status = 'cancelled'
        self.commission_status = 'cancelled'
        self.notes = f"{self.notes}\nCancelled: {reason}".strip()
        self.save()
        
        # When cancelling, restore product availability
        if self.product:
            if self.product.category.is_single_item:
                self.product.status = 'available'
                self.product.quantity = 1
            else:
                self.product.quantity += 1
                if self.product.quantity > 0:
                    self.product.status = 'available'
            self.product.save()
        
        # Update commission record if exists
        try:
            commission_record = self.seller_commission_record
            commission_record.status = 'cancelled'
            commission_record.notes = f"Cancelled: {reason}"
            commission_record.save()
        except SellerCommission.DoesNotExist:
            pass
        
        CreditTransactionLog.objects.create(
            transaction=self,
            action='cancelled',
            performed_by=cancelled_by or self.dealer,
            notes=reason
        )
        
        # Update summary
        self._update_seller_commission_summary()
    
    def reverse_transaction(self, reversed_by=None, reason=""):
        """
        Reverse a credit transaction:
        - Mark transaction as reversed
        - Make product available again
        - Cancel commission
        - Create reversal log
        """
        if self.payment_status == 'reversed':
            raise ValidationError("Transaction already reversed")
        
        if self.payment_status == 'paid':
            raise ValidationError("Paid transactions cannot be reversed. Please contact admin.")
        
        with db_transaction.atomic():
            # Store old status
            old_status = self.payment_status
            product = self.product
            
            # ============================================
            # RESTORE PRODUCT STATUS
            # ============================================
            if product.category.is_single_item:
                product.status = 'available'
                product.quantity = 1
            else:
                product.quantity += 1
                if product.quantity > 0:
                    product.status = 'available'
                if product.quantity <= product.reorder_level:
                    product.status = 'lowstock'
            
            product.save()
            
            # Create reversal stock entry
            from inventory.models import StockEntry
            StockEntry.objects.create(
                product=product,
                quantity=1,
                entry_type='reversal',
                unit_price=self.ceiling_price,
                total_amount=self.ceiling_price,
                reference_id=f"REV-{self.transaction_id}",
                notes=f'Credit reversal - {reason}',
                created_by=reversed_by
            )
            
            # Update transaction status
            self.payment_status = 'reversed'
            self.commission_status = 'cancelled'  # Cancel commission on reversal
            self.reversal_reason = reason
            self.reversed_at = timezone.now()
            self.reversed_by = reversed_by
            self.save()
            
            # Update commission record if exists
            try:
                commission_record = self.seller_commission_record
                commission_record.status = 'cancelled'
                commission_record.notes = f"Reversed: {reason}"
                commission_record.save()
            except SellerCommission.DoesNotExist:
                pass
            
            # Create reversal log
            CreditTransactionLog.objects.create(
                transaction=self,
                action='reversed',
                performed_by=reversed_by,
                notes=f"Transaction reversed. Product restored. Commission cancelled. Reason: {reason}"
            )
            
            # Update summary
            self._update_seller_commission_summary()
            
            logger.info(
                f"[CREDIT REVERSAL] Transaction: {self.transaction_id} | "
                f"Product: {product.product_code} | "
                f"Old Status: {old_status} | New Status: reversed | "
                f"Product Status: {product.status} | "
                f"Product Quantity: {product.quantity} | "
                f"Reason: {reason}"
            )
            
            return True
    
    def _update_seller_commission_summary(self):
        """Update or create seller commission summary"""
        summary, created = SellerCommissionSummary.objects.get_or_create(
            seller=self.dealer
        )
        summary.update_from_transactions()
    
    def get_seller_commission_info(self):
        """Get commission information for the seller"""
        return {
            'seller': self.dealer.get_full_name() or self.dealer.username,
            'commission_type': self.get_commission_type_display(),
            'commission_value': self.commission_value,
            'commission_amount': self.commission_amount,
            'commission_status': self.get_commission_status_display(),
            'commission_paid_date': self.commission_paid_date
        }
    
    @property
    def days_since_given(self):
        """Days since phone was given to customer"""
        delta = date.today() - self.transaction_date.date()
        return delta.days
    
    @property
    def etr_number(self):
        """Get just the ETR number (last 4 digits)"""
        if self.etr_receipt_number:
            return self.etr_receipt_number
        if self.transaction_id and self.transaction_id.startswith('#SALE-'):
            return self.transaction_id.replace('#SALE-', '')
        return "0000"


# ====================================
# COMPANY PAYMENT (Bulk payments from a company)
# ====================================
class CompanyPayment(models.Model):
    """
    Track when a credit company pays you - can be for multiple transactions
    """
    PAYMENT_METHODS = [
        ('mpesa', 'M-Pesa'),
        ('bank', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('cash', 'Cash'),
    ]
    
    # Payment ID (auto-generated)
    payment_id = models.CharField(max_length=100, unique=True)
    
    # Which company paid
    credit_company = models.ForeignKey(
        CreditCompany,
        on_delete=models.PROTECT,
        related_name='payments'
    )
    
    # Transactions included in this payment
    transactions = models.ManyToManyField(
        CreditTransaction,
        related_name='company_payments'
    )
    
    # Payment details
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Total amount paid"
    )
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    payment_reference = models.CharField(
        max_length=200,
        help_text="M-Pesa code, bank reference, cheque number, etc."
    )
    payment_date = models.DateField()
    
    # Bank details (if applicable)
    bank_name = models.CharField(max_length=200, blank=True)
    account_number = models.CharField(max_length=100, blank=True)
    
    # Notes
    notes = models.TextField(blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='recorded_payments'
    )
    
    class Meta:
        ordering = ['-payment_date']
        verbose_name = 'Company Payment'
        verbose_name_plural = 'Company Payments'
    
    def __str__(self):
        return f"{self.payment_id} - {self.credit_company.name} - KSH {self.amount} - {self.payment_date}"
    
    def save(self, *args, **kwargs):
        if not self.payment_id:
            self.payment_id = self._generate_payment_id()
        super().save(*args, **kwargs)
    
    def _generate_payment_id(self):
        """Generate payment ID: PAY-YYYYMMDD-XXX"""
        today = date.today()
        prefix = f"PAY-{today.strftime('%Y%m%d')}"
        count = CompanyPayment.objects.filter(
            payment_id__startswith=prefix
        ).count() + 1
        return f"{prefix}-{str(count).zfill(3)}"
    
    def process_payment(self):
        """Mark all transactions in this payment as paid"""
        for transaction in self.transactions.filter(payment_status='pending'):
            transaction.mark_as_paid(
                payment_ref=self.payment_reference,
                paid_by=self.created_by
            )


# ====================================
# TRANSACTION LOG (Audit trail)
# ====================================
class CreditTransactionLog(models.Model):
    """
    Simple log to track what happened with each transaction
    """
    ACTION_CHOICES = [
        ('created', 'Transaction Created'),
        ('paid', 'Paid by Company'),
        ('cancelled', 'Cancelled'),
        ('reversed', 'Reversed'),
        ('updated', 'Updated'),
        ('commission_paid', 'Commission Paid to Seller'),
        ('commission_cancelled', 'Commission Cancelled'),
    ]
    
    transaction = models.ForeignKey(
        CreditTransaction,
        on_delete=models.CASCADE,
        related_name='logs'
    )
    
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.transaction.transaction_id} - {self.action} - {self.created_at.date()}"


# ====================================
# HELPER FUNCTIONS
# ====================================

def create_credit_transaction_with_commission(
    credit_company, customer, dealer, product,
    ceiling_price, commission_type='percentage',
    commission_value=0, imei='', company_reference='',
    notes=''
):
    """
    Helper function to create a credit transaction with commission
    """
    # Calculate commission
    if commission_type == 'percentage':
        commission_amount = (ceiling_price * commission_value) / Decimal('100.00')
    else:
        commission_amount = commission_value
    
    # Round to 2 decimal places
    commission_amount = round(commission_amount, 2)
    
    with db_transaction.atomic():
        # Create transaction
        transaction = CreditTransaction.objects.create(
            credit_company=credit_company,
            customer=customer,
            dealer=dealer,
            product=product,
            ceiling_price=ceiling_price,
            commission_type=commission_type,
            commission_value=commission_value,
            commission_amount=commission_amount,
            imei=imei,
            company_reference=company_reference,
            notes=notes
        )
        
        # Create commission record
        SellerCommission.objects.create(
            seller=dealer,
            transaction=transaction,
            amount=commission_amount
        )
        
        # Update product status
        if product.category.is_single_item:
            product.status = 'sold'
            product.quantity = 0
        else:
            product.quantity -= 1
            if product.quantity <= 0:
                product.status = 'sold'
            elif product.quantity <= product.reorder_level:
                product.status = 'lowstock'
        product.save()
        
        # Create stock entry
        from inventory.models import StockEntry
        StockEntry.objects.create(
            product=product,
            quantity=-1,
            entry_type='credit_sale',
            unit_price=ceiling_price,
            total_amount=ceiling_price,
            reference_id=transaction.transaction_id,
            notes=f'Credit sale to {customer.full_name} via {credit_company.name}',
            created_by=dealer
        )
        
        # Create log
        CreditTransactionLog.objects.create(
            transaction=transaction,
            action='created',
            performed_by=dealer,
            notes=f"Created with commission: KSH {commission_amount}"
        )
        
        # Update seller commission summary
        summary, _ = SellerCommissionSummary.objects.get_or_create(seller=dealer)
        summary.update_from_transactions()
        
        logger.info(
            f"[CREDIT TRANSACTION] Created: {transaction.transaction_id} | "
            f"Seller: {dealer.username} | Commission: KSH {commission_amount}"
        )
    
    return transaction


# Add commission-related methods to User via monkey-patching or mixin
# These can be used in views by importing the functions

def get_user_total_commission(user):
    """Get total commission earned by a user"""
    return CreditTransaction.objects.filter(
        dealer=user,
        payment_status='paid'
    ).aggregate(
        total=models.Sum('commission_amount')
    )['total'] or Decimal('0.00')


def get_user_pending_commission(user):
    """Get pending commission for a user"""
    return CreditTransaction.objects.filter(
        dealer=user,
        payment_status='paid',
        commission_status='pending'
    ).aggregate(
        total=models.Sum('commission_amount')
    )['total'] or Decimal('0.00')


def get_user_paid_commission(user):
    """Get paid commission for a user"""
    return CreditTransaction.objects.filter(
        dealer=user,
        commission_status='paid'
    ).aggregate(
        total=models.Sum('commission_amount')
    )['total'] or Decimal('0.00')


def get_user_commission_summary(user):
    """Get commission summary for a user"""
    return {
        'total_earned': get_user_total_commission(user),
        'pending': get_user_pending_commission(user),
        'paid': get_user_paid_commission(user),
        'transactions': CreditTransaction.objects.filter(dealer=user).count(),
        'paid_transactions': CreditTransaction.objects.filter(
            dealer=user, 
            commission_status='paid'
        ).count()
    }