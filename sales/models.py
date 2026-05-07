# ==============================
# SALE MODELS
# ==============================
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from decimal import Decimal
import uuid
import logging
from django.db import models, transaction
from django.db.models import F, Max, Sum
from django.contrib.auth.models import User
from django.utils import timezone
from inventory.models import Product, StockEntry
import re
import logging
import math

logger = logging.getLogger(__name__)


# ============================================
# UNIFIED COUNTER MODEL (SALE ID = ETR Receipt)
# ============================================

class SaleCounter(models.Model):
    """
    Single counter for both Sale ID and ETR Receipt Number
    Sale ID: SALE-00001, SALE-00002, SALE-00003...
    ETR Receipt: 00001, 00002, 00003...
    Both share the same sequential number
    """
    counter = models.PositiveIntegerField(default=0)  # Start at 0, first will be 1 -> 00001
    last_used = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'sale_counters'
        verbose_name = 'Sale Counter'
        verbose_name_plural = 'Sale Counters'
    
    def __str__(self):
        return f"Sale/ETR Counter: {self.counter:05d}"


# ============================================
# SALE ID & ETR RECEIPT GENERATOR (SAME NUMBER)
# ============================================

def generate_next_counter() -> int:
    """
    Generate next sequential counter number
    Starts from 1 -> 00001, then 2 -> 00002, etc.
    
    Returns:
        int: The next counter number
    """
    with transaction.atomic():
        # Get or create counter with database lock
        counter_obj, created = SaleCounter.objects.select_for_update().get_or_create(
            pk=1,
            defaults={'counter': 0}
        )
        
        # Increment counter atomically
        counter_obj.counter += 1
        counter_obj.save(update_fields=['counter', 'last_used'])
        
        logger.info(f"[COUNTER GENERATED] Counter: {counter_obj.counter:05d}")
        
        return counter_obj.counter


def generate_sale_id() -> str:
    """
    Generate sale ID using the unified counter
    Format: SALE-00001, SALE-00002, SALE-00003...
    """
    counter = generate_next_counter()
    sale_id = f"SALE-{counter:05d}"
    
    logger.info(f"[SALE ID GENERATED] Sale ID: {sale_id}")
    
    return sale_id


def generate_etr_receipt_number(counter: int = None) -> str:
    """
    Generate ETR receipt number (same number as Sale ID)
    Format: 00001, 00002, 00003...
    
    Args:
        counter: Optional counter number (if not provided, generates new one)
    """
    if counter is None:
        counter = generate_next_counter()
    
    receipt_number = f"{counter:05d}"
    
    logger.info(f"[ETR RECEIPT GENERATED] Receipt: {receipt_number}")
    
    return receipt_number


# ==================================
# SALE MODEL
# ==================================

