from django.db import models

# Create your models here.
# ==============================
# SALE IMPORTS
# ==============================

from decimal import Decimal
import uuid
import logging
from django.db import models, transaction
from django.db.models import F, Max, Sum
from django.contrib.auth.models import User
from django.utils import timezone
from inventory.models import Product, StockEntry
import re

    

logger = logging.getLogger(__name__)




# ============================================
# SALE COUNTER MODEL
# ============================================

class SaleCounter(models.Model):
    """
    Tracks sale counters per year for generating sequential sale IDs
    This ensures uniqueness even with concurrent transactions
    """
    year = models.PositiveIntegerField(unique=True, primary_key=True)
    counter = models.PositiveIntegerField(default=0)
    
    class Meta:
        db_table = 'sale_counters'
        verbose_name = 'Sale Counter'
        verbose_name_plural = 'Sale Counters'
    
    def __str__(self):
        return f"Year {self.year}: {self.counter} sales"












# ============================================
# UPDATED SALE ID GENERATOR
# ============================================

def generate_custom_sale_id() -> str:
    """
    Generate sale ID using dedicated counter table
    Format: FSL{YEAR}{SEQUENTIAL_NUMBER}
    Examples: FSL2025001, FSL2025002, FSL2025003
    
    Features:
    - Atomic counter increment (no race conditions)
    - Year-based reset (counter restarts each year)
    - Zero-padded 3-digit counter
    """
    current_year = timezone.now().year
    
    with transaction.atomic():
        # Get or create counter for current year with database lock
        counter_obj, created = SaleCounter.objects.select_for_update().get_or_create(
            year=current_year,
            defaults={'counter': 0}
        )
        
        # Increment counter atomically
        counter_obj.counter += 1
        counter_obj.save(update_fields=['counter'])
        
        # Format: FSL + YEAR + COUNTER (zero-padded to 3 digits)
        sale_id = f"FSL{current_year}{counter_obj.counter:03d}"
        
        logger.info(
            f"[SALE ID GENERATED] Year: {current_year} | "
            f"Counter: {counter_obj.counter} | Sale ID: {sale_id}"
        )
        
        return sale_id









# ==================================
# SALE MODEL
# ==================================

