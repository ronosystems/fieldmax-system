# ====================================
#  INVENTORY MODELS  📦
# ====================================
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Max, Sum
from cloudinary.models import CloudinaryField
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from decimal import Decimal
import uuid
import random
import string
import logging
import json

logger = logging.getLogger(__name__)



# ====================================
#  INVENTORY SUPPLIER MODEL 📦
# ====================================
class Supplier(models.Model):
    """fieldmax product suppliers"""
    name = models.CharField(max_length=200)
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
        return self.name or "Unnamed Supplier"

    @property
    def product_count(self):
        return self.products.count()

# ====================================
# INVENTORY CATEGORY MODEL  📦
# ====================================
class Category(models.Model):
    """
    - Product categories that define item types
    - Auto generates category codes
    """
    
    SKU_TYPE_CHOICES = [
        ('imei', 'IMEI NUMBER'),
        ('serial', 'SERIAL NUMBER'),
    ]
    
    ITEM_TYPE_CHOICES = [
        ('single', 'Single Item'),
        ('bulk', 'Bulk Item'),
    ]

    name = models.CharField(max_length=100, unique=True)
    item_type = models.CharField(
        max_length=10, 
        choices=ITEM_TYPE_CHOICES,
        help_text="Single: Unique items (phones). Bulk: Stock items (cables)"
    )
    sku_type = models.CharField(
        max_length=10, 
        choices=SKU_TYPE_CHOICES,
        help_text="Type of identifier for this category"
    )
    category_code = models.CharField(max_length=50, unique=True, blank=True)
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
        """
        Auto-generate category code
        Examples:
        - SMART PHONES → FSL.SMARTPHONES
        - CHARGERS → FSL.CHARGERS
        """
        if not self.category_code:
            # Convert name to uppercase, remove spaces and special characters
            clean_name = self.name.strip().upper() if self.name else "UNNAMED"
            clean_name = ''.join(e for e in clean_name if e.isalnum())
            self.category_code = f"FSL.{clean_name}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name or 'Unnamed'} ({self.category_code or 'No Code'}) - {self.get_item_type_display() or 'Unknown'}"

    @property
    def is_single_item(self):
        return self.item_type == 'single'
    
    @property
    def is_bulk_item(self):
        return self.item_type == 'bulk'
    
    @property
    def product_count(self):
        return self.products.count()