class Sale(models.Model):
    """
    Represents ONE TRANSACTION (not one item)
    - Each sale can have multiple items (stored in SaleItem)
    - One receipt number per sale
    - Sale ID and ETR Receipt Number are the same sequential number
    """

    PAYMENT_METHODS = [
        ('Cash', 'Cash'),
        ('M-Pesa', 'M-Pesa'),
        ('Card', 'Card'),
        ('Points', 'Points'),
        ('Credit', 'Credit'),
    ]
    
    ETR_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('failed', 'Failed')
    ]
    
    batch_id = models.CharField(max_length=50, blank=True, null=True)
    
    # Sale ID (same as ETR receipt number but with SALE- prefix)
    sale_id = models.CharField(
        max_length=40, 
        primary_key=True, 
        editable=False, 
        default=generate_sale_id
    )
    
    # The sequential number (shared between sale_id and etr_receipt_number)
    sequence_number = models.PositiveIntegerField(
        unique=True,
        editable=False,
        null=True,
        blank=True,
        help_text="Sequential number shared with ETR receipt"
    )
    
    # Transaction details
    seller = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="sales_made"
    )
    sale_date = models.DateTimeField(default=timezone.now)
    
    # Client details (same for all items in this sale)
    buyer_name = models.CharField(max_length=200, blank=True, null=True)
    buyer_phone = models.CharField(max_length=20, blank=True, null=True)
    buyer_id_number = models.CharField(max_length=50, blank=True, null=True)
    nok_name = models.CharField(max_length=200, blank=True, null=True)
    nok_phone = models.CharField(max_length=20, blank=True, null=True)
    
    # Calculated totals (sum of all items)
    total_quantity = models.PositiveIntegerField(default=0)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Payment details
    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHODS,
        default='Cash'
    )
    
    # ETR Receipt Number (same sequence as sale_id)
    etr_receipt_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        help_text="ETR receipt number in format: 00001, 00002, etc. (same number as sale_id)"
    )
    fiscal_receipt_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        help_text="Fiscal receipt number"
    )
    
    # ETR processing
    etr_status = models.CharField(
        max_length=20,
        choices=ETR_STATUS_CHOICES,
        default='pending'
    )
    etr_processed_at = models.DateTimeField(blank=True, null=True)
    etr_error_message = models.TextField(blank=True, null=True)
    
    # Credit sale tracking
    is_credit = models.BooleanField(
        default=False, 
        help_text="Whether this sale is on credit"
    )
    credit_sale_id = models.CharField(
        max_length=50, 
        blank=True, 
        null=True, 
        help_text="Reference to credit app sale ID"
    )
    
    # Points related fields
    points_redeemed = models.IntegerField(
        default=0, 
        help_text="Points redeemed in this sale"
    )
    points_discount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Discount amount from points redemption"
    )
    original_subtotal = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Original subtotal before points discount"
    )
    
    # Customer for loyalty points
    customer = models.ForeignKey(
        'Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sales',
        help_text="Customer who made this purchase (for loyalty points)"
    )
    points_earned = models.DecimalField(
        max_digits=10,
        decimal_places=1,
        default=Decimal('0.0'),
        help_text="Points earned from this sale (1% of total)"
    )
    
    # Reversal tracking
    is_reversed = models.BooleanField(default=False)
    reversed_at = models.DateTimeField(blank=True, null=True)
    reversed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reversed_sales",
    )
    reversal_reason = models.TextField(blank=True, null=True)

    # for split payments
    is_split_payment = models.BooleanField(
        default=False,
        help_text="Whether this sale used multiple payment methods"
    )
    payment_breakdown = models.JSONField(
        default=dict,
        blank=True,
        null=True,
        help_text="JSON breakdown of split payments"
    )
    
    class Meta:
        db_table = 'sales'
        ordering = ['-sale_date']
        indexes = [
            models.Index(fields=['-sale_date']),
            models.Index(fields=['seller', '-sale_date']),
            models.Index(fields=['etr_receipt_number']),
            models.Index(fields=['sequence_number']),
            models.Index(fields=['sale_id']),
        ]

    def __str__(self) -> str:
        item_count = self.items.count()
        return f"Sale #{self.sale_id} - {item_count} item(s) - KSH {self.total_amount}"

    def save(self, *args, **kwargs):
        is_new = not self.sale_id or self._state.adding
        
        if is_new:
            # Generate new sequence number
            self.sequence_number = generate_next_counter()
            self.sale_id = f"SALE-{self.sequence_number:05d}"
            self.etr_receipt_number = f"{self.sequence_number:05d}"
            
            logger.info(
                f"[SALE CREATED] Sale ID: {self.sale_id} | "
                f"ETR Receipt: {self.etr_receipt_number} | "
                f"Sequence: {self.sequence_number:05d}"
            )
        
        super().save(*args, **kwargs)

    def recalculate_totals(self):
        """Recalculate totals from all items"""
        items_aggregate = self.items.aggregate(
            total_qty=Sum('quantity'),
            total_amount=Sum('total_price')
        )
        
        self.total_quantity = items_aggregate['total_qty'] or 0
        self.subtotal = items_aggregate['total_amount'] or Decimal('0.00')
        self.total_amount = self.subtotal + self.tax_amount
        self.save(update_fields=['total_quantity', 'subtotal', 'total_amount'])

    def assign_etr_receipt_number(self, fiscal_receipt_number: str = None):
        """
        Assign ETR receipt number (already set during save, but here for compatibility)
        """
        if self.etr_receipt_number:
            logger.warning(
                f"Sale {self.sale_id} already has ETR receipt number: "
                f"{self.etr_receipt_number}"
            )
            return
        
        # ETR receipt number is already set during save
        # This method is kept for compatibility with external systems
        
        if fiscal_receipt_number:
            self.fiscal_receipt_number = fiscal_receipt_number
        
        self.etr_processed_at = timezone.now()
        self.etr_status = 'processed'
        
        self.save(update_fields=[
            'fiscal_receipt_number',
            'etr_processed_at',
            'etr_status'
        ])
        
        logger.info(
            f"[ETR ASSIGNED] Sale: {self.sale_id} | "
            f"Receipt: {self.etr_receipt_number} | "
            f"Items: {self.items.count()}"
        )

    # ============================================
    # REVERSE SALE METHOD
    # ============================================
    def reverse_sale(self, reversed_by=None, reason=''):
        """
        Reverse this sale:
        - Restock products (single and bulk)
        - Create stock entries for the reversal
        - Mark the sale as reversed
        """
        if self.is_reversed:
            return f"Sale {self.sale_id} already reversed"
        
        try:
            with transaction.atomic():
                reversed_items = []
                
                for item in self.items.all():
                    product = item.product
                    
                    # Store old values for logging
                    old_quantity = product.quantity
                    old_status = product.status
                    
                    logger.info(f"Reversing item: {product.product_code}, Status: {old_status}, Quantity: {old_quantity}")
                    
                    # ============================================
                    # PROPERLY RESTORE PRODUCT
                    # ============================================
                    if product.category.is_single_item:
                        # Single item: Restore to available (status only, no quantity)
                        product.status = 'available'
                        # Quantity remains 0 (not used for single items)
                        logger.info(f"Single item {product.product_code}: Status changed to 'available'")
                    else:
                        # Bulk item: Add quantity back
                        product.quantity += item.quantity
                        # If quantity > 0 and status was 'outofstock', set to available
                        if product.quantity > 0 and product.status in ['outofstock', 'sold']:
                            product.status = 'available'
                        logger.info(f"Bulk item {product.product_code}: Quantity restored to {product.quantity}")
                    
                    # Save the product
                    product.save()
                    
                    # Create stock entry for the reversal
                    stock_entry = StockEntry.objects.create(
                        product=product,
                        quantity=item.quantity,
                        entry_type='reversal',
                        unit_price=item.unit_price,
                        total_amount=item.total_price,
                        reference_id=f"REVERSE-{self.sale_id}",
                        created_by=reversed_by,
                        notes=f"Reversal of sale {self.sale_id}. Reason: {reason}" if reason else f"Reversal of sale {self.sale_id}"
                    )
                    
                    reversed_items.append({
                        'product': product.product_code,
                        'name': product.display_name,
                        'quantity': item.quantity,
                        'old_status': old_status,
                        'new_status': product.status,
                        'old_quantity': old_quantity,
                        'new_quantity': product.quantity
                    })
                    
                    logger.info(f"Stock entry created: {stock_entry.id} for product {product.product_code}")
                
                # Mark sale as reversed
                self.is_reversed = True
                self.reversed_at = timezone.now()
                self.reversed_by = reversed_by
                self.reversal_reason = reason
                self.save()
                
                # Log summary
                logger.info(
                    f"SALE REVERSED: #{self.sale_id} | "
                    f"Items: {len(reversed_items)} | "
                    f"Reason: {reason or 'Not specified'} | "
                    f"By: {reversed_by.username if reversed_by else 'System'}"
                )
                
                return f"Sale #{self.sale_id} reversed successfully. {len(reversed_items)} items restored to inventory."
                
        except Exception as e:
            logger.error(f"Error reversing sale {self.sale_id}: {str(e)}")
            raise

    # ============================================
    # PROPERTIES
    # ============================================
    
    @property
    def can_be_reversed(self) -> bool:
        return not self.is_reversed

    @property
    def item_count(self) -> int:
        return self.items.count()
    
    @property
    def has_sku_items(self):
        return self.items.filter(product__sku_value__isnull=False).exclude(product__sku_value="").exists()
    
    @property
    def reversed(self):
        """Alias for is_reversed for template compatibility"""
        return self.is_reversed
    
    @property
    def change(self):
        """Calculate change amount"""
        if self.amount_paid and self.total_amount:
            return self.amount_paid - self.total_amount
        return Decimal('0.00')

    @property
    def balance(self):
        """Calculate balance if payment is insufficient"""
        if self.amount_paid and self.total_amount and self.amount_paid < self.total_amount:
            return self.total_amount - self.amount_paid
        return Decimal('0.00')


