from django.db import models
from django.contrib.auth.models import User

class DynamicChoice(models.Model):
    """Base model for dynamic choices"""
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

class ShopConfiguration(models.Model):
    """Shop-specific configurations"""
    shop = models.ForeignKey('ShopBranch', on_delete=models.CASCADE, related_name='configurations')
    config_key = models.CharField(max_length=100)
    config_value = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['shop', 'config_key']
    
    def __str__(self):
        return f"{self.shop.name} - {self.config_key}"