# ====================================
# INVENTORY PRODUCT MODEL 📦
# ====================================
# ====================================
# INVENTORY PRODUCT MODEL 📦
# ====================================
class Product(models.Model):
    """
    Represents inventory items.
    - Single items: Each unit gets its own Product record with unique SKU (IMEI/Serial)
    - Bulk items: Multiple units share one Product record with same SKU
    - Auto generates product code (FSL format starting from FSL00200)
    - Auto generates barcode when blank
    """
    
    STATUS_CHOICES = [
        ('available', 'Available'),
        ('sold', 'Sold'),
        ('reserved', 'Reserved'),
        ('damaged', 'Damaged'),
        ('lowstock', 'Low Stock'),
        ('outofstock', 'Out of Stock'),
    ]

    CONDITION_CHOICES = [
        ('new', 'Brand New'),
        ('refurbished', 'Refurbished'),
        ('used', 'Used - Excellent'),
        ('used_good', 'Used - Good'),
        ('used_fair', 'Used - Fair'),
    ]

    # Basic Information
    name = models.CharField(max_length=255, blank=True, null=True, 
                           help_text="Product name (auto-generated from brand/model if blank)")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    product_code = models.CharField(max_length=20, unique=True, blank=True, db_index=True)
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    
    # Featured and tracking
    is_featured = models.BooleanField(default=False)
    view_count = models.PositiveIntegerField(default=0)
    sales_count = models.PositiveIntegerField(default=0)

    # SKU (IMEI/Serial) - MUST BE UNIQUE for single items
    sku_value = models.CharField(
        max_length=200, 
        help_text="IMEI NUMBER OR SERIAL NUMBER - MUST BE UNIQUE for each unit",
        db_index=True,
        unique=True,  # Enforce uniqueness across all products
        blank=True,    
        null=True 
    )

    # Barcode - Auto-generated for ALL products when blank
    barcode = models.CharField(
        max_length=30,
        db_index=True,
        unique=True,
        blank=True,
        null=True,
        help_text="Barcode - Auto-generated if left blank"
    )
    
    # Quantity
    quantity = models.PositiveIntegerField(
        default=1,
        help_text="1 for single items (auto-set), multiple for bulk items"
    )
    
    # Pricing
    buying_price = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        help_text="Cost price (what you paid)"
    )
    selling_price = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        help_text="Retail selling price (display price for customers)"
    )
    best_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        help_text="Wholesale selling price (used for bulk sales/discounts)",
        null=True,
        blank=True
    )
    
    # Images
    image = CloudinaryField('image', blank=True, null=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='available')
    
    # Brand and Model - REQUIRED for single items
    brand = models.CharField(max_length=100, blank=True, null=True)
    model = models.CharField(max_length=200, blank=True, null=True)
    
    # Specifications as JSON
    specifications = models.JSONField(
        default=dict,
        blank=True,
        help_text="Store RAM, storage, color, screen size, etc. Example: {'ram': '8GB', 'storage': '256GB', 'color': 'Black'}"
    )
    
    condition = models.CharField(
        max_length=20,
        choices=CONDITION_CHOICES,
        default='new'
    )
    
    warranty_months = models.PositiveIntegerField(
        default=12,
        help_text="Warranty period in months"
    )
    
    description = models.TextField(blank=True, null=True)
    
    supplier = models.ForeignKey(
        Supplier, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='products'
    )

    reorder_level = models.PositiveIntegerField(
        default=5,
        null=True,
        blank=True,
        help_text="Minimum stock level before reordering (for bulk items only)"
    )
    
    last_restocked = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="When was this last restocked"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['category', 'status']),
            models.Index(fields=['sku_value']),
            models.Index(fields=['barcode']),
            models.Index(fields=['product_code']),
            models.Index(fields=['brand', 'model']),
            models.Index(fields=['-created_at']),
        ]
    
    def save(self, *args, **kwargs):
        """
        Override save to:
        1. Auto-generate product_code (FSL format starting from FSL00200)
        2. Auto-generate name from brand/model if blank
        3. Auto-generate barcode if not provided (for ALL products)
        4. Enforce single item quantity = 1
        5. Update status
        """
        
        # Auto-generate name from brand/model if not provided
        if not self.name and self.brand and self.model:
            spec_str = ""
            if self.specifications and isinstance(self.specifications, dict):
                storage = self.specifications.get('storage', '')
                ram = self.specifications.get('ram', '')
                color = self.specifications.get('color', '')
                specs = [f for f in [ram, storage, color] if f]
                if specs:
                    spec_str = f" ({' '.join(specs)})"
            self.name = f"{self.brand} {self.model}{spec_str}"
        
        # Auto-generate unique product_code starting from FSL00200
        if not self.product_code:
            self.product_code = self._generate_product_code()

        # Auto-generate barcode if not provided (for ALL products)
        if not self.barcode:
            self.barcode = self._generate_barcode()
        
        # Enforce single item quantity = 1
        if self.category and self.category.is_single_item:
            self.quantity = 1
        
        # Auto-update status
        self._update_status()
        
        # Validate before saving
        self.clean()
        
        super().save(*args, **kwargs)
    
    def _generate_product_code(self):
        """
        Generate unique sequential product code
        Format: FSL + 5-digit sequential number
        Starting from FSL00200
        Examples: FSL00200, FSL00201, FSL00202
        """
        try:
            # Get the highest existing product code that starts with 'FSL'
            max_code = Product.objects.filter(
                product_code__startswith='FSL'
            ).aggregate(Max('product_code'))['product_code__max']
            
            if max_code and max_code.startswith('FSL'):
                try:
                    # Extract number from last code (FSL00200 -> 200)
                    last_number = int(max_code[3:])
                    new_number = last_number + 1
                except (ValueError, IndexError):
                    # If existing code is invalid format, start from 200
                    new_number = 200
            else:
                # No existing products, start from 200
                new_number = 200
            
            return f"FSL{str(new_number).zfill(5)}"
        except Exception:
            # Fallback using timestamp
            import time
            return f"FSL{str(int(time.time()))[-5:]}"

    def _generate_barcode(self):
        """
        Generate unique barcode for ALL products
        Format options based on item type:
        - Single items: 15-digit format (compatible with IMEI-like scanning)
        - Bulk items: 13-digit EAN-13 format
        """
        import time
        import hashlib
        import random
        
        # Get base for uniqueness
        base = f"{self.product_code or 'NEW'}{time.time()}{random.randint(1000, 9999)}"
        
        # Create a hash and convert to digits
        hash_obj = hashlib.md5(base.encode())
        hash_digest = hash_obj.hexdigest()
        
        # Convert hex to digits
        digits = ''.join(c for c in hash_digest if c.isdigit())
        
        # Ensure we have enough digits
        while len(digits) < 30:
            digits += digits
        
        # Generate different formats based on item type
        if self.category and self.category.is_single_item:
            # Single items: 15-digit format
            barcode = digits[:15]
            
            # Ensure starts with non-zero
            if barcode[0] == '0':
                barcode = '1' + barcode[1:]
        else:
            # Bulk items: 13-digit EAN-13 format
            barcode = digits[:12]  # First 12 digits
            # Calculate check digit (simple modulo 10)
            total = 0
            for i, digit in enumerate(barcode):
                if i % 2 == 0:
                    total += int(digit) * 1
                else:
                    total += int(digit) * 3
            check_digit = (10 - (total % 10)) % 10
            barcode = f"{barcode}{check_digit}"
        
        # Ensure uniqueness
        original_barcode = barcode
        counter = 1
        while Product.objects.filter(barcode=barcode).exists():
            # Add counter and regenerate
            if self.category and self.category.is_single_item:
                # For single items, modify middle digits
                mid = int(barcode[7:12]) + counter
                barcode = f"{barcode[:7]}{str(mid).zfill(5)}{barcode[12:]}"
            else:
                # For bulk items, modify and recalculate check digit
                base_digits = digits[:11] + str(counter).zfill(1)
                total = 0
                for i, digit in enumerate(base_digits):
                    if i % 2 == 0:
                        total += int(digit) * 1
                    else:
                        total += int(digit) * 3
                check_digit = (10 - (total % 10)) % 10
                barcode = f"{base_digits}{check_digit}"
            counter += 1
            if counter > 100:  # Safety valve
                # Fallback to timestamp
                timestamp = str(int(time.time()))[-12:]
                barcode = f"{timestamp}{counter}"
                break
        
        logger.info(f"✅ Generated barcode: {barcode} for product {self.product_code}")
        return barcode

    def _update_status(self):
        """
        Auto-update status based on quantity and item type
        """
        if not self.category:
            return
            
        if self.category.is_single_item:
            # Single items: available, reserved, sold, or damaged
            if self.quantity > 0:
                if self.status not in ['sold', 'damaged']:
                    self.status = 'available'
            elif self.quantity == 0:
                self.status = 'sold'
        else:
            # Bulk items: based on quantity levels
            if self.quantity > 5:
                self.status = 'available'
            elif 1 <= self.quantity <= 5:
                self.status = 'lowstock'
            elif self.quantity == 0:
                self.status = 'outofstock'

    def clean(self):
        """Validation before saving"""
        if not self.category:
            raise ValidationError("Category is required")
            
        # Validate pricing
        if self.buying_price and self.selling_price:
            if self.buying_price > self.selling_price:
                raise ValidationError("Buying price cannot exceed selling price")
        
        if self.best_price and self.selling_price and self.best_price > self.selling_price:
            raise ValidationError("Best price cannot exceed selling price")
        
        # Single items validation
        if self.category.is_single_item:
            # Must have quantity = 1
            if self.quantity != 1:
                raise ValidationError("Single items must have quantity = 1")
            
            # Must have SKU
            if not self.sku_value:
                raise ValidationError("SKU value (IMEI/Serial) is required for single items")
            
            # Should have brand and model
            if not self.brand or not self.model:
                raise ValidationError("Brand and model are required for single items")
        
        # Bulk items validation
        if self.category.is_bulk_item:
            if self.quantity is not None and self.quantity < 0:
                raise ValidationError("Quantity cannot be negative")
        
        # SKU validation based on category
        if self.sku_value and self.category:
            if self.category.sku_type == 'imei':
                if not self.sku_value.isdigit():
                    raise ValidationError("IMEI must contain only digits")
                
                # Optional: Validate IMEI length (usually 15 digits)
                if len(self.sku_value) != 15:
                    logger.warning(f"IMEI {self.sku_value} has unusual length: {len(self.sku_value)}")


    def to_json(self):
        return json.dumps({
            'id': self.id,
            'code': self.product_code,
            'name': self.display_name,
            'price': float(self.selling_price),
            'stock': self.quantity,
            'sku': self.sku_value or '',
        })


    def __str__(self):
        """Safe string representation that handles None values"""
        try:
            display_name = self.display_name or "Unnamed Product"
            product_code = self.product_code or "No Code"
            status_display = self.get_status_display() if self.status else "Unknown"
            
            if self.category and self.category.is_single_item and self.sku_value:
                return f"{display_name} - {self.sku_value} ({product_code})"
            
            return f"{display_name} ({product_code}) - {status_display}"
        except Exception:
            # Ultimate fallback
            return f"Product #{self.id or 'New'}"
    
    @property
    def can_be_used_for_credit(self):
        """
        Check if this product can be used for a new credit transaction
        """
        try:
            if self.status != 'available':
                return False, f"Product is {self.get_status_display()}"
            
            if self.quantity < 1:
                return False, "Product is out of stock"
            
            return True, "Product is available"
        except Exception:
            return False, "Error checking availability"

    @property
    def can_restock(self):
        """Check if this product can be restocked"""
        return self.category and self.category.is_bulk_item

    @property
    def profit_margin(self):
        if self.buying_price and self.selling_price:
            return self.selling_price - self.buying_price
        return Decimal('0.00')

    @property
    def profit_percentage(self):
        if self.buying_price and self.buying_price > 0 and self.selling_price:
            return ((self.selling_price - self.buying_price) / self.buying_price) * 100
        return Decimal('0.0')

    @property
    def needs_reorder(self):
        if self.category and self.category.is_bulk_item and self.reorder_level and self.quantity is not None:
            return self.quantity <= self.reorder_level
        return False
    
    @property
    def display_name(self):
        """Safe display name that handles None values"""
        try:
            if self.brand or self.model:
                brand_part = self.brand or "Unknown Brand"
                model_part = self.model or "Unknown Model"
                
                spec_str = ""
                if self.specifications and isinstance(self.specifications, dict):
                    storage = self.specifications.get('storage', '')
                    ram = self.specifications.get('ram', '')
                    color = self.specifications.get('color', '')
                    specs = [f for f in [ram, storage, color] if f]
                    if specs:
                        spec_str = f" ({' '.join(specs)})"
                
                return f"{brand_part} {model_part}{spec_str}"
            
            elif self.name:
                return self.name
            
            elif self.product_code:
                return f"Product {self.product_code}"
            
            else:
                return f"Product #{self.id or 'New'}"
        except Exception:
            # Ultimate fallback
            return f"Product #{self.id or 'New'}"
    
    @property
    def is_in_warranty(self):
        """Check if item still under warranty"""
        if not self.warranty_months or not self.created_at:
            return False
        from datetime import timedelta
        from django.utils import timezone
        warranty_end = self.created_at + timedelta(days=self.warranty_months * 30)
        return timezone.now() < warranty_end
    
    @property
    def price_difference(self):
        """Difference between selling price and best price"""
        if self.best_price and self.selling_price:
            return self.selling_price - self.best_price
        return Decimal('0.00')
    
    # Add these methods to your existing Product class

    @property
    def stock_status(self):
        """Get detailed stock status"""
        if not self.category:
            return 'unknown'
    
        if self.category.is_single_item:
            if self.quantity == 0:
                return 'outofstock'
            elif self.status == 'reserved':
                return 'reserved'
            elif self.status == 'damaged':
                return 'damaged'
            else:
                return 'available'
        else:
        # Bulk items
            if self.quantity <= 0:
                return 'outofstock'
            elif self.reorder_level and self.quantity <= self.reorder_level:
                return 'needs_reorder'
            elif self.quantity <= 5:  # Low stock threshold
                return 'lowstock'
            else:
                return 'available'

    @property
    def stock_status_badge(self):
        """Get Bootstrap badge class for stock status"""
        status_map = {
            'available': 'success',
            'lowstock': 'warning',
            'needs_reorder': 'danger',
            'outofstock': 'secondary',
            'reserved': 'info',
            'damaged': 'dark',
        }
        return status_map.get(self.stock_status, 'light')

    @property
    def stock_status_icon(self):
        """Get icon for stock status"""
        icon_map = {
            'available': 'fa-check-circle',
            'lowstock': 'fa-exclamation-triangle',
            'needs_reorder': 'fa-exclamation-circle',
            'outofstock': 'fa-times-circle',
            'reserved': 'fa-clock',
            'damaged': 'fa-exclamation-triangle',
        }
        return icon_map.get(self.stock_status, 'fa-box')

    @property
    def can_be_used_for_credit(self):
        """
        Check if this product can be used for a new credit transaction
        Only single items can be used for credit
        """
        try:
            # First check if this is a single item
            if not self.category.is_single_item:
                return False, "Only single items (phones, electronics) can be used for credit"
        
            if self.status != 'available':
                return False, f"Product is {self.get_status_display()}"
        
            if self.quantity < 1:
                return False, "Product is out of stock"
        
            # Check if this product already has ANY credit transaction
            from credit.models import CreditTransaction
            if CreditTransaction.objects.filter(product=self).exists():
                return False, "Product already has a credit transaction"
        
            return True, "Product is available for credit"
        except Exception as e:
            logger.error(f"Error checking credit availability: {str(e)}")
            return False, "Error checking availability"