# ==================================
# SALE ITEM MODEL
# ==================================

class SaleItem(models.Model):
    """
    Individual items within a sale
    - Links to parent Sale record
    - Stores product details at time of sale
    - Properly handles single items vs bulk items
    """
    
    sale = models.ForeignKey('Sale', on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='sale_items',
        help_text="Product sold"
    )
    
    # Product details at time of sale (frozen snapshot)
    product_code = models.CharField(max_length=100)
    product_name = models.CharField(max_length=255)
    sku_value = models.CharField(max_length=200, blank=True, null=True)
    
    # Quantities and pricing
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    total_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    
    # FIFO tracking
    created_at = models.DateTimeField(auto_now_add=True)
    product_age_days = models.PositiveIntegerField(
        default=0,
        help_text="Age of product when sold (for FIFO verification)"
    )

    class Meta:
        db_table = 'sale_items'
        ordering = ['id']
        indexes = [
            models.Index(fields=['sale', 'product']),
            models.Index(fields=['product']),
        ]

    def __str__(self):
        return f"{self.product_name} x{self.quantity} - KSH {self.total_price}"

    def save(self, *args, **kwargs):
        # Calculate total if not set
        if not self.total_price:
            self.total_price = self.unit_price * self.quantity
        
        # Calculate product age at time of sale
        if not self.product_age_days and self.product:
            self.product_age_days = (timezone.now() - self.product.created_at).days
        
        super().save(*args, **kwargs)
        
        # Update parent sale totals
        self.sale.recalculate_totals()

    # ============================================
    # CAN BE SOLD METHOD
    # ============================================
    def can_be_sold(self) -> tuple:
        """
        Check if this item can be sold
        Returns: (bool, str) - (can_sell, reason_if_not)
        """
        try:
            product = self.product
            
            # Refresh product from database to get latest status
            product.refresh_from_db()
            
            if product.category.is_single_item:
                # Single items: just check status
                if product.status == 'sold':
                    return False, f"Item {product.display_name} has already been sold"
                if self.quantity != 1:
                    return False, "Single items must be sold one at a time"
                
                # Check if this product appears in any active sale (not reversed)
                from sales.models import SaleItem
                active_sales = SaleItem.objects.filter(
                    product=product,
                    sale__is_reversed=False
                ).exclude(sale=self.sale if self.sale_id else None)
                
                if active_sales.exists():
                    return False, f"Item {product.display_name} has already been sold in another transaction"
            else:
                # Bulk items: check quantity
                if product.quantity < self.quantity:
                    return False, f"Insufficient stock. Available: {product.quantity}, Requested: {self.quantity}"
            
            return True, "Available for sale"
            
        except Exception as e:
            logger.error(f"Error checking availability: {str(e)}")
            return False, f"Error checking availability: {str(e)}"

    def process_sale(self):
        """
        Process this item's sale (deduct stock)
        - For single items: Mark as SOLD (no quantity change)
        - For bulk items: Reduce quantity
        - Create stock entry for the sale
        """
        with transaction.atomic():
            # Lock the product row to prevent race conditions
            product = Product.objects.select_for_update().get(pk=self.product.pk)
            
            # Store old values for logging
            old_quantity = product.quantity
            old_status = product.status
            
            # Update product based on type
            if product.category.is_single_item:
                # Single item: just mark as sold - NO QUANTITY CHANGE
                if product.status == 'sold':
                    raise ValueError(
                        f"Cannot sell {product.display_name} - "
                        f"This item has already been sold"
                    )
                product.status = 'sold'
                # Quantity remains 0 (not used for single items)
                log_type = "SINGLE ITEM"
            else:
                # Bulk item: reduce quantity
                if product.quantity < self.quantity:
                    raise ValueError(
                        f"Insufficient stock for {product.display_name}. "
                        f"Available: {product.quantity}, Requested: {self.quantity}"
                    )
                product.quantity -= self.quantity
                log_type = "BULK ITEM"
            
            # Save product
            product.save()
            
            # Create stock entry for the sale
            stock_entry = StockEntry.objects.create(
                product=product,
                quantity=-self.quantity if not product.category.is_single_item else -1,
                entry_type='sale',
                unit_price=self.unit_price,
                total_amount=self.total_price,
                reference_id=f"SALE-{self.sale.sale_id}",
                created_by=self.sale.seller,
                notes=f"Sale #{self.sale.sale_id} - {self.product_name}"
            )
            
            # Detailed logging
            logger.info(
                f"[SALE ITEM PROCESSED] "
                f"Sale: {self.sale.sale_id} | "
                f"Type: {log_type} | "
                f"Product: {product.product_code} | "
                f"Name: {product.display_name} | "
                f"Quantity: {self.quantity} | "
                f"Old Status: {old_status} | "
                f"New Status: {product.status} | "
                f"Unit Price: KSH {self.unit_price} | "
                f"Total: KSH {self.total_price}"
            )
            
            return True

    @property
    def item_type(self) -> str:
        """Return item type (Single/Bulk)"""
        return "Single" if self.product.category.is_single_item else "Bulk"
    
    @property
    def profit(self) -> Decimal:
        """Calculate profit for this item"""
        if self.product.buying_price:
            return (self.unit_price - self.product.buying_price) * self.quantity
        return Decimal('0.00')
    
    @property
    def margin_percentage(self) -> float:
        """Calculate profit margin percentage"""
        if self.product.buying_price and self.product.buying_price > 0:
            profit_per_unit = self.unit_price - self.product.buying_price
            return float((profit_per_unit / self.product.buying_price) * 100)
        return 0.0


