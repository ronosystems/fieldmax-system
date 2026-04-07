# In finance/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from credit.models import CompanyPayment
from .models import FinancialTransaction, CashAccount, BankAccount
from decimal import Decimal

@receiver(post_save, sender=CompanyPayment)
def create_finance_entry_for_company_payment(sender, instance, created, **kwargs):
    """Automatically create finance entry when a company payment is recorded"""
    if created:
        # Create financial transaction
        FinancialTransaction.objects.create(
            transaction_type='income',
            category='credit_reconciliation',
            amount=instance.amount,
            description=f"Credit payment from {instance.credit_company.name} - {instance.payment_id}",
            payment_method=instance.payment_method,
            payment_reference=instance.payment_reference,
            recipient_name=instance.credit_company.name,
            created_by=instance.created_by,
            notes=instance.notes
        )
        
        # Update account balance
        if instance.payment_method == 'cash':
            cash_account, _ = CashAccount.objects.get_or_create(id=1)
            cash_account.balance += instance.amount
            cash_account.save()
        else:
            bank_account, _ = BankAccount.objects.get_or_create(id=1)
            bank_account.balance += instance.amount
            bank_account.save()