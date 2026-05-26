# ====================================
#  INVENTORY MODELS  📦
#  Version 2.0 - SKU-Based Architecture
# ====================================
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Max, Sum, Q, Avg, Count
from cloudinary.models import CloudinaryField
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from decimal import Decimal
import logging
import json
from datetime import timedelta

logger = logging.getLogger(__name__)


# ====================================
#  INVENTORY SUPPLIER MODEL 📦
# ====================================
class Supplier(models.Model):
    """Product suppliers"""
    name = models.CharField(max_length=200, unique=True)
    contact_person = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True, null=True)
    tax_id = models.CharField(max_length=50, blank=True, null=True)
    payment_terms = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Supplier'
        verbose_name_plural = 'Suppliers'

    def __str__(self):
        return self.name

    @property
    def product_count(self):
        return self.products.count()


# ====================================
# INVENTORY CATEGORY MODEL  📦
# ====================================
class Category(models.Model):
    """
    Product categories that define item types
    """
    
    ITEM_TYPE_CHOICES = [
        ('single', 'Single Item'),
        ('bulk', 'Bulk Item'),
    ]
    
    IDENTIFIER_TYPE_CHOICES = [
        ('imei', 'IMEI Number (15-digit)'),
        ('serial', 'Serial Number'),
        ('none', 'No Unique Identifier'),
    ]

    name = models.CharField(max_length=100, unique=True)
    item_type = models.CharField(
        max_length=10, 
        choices=ITEM_TYPE_CHOICES,
        help_text="Single: Unique items (phones). Bulk: Stock items (cables)"
    )
    identifier_type = models.CharField(
        max_length=10, 
        choices=IDENTIFIER_TYPE_CHOICES,
        default='imei',
        help_text="Type of identifier for tracking individual units"
    )
    category_code = models.CharField(max_length=50, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['category_code']),
        ]

    def save(self, *args, **kwargs):
        """Auto-generate category code"""
        if not self.category_code:
            clean_name = self.name.strip().upper() if self.name else "UNNAMED"
            clean_name = ''.join(e for e in clean_name if e.isalnum())
            self.category_code = f"FSL.{clean_name}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.category_code})"

    @property
    def is_single_item(self):
        return self.item_type == 'single'
    
    @property
    def is_bulk_item(self):
        return self.item_type == 'bulk'
    
    @property
    def requires_unique_id(self):
        return self.identifier_type in ['imei', 'serial']
    
    @property
    def product_count(self):
        return self.products.count()