class Sale(models.Model):
    """
    ✅ FIXED: Represents ONE TRANSACTION (not one item)
    - Each sale can have multiple items (stored in SaleItem)
    - One receipt number per sale
    - One row in sales table per transaction
    """

    batch_id = models.CharField(max_length=50, blank=True, null=True)  # Add this
    payment_method = models.CharField(max_length=50, default='Cash')    # Add this
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # Add this
    sale_id = models.CharField(max_length=40, primary_key=True, editable=False)
    
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
    
    # Receipt numbers (ONE per sale, not per item)
    etr_receipt_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        help_text="ETR receipt number in format Rcpt_No:0001"
    )
    etr_receipt_counter = models.PositiveIntegerField(
        blank=True,
        null=True,
        db_index=True,
        help_text="Sequential counter for ETR receipts (1, 2, 3...)"
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
        choices=[
            ('pending', 'Pending'),
            ('processed', 'Processed'),
            ('failed', 'Failed')
        ],
        default='pending'
    )
    
    # Credit sale tracking
    is_credit = models.BooleanField(default=False, help_text="Whether this sale is on credit")
    credit_sale_id = models.CharField(max_length=50, blank=True, null=True, help_text="Reference to credit app sale ID")

    payment_method = models.CharField(
        max_length=20,
        choices=[
            ('Cash', 'Cash'),
            ('M-Pesa', 'M-Pesa'),
            ('Card', 'Card'),
            ('Points', 'Points'),
            ('Credit', 'Credit'),
        ],
        default='Cash'
    )

    etr_processed_at = models.DateTimeField(blank=True, null=True)
    etr_error_message = models.TextField(blank=True, null=True)
    
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

    class Meta:
        db_table = 'sales'
        ordering = ['-sale_date']
        indexes = [
            models.Index(fields=['-sale_date']),
            models.Index(fields=['seller', '-sale_date']),
            models.Index(fields=['etr_receipt_number']),
            models.Index(fields=['etr_receipt_counter']),
        ]

    def __str__(self) -> str:
        item_count = self.items.count()
        return f"Sale #{self.sale_id} - {item_count} item(s) - KSH {self.total_amount}"

    def save(self, *args, **kwargs):
        if not self.sale_id:
            # Find the highest numeric sale_id
            max_sale = Sale.objects.all().order_by('-sale_id').first()
            if max_sale:
                # Extract numeric part
                match = re.search(r'\d+', max_sale.sale_id)
                if match:
                    next_number = int(match.group()) + 1
                else:
                    next_number = 500  # Start from 500 if no numeric found
            else:
                next_number = 500  # First sale starts from 500
            
            # Ensure we start from 500 minimum
            if next_number < 500:
                next_number = 500
            
            self.sale_id = f"SALE-{next_number:04d}"  # Format as SALE-0500
        
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
        """Assign sequential ETR receipt number"""
        if self.etr_receipt_number:
            logger.warning(
                f"Sale {self.sale_id} already has ETR receipt number: "
                f"{self.etr_receipt_number}"
            )
            return
        
        with transaction.atomic():
            max_counter = Sale.objects.select_for_update().aggregate(
                max_counter=Max('etr_receipt_counter')
            )['max_counter']
            
            next_counter = (max_counter or 0) + 1
            
            self.etr_receipt_counter = next_counter
            self.etr_receipt_number = f"{next_counter:04d}"
            if fiscal_receipt_number:
                self.fiscal_receipt_number = fiscal_receipt_number
            self.etr_processed_at = timezone.now()
            self.etr_status = 'processed'
            
            self.save(update_fields=[
                'etr_receipt_counter',
                'etr_receipt_number',
                'fiscal_receipt_number',
                'etr_processed_at',
                'etr_status'
            ])
            
            logger.info(
                f"[ETR ASSIGNED] Sale: {self.sale_id} | Receipt: {self.etr_receipt_number} | "
                f"Counter: {next_counter} | Items: {self.items.count()}"
            )

  

    def reverse_sale(self, reversed_by=None):
        """
        Reverse this sale:
        - Restock products (single and bulk)
        - Create stock entries for the reversal
        - Mark the sale as reversed
        """
        if self.is_reversed:
            return f"Sale {self.sale_id} already reversed"

        for item in self.items.all():
            product = item.product
            if product.category.is_single_item:
                product.status = 'available'
            else:
                product.quantity += item.quantity
            product.save()

            StockEntry.objects.create(
                product=product,
                quantity=item.quantity,
                unit_price=product.buying_price,
                reference_id=f"REVERSE-{self.sale_id}",
                notes=f"Reversal of sale {self.sale_id}",
            )

        self.is_reversed = True
        self.reversed_at = timezone.now()
        self.reversed_by = reversed_by
        self.save()

        return f"Sale {self.sale_id} reversed successfully!"


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





#======================================
# SALE ITEM MODEL
#======================================

