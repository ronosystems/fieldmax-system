from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
import json
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from inventory.models import Product 






# ============================================
# PEMDING ORDER
# ============================================

class PendingOrder(models.Model):
    """
    Orders submitted by customers that need staff approval
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
    ]
    
    # Order ID
    order_id = models.CharField(max_length=50, unique=True, editable=False)
    
    # Customer Details
    buyer_name = models.CharField(max_length=200)
    buyer_phone = models.CharField(max_length=20)
    buyer_email = models.CharField(max_length=255, blank=True, null=True)
    buyer_id_number = models.CharField(max_length=50, blank=True, null=True)
    
    # Order Details (stored as JSON)
    cart_data = models.TextField(help_text="JSON data of cart items")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    item_count = models.PositiveIntegerField(default=0)
    
    # Payment Details
    payment_method = models.CharField(max_length=50, default='cash')
    notes = models.TextField(blank=True, null=True)
    
    # Status Tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Staff Actions
    reviewed_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='reviewed_orders'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)
    
    # Link to actual Sale (once approved)
    sale_id = models.CharField(max_length=50, blank=True, null=True)


    approved_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        related_name='approved_orders',
        blank=True, 
        null=True
    )
    approved_date = models.DateTimeField(blank=True, null=True)
    
    rejected_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        related_name='rejected_orders',
        blank=True, 
        null=True
    )
    rejected_date = models.DateTimeField(blank=True, null=True)
    rejection_reason = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        db_table = 'pending_orders'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['buyer_phone']),
        ]
    
    def __str__(self):
        return f"Order {self.order_id} - {self.buyer_name} - {self.get_status_display()}"
    
    def save(self, *args, **kwargs):
        if not self.order_id:
            # Generate order ID: PO-YYYYMMDD-XXXX
            from django.db.models import Max
            today = timezone.now().strftime('%Y%m%d')
            prefix = f"PO-{today}"
            
            last_order = PendingOrder.objects.filter(
                order_id__startswith=prefix
            ).aggregate(Max('order_id'))['order_id__max']
            
            if last_order:
                last_num = int(last_order.split('-')[-1])
                new_num = last_num + 1
            else:
                new_num = 1
            
            self.order_id = f"{prefix}-{new_num:04d}"
        
        super().save(*args, **kwargs)
    
    @property
    def cart_items(self):
        """Parse and return cart items from cart_data JSON"""
        try:
            return json.loads(self.cart_data)
        except:
            return []
    
    @property
    def can_be_approved(self):
        return self.status == 'pending'
    
    @property
    def can_be_rejected(self):
        return self.status == 'pending'








# ============================================
# PENDING ORDER ITEM 
# ============================================

class PendingOrderItem(models.Model):
    """
    Individual items in a pending order
    """
    order = models.ForeignKey(
        PendingOrder, 
        on_delete=models.CASCADE, 
        related_name='items'
    )
    product_name = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'pending_order_items'
        ordering = ['id']
    
    def __str__(self):
        return f"{self.product_name} x{self.quantity} - {self.order.order_id}"
    
    @property
    def total_price(self):
        return self.unit_price * self.quantity
    



    
    
class Customer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    
    # Basic Info
    full_name = models.CharField(max_length=200)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20)
    
    # Address
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.full_name} ({self.email})"


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    # Order Info
    order_number = models.CharField(max_length=50, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='orders')
    
    # Customer details (in case customer is deleted)
    customer_name = models.CharField(max_length=200)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20)
    
    # Delivery Address
    delivery_address = models.TextField()
    delivery_city = models.CharField(max_length=100)
    delivery_postal_code = models.CharField(max_length=20, blank=True, null=True)
    
    # Order Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    
    # Pricing
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Notes
    notes = models.TextField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status']),
            models.Index(fields=['customer']),
        ]

    def __str__(self):
        return f"Order {self.order_number} - {self.customer_name}"

    def save(self, *args, **kwargs):
        if not self.order_number:
            # Generate unique order number
            timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
            self.order_number = f"ORD-{timestamp}"
        
        # Calculate totals
        self.total_amount = self.subtotal + self.delivery_fee
        
        super().save(*args, **kwargs)

    def calculate_subtotal(self):
        """Calculate subtotal from order items"""
        subtotal = sum(item.subtotal for item in self.items.all())
        self.subtotal = subtotal
        self.save(update_fields=['subtotal', 'total_amount'])
        return subtotal


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    
    # Product details (in case product is deleted)
    product_code = models.CharField(max_length=50)
    product_name = models.CharField(max_length=200)
    product_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Order details
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.product_name} x {self.quantity}"

    def save(self, *args, **kwargs):
        # Calculate subtotal
        self.subtotal = self.product_price * self.quantity
        super().save(*args, **kwargs)
        
        # Update order subtotal
        self.order.calculate_subtotal()
        
        # Update product sales count if this is a new item
        if self.pk is None and self.product:
            self.product.sales_count += self.quantity
            self.product.save(update_fields=['sales_count'])


# Optional: Cart model for managing shopping carts
class Cart(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='carts', null=True, blank=True)
    session_key = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.customer:
            return f"Cart - {self.customer.full_name}"
        return f"Cart - Session {self.session_key}"

    def get_total(self):
        return sum(item.subtotal for item in self.items.all())


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['cart', 'product']

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

    def save(self, *args, **kwargs):
        self.subtotal = self.product.selling_price * self.quantity
        super().save(*args, **kwargs)