# ====================================
# PRODUCT SKU MODEL (VARIANT LEVEL) 📦
# ====================================
class Product(models.Model):
    """
    Product SKU - Represents a PRODUCT VARIANT (not individual items)
    
    Example: 
    - SKU FSL001: Samsung A07 4/128GB (has 7 individual phone units)
    - SKU FSL002: Samsung A07 4/64GB (has 6 individual phone units)
    - SKU FSL003: Oraimo USB-C Cable (has 50 units in stock)
    """
    
    CONDITION_CHOICES = [
        ('new', 'Brand New'),
        ('refurbished', 'Refurbished'),
        ('used', 'Used - Excellent'),
        ('used_good', 'Used - Good'),
        ('used_fair', 'Used - Fair'),
    ]

    # ============================================
    # SKU IDENTIFICATION
    # ============================================
    sku_code = models.CharField(
        max_length=20, 
        unique=True, 
        db_index=True,
        verbose_name="SKU Code",
        help_text="Unique product code"
    )
    
    # ============================================
    # PRODUCT VARIANT INFORMATION
    # ============================================
    name = models.CharField(
        max_length=255,
        verbose_name="Product Name",
        help_text="Display name (auto-generated if blank)"
    )
    
    brand = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name="Brand"
    )
    
    model = models.CharField(
        max_length=200,
        db_index=True,
        verbose_name="Model"
    )
    
    category = models.ForeignKey(
        Category, 
        on_delete=models.PROTECT, 
        related_name='products',
        verbose_name="Category"
    )
    
    specifications = models.JSONField(
        default=dict,
        blank=True, 
        verbose_name="Specifications",
        help_text="RAM, storage, color, etc. Example: {'ram': '4GB', 'storage': '128GB', 'color': 'Black'}"
    )

    bulk_serial_number = models.CharField(
        max_length=100, 
        blank=True, 
        null=True,
        db_index=True,
        verbose_name="Bulk Serial/Batch Number",
        help_text="Single serial number or batch ID for all bulk items (e.g., BATCH-2024-001)"
    )
    
    # ============================================
    # PRICING (Base prices for this SKU)
    # ============================================
    buying_price = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        verbose_name="Buying Price (KES)"
    )
    
    selling_price = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        verbose_name="Selling Price (KES)"
    )
    
    best_price = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Best/Retail Price (KES)"
    )
    
    # ============================================
    # STOCK MANAGEMENT (Aggregated from units)
    # ============================================
    total_quantity = models.PositiveIntegerField(
        default=0,
        verbose_name="Total Quantity",
        help_text="Total units of this SKU (auto-calculated)"
    )
    
    available_quantity = models.PositiveIntegerField(
        default=0,
        verbose_name="Available Quantity",
        help_text="Units available for sale (auto-calculated)"
    )
    
    reserved_quantity = models.PositiveIntegerField(
        default=0,
        verbose_name="Reserved Quantity",
        help_text="Units reserved for pending orders (auto-calculated)"
    )
    
    damaged_quantity = models.PositiveIntegerField(
        default=0,
        verbose_name="Damaged Quantity",
        help_text="Units marked as damaged (auto-calculated)"
    )
    
    # For bulk items (cables, accessories without unique IDs)
    bulk_quantity = models.PositiveIntegerField(
        default=0,
        verbose_name="Bulk Quantity",
        help_text="For bulk items: number of identical units in stock"
    )
    
    # ============================================
    # SUPPLIER AND STOCK MANAGEMENT
    # ============================================
    supplier = models.ForeignKey(
        Supplier, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='products',
        verbose_name="Supplier"
    )
    
    reorder_level = models.PositiveIntegerField(
        default=5,
        verbose_name="Reorder Level",
        help_text="Minimum stock level before reordering"
    )
    
    last_restocked = models.DateTimeField(
        null=True, 
        blank=True,
        verbose_name="Last Restocked"
    )
    
    warranty_months = models.PositiveIntegerField(
        default=12,
        verbose_name="Warranty (Months)"
    )
    
    # ============================================
    # IMAGES
    # ============================================
    image = CloudinaryField('image', blank=True, null=True)
    
    # ============================================
    # STATUS
    # ============================================
    is_active = models.BooleanField(default=True)
    is_discontinued = models.BooleanField(default=False)
    
    # ============================================
    # AUDIT FIELDS
    # ============================================
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_products',
        verbose_name="Created By"
    )
    last_modified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='modified_products',
        verbose_name="Last Modified By"
    )
    
    description = models.TextField(blank=True, null=True, verbose_name="Description")

    class Meta:
        ordering = ['sku_code']
        indexes = [
            models.Index(fields=['sku_code']),
            models.Index(fields=['brand', 'model']),
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['available_quantity']),
            models.Index(fields=['selling_price']),
        ]
        unique_together = [
            ['brand', 'model', 'specifications'],
        ]
        verbose_name = 'Product SKU'
        verbose_name_plural = 'Product SKUs'

    def save(self, *args, **kwargs):
        """Auto-generate SKU code and name if not provided"""
        
        # Store who modified this
        if 'modified_by' in kwargs:
            self.last_modified_by = kwargs.pop('modified_by')
        if 'created_by' in kwargs and not self.pk:
            self.created_by = kwargs.pop('created_by')
        
        # Generate SKU code if not exists
        if not self.sku_code:
            self.sku_code = self._generate_sku_code()
        
        # Auto-generate name from brand, model, and specs if not provided
        if not self.name:
            self.name = self._generate_name()
        
        # Validate
        self.clean()
        
        super().save(*args, **kwargs)
    
    def _generate_sku_code(self):
        """
        Generate unique sequential SKU code with dynamic width
        Examples: 
        - First 999: FSL001 to FSL999 (3 digits)
        - Next 9000: FSL1000 to FSL9999 (4 digits)
        - Next 90000: FSL10000 to FSL99999 (5 digits)
        - Continues forever: FSL100000, FSL1000000, etc.
        """
        from django.db import transaction
    
        with transaction.atomic():
            last_product = Product.objects.select_for_update().filter(
                sku_code__regex=r'^FSL\d+$'
            ).order_by('-sku_code').first()
        
            if last_product and last_product.sku_code:
                try:
                    # Extract number after 'FSL' (works for any length)
                    number_part = last_product.sku_code[3:]
                    last_number = int(number_part)
                    new_number = last_number + 1
                except (ValueError, IndexError):
                    new_number = 1
            else:
                new_number = 1
        
            # For numbers 1-999: use 3-digit padding (FSL001 to FSL999)
            # For numbers 1000+: use no padding (FSL1000, FSL1001, etc.)
            if new_number < 1000:
                return f"FSL{new_number:03d}"  # More elegant than zfill
            else:
                return f"FSL{new_number}"
    
    def _generate_name(self):
        """Generate product name from brand, model, and specifications"""
        name_parts = [self.brand, self.model]
        
        if self.specifications:
            # Extract key specs for name
            storage = self.specifications.get('storage', '')
            ram = self.specifications.get('ram', '')
            color = self.specifications.get('color', '')
            
            specs = []
            if ram:
                specs.append(ram)
            if storage:
                specs.append(storage)
            if color:
                specs.append(color)
            
            if specs:
                name_parts.append(f"({' '.join(specs)})")
        
        return ' '.join(name_parts)
    
    def clean(self):
        """Validation"""
        if not self.category:
            raise ValidationError("Category is required")
        
        # Validate pricing
        if self.buying_price and self.selling_price:
            if self.buying_price > self.selling_price:
                raise ValidationError("Buying price cannot exceed selling price")
        
        if self.best_price and self.selling_price:
            if self.best_price > self.selling_price:
                raise ValidationError("Best price cannot exceed selling price")
  
    def update_quantities(self):
        """Update all quantity fields based on product units and bulk quantity"""
        if self.category.is_single_item:
            # For single items, calculate from individual units
            self.total_quantity = self.units.count()
            self.available_quantity = self.units.filter(status='available').count()
            self.reserved_quantity = self.units.filter(status='reserved').count()
            self.damaged_quantity = self.units.filter(status='damaged').count()
            self.bulk_quantity = 0
        else:
            # For bulk items, sum from stock entries
            try:
                from .models import StockEntry
                total = StockEntry.objects.filter(product_sku=self).aggregate(total=Sum('quantity'))['total'] or 0
                self.bulk_quantity = max(0, total)
            except Exception as e:
                logger.warning(f"Could not calculate bulk quantity for {self.sku_code}: {e}")
                self.bulk_quantity = 0
        
        self.save(update_fields=['total_quantity', 'available_quantity', 'reserved_quantity', 'damaged_quantity', 'bulk_quantity'])
    
    # ============================================
    # PROPERTIES
    # ============================================
    
    @property
    def display_name(self):
        """Full display name with SKU"""
        return f"{self.name} ({self.sku_code})"
    
    @property
    def current_stock(self):
        """Current available stock"""
        if self.category.is_single_item:
            return self.available_quantity
        else:
            return self.bulk_quantity
    
    @property
    def needs_reorder(self):
        """Check if product needs reordering"""
        if not self.is_active or self.is_discontinued:
            return False
        
        current = self.current_stock
        return current <= self.reorder_level and current > 0
    
    @property
    def is_out_of_stock(self):
        """Check if product is out of stock"""
        return self.current_stock == 0
    
    @property
    def is_low_stock(self):
        """Check if product is low on stock"""
        return 0 < self.current_stock <= self.reorder_level
    
    @property
    def profit_margin(self):
        """Profit per unit"""
        if self.buying_price and self.selling_price:
            return self.selling_price - self.buying_price
        return Decimal('0.00')
    
    @property
    def profit_percentage(self):
        """Profit percentage"""
        if self.buying_price and self.buying_price > 0:
            return (self.profit_margin / self.buying_price) * 100
        return Decimal('0.0')
    
    @property
    def stock_value(self):
        """Total stock value at buying price"""
        return self.current_stock * self.buying_price
    
    @property
    def retail_value(self):
        """Total retail value at selling price"""
        return self.current_stock * self.selling_price
    
    @property
    def can_be_used_for_credit(self):
        """Check if this product can be used for a new credit transaction"""
        try:
            if not self.category.is_single_item:
                return False, "Only single items (phones, electronics) can be used for credit"
            
            if self.available_quantity < 1:
                return False, "Product is out of stock"
            
            # Check if any units already have credit transactions
            try:
                from credit.models import CreditTransaction
                if CreditTransaction.objects.filter(product_sku=self).exists():
                    return False, "Product already has a credit transaction"
            except ImportError:
                pass  # Credit app not installed
            
            return True, "Product is available for credit"
        except Exception as e:
            logger.error(f"Error checking credit availability: {str(e)}")
            return False, "Error checking availability"
    
    @property
    def financial_loss_amount(self):
        """Calculate potential financial loss if all stock is lost"""
        if self.is_discontinued:
            return self.total_quantity * self.buying_price
        return Decimal('0.00')
    
    @property
    def price_difference(self):
        """Difference between selling price and best price"""
        if self.best_price and self.selling_price:
            return self.selling_price - self.best_price
        return Decimal('0.00')
    
    @property
    def stock_status_badge(self):
        """Get Bootstrap badge class for stock status"""
        if self.is_out_of_stock:
            return 'secondary'
        elif self.needs_reorder:
            return 'danger'
        elif self.is_low_stock:
            return 'warning'
        return 'success'
    
    @property
    def stock_status_icon(self):
        """Get icon for stock status"""
        if self.is_out_of_stock:
            return 'fa-times-circle'
        elif self.needs_reorder:
            return 'fa-exclamation-circle'
        elif self.is_low_stock:
            return 'fa-exclamation-triangle'
        return 'fa-check-circle'
    
    def to_json(self):
        """Serialize product to JSON"""
        return json.dumps({
            'id': self.id,
            'sku': self.sku_code,
            'name': self.name,
            'brand': self.brand,
            'model': self.model,
            'price': float(self.selling_price),
            'stock': self.current_stock,
            'available': self.available_quantity,
            'category': self.category.name,
        })
    
    def __str__(self):
        return self.display_name
    
    def get_absolute_url(self):
        """URL to view this product"""
        from django.urls import reverse
        return reverse('inventory:product_detail', args=[str(self.id)])


