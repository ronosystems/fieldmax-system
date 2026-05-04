from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal

# Correct import - 'shops' (plural)
from shops.models import ShopBranch

class RepairJob(models.Model):
    # Reference to ShopBranch from your shops app
    shop = models.ForeignKey(
        ShopBranch, 
        on_delete=models.CASCADE,
        related_name='repair_jobs',
        null=True, 
        blank=True,
        verbose_name="Shop Branch"
    )
    
    # ... rest of your model fields remain the same ...
    customer_name = models.CharField(max_length=100)
    customer_phone = models.CharField(max_length=15, blank=True, null=True)
    device_type = models.CharField(max_length=50)
    device_model = models.CharField(max_length=100, blank=True, null=True)
    issue_description = models.TextField()
    
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('in_progress', 'In Progress'),
            ('completed', 'Completed'),
            ('picked_up', 'Picked Up'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending'
    )
    
    material_cost = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Cost of materials used for repair"
    )
    
    labor_cost = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Labor/service charges"
    )
    
    total_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        blank=True, 
        null=True,
        help_text="Total amount customer needs to pay (material + labor)"
    )
    
    amount_paid = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text="Amount already paid by customer"
    )
    
    remaining_balance = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        blank=True, 
        null=True,
        help_text="Remaining amount to be paid"
    )
    
    payment_method = models.CharField(
        max_length=50,
        choices=[
            ('cash', 'Cash'),
            ('mpesa', 'M-Pesa'),
            ('bank', 'Bank Transfer'),
            ('mixed', 'Mixed'),
        ],
        default='cash',
        blank=True,
        null=True
    )
    
    mpesa_transaction_code = models.CharField(max_length=50, blank=True, null=True)
    technician_name = models.CharField(max_length=100, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    picked_up_at = models.DateTimeField(blank=True, null=True)
    
    notes = models.TextField(blank=True, null=True)
    warranty_days = models.IntegerField(default=30, help_text="Warranty period in days")
    
    def save(self, *args, **kwargs):
        from django.utils import timezone
        self.total_amount = self.material_cost + self.labor_cost
        self.remaining_balance = self.total_amount - self.amount_paid
        
        if self.status == 'completed' and not self.completed_at:
            self.completed_at = timezone.now()
        
        if self.status == 'picked_up' and not self.picked_up_at:
            self.picked_up_at = timezone.now()
            
        super().save(*args, **kwargs)
    
    def __str__(self):
        shop_name = self.shop.name if self.shop else "No Shop"
        return f"{shop_name} - {self.customer_name} - {self.device_type} - ${self.total_amount}"
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Repair Jobs"


class RepairJobExpense(models.Model):
    repair_job = models.ForeignKey(RepairJob, on_delete=models.CASCADE, related_name='expenses')
    description = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date_incurred = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.repair_job.customer_name} - {self.description}: ${self.amount}"