# ============================================
# PAYMENT RECORD MODEL - FOR SPLIT PAYMENTS
# ============================================

class PaymentRecord(models.Model):
    """
    Individual payment records for split payments
    One sale can have multiple payment records (Cash, M-Pesa, Card, Points)
    """
    
    PAYMENT_METHODS = [
        ('Cash', 'Cash'),
        ('M-Pesa', 'M-Pesa'),
        ('Card', 'Card/Bank'),
        ('Points', 'Loyalty Points'),
    ]
    
    sale = models.ForeignKey(
        'Sale', 
        on_delete=models.CASCADE, 
        related_name='payment_records'
    )
    method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Cash specific fields
    cash_tendered = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cash_change = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # M-Pesa specific fields
    mpesa_phone = models.CharField(max_length=20, blank=True, null=True)
    mpesa_transaction_id = models.CharField(max_length=50, blank=True, null=True)
    mpesa_checkout_request_id = models.CharField(max_length=100, blank=True, null=True)
    
    # Card/Bank specific fields
    bank_name = models.CharField(max_length=50, blank=True, null=True)
    card_last_four = models.CharField(max_length=4, blank=True, null=True)
    
    # Points specific fields
    points_redeemed = models.IntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_payments'
    )
    
    class Meta:
        db_table = 'payment_records'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sale', 'method']),
            models.Index(fields=['mpesa_transaction_id']),
        ]
        verbose_name = 'Payment Record'
        verbose_name_plural = 'Payment Records'
    
    def __str__(self):
        return f"{self.method} - KSH {self.amount} for Sale #{self.sale.sale_id}"
    
    @property
    def display_amount(self):
        return f"KSH {self.amount:,.2f}"