# ====================================
# INVENTORY PRODUCT IMAGE    📦
# ====================================
class ProductImage(models.Model):
    """Multiple images per product"""
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='images'
    )
    image = CloudinaryField('image')
    is_primary = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['order', '-is_primary', 'created_at']
        unique_together = ['product', 'is_primary']  # Only one primary image per product
    
    def save(self, *args, **kwargs):
        # If this is set as primary, remove primary from other images
        if self.is_primary:
            ProductImage.objects.filter(product=self.product, is_primary=True).update(is_primary=False)
        super().save(*args, **kwargs)
    
    def __str__(self):
        try:
            return f"Image for {self.product.display_name if self.product else 'Unknown Product'}"
        except Exception:
            return f"ProductImage #{self.id}"

# ====================================
# INVENTORY STOCK ENTRY MODEL 📦
# ====================================
class StockEntry(models.Model):
    """
    Tracks all inventory movements:
    - Purchase: Add new stock
    - Sale: Sell items
    - Reversal: Customer returns item
    - Adjustment: Manual correction
    """
    
    ENTRY_TYPE_CHOICES = [
        ('purchase', 'Purchase'),
        ('sale', 'Sale'),
        ('reversal', 'Reversal'),
        ('adjustment', 'Adjustment'),
    ]

    # Links
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='stock_entries',
        help_text="Product this entry affects"
    )
    
    # Transaction Details
    quantity = models.IntegerField(
        help_text="Positive for stock IN, Negative for stock OUT"
    )
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPE_CHOICES)
    
    # Pricing
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
    
    # Reference
    reference_id = models.CharField(
        max_length=255, 
        blank=True, 
        null=True,
        help_text="Invoice/Receipt/Order number"
    )
    notes = models.TextField(blank=True, null=True)
    
    # Metadata
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
            models.Index(fields=['product', '-created_at']),
        ]

    def save(self, *args, **kwargs):
        # Calculate total amount if not provided
        if not self.total_amount and self.unit_price:
            self.total_amount = abs(self.quantity) * self.unit_price
        
        # Validate before saving
        self.clean()
        
        # Save the stock entry
        super().save(*args, **kwargs)
        
        # Stock quantity is now handled by the signal below
        # No manual update here to prevent double counting

    def clean(self):
        """Validation"""
        if not self.product:
            raise ValidationError("Product is required")
            
        # Quantity cannot be zero
        if self.quantity == 0:
            raise ValidationError("Quantity cannot be zero")
        
        # Sales cannot exceed available stock
        if self.entry_type == 'sale' and abs(self.quantity) > (self.product.quantity or 0):
            raise ValidationError(
                f"Cannot sell {abs(self.quantity)} units. Only {self.product.quantity} available."
            )
        
        # Single items: purchases and reversals must be quantity 1
        if self.product.category and self.product.category.is_single_item:
            if self.entry_type in ['purchase', 'reversal'] and abs(self.quantity) != 1:
                raise ValidationError("Single items must have quantity = 1")

    def __str__(self):
        try:
            direction = "IN" if self.quantity > 0 else "OUT"
            entry_type = self.get_entry_type_display() if self.entry_type else "Unknown"
            product_code = self.product.product_code if self.product else "No Product"
            return f"{entry_type} {direction} - {product_code} - {abs(self.quantity)} units"
        except Exception:
            return f"StockEntry #{self.id}"

    @property
    def is_stock_in(self):
        return self.quantity > 0

    @property
    def is_stock_out(self):
        return self.quantity < 0

    @property
    def absolute_quantity(self):
        return abs(self.quantity)