# ====================================
# PRODUCT UNIT MODEL (INDIVIDUAL ITEMS) 📦
# ====================================
class ProductUnit(models.Model):
    """
    Individual physical items for single-item categories (phones, electronics)
    
    Each unit belongs to a Product SKU and has its own unique identifier
    """
    
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('sold', 'Sold'),
        ('reserved', 'Reserved'),
        ('damaged', 'Damaged'),
        ('stolen', 'Stolen'),
        ('lost', 'Lost'),
        ('returned', 'Returned'),
        ('writeoff', 'Written Off'),
    ]
    
    CONDITION_CHOICES = [
        ('new', 'Brand New'),
        ('refurbished', 'Refurbished'),
        ('used_excellent', 'Used - Excellent'),
        ('used_good', 'Used - Good'),
        ('used_fair', 'Used - Fair'),
        ('damaged', 'Damaged'),
    ]

    # ============================================
    # RELATIONSHIPS
    # ============================================
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='units',
        verbose_name="Product SKU"
    )
    
    # ============================================
    # UNIQUE IDENTIFIERS
    # ============================================
    imei_number = models.CharField(
        max_length=15,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="IMEI Number",
        help_text="15-digit IMEI number (for phones)"
    )
    
    serial_number = models.CharField(
        max_length=200,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Serial Number",
        help_text="Unique serial number"
    )
    
    # ============================================
    # UNIT-SPECIFIC OVERRIDES
    # ============================================
    unit_buying_price = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Unit Buying Price",
        help_text="Override product buying price for this specific unit"
    )
    
    unit_selling_price = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Unit Selling Price",
        help_text="Override product selling price for this specific unit"
    )
    
    # ============================================
    # STATUS AND CONDITION
    # ============================================
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='available',
        db_index=True,
        verbose_name="Status"
    )
    
    condition = models.CharField(
        max_length=20,
        choices=CONDITION_CHOICES,
        default='new',
        verbose_name="Condition"
    )
    
    # ============================================
    # SALES INFORMATION
    # ============================================
    
    sold_at_price = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Sold At Price"
    )
    
    sold_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Sold Date"
    )
    
    sold_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sold_units',
        verbose_name="Sold By"
    )
    
    # ============================================
    # PURCHASE INFORMATION
    # ============================================
    purchase_date = models.DateTimeField(
        default=timezone.now,
        verbose_name="Purchase Date"
    )
    
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Supplier"
    )
    
    purchase_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Actual Purchase Price"
    )
    
    # ============================================
    # WARRANTY
    # ============================================
    warranty_start = models.DateTimeField(
        default=timezone.now,
        verbose_name="Warranty Start"
    )
    
    warranty_end = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Warranty End"
    )
    
    # ============================================
    # THEFT / LOSS TRACKING
    # ============================================
    loss_type = models.CharField(
        max_length=20,
        choices=[
            ('stolen', 'Stolen'),
            ('lost', 'Lost'),
            ('damaged_total', 'Totally Damaged'),
        ],
        null=True,
        blank=True,
        verbose_name="Loss Type"
    )
    
    loss_reported_date = models.DateTimeField(
        null=True, 
        blank=True,
        verbose_name="Loss Reported Date"
    )
    
    loss_reported_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='reported_unit_losses',
        verbose_name="Loss Reported By"
    )
    
    loss_notes = models.TextField(blank=True, null=True)
    police_report_number = models.CharField(max_length=100, blank=True, null=True)
    
    # ============================================
    # INSURANCE TRACKING
    # ============================================
    insurance_claim_filed = models.BooleanField(
        default=False,
        verbose_name="Insurance Claim Filed"
    )
    insurance_claim_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Insurance Claim Number"
    )
    insurance_claim_amount = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        null=True, 
        blank=True,
        verbose_name="Insurance Claim Amount"
    )
    insurance_payout_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Insurance Payout Amount"
    )
    insurance_payout_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Insurance Payout Date"
    )
    
    # ============================================
    # RECOVERY TRACKING
    # ============================================
    recovered_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Recovered Date"
    )
    recovered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recovered_units',
        verbose_name="Recovered By"
    )
    recovery_notes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Recovery Notes"
    )
    
    # ============================================
    # LOCATION TRACKING
    # ============================================
    warehouse_location = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Warehouse Location"
    )
    
    shelf_location = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Shelf Location"
    )
    
    # ============================================
    # NOTES
    # ============================================
    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Notes",
        help_text="e.g., 'Scratch on screen', 'Missing original box'"
    )
    
    # ============================================
    # AUDIT FIELDS
    # ============================================
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_units',
        verbose_name="Created By"
    )
    last_modified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='modified_units',
        verbose_name="Last Modified By"
    )

    class Meta:
        ordering = ['product__sku_code', '-created_at']
        indexes = [
            models.Index(fields=['imei_number']),
            models.Index(fields=['serial_number']),
            models.Index(fields=['status']),
            models.Index(fields=['product', 'status']),
            models.Index(fields=['sold_date']),
            models.Index(fields=['warranty_end']),
        ]
        verbose_name = 'Product Unit'
        verbose_name_plural = 'Product Units'

    def save(self, *args, **kwargs):
        """Validate before saving"""
        
        # Store who modified this
        if 'modified_by' in kwargs:
            self.last_modified_by = kwargs.pop('modified_by')
        if 'created_by' in kwargs and not self.pk:
            self.created_by = kwargs.pop('created_by')
        
        # Ensure at least one identifier is present
        if not self.imei_number and not self.serial_number:
            if self.product.category.requires_unique_id:
                raise ValidationError("IMEI or Serial Number is required for this category")
        
        # Validate IMEI length if provided
        if self.imei_number:
            if len(self.imei_number) != 15:
                raise ValidationError("IMEI number must be exactly 15 digits")
            if not self.imei_number.isdigit():
                raise ValidationError("IMEI number must contain only digits")
        
        # Set warranty end date if not set
        if not self.warranty_end and self.product.warranty_months:
            self.warranty_end = self.warranty_start + timedelta(days=self.product.warranty_months * 30)
        
        self.clean()
        super().save(*args, **kwargs)
    
    def clean(self):
        """Validation"""
        if self.status == 'sold' and not self.sold_date:
            self.sold_date = timezone.now()
    
    # ============================================
    # PROPERTIES
    # ============================================
    
    @property
    def effective_buying_price(self):
        """Get effective buying price (unit override or product default)"""
        return self.unit_buying_price or self.product.buying_price
    
    @property
    def effective_selling_price(self):
        """Get effective selling price (unit override or product default)"""
        return self.unit_selling_price or self.product.selling_price
    
    @property
    def unique_identifier(self):
        """Return the primary unique identifier"""
        if self.imei_number:
            return f"IMEI: {self.imei_number}"
        elif self.serial_number:
            return f"S/N: {self.serial_number}"
        return "No identifier"
    
    @property
    def is_in_warranty(self):
        """Check if unit is still under warranty"""
        if not self.warranty_end:
            return False
        return timezone.now() < self.warranty_end
    
    @property
    def warranty_remaining_days(self):
        """Days remaining under warranty"""
        if not self.is_in_warranty:
            return 0
        remaining = self.warranty_end - timezone.now()
        return remaining.days
    
    @property
    def profit_on_sale(self):
        """Profit earned if sold"""
        if self.sold_at_price and self.effective_buying_price:
            return self.sold_at_price - self.effective_buying_price
        return Decimal('0.00')
    
    # ============================================
    # BUSINESS METHODS
    # ============================================
    
    def mark_as_sold(self, customer, price=None, sold_by=None):
        """Mark this unit as sold"""
        self.status = 'sold'
        self.sold_at_price = price or self.effective_selling_price
        self.sold_date = timezone.now()
        self.sold_by = sold_by
        self.save()
        
        # Update product quantities
        self.product.update_quantities()
        
        logger.info(f"✅ Unit sold: {self.product.sku_code} - {self.unique_identifier}")
        return True
    
    def mark_as_reserved(self):
        """Mark this unit as reserved"""
        self.status = 'reserved'
        self.save()
        self.product.update_quantities()
    
    def mark_as_available(self):
        """Make unit available again"""
        self.status = 'available'
        self.sold_at_price = None
        self.sold_date = None
        self.save()
        self.product.update_quantities()
    
    def mark_as_damaged(self, notes=None, reported_by=None):
        """Mark unit as damaged"""
        self.status = 'damaged'
        if notes:
            self.notes = notes
        self.save(modified_by=reported_by)
        self.product.update_quantities()
        logger.warning(f"⚠️ Unit damaged: {self.product.sku_code} - {self.unique_identifier}")
    
    def mark_as_stolen(self, reported_by, police_report=None, notes=None):
        """Mark unit as stolen"""
        self.status = 'stolen'
        self.loss_type = 'stolen'
        self.loss_reported_date = timezone.now()
        self.loss_reported_by = reported_by
        self.loss_notes = notes
        self.police_report_number = police_report
        self.save(modified_by=reported_by)
        self.product.update_quantities()
        logger.warning(f"🚨 Unit stolen: {self.product.sku_code} - {self.unique_identifier}")
    
    def file_insurance_claim(self, claim_number, claim_amount):
        """File insurance claim for stolen/lost unit"""
        self.insurance_claim_filed = True
        self.insurance_claim_number = claim_number
        self.insurance_claim_amount = claim_amount
        self.save()
        logger.info(f"Insurance claim filed for {self.product.sku_code} - {self.unique_identifier}")
        return True
    
    def record_insurance_payout(self, payout_amount, payout_date=None):
        """Record insurance payout received"""
        self.insurance_payout_amount = payout_amount
        self.insurance_payout_date = payout_date or timezone.now()
        self.save()
        logger.info(f"Insurance payout received: KES {payout_amount}")
        return True
    
    def mark_as_recovered(self, recovered_by, notes=None):
        """Mark stolen/lost unit as recovered"""
        self.status = 'available'
        self.loss_type = None
        self.loss_reported_date = None
        self.recovered_date = timezone.now()
        self.recovered_by = recovered_by
        self.recovery_notes = notes
        self.save(modified_by=recovered_by)
        self.product.update_quantities()
        logger.info(f"Unit recovered: {self.product.sku_code} - {self.unique_identifier}")
        return True
    
    def __str__(self):
        return f"{self.product.sku_code} - {self.unique_identifier} ({self.get_status_display()})"