# ==================================
# SALE REVERSAL MODEL
# ==================================

class SaleReversal(models.Model):
    """
    Reversal record for entire sale (all items)
    Handles the reversal process for both single and bulk items
    """
    
    sale = models.OneToOneField(Sale, related_name='reversal', on_delete=models.CASCADE)
    reversed_at = models.DateTimeField(auto_now_add=True)
    reversed_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name="sale_reversals"
    )
    reason = models.TextField(blank=True, null=True)
    
    # Tracking fields
    items_processed = models.PositiveIntegerField(default=0, help_text="Number of items reversed")
    total_amount_reversed = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        default=Decimal('0.00'),
        help_text="Total amount reversed"
    )
    reversal_reference = models.CharField(
        max_length=100, 
        blank=True, 
        null=True,
        help_text="Reference ID for the reversal transaction"
    )

    class Meta:
        verbose_name = "Sale Reversal"
        verbose_name_plural = "Sale Reversals"
        ordering = ['-reversed_at']
        indexes = [
            models.Index(fields=['-reversed_at']),
            models.Index(fields=['sale']),
        ]

    def __str__(self) -> str:
        return f"Reversal for Sale #{self.sale.sale_id} - {self.reversed_at.strftime('%Y-%m-%d %H:%M')}"

    def save(self, *args, **kwargs):
        """Generate reversal reference if not provided"""
        if not self.reversal_reference:
            self.reversal_reference = f"REV-{self.sale.sale_id}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        super().save(*args, **kwargs)

    def process_reversal(self):
        """
        Reverse all items in the sale
        - Single items: Mark as 'available' (no quantity)
        - Bulk items: Add quantity back to stock
        - Create stock entries for each reversed item
        - Mark the original sale as reversed
        """
        # Check if sale is already reversed
        if self.sale.is_reversed:
            logger.warning(
                f"[REVERSAL FAILED] Sale #{self.sale.sale_id} "
                f"has already been reversed at {self.sale.reversed_at}"
            )
            raise ValueError(f"Sale #{self.sale.sale_id} has already been reversed.")

        logger.info(
            f"[REVERSAL STARTED] Sale #{self.sale.sale_id} | "
            f"Items: {self.sale.items.count()} | "
            f"Reason: {self.reason or 'Not specified'} | "
            f"By: {self.reversed_by.username if self.reversed_by else 'System'}"
        )

        with transaction.atomic():
            reversed_items = []
            total_reversed = Decimal('0.00')
            
            for item in self.sale.items.all():
                # Lock product row for safe stock update
                product = Product.objects.select_for_update().get(pk=item.product_id)
                
                # Store old values for logging
                old_quantity = product.quantity
                old_status = product.status
                
                # -------------------------
                # UPDATE PRODUCT BASED ON TYPE
                # -------------------------
                if product.category.is_single_item:
                    # Single item: restore to available (status only)
                    product.status = 'available'
                    # Quantity remains 0 (not used)
                    reversal_type = "SINGLE ITEM"
                else:
                    # Bulk item: add quantity back
                    product.quantity += item.quantity
                    reversal_type = "BULK ITEM"
                
                # Save product
                product.save()
                
                # -------------------------
                # LOG STOCK ENTRY
                # -------------------------
                stock_entry = StockEntry.objects.create(
                    product=product,
                    quantity=item.quantity,
                    entry_type='reversal',
                    unit_price=item.unit_price,
                    total_amount=item.total_price,
                    reference_id=f"REV-{self.sale.sale_id}",
                    created_by=self.reversed_by,
                    notes=f"Reversal of Sale #{self.sale.sale_id} - {self.reason or 'No reason provided'}"
                )
                
                # Track reversed amount
                total_reversed += item.total_price
                reversed_items.append({
                    'product': product.product_code,
                    'name': product.display_name,
                    'quantity': item.quantity,
                    'amount': item.total_price,
                    'type': reversal_type
                })
                
                logger.info(
                    f"[REVERSAL ITEM] "
                    f"Sale: {self.sale.sale_id} | "
                    f"Type: {reversal_type} | "
                    f"Product: {product.product_code} | "
                    f"Name: {product.display_name} | "
                    f"Quantity: {item.quantity} | "
                    f"Stock: {old_quantity} → {product.quantity} | "
                    f"Status: {old_status} → {product.status} | "
                    f"Amount: KSH {item.total_price}"
                )

            # -------------------------
            # MARK SALE AS REVERSED
            # -------------------------
            self.sale.is_reversed = True
            self.sale.reversed_at = self.reversed_at
            self.sale.reversal_reason = self.reason
            self.sale.reversed_by = self.reversed_by
            self.sale.save(update_fields=[
                'is_reversed', 
                'reversed_at', 
                'reversal_reason', 
                'reversed_by'
            ])
            
            # Update reversal record with totals
            self.items_processed = len(reversed_items)
            self.total_amount_reversed = total_reversed
            self.save(update_fields=['items_processed', 'total_amount_reversed'])

            # Summary logging
            logger.info(
                f"[REVERSAL COMPLETED] "
                f"Sale: {self.sale.sale_id} | "
                f"Items Processed: {len(reversed_items)} | "
                f"Total Amount: KSH {total_reversed} | "
                f"Reference: {self.reversal_reference}"
            )

            return True

    def can_reverse(self) -> tuple:
        """
        Check if the sale can be reversed
        Returns: (bool, str) - (can_reverse, reason_if_not)
        """
        if self.sale.is_reversed:
            return False, f"Sale #{self.sale.sale_id} has already been reversed"
        
        if self.sale.items.count() == 0:
            return False, f"Sale #{self.sale.sale_id} has no items to reverse"
        
        for item in self.sale.items.all():
            if item.product is None:
                return False, f"Item {item.product_name} has no associated product"
        
        return True, "Sale can be reversed"

    @property
    def is_successful(self) -> bool:
        """Check if reversal was processed"""
        return self.items_processed > 0
    
    @property
    def formatted_amount(self) -> str:
        """Format total reversed amount"""
        return f"KSH {self.total_amount_reversed:,.0f}"
    
    @property
    def time_ago(self) -> str:
        """Get time since reversal"""
        from django.utils.timesince import timesince
        return timesince(self.reversed_at)