# ====================================
# INVENTORY STOCK ALERT MODEL  📦
# ====================================
class StockAlert(models.Model):
    """Alert when products are running low or out of stock"""
    
    ALERT_TYPE_CHOICES = [
        ('lowstock', 'Low Stock'),
        ('needs_reorder', 'Needs Reorder'),
        ('outofstock', 'Out of Stock'),
        ('expiring', 'Expiring Soon'),
        ('damaged', 'Damaged Stock'),
    ]
    
    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('danger', 'Danger'),
        ('critical', 'Critical'),
    ]
    
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='alerts')
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPE_CHOICES, default='lowstock')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='warning')
    
    # Thresholds
    current_stock = models.PositiveIntegerField(default=0)
    threshold = models.PositiveIntegerField(default=5)
    reorder_level = models.PositiveIntegerField(null=True, blank=True)
    
    # Alert management
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
    
    # Tracking
    last_alerted = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    alert_count = models.PositiveIntegerField(default=0)
    
    class Meta:
        ordering = ['-severity', '-created_at']
        indexes = [
            models.Index(fields=['product', 'is_active']),
            models.Index(fields=['alert_type']),
            models.Index(fields=['severity']),
        ]

    def __str__(self):
        """Safe string representation"""
        try:
            product_name = self.product.display_name if self.product else "Unknown Product"
            return f"{self.get_alert_type_display()}: {product_name}"
        except Exception:
            return f"StockAlert #{self.id}"

    def check_and_alert(self):
        """Check if product needs alert and update"""
        if not self.is_active or self.is_dismissed:
            return False
            
        if not self.product:
            return False
        
        # Update current stock
        self.current_stock = self.product.quantity or 0
        
        # Determine if alert should trigger
        should_alert = False
        new_alert_type = self.alert_type
        
        if self.product.category and self.product.category.is_bulk_item:
            # Bulk items logic
            if self.product.quantity <= 0:
                should_alert = True
                new_alert_type = 'outofstock'
                self.severity = 'critical'
            elif self.product.reorder_level and self.product.quantity <= self.product.reorder_level:
                should_alert = True
                new_alert_type = 'needs_reorder'
                self.severity = 'danger'
            elif self.product.quantity <= self.threshold:
                should_alert = True
                new_alert_type = 'lowstock'
                self.severity = 'warning'
        else:
            # Single items logic
            if self.product.quantity == 0:
                should_alert = True
                new_alert_type = 'outofstock'
                self.severity = 'critical'
            elif self.product.status == 'damaged':
                should_alert = True
                new_alert_type = 'damaged'
                self.severity = 'danger'
        
        if should_alert:
            self.alert_type = new_alert_type
            self.last_alerted = timezone.now()
            self.alert_count += 1
            self.save()
            return True
        
        return False

    def dismiss(self, user=None, reason=""):
        """Dismiss this alert"""
        self.is_dismissed = True
        self.is_active = False
        self.dismissed_by = user
        self.dismissed_at = timezone.now()
        self.dismissed_reason = reason
        self.save()

    def reactivate(self):
        """Reactivate a dismissed alert"""
        self.is_dismissed = False
        self.is_active = True
        self.dismissed_by = None
        self.dismissed_at = None
        self.dismissed_reason = ""
        self.save()