# ====================================
# STOCK ENTRY MODEL 📦
# ====================================
class StockEntry(models.Model):
    """
    Tracks all inventory movements for BOTH single and bulk items
    """
    
    ENTRY_TYPE_CHOICES = [
        ('purchase', 'Purchase'),
        ('sale', 'Sale'),
        ('reversal', 'Reversal / Return'),
        ('adjustment', 'Manual Adjustment'),
        ('damage', 'Damaged Write-off'),
        ('theft', 'Theft/Loss'),
    ]

    # For single items: link to ProductUnit
    product_unit = models.ForeignKey(
        ProductUnit,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='stock_entries',
        help_text="For single items with unique identifiers"
    )
    
    # For bulk items: link to Product SKU
    product_sku = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='stock_entries',
        help_text="For bulk items without unique identifiers"
    )
    
    quantity = models.IntegerField(
        help_text="Positive for stock IN, Negative for stock OUT"
    )
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPE_CHOICES)
    
    unit_price = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        help_text="Price per unit at time of transaction"
    )
    total_amount = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        help_text="Total transaction value"
    )
    
    reference_id = models.CharField(
        max_length=255, 
        blank=True, 
        null=True,
        help_text="Invoice/Receipt/Order number"
    )
    notes = models.TextField(blank=True, null=True)
    
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='stock_entries'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Stock Entry'
        verbose_name_plural = 'Stock Entries'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['entry_type']),
            models.Index(fields=['product_sku', '-created_at']),
            models.Index(fields=['product_unit', '-created_at']),
        ]

    def clean(self):
        """Validation"""
        if self.quantity == 0:
            raise ValidationError("Quantity cannot be zero")
        
        # Must have either unit or SKU, not both
        if not self.product_unit and not self.product_sku:
            raise ValidationError("Either Product Unit or Product SKU is required")
        
        if self.product_unit and self.product_sku:
            raise ValidationError("Cannot specify both Product Unit and Product SKU")
        
        # For sales, check available stock
        if self.entry_type == 'sale' and self.quantity < 0:
            if self.product_unit:
                if self.product_unit.status != 'available':
                    raise ValidationError("This unit is not available for sale")
            elif self.product_sku and self.product_sku.category.is_bulk_item:
                if abs(self.quantity) > self.product_sku.bulk_quantity:
                    raise ValidationError(f"Insufficient stock. Only {self.product_sku.bulk_quantity} available")

    def save(self, *args, **kwargs):
        if not self.total_amount and self.unit_price:
            self.total_amount = abs(self.quantity) * self.unit_price
        
        self.clean()
        super().save(*args, **kwargs)
        
        # Update stock quantities
        if self.product_unit:
            if self.entry_type == 'sale':
                self.product_unit.mark_as_sold(
                    customer=None,
                    price=self.unit_price,
                    sold_by=self.created_by
                )
            elif self.entry_type == 'purchase':
                self.product_unit.status = 'available'
                self.product_unit.save()
        elif self.product_sku and self.product_sku.category.is_bulk_item:
            # Skip automatic stock update for sale entries
            if self.entry_type != 'sale':  # ← ADD THIS LINE
                total = StockEntry.objects.filter(product_sku=self.product_sku).aggregate(
                    total=Sum('quantity')
                )['total'] or 0
                self.product_sku.bulk_quantity = max(0, total)
                self.product_sku.save(update_fields=['bulk_quantity', 'updated_at'])

    def __str__(self):
        direction = "IN" if self.quantity > 0 else "OUT"
        if self.product_unit:
            identifier = self.product_unit.unique_identifier
        else:
            identifier = self.product_sku.sku_code if self.product_sku else "Unknown"
        return f"{self.get_entry_type_display()} {direction} - {identifier} - {abs(self.quantity)} units"