# ==================================
# FISCAL RECEIPT MODEL
# ==================================

class FiscalReceipt(models.Model):
    """Fiscal receipt for entire sale"""
    
    sale = models.OneToOneField(Sale, related_name='fiscal_receipt', on_delete=models.CASCADE)
    receipt_number = models.CharField(max_length=100, unique=True)
    issued_at = models.DateTimeField(default=timezone.now)
    qr_code = models.TextField(blank=True, null=True)
    verification_url = models.URLField(blank=True, null=True)
    receipt_data = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = 'Fiscal Receipt'
        verbose_name_plural = 'Fiscal Receipts'
        ordering = ['-issued_at']

    def __str__(self) -> str:
        return f"Receipt {self.receipt_number} for Sale #{self.sale.sale_id}"


# ====================================
# CUSTOMER MODEL - SIMPLE LOYALTY PROGRAM
# 1% of sale value = points earned
# ====================================

from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
import logging

logger = logging.getLogger(__name__)


class Customer(models.Model):
    """Customer model for simple loyalty program - 1% of sale value = points earned"""
    
    # Basic Info
    phone_number = models.CharField(
        max_length=20, 
        unique=True, 
        db_index=True,
        help_text="Unique phone number used for customer identification"
    )
    full_name = models.CharField(
        max_length=200, 
        blank=False, 
        null=False,
        default="Unknown Customer"
    )
    email = models.EmailField(blank=True, null=True)
    id_number = models.CharField(max_length=50, blank=True, null=True)
    
    # Loyalty Points - Decimal to support fractional points (e.g., 1.5 points)
    points_balance = models.DecimalField(
        max_digits=10, 
        decimal_places=1, 
        default=Decimal('0.0'),
        help_text="Current loyalty points balance (1 point = KSH 1 value)"
    )
    total_points_earned = models.DecimalField(
        max_digits=10, 
        decimal_places=1, 
        default=Decimal('0.0'),
        help_text="Total points earned all time"
    )
    total_points_redeemed = models.DecimalField(
        max_digits=10, 
        decimal_places=1, 
        default=Decimal('0.0'),
        help_text="Total points redeemed"
    )
    
    # Statistics
    total_purchases = models.PositiveIntegerField(default=0)
    total_spent = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    last_purchase_date = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    # Registration source
    registered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registered_customers'
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['phone_number']),
            models.Index(fields=['-created_at']),
        ]
        verbose_name = "Customer"
        verbose_name_plural = "Customers"
    
    def __str__(self):
        return f"{self.full_name} ({self.phone_number}) - {self.points_balance} pts"
    
    def save(self, *args, **kwargs):
        if not self.full_name:
            self.full_name = f"Customer {self.phone_number}"
        super().save(*args, **kwargs)
    
    def calculate_points_to_earn(self, amount):
        """
        Calculate points based on amount spent.
        1% of total sale value = points earned
        
        Examples:
        - KSH 100 = 1.0 point (1% of 100)
        - KSH 150 = 1.5 points (1% of 150)
        - KSH 200 = 2.0 points (1% of 200)
        - KSH 1,000 = 10.0 points (1% of 1,000)
        - KSH 10,000 = 100.0 points (1% of 10,000)
        - KSH 90,000 = 900.0 points (1% of 90,000)
        - KSH 100,000 = 1,000.0 points (1% of 100,000)
        """
        if amount < 100:
            return Decimal('0.0')
        
        # Calculate 1% of amount
        points = Decimal(str(amount)) * Decimal('0.01')
        
        # Round to 1 decimal place
        points = points.quantize(Decimal('0.1'))
        
        return points
    
    def add_points(self, points, sale=None, description=""):
        """
        Add points directly to customer balance
        Accepts Decimal points (e.g., 1.5 points)
        
        Args:
            points: Number of points to add (supports decimals like 1.5)
            sale: Optional Sale object to link transaction
            description: Optional description string
        
        Returns:
            Decimal: Number of points actually added
        """
        if not self.pk or not self.phone_number:
            logger.warning("Attempted to add points to unregistered customer - BLOCKED")
            return Decimal('0.0')
        
        # Convert to Decimal with 1 decimal place
        points_to_add = Decimal(str(points)).quantize(Decimal('0.1'))
        
        if points_to_add <= 0:
            return Decimal('0.0')
        
        # Convert existing balances to Decimal
        current_balance = Decimal(str(self.points_balance))
        current_total_earned = Decimal(str(self.total_points_earned))
        
        # Update customer balance
        self.points_balance = current_balance + points_to_add
        self.total_points_earned = current_total_earned + points_to_add
        
        self.save(update_fields=['points_balance', 'total_points_earned'])
        
        # Update customer statistics if sale is provided
        if sale:
            self.total_purchases += 1
            self.total_spent += sale.total_amount
            self.last_purchase_date = timezone.now()
            self.save(update_fields=['total_purchases', 'total_spent', 'last_purchase_date'])
        
        # Create loyalty transaction record
        LoyaltyTransaction.objects.create(
            customer=self,
            sale=sale,
            points=points_to_add,
            transaction_type='earned',
            description=description or f"Earned {points_to_add} points"
        )
        
        logger.info(f"✅ Customer {self.phone_number} earned {points_to_add} points")
        return points_to_add
    
    def add_points_from_sale(self, sale, description=""):
        """
        Add points to customer balance based on sale amount.
        1% of sale total = points earned
        
        Args:
            sale: Sale object to calculate points from
            description: Optional description string
        
        Returns:
            Decimal: Number of points actually added
        """
        if not self.pk or not self.phone_number:
            logger.warning("Attempted to add points to unregistered customer - BLOCKED")
            return Decimal('0.0')
        
        if not sale:
            return Decimal('0.0')
        
        # Calculate points as 1% of sale total
        points_to_add = self.calculate_points_to_earn(float(sale.total_amount))
        
        if points_to_add <= 0:
            return Decimal('0.0')
        
        # Update customer balance
        self.points_balance = Decimal(str(self.points_balance)) + points_to_add
        self.total_points_earned = Decimal(str(self.total_points_earned)) + points_to_add
        
        self.save(update_fields=['points_balance', 'total_points_earned'])
        
        # Update customer statistics
        self.total_purchases += 1
        self.total_spent += sale.total_amount
        self.last_purchase_date = timezone.now()
        self.save(update_fields=['total_purchases', 'total_spent', 'last_purchase_date'])
        
        # Create loyalty transaction record
        LoyaltyTransaction.objects.create(
            customer=self,
            sale=sale,
            points=points_to_add,
            transaction_type='earned',
            description=description or f"Earned {points_to_add} points (1% of KSH {sale.total_amount:,.0f})"
        )
        
        logger.info(f"✅ Customer {self.phone_number} earned {points_to_add} points (1% of {sale.total_amount})")
        return points_to_add
    
    def redeem_points(self, points_to_redeem, sale=None, description=""):
        """
        Redeem points from customer balance (1 point = KSH 1 discount)
        
        Args:
            points_to_redeem: Number of points to redeem (supports decimals)
            sale: Optional Sale object to link transaction
            description: Optional description string
        
        Returns:
            Decimal: Cash value of redeemed points (1 point = KSH 1)
        """
        if not self.pk or not self.phone_number:
            logger.warning("Attempted to redeem points for unregistered customer - BLOCKED")
            raise ValueError("Cannot redeem points: Customer is not registered")
        
        points_to_redeem = Decimal(str(points_to_redeem)).quantize(Decimal('0.1'))
        
        if points_to_redeem <= 0:
            raise ValueError("Points to redeem must be greater than 0")
        
        current_balance = Decimal(str(self.points_balance))
        
        if current_balance < points_to_redeem:
            raise ValueError(f"Insufficient points. Available: {current_balance}, Requested: {points_to_redeem}")
        
        # Deduct points
        self.points_balance = current_balance - points_to_redeem
        self.total_points_redeemed = Decimal(str(self.total_points_redeemed)) + points_to_redeem
        self.save(update_fields=['points_balance', 'total_points_redeemed'])
        
        # Create loyalty transaction record (negative points for redemption)
        LoyaltyTransaction.objects.create(
            customer=self,
            sale=sale,
            points=-points_to_redeem,
            transaction_type='redeemed',
            description=description or f"Redeemed {points_to_redeem} points"
        )
        
        cash_value = points_to_redeem  # 1 point = KSH 1
        logger.info(f"💰 Customer {self.phone_number} redeemed {points_to_redeem} points (KSH {cash_value})")
        
        return cash_value
    
    def can_redeem(self, points_to_redeem, sale_total):
        """
        Check if customer can redeem specified points.
        
        Returns:
            tuple: (can_redeem: bool, message: str, max_points: Decimal)
        """
        if not self.pk or not self.phone_number:
            return False, "Customer is not registered", Decimal('0.0')
        
        points_to_redeem = Decimal(str(points_to_redeem)).quantize(Decimal('0.1'))
        
        if points_to_redeem <= 0:
            return False, "Points to redeem must be greater than 0", Decimal('0.0')
        
        current_balance = Decimal(str(self.points_balance))
        
        if current_balance < points_to_redeem:
            return False, f"Insufficient points. Available: {current_balance}", current_balance
        
        if points_to_redeem > sale_total:
            max_points = Decimal(str(sale_total)).quantize(Decimal('0.1'))
            return False, f"Points cannot exceed sale amount. Max: {max_points} points", max_points
        
        return True, "Can redeem", points_to_redeem
    
    @property
    def is_registered(self):
        """Check if customer is properly registered"""
        return bool(self.pk and self.phone_number and self.full_name)
    
    @property
    def points_value_ksh(self):
        """Cash value of points (1 point = KSH 1)"""
        return Decimal(str(self.points_balance))
    
    @property
    def display_points(self):
        """Format points for display (e.g., '1.5')"""
        points = Decimal(str(self.points_balance))
        if points == int(points):
            return str(int(points))
        return str(points)