# ====================================
# INVENTORY PRODUCT REVIEW MODEL 📦
# ====================================
class ProductReview(models.Model):
    """Customer product reviews"""
    RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    customer_name = models.CharField(max_length=200)
    rating = models.PositiveIntegerField(choices=RATING_CHOICES, default=5)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product', '-created_at']),
            models.Index(fields=['rating']),
        ]

    def __str__(self):
        """Safe string representation"""
        try:
            product_name = self.product.display_name if self.product else "Unknown Product"
            return f"Review for {product_name} - {self.rating or 0} stars"
        except Exception:
            return f"Review #{self.id}"








# =========================================
# SIGNALS - Complete Stock Entry Management
# =========================================

@receiver(post_save, sender=Product)
def manage_product_stock_entries(sender, instance, created, **kwargs):
    """
    Automatically manage StockEntries when products are created
    """
    try:
        # ONLY for new products - create initial stock entry
        if created:
            # Check if any stock entries already exist (shouldn't, but just in case)
            if not StockEntry.objects.filter(product=instance).exists():
                quantity = instance.quantity or 1
                unit_price = instance.buying_price or Decimal('0.00')
                total_amount = quantity * unit_price
                
                StockEntry.objects.create(
                    product=instance,
                    quantity=quantity,
                    entry_type='purchase',
                    unit_price=unit_price,
                    total_amount=total_amount,
                    reference_id=f"INIT-{instance.product_code or instance.id}",
                    notes=f"Initial stock - {instance.display_name}",
                    created_by=instance.owner,
                    created_at=timezone.now()
                )
                
                logger.info(f"✅ INITIAL STOCK: {instance.product_code} - Qty: {quantity}")
        
    except Exception as e:
        logger.error(f"❌ Error in stock entry management: {str(e)}")

