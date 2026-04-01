# credit/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from decimal import Decimal
from django.db import models
import logging

from .models import CreditTransaction, CompanyPayment
from finance.models import FinancialTransaction, CashAccount, BankAccount, CreditAccount

logger = logging.getLogger(__name__)


@receiver(post_save, sender=CreditTransaction)
def credit_transaction_paid_signal(sender, instance, created, **kwargs):
    """
    When a credit transaction is marked as paid, create a financial transaction
    """
    # Only process when payment_status changes to 'paid'
    if instance.payment_status == 'paid' and not instance.finance_transaction_id:
        try:
            # Create financial transaction for income
            financial_trans = FinancialTransaction.objects.create(
                transaction_type='income',
                category='commission',
                amount=instance.ceiling_price,
                description=f"Credit payment from {instance.credit_company.name} - {instance.transaction_id} - {instance.customer.full_name}",
                payment_method=instance.payment_reference and 'bank' or 'cash',
                payment_reference=instance.payment_reference or instance.transaction_id,
                recipient_name=instance.credit_company.name,
                created_by=instance.dealer,
                notes=f"Credit sale payment for product: {instance.product_name}, Customer: {instance.customer.full_name}"
            )
            
            # Link back to credit transaction
            instance.finance_transaction_id = financial_trans.id
            instance.save(update_fields=['finance_transaction_id'])
            
            logger.info(f"Created financial transaction for credit payment {instance.transaction_id}: KSH {instance.ceiling_price}")
            
        except Exception as e:
            logger.error(f"Error creating financial transaction for credit {instance.transaction_id}: {str(e)}")


@receiver(post_save, sender=CompanyPayment)
def company_payment_signal(sender, instance, created, **kwargs):
    """
    When a company makes a bulk payment, create financial transaction
    """
    if created:
        try:
            # Calculate total commission from paid transactions
            total_commission = instance.transactions.aggregate(
                total=models.Sum('commission_amount')
            )['total'] or Decimal('0.00')
            
            # Create financial transaction for the payment
            financial_trans = FinancialTransaction.objects.create(
                transaction_type='income',
                category='commission',
                amount=instance.amount,
                description=f"Bulk payment from {instance.credit_company.name} - {instance.payment_id}",
                payment_method=instance.payment_method,
                payment_reference=instance.payment_reference,
                recipient_name=instance.credit_company.name,
                created_by=instance.created_by,
                notes=f"Payment includes {instance.transactions.count()} transactions. Total commission: KSH {total_commission}"
            )
            
            # Link to each transaction
            for trans in instance.transactions.all():
                trans.finance_transaction_id = financial_trans.id
                trans.save(update_fields=['finance_transaction_id'])
            
            # Update finance accounts
            if instance.payment_method == 'cash':
                cash_account, _ = CashAccount.objects.get_or_create(id=1)
                cash_account.update_balance(instance.amount, 'income', instance.created_by)
            elif instance.payment_method == 'bank':
                bank_account, _ = BankAccount.objects.get_or_create(id=1)
                bank_account.update_balance(instance.amount, 'income', instance.created_by)
            elif instance.payment_method == 'mpesa':
                bank_account, _ = BankAccount.objects.get_or_create(id=1)
                bank_account.update_balance(instance.amount, 'income', instance.created_by)
            
            logger.info(f"Created financial transaction for company payment {instance.payment_id}: KSH {instance.amount}")
            
        except Exception as e:
            logger.error(f"Error creating financial transaction for payment {instance.payment_id}: {str(e)}")