# ====================================
# PRODUCT IMAGE MODEL 📦
# ====================================
class ProductImage(models.Model):
    """Multiple images per product SKU"""
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='images'
    )
    image = CloudinaryField('image')
    is_primary = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    caption = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['order', '-is_primary', 'created_at']
        unique_together = ['product', 'is_primary']
    
    def save(self, *args, **kwargs):
        if self.is_primary:
            ProductImage.objects.filter(product=self.product, is_primary=True).update(is_primary=False)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Image for {self.product.display_name}"


# ====================================
# STOCK ALERT MODEL 📦
# ====================================
class StockAlert(models.Model):
    """Alert when products are running low or out of stock"""
    
    ALERT_TYPE_CHOICES = [
        ('lowstock', 'Low Stock'),
        ('needs_reorder', 'Needs Reorder'),
        ('outofstock', 'Out of Stock'),
        ('expiring', 'Warranty Expiring Soon'),
    ]
    
    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('danger', 'Danger'),
        ('critical', 'Critical'),
    ]
    
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='alerts'
    )
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPE_CHOICES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES)
    
    current_stock = models.PositiveIntegerField(default=0)
    threshold = models.PositiveIntegerField(default=5)
    
    is_active = models.BooleanField(default=True)
    is_dismissed = models.BooleanField(default=False)
    dismissed_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='dismissed_alerts'
    )
    dismissed_at = models.DateTimeField(null=True, blank=True)
    dismissed_reason = models.TextField(blank=True, null=True)
    
    last_alerted = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    alert_count = models.PositiveIntegerField(default=0)
    
    
    class Meta:
        ordering = ['-severity', '-created_at']
        indexes = [
            models.Index(fields=['product', 'is_active']),
            models.Index(fields=['alert_type']),
        ]

    def __str__(self):
        return f"{self.get_alert_type_display()}: {self.product.display_name}"

    
    def dismiss(self, user=None, reason=""):
        """Dismiss this alert"""
        self.is_active = False
        self.is_dismissed = True
        self.dismissed_by = user
        self.dismissed_at = timezone.now()
        self.dismissed_reason = reason
        self.save()
        logger.info(f"Alert dismissed for {self.product.sku_code}")
    
    def reactivate(self):
        """Reactivate a dismissed alert"""
        self.is_active = True
        self.is_dismissed = False
        self.dismissed_by = None
        self.dismissed_at = None
        self.dismissed_reason = None
        self.alert_count = 0
        self.last_alerted = timezone.now()
        self.save()
        logger.info(f"Alert reactivated for {self.product.sku_code}")