@receiver(pre_save, sender=StockEntry)
def validate_stock_entry(sender, instance, **kwargs):
    """
    Validate stock entries before saving
    """
    try:
        if instance.quantity == 0:
            raise ValidationError("Stock entry quantity cannot be zero")
        
        # For sales, ensure we have enough stock
        if instance.entry_type == 'sale' and instance.quantity < 0:
            available_stock = instance.product.quantity or 0
            if abs(instance.quantity) > available_stock:
                raise ValidationError(
                    f"Cannot sell {abs(instance.quantity)} units. "
                    f"Only {available_stock} available."
                )
        
        # For single items, enforce quantity = 1
        if instance.product.category and instance.product.category.is_single_item:
            if instance.entry_type in ['purchase', 'reversal'] and abs(instance.quantity) != 1:
                raise ValidationError("Single items must have quantity = 1 for purchase/reversal")
                
    except AttributeError:
        # Product might not be set yet during initial creation
        pass
    except Exception as e:
        logger.error(f"❌ Stock entry validation error: {str(e)}")




@receiver(post_save, sender=StockEntry)
def update_product_quantity_from_entries(sender, instance, created, **kwargs):
    """Update product quantity based on all stock entries"""
    if created:
        try:
            product = instance.product
            # Calculate total from ALL entries for this product
            total = StockEntry.objects.filter(product=product).aggregate(
                total=Sum('quantity')
            )['total'] or 0
            
            # Update product quantity
            product.quantity = total
            product.save()
            
            logger.info(f"📦 STOCK UPDATE: {product.product_code} - New quantity: {total}")
        except Exception as e:
            logger.error(f"❌ Error updating product quantity: {str(e)}")