class LoyaltyTransaction(models.Model):
    """Track all loyalty point movements"""
    
    TRANSACTION_TYPES = [
        ('earned', 'Points Earned'),
        ('redeemed', 'Points Redeemed'),
        ('expired', 'Points Expired'),
        ('adjusted', 'Manual Adjustment'),
    ]
    
    customer = models.ForeignKey(
        Customer, 
        on_delete=models.CASCADE,
        related_name='loyalty_transactions'
    )
    sale = models.ForeignKey(
        'sales.Sale', 
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='loyalty_transactions'
    )
    points = models.DecimalField(
        max_digits=10, 
        decimal_places=1,
        default=Decimal('0.0'),
        help_text="Positive for earned, negative for redeemed"
    )
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    description = models.CharField(max_length=255, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['customer', '-created_at']),
            models.Index(fields=['sale']),
        ]
        verbose_name = "Loyalty Transaction"
        verbose_name_plural = "Loyalty Transactions"
    
    def __str__(self):
        sign = "+" if self.points > 0 else ""
        return f"{self.customer} - {sign}{self.points} ({self.transaction_type})"
    
    @property
    def points_abs(self):
        """Absolute value of points (for display)"""
        return abs(float(self.points))
    
    @property
    def is_earned(self):
        return self.transaction_type == 'earned'
    
    @property
    def is_redeemed(self):
        return self.transaction_type == 'redeemed'
    
    @property
    def display_points(self):
        """Format points for display"""
        points = abs(self.points)
        if points == int(points):
            return str(int(points))
        return str(points)