class SaleItem(models.Model):
    """
    ✅ FIXED: Individual items within a sale
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

    def process_sale(self):
        """
        Process this item's sale (deduct stock)
        - For single items: Mark as SOLD and set quantity to 0
        - For bulk items: Reduce quantity
        - Create stock entry for the sale
        """
        with transaction.atomic():
            # Lock the product row to prevent race conditions
            product = Product.objects.select_for_update().get(pk=self.product.pk)
            
            # Check if product is already sold (for single items)
            if product.category.is_single_item:
                if product.status == 'sold' or product.quantity <= 0:
                    raise ValueError(
                        f"Cannot sell {product.display_name} - "
                        f"This item has already been sold"
                    )
                if self.quantity != 1:
                    raise ValueError(
                        f"Single items must be sold with quantity 1. "
                        f"Requested: {self.quantity}"
                    )
            else:
                # Bulk items check
                if product.quantity < self.quantity:
                    raise ValueError(
                        f"Insufficient stock for {product.display_name}. "
                        f"Available: {product.quantity}, Requested: {self.quantity}"
                    )
            
            # Store old values for logging
            old_quantity = product.quantity
            old_status = product.status
            
            # Update product based on type
            if product.category.is_single_item:
                # Single item: mark as sold
                product.status = 'sold'
                product.quantity = 0
                log_type = "SINGLE ITEM"
            else:
                # Bulk item: reduce quantity
                product.quantity -= self.quantity
                # Status will auto-update via _update_status() in product.save()
                log_type = "BULK ITEM"
            
            # Save product (will trigger _update_status for bulk items)
            product.save()
            
            # Create stock entry for the sale
            stock_entry = StockEntry.objects.create(
                product=product,
                quantity=-self.quantity,  # Negative for stock OUT
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
                f"Old Stock: {old_quantity} | "
                f"New Stock: {product.quantity} | "
                f"Old Status: {old_status} | "
                f"New Status: {product.status} | "
                f"Unit Price: KSH {self.unit_price} | "
                f"Total: KSH {self.total_price}"
            )
            
            return True

    def can_be_sold(self) -> tuple:
        """
        Check if this item can be sold
        Returns: (bool, str) - (can_sell, reason_if_not)
        """
        try:
            product = self.product
            
            if product.category.is_single_item:
                if product.status == 'sold':
                    return False, "Item has already been sold"
                if product.quantity <= 0:
                    return False, "Item is out of stock"
                if self.quantity != 1:
                    return False, "Single items must be sold one at a time"
            else:
                if product.quantity < self.quantity:
                    return False, f"Insufficient stock. Available: {product.quantity}"
            
            return True, "Available for sale"
            
        except Exception as e:
            return False, f"Error checking availability: {str(e)}"

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






#======================================
# SALE REVERSAL MODEL
#======================================

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

    # ========================================
    # MAIN REVERSAL METHOD (FIXED & COMPLETE)
    # ========================================
    def process_reversal(self):
        """
        Reverse all items in the sale
        - Single items: Mark as 'available' with quantity 1
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
                    # Single item: restore to available with quantity 1
                    product.status = 'available'
                    product.quantity = 1
                    reversal_type = "SINGLE ITEM"
                else:
                    # Bulk item: add quantity back
                    product.quantity += item.quantity
                    reversal_type = "BULK ITEM"
                
                # Save product (will trigger _update_status for bulk items)
                product.save()
                
                # -------------------------
                # LOG STOCK ENTRY
                # -------------------------
                stock_entry = StockEntry.objects.create(
                    product=product,
                    quantity=item.quantity,  # Positive for stock IN
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
                
                # Detailed logging
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

    # ========================================
    # VALIDATION METHODS
    # ========================================
    
    def can_reverse(self) -> tuple:
        """
        Check if the sale can be reversed
        Returns: (bool, str) - (can_reverse, reason_if_not)
        """
        if self.sale.is_reversed:
            return False, f"Sale #{self.sale.sale_id} has already been reversed"
        
        if self.sale.items.count() == 0:
            return False, f"Sale #{self.sale.sale_id} has no items to reverse"
        
        # Check each item
        for item in self.sale.items.all():
            if item.product is None:
                return False, f"Item {item.product_name} has no associated product"
        
        return True, "Sale can be reversed"

    def get_reversal_summary(self) -> dict:
        """
        Get summary of what will be reversed
        """
        summary = {
            'sale_id': self.sale.sale_id,
            'date': self.sale.sale_date,
            'total_items': self.sale.items.count(),
            'total_amount': self.sale.total_amount,
            'items': []
        }
        
        for item in self.sale.items.all():
            summary['items'].append({
                'product_name': item.product_name,
                'product_code': item.product_code,
                'quantity': item.quantity,
                'amount': item.total_price,
                'type': 'Single' if item.product and item.product.category.is_single_item else 'Bulk'
            })
        
        return summary

    # ========================================
    # PROPERTIES
    # ========================================
    
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

    class Meta:
        verbose_name = "Sale Reversal"
        verbose_name_plural = "Sale Reversals"
        ordering = ['-reversed_at']





#=======================================
#FISCAL RECEIPT MODEL
#=======================================

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