# =========================================
# NEW SIGNAL - Auto-create stock alerts
# =========================================
@receiver(post_save, sender=Product)
def create_stock_alerts(sender, instance, created, **kwargs):
    """Auto-create or update stock alerts for products"""
    try:
        if not instance.category:
            return
        
        # Determine alert type and threshold
        alert_type = 'lowstock'
        threshold = 5
        severity = 'warning'
        
        if instance.category.is_bulk_item:
            if instance.quantity <= 0:
                alert_type = 'outofstock'
                severity = 'critical'
            elif instance.reorder_level and instance.quantity <= instance.reorder_level:
                alert_type = 'needs_reorder'
                severity = 'danger'
            elif instance.quantity <= threshold:
                alert_type = 'lowstock'
                severity = 'warning'
            else:
                # Stock is fine, deactivate any existing alerts
                StockAlert.objects.filter(product=instance, is_active=True).update(
                    is_active=False,
                    is_dismissed=True
                )
                return
        else:
            # Single items
            if instance.quantity == 0:
                alert_type = 'outofstock'
                severity = 'critical'
            elif instance.status == 'damaged':
                alert_type = 'damaged'
                severity = 'danger'
            else:
                # Available, deactivate alerts
                StockAlert.objects.filter(product=instance, is_active=True).update(
                    is_active=False,
                    is_dismissed=True
                )
                return
        
        # Create or update alert
        alert, created = StockAlert.objects.update_or_create(
            product=instance,
            is_dismissed=False,
            defaults={
                'alert_type': alert_type,
                'severity': severity,
                'current_stock': instance.quantity,
                'threshold': threshold,
                'reorder_level': instance.reorder_level,
                'is_active': True,
                'last_alerted': timezone.now(),
            }
        )
        
        if created:
            logger.info(f"✅ Created {alert_type} alert for {instance.product_code}")
        else:
            logger.info(f"✅ Updated {alert_type} alert for {instance.product_code}")
            
    except Exception as e:
        logger.error(f"❌ Error creating stock alert: {str(e)}")