# ====================================
# PRODUCT REVIEW MODEL 📦
# ====================================
class ProductReview(models.Model):
    """Customer product reviews"""
    RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]

    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='reviews',
        verbose_name="Product"
    )
    product_unit = models.ForeignKey(
        ProductUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviews',
        verbose_name="Specific Unit (if applicable)"
    )
    customer_name = models.CharField(max_length=200)
    customer_email = models.EmailField(blank=True, null=True)
    rating = models.PositiveIntegerField(choices=RATING_CHOICES, default=5)
    title = models.CharField(max_length=200, blank=True)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(
        default=False,
        help_text="Verified purchase - customer actually bought this product"
    )
    is_active = models.BooleanField(default=True)
    helpful_count = models.PositiveIntegerField(default=0)
    not_helpful_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', '-created_at']),
            models.Index(fields=['rating']),
            models.Index(fields=['is_verified']),
        ]
        verbose_name = 'Product Review'
        verbose_name_plural = 'Product Reviews'

    def __str__(self):
        return f"Review for {self.product.display_name} - {self.rating} stars"

    @property
    def average_rating(self):
        """Get average rating for product"""
        return self.product.reviews.filter(is_active=True).aggregate(
            avg=models.Avg('rating')
        )['avg'] or 0


# ====================================
# RETURN REQUEST MODEL 📦
# ====================================
class ReturnRequest(models.Model):
    """Track product returns from customers with verification"""
    
    RETURN_STATUS_CHOICES = [
        ('pending', 'Pending Submission'),
        ('submitted', 'Submitted - Awaiting Verification'),
        ('verified', 'Verified - Awaiting Approval'),
        ('approved', 'Approved - Awaiting Processing'),
        ('rejected', 'Rejected'),
        ('processed', 'Processed'),
        ('damaged_loss', 'Damaged - Recorded as Loss'),
    ]
    
    RETURN_REASON_CHOICES = [
        ('defective', 'Defective Product'),
        ('wrong_item', 'Wrong Item Received'),
        ('changed_mind', 'Changed Mind'),
        ('damaged', 'Damaged During Shipping'),
        ('not_as_described', 'Not as Described'),
        ('other', 'Other'),
    ]
    
    return_id = models.CharField(max_length=50, unique=True, editable=False)
    sale_id = models.CharField(max_length=50, blank=True, null=True, help_text="Original sale ID")
    etr_number = models.CharField(max_length=100, blank=True, null=True, help_text="ETR receipt number")
    related_sale = models.ForeignKey(
        'sales.Sale',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='returns'
    )
    
    # Product information
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='returns'
    )
    product_unit = models.ForeignKey(
        ProductUnit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='returns',
        help_text="Specific unit being returned (for single items)"
    )
    
    quantity = models.PositiveIntegerField(default=1)
    
    # Return details
    reason = models.CharField(max_length=50, choices=RETURN_REASON_CHOICES)
    reason_text = models.TextField(blank=True, null=True)
    
    # Customer reported condition
    reported_condition = models.CharField(
        max_length=20,
        choices=[
            ('new', 'Like New'),
            ('good', 'Good'),
            ('fair', 'Fair'),
            ('damaged', 'Damaged'),
        ],
        default='good'
    )
    
    # Financial
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Tracking
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='return_requests'
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    
    # Verification
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_returns'
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_notes = models.TextField(blank=True, null=True)
    
    # Approval
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_returns'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=RETURN_STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True, null=True)
    
    # Processing
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_returns'
    )
    
    class Meta:
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['return_id']),
            models.Index(fields=['-requested_at']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.return_id:
            self.return_id = self._generate_return_id()
        super().save(*args, **kwargs)
    
    def _generate_return_id(self):
        """Generate sequential return ID: FSL-R-001"""
        from django.db import transaction
        
        prefix = "FSL-R-"
        
        with transaction.atomic():
            # Get the last return ID
            last_return = ReturnRequest.objects.filter(
                return_id__startswith=prefix
            ).order_by('-return_id').first()
            
            if last_return and last_return.return_id:
                try:
                    # Extract the number from last ID
                    number_part = last_return.return_id.replace(prefix, "")
                    last_number = int(number_part)
                    new_number = last_number + 1
                except (ValueError, IndexError):
                    new_number = 1
            else:
                new_number = 1
            
            # Format with leading zeros (3 digits)
            return f"{prefix}{str(new_number).zfill(3)}"
    
    def process_restock(self, user):
        """Process the return and restock the product"""
        from django.db import transaction
        
        with transaction.atomic():
            if self.product.category.is_single_item and self.product_unit:
                # Restock individual unit
                self.product_unit.mark_as_available()
                self.product_unit.notes = "Returned on {} - Reason: {}".format(
                    timezone.now().date(), 
                    self.reason
                )
                self.product_unit.save()
            else:
                # Restock bulk item
                StockEntry.objects.create(
                    product_sku=self.product,
                    quantity=self.quantity,
                    entry_type='reversal',
                    unit_price=self.refund_amount / self.quantity if self.refund_amount else self.product.buying_price,
                    total_amount=self.refund_amount,
                    reference_id=self.return_id,
                    notes="Return from customer - {}".format(
                        self.reason_text or self.get_reason_display()
                    ),
                    created_by=user
                )
            
            self.status = 'processed'
            self.processed_by = user
            self.processed_at = timezone.now()
            self.save()
            
            logger.info("Return processed: {} - {}".format(self.return_id, self.product.sku_code))
    
    def __str__(self):
        return "Return #{} - {}".format(self.return_id, self.product.sku_code)








# ====================================
# SIGNALS - Automatic Quantity Updates
# ====================================

@receiver([post_save, post_delete], sender=ProductUnit)
def update_product_quantities_from_units(sender, instance, **kwargs):
    """Update Product SKU quantities when units are added/removed/modified"""
    if instance.product.category.is_single_item:
        instance.product.update_quantities()


@receiver(post_save, sender=StockEntry)
def update_from_stock_entry(sender, instance, created, **kwargs):
    """Update product quantities when stock entry is created"""
    if created:
        if instance.product_unit:
            instance.product_unit.product.update_quantities()
        elif instance.product_sku and instance.product_sku.category.is_bulk_item:
            # Quantity already updated in save method
            pass


@receiver(post_save, sender=Product)
def create_stock_alerts(sender, instance, created, **kwargs):
    """Auto-create stock alerts for products that need them"""
    try:
        if not instance.is_active or instance.is_discontinued:
            return
        
        current_stock = instance.current_stock
        alert_type = None
        severity = 'warning'
        
        if current_stock == 0:
            alert_type = 'outofstock'
            severity = 'critical'
        elif current_stock <= instance.reorder_level:
            alert_type = 'needs_reorder'
            severity = 'danger'
        elif current_stock <= 5:
            alert_type = 'lowstock'
            severity = 'warning'
        
        if alert_type:
            StockAlert.objects.update_or_create(
                product=instance,
                is_dismissed=False,
                defaults={
                    'alert_type': alert_type,
                    'severity': severity,
                    'current_stock': current_stock,
                    'threshold': instance.reorder_level,
                    'is_active': True,
                    'last_alerted': timezone.now(),
                }
            )
        else:
            # Dismiss any existing alerts for well-stocked products
            StockAlert.objects.filter(product=instance, is_active=True).update(
                is_active=False,
                is_dismissed=True
            )
            
    except Exception as e:
        logger.error(f"Error creating stock alert: {str(e)}")


@receiver(pre_save, sender=ProductUnit)
def validate_unit_identifiers(sender, instance, **kwargs):
    """Ensure unique identifiers per product"""
    if instance.imei_number:
        # Check if IMEI already exists for same product
        existing = ProductUnit.objects.filter(
            product=instance.product,
            imei_number=instance.imei_number
        ).exclude(pk=instance.pk)
        
        if existing.exists():
            raise ValidationError(f"IMEI {instance.imei_number} already exists for this product")
    
    if instance.serial_number:
        existing = ProductUnit.objects.filter(
            product=instance.product,
            serial_number=instance.serial_number
        ).exclude(pk=instance.pk)
        
        if existing.exists():
            raise ValidationError(f"Serial {instance.serial_number} already exists for this product")


@receiver(post_save, sender='inventory.StockEntry')
def create_finance_transaction_for_stock_entry(sender, instance, created, **kwargs):
    from finance.models import StockPurchase, FinancialTransaction, AccountTransaction, CashAccount, BankAccount, PurchaseAccount
    from decimal import Decimal
    
    # Only process purchase entries (positive quantity)
    if not created or instance.quantity <= 0:
        return
    
    # Skip if already processed
    if hasattr(instance, 'finance_transactions') and instance.finance_transactions.exists():
        return
    
    # Determine product info
    product = None
    product_name = "Unknown Product"
    sku_code = ""
    
    if instance.product_sku:
        product = instance.product_sku
        product_name = product.name
        sku_code = product.sku_code
    elif instance.product_unit:
        product = instance.product_unit.product
        product_name = product.name
        sku_code = product.sku_code
    else:
        return
    
    # Calculate amount
    total_amount = instance.total_amount or (instance.unit_price * instance.quantity)
    
    # Determine payment method
    payment_method = 'bank'
    account_type = 'bank'
    if instance.reference_id:
        if 'MPESA' in instance.reference_id.upper() or 'STK' in instance.reference_id.upper():
            payment_method = 'mpesa'
            account_type = 'bank'
        elif 'CASH' in instance.reference_id.upper():
            payment_method = 'cash'
            account_type = 'cash'
    
    # ============================================
    # ADD UNIQUE IDENTIFIER TO PREVENT DUPLICATES
    # ============================================
    unique_suffix = f"#{instance.id}-{instance.created_at.strftime('%Y%m%d%H%M%S%f')}"
    
    try:
        from django.db import transaction
        
        with transaction.atomic():
            # Create FinancialTransaction with unique description
            fin_trans = FinancialTransaction.objects.create(
                transaction_type='expense',
                category='operational',
                amount=total_amount,
                description=f"Stock Purchase: {product_name} ({sku_code}) - {instance.quantity} units @ KES {instance.unit_price} [{unique_suffix}]",
                payment_method=payment_method,
                payment_reference=instance.reference_id or f"STOCK-{instance.id}-{unique_suffix}",
                recipient_name=product.supplier.name if product.supplier else "",
                created_by=instance.created_by,
                notes=f"Stock Entry #{instance.id} - Added {instance.quantity} units"
            )
            
            # Create AccountTransaction
            acc_trans = AccountTransaction.objects.create(
                account_type=account_type,
                transaction_type='expense',
                amount=total_amount,
                description=f"Stock Purchase: {product_name} ({sku_code}) [{unique_suffix}]",
                reference=instance.reference_id or f"STOCK-{instance.id}",
                created_by=instance.created_by,
                notes=f"Stock Entry #{instance.id} - {instance.quantity} units @ KES {instance.unit_price}"
            )
            
            # Update account balance (Cash or Bank)
            if account_type == 'cash':
                cash_acc, _ = CashAccount.objects.get_or_create(id=1)
                cash_acc.update_balance(total_amount, 'expense', instance.created_by)
            else:
                bank_acc, _ = BankAccount.objects.get_or_create(id=1)
                bank_acc.update_balance(total_amount, 'expense', instance.created_by)
            
            # Update PurchaseAccount
            purchase_account = PurchaseAccount.get_or_create_account()
            purchase_account.add_purchase_cost(
                amount=total_amount,
                product_reference=sku_code,
                user=instance.created_by
            )
            
            # Create StockPurchase record
            stock_purchase = StockPurchase.objects.create(
                stock_entry=instance,
                product_name=product_name,
                sku_code=sku_code,
                quantity=instance.quantity,
                unit_price=instance.unit_price,
                total_amount=total_amount,
                purchase_date=instance.created_at,
                reference_id=instance.reference_id,
                notes=instance.notes,
                financial_transaction=fin_trans,
                account_transaction=acc_trans,
                created_by=instance.created_by
            )
            
            logger.info(f"✅ Finance transaction created for stock purchase: {stock_purchase.id} - KES {total_amount}")
            print(f"✅ Stock purchase #{instance.id} recorded: KES {total_amount} added to Purchase Account")
            
    except Exception as e:
        logger.error(f"Failed to create finance transaction for stock entry {instance.id}: {str(e)}")
        print(f"❌ Error: {str(e)}")




# ====================================
# HELPER FUNCTIONS
# ====================================

def bulk_create_units(sku_code, units_data, created_by=None):
    """
    Bulk create product units for a SKU
    
    Args:
        sku_code: The SKU code (e.g., 'FSL001', 'FSL1000')
        units_data: List of dicts with 'imei_number' or 'serial_number' and optional overrides
        created_by: User creating these units
    
    Returns:
        List of created ProductUnit objects
    
    Example:
        units_data = [
            {'imei_number': '123456789012345'},
            {'imei_number': '123456789012346', 'unit_selling_price': 180},
            {'serial_number': 'SN123456'},
        ]
    """
    product = Product.objects.get(sku_code=sku_code)
    units = []
    
    for data in units_data:
        unit = ProductUnit(
            product=product,
            created_by=created_by,
            **data
        )
        units.append(unit)
    
    created_units = ProductUnit.objects.bulk_create(units)
    product.update_quantities()
    
    logger.info(f"✅ Bulk created {len(created_units)} units for {sku_code}")
    return created_units


def get_stock_report():
    """Generate comprehensive stock report"""
    from django.db.models import Q, F
    from decimal import Decimal
    
    report = {
        'total_skus': Product.objects.filter(is_active=True).count(),
        'total_stock_value': Decimal('0.00'),
        'total_retail_value': Decimal('0.00'),
        'out_of_stock': Product.objects.filter(
            is_active=True
        ).filter(
            Q(category__item_type='single', available_quantity=0) |
            Q(category__item_type='bulk', bulk_quantity=0)
        ).count(),
        'low_stock': Product.objects.filter(
            is_active=True,
            category__item_type='bulk',
            bulk_quantity__lte=F('reorder_level'),
            bulk_quantity__gt=0
        ).count(),
        'categories': []
    }
    
    # Calculate values - handle potential None values
    for product in Product.objects.filter(is_active=True).select_related('category'):
        try:
            stock = product.current_stock or 0
            report['total_stock_value'] += Decimal(str(stock)) * (product.buying_price or Decimal('0.00'))
            report['total_retail_value'] += Decimal(str(stock)) * (product.selling_price or Decimal('0.00'))
        except (TypeError, ValueError) as e:
            logger.error(f"Error calculating stock for product {product.sku_code}: {e}")
    
    # Category totals
    for category in Category.objects.filter(is_active=True).prefetch_related('products'):
        category_total = Decimal('0.00')
        product_count = 0
        
        for product in category.products.filter(is_active=True):
            try:
                stock = product.current_stock or 0
                category_total += Decimal(str(stock)) * (product.buying_price or Decimal('0.00'))
                product_count += 1
            except (TypeError, ValueError) as e:
                logger.error(f"Error in category {category.name}: {e}")
        
        report['categories'].append({
            'name': category.name,
            'product_count': product_count,
            'total_value': category_total
        })
    
    return report


__all__ = [
    'Supplier',
    'Category', 
    'Product',
    'ProductUnit',
    'StockEntry',
    'ProductImage',
    'StockAlert',
    'ProductReview',
    'ReturnRequest',
    'bulk_create_units',
    'get_stock_report',
]