class LoyaltySettings(models.Model):
    """Global loyalty program settings"""
    
    min_purchase_for_points = models.PositiveIntegerField(
        default=100,
        help_text="Minimum purchase amount to earn points (KSH)"
    )
    points_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('1.00'),
        help_text="Percentage of sale to award as points (e.g., 1.00 = 1%)"
    )
    max_points_per_transaction = models.PositiveIntegerField(
        default=100000,
        help_text="Maximum points that can be earned in a single transaction"
    )
    min_redeem_points = models.PositiveIntegerField(
        default=1,
        help_text="Minimum points required to redeem"
    )
    max_redeem_percentage = models.PositiveIntegerField(
        default=100,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Maximum percentage of sale that can be paid with points"
    )
    points_expiry_days = models.PositiveIntegerField(
        default=365,
        help_text="Number of days before points expire"
    )
    welcome_points = models.PositiveIntegerField(
        default=10,
        help_text="Points awarded to new customers on registration"
    )
    require_id_for_registration = models.BooleanField(
        default=False,
        help_text="Require ID number for customer registration"
    )
    require_email_for_registration = models.BooleanField(
        default=False,
        help_text="Require email for customer registration"
    )
    
    class Meta:
        verbose_name = "Loyalty Settings"
        verbose_name_plural = "Loyalty Settings"
    
    def __str__(self):
        return f"Loyalty Program Settings ({self.points_percentage}% of sale = points)"
    
    @classmethod
    def get_settings(cls):
        """Get or create default settings"""
        settings, created = cls.objects.get_or_create(pk=1)
        return settings