# ====================================
# RETURN REQUEST MODEL
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
        ('mismatch', 'Product Mismatch Detected'),
    ]
    
    RETURN_REASON_CHOICES = [
        ('defective', 'Defective Product'),
        ('wrong_item', 'Wrong Item Received'),
        ('changed_mind', 'Changed Mind'),
        ('damaged', 'Damaged During Shipping'),
        ('not_as_described', 'Not as Described'),
        ('other', 'Other'),
    ]
    
    VERIFICATION_STATUS_CHOICES = [
        ('pending', 'Pending Verification'),
        ('passed', 'Verification Passed'),
        ('failed', 'Verification Failed'),
        ('partial', 'Partial Match'),
    ]
    
    # Return identification
    return_id = models.CharField(max_length=50, unique=True, default=uuid.uuid4, editable=False)
    
    # Link to original sale (if exists) - FIXED: Using string reference
    related_sale = models.ForeignKey(
        'sales.Sale',  # Changed from Sale to 'sales.Sale' (string reference)
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='returns'
    )
    
    # Product information
    product = models.ForeignKey(
        'Product', 
        on_delete=models.CASCADE, 
        related_name='returns'
    )
    product_code = models.CharField(max_length=100)
    product_name = models.CharField(max_length=255)
    sku_value = models.CharField(max_length=200, blank=True, null=True)
    quantity = models.PositiveIntegerField(default=1)
    
    # Return details
    reason = models.CharField(max_length=50, choices=RETURN_REASON_CHOICES)
    reason_text = models.TextField(blank=True, null=True, help_text="Additional details about the return")
    
    # Search identifiers
    etr_number = models.CharField(max_length=100, blank=True, null=True, help_text="ETR receipt number from sale")
    sale_id = models.CharField(max_length=50, blank=True, null=True, help_text="Original sale ID")
    
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
    
    # ============================================
    # VERIFICATION FIELDS (Manager Verification)
    # ============================================
    verification_status = models.CharField(
        max_length=20, 
        choices=VERIFICATION_STATUS_CHOICES, 
        default='pending'
    )
    verified_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='verified_returns'
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    
    # Physical verification checks
    verification_notes = models.TextField(blank=True, null=True)
    
    # Verification checklist
    physical_product_seen = models.BooleanField(default=False)
    serial_number_matches = models.BooleanField(default=False)
    condition_matches_report = models.BooleanField(default=False)
    accessories_present = models.BooleanField(default=False)
    box_present = models.BooleanField(default=False)
    receipt_present = models.BooleanField(default=False)
    
    # Photos of returned product
    product_photo_1 = models.ImageField(upload_to='returns/', blank=True, null=True)
    product_photo_2 = models.ImageField(upload_to='returns/', blank=True, null=True)
    product_photo_3 = models.ImageField(upload_to='returns/', blank=True, null=True)
    damage_photo = models.ImageField(upload_to='returns/damage/', blank=True, null=True)
    
    # System verification
    system_sku = models.CharField(max_length=200, blank=True, null=True, help_text="SKU from system")
    system_serial = models.CharField(max_length=200, blank=True, null=True, help_text="Serial from system")
    system_condition = models.CharField(max_length=50, blank=True, null=True, help_text="Condition in system")
    
    # Actual returned item details (recorded by manager)
    actual_sku = models.CharField(max_length=200, blank=True, null=True)
    actual_serial = models.CharField(max_length=200, blank=True, null=True)
    actual_condition = models.CharField(
        max_length=20,
        choices=[
            ('new', 'Like New'),
            ('good', 'Good'),
            ('fair', 'Fair'),
            ('damaged', 'Damaged'),
            ('different', 'Different Product'),
        ],
        blank=True,
        null=True
    )
    
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
            models.Index(fields=['verification_status']),
            models.Index(fields=['sale_id']),
            models.Index(fields=['etr_number']),
            models.Index(fields=['sku_value']),
            models.Index(fields=['product_code']),
            models.Index(fields=['-requested_at']),
        ]
    
    def __str__(self):
        return f"Return #{self.return_id} - {self.product_name}"
    
    def submit_for_verification(self):
        """Submit return for manager verification"""
        self.status = 'submitted'
        self.save()
    
    def verify_product(self, user, verification_data):
        """Manager verifies the physical product matches system records"""
        self.verified_by = user
        self.verified_at = timezone.now()
        self.verification_notes = verification_data.get('notes', '')
        
        # Update verification checklist
        self.physical_product_seen = verification_data.get('physical_product_seen', False)
        self.serial_number_matches = verification_data.get('serial_number_matches', False)
        self.condition_matches_report = verification_data.get('condition_matches_report', False)
        self.accessories_present = verification_data.get('accessories_present', False)
        self.box_present = verification_data.get('box_present', False)
        self.receipt_present = verification_data.get('receipt_present', False)
        
        # Record actual item details
        self.actual_sku = verification_data.get('actual_sku', '')
        self.actual_serial = verification_data.get('actual_serial', '')
        self.actual_condition = verification_data.get('actual_condition', '')
        
        # Check if product matches
        system_matches = True
        issues = []
        
        if self.product.sku_value and self.actual_sku != self.product.sku_value:
            system_matches = False
            issues.append('SKU mismatch')
        
        if self.actual_condition and self.actual_condition != self.reported_condition:
            issues.append('condition mismatch')
        
        if system_matches and not issues:
            self.verification_status = 'passed'
            self.status = 'verified'
        else:
            self.verification_status = 'failed'
            self.status = 'mismatch'
            self.notes = f"Verification failed: {', '.join(issues)}"
        
        self.save()
        return system_matches, issues
    
    def approve(self, user):
        """Approve the verified return"""
        if self.verification_status != 'passed':
            raise ValueError("Only verified returns can be approved")
        
        self.status = 'approved'
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save()
        
    def reject(self, user, reason):
        """Reject the return request"""
        self.status = 'rejected'
        self.approved_by = user
        self.approved_at = timezone.now()
        self.notes = reason
        self.save()
    
    def process(self, user):
        """Process the approved return (restock product)"""
        if self.status != 'approved':
            raise ValueError("Only approved returns can be processed")
        
        from django.db import transaction
        
        with transaction.atomic():
            # Update product stock
            product = self.product
            if product.category.is_single_item:
                product.status = 'available'
                product.quantity = 1
            else:
                product.quantity += self.quantity
            product.save()
            
            # Create stock entry
            StockEntry.objects.create(
                product=product,
                quantity=self.quantity,
                entry_type='return',
                unit_price=self.refund_amount / self.quantity if self.refund_amount else product.buying_price,
                total_amount=self.refund_amount or (product.buying_price * self.quantity),
                reference_id=f"RETURN-{self.return_id}",
                notes=f"Return from customer - Verified by {self.verified_by.username if self.verified_by else 'Manager'}",
                created_by=user
            )
            
            self.status = 'processed'
            self.processed_by = user
            self.processed_at = timezone.now()
            self.save()