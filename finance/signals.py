# finance/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from credit.models import CompanyPayment
from .models import (
    FinancialTransaction, CashAccount, BankAccount, CapitalAccount, 
    CapitalInjection, CapitalInjectionRepayment, StockPurchase, 
    PurchaseAccount, IncomeTransaction, IncomeAccount
)
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


@receiver(post_save, sender='sales.Sale')
def process_sale_accounting(sender, instance, created, **kwargs):
    """
    Process accounting when a sale is completed:
    1. Create IncomeTransaction for capital tracking
    2. Process sale accounting (income, cost, profit)
    """
    # Only process when sale is completed
    if not (hasattr(instance, 'status') and instance.status == 'completed'):
        return
    
    if instance.is_reversed:
        return
    
    from .models import SaleAccountingHelper, IncomeAccount, IncomeTransaction
    
    # STEP 1: Create IncomeTransaction for capital account (if new sale)
    if created:
        income_account = IncomeAccount.get_or_create_account()
        IncomeTransaction.objects.create(
            income_account=income_account,
            amount=instance.total_amount,
            transaction_type='sale',
            reference=instance.sale_id,
            description=f"Sale {instance.sale_id}",
            transaction_date=instance.sale_date,
            created_by=instance.seller
        )
        print(f"✅ Auto-created IncomeTransaction for sale {instance.sale_id}")
    
    # STEP 2: Process sale accounting (Income, COGS, Profit)
    result = SaleAccountingHelper.process_sale(instance)
    print(f"Sale {instance.sale_id} accounted: Income={result['income']}, Cost={result['cost']}, Profit={result['profit']}")


@receiver(post_save, sender=CapitalInjection)
def update_capital_account_on_injection(sender, instance, created, **kwargs):
    """Auto-update capital account when injection is completed"""
    if instance.status == 'completed':
        capital_account = CapitalAccount.get_or_create_account()
        capital_account.refresh_from_db()
        print(f"✅ Capital account updated after injection {instance.injection_id}: Net={capital_account.net_capital}")


@receiver(post_save, sender=CapitalInjectionRepayment)
def update_capital_account_on_repayment(sender, instance, created, **kwargs):
    """Auto-update capital account on loan repayment"""
    capital_account = CapitalAccount.get_or_create_account()
    capital_account.refresh_from_db()
    print(f"✅ Capital account updated after repayment: Net={capital_account.net_capital}")


@receiver(post_save, sender=StockPurchase)
def deduct_capital_on_stock_purchase(sender, instance, created, **kwargs):
    """Deduct from capital account when stock is purchased"""
    if created:
        capital_account = CapitalAccount.get_or_create_account()
        capital_account.deduct_for_purchase(instance.total_amount, instance.created_by)
        print(f"💰 Capital deducted: KES {instance.total_amount:,.2f} for purchase {instance.sku_code}")


@receiver(post_save, sender=IncomeTransaction)
def add_sales_revenue_to_capital(sender, instance, created, **kwargs):
    """Add sales revenue to capital account when a sale is recorded"""
    if created and instance.transaction_type == 'sale':
        capital_account = CapitalAccount.get_or_create_account()
        capital_account.add_sales_revenue(instance.amount, instance.created_by)
        print(f"💰 Sales revenue added to capital: KES {instance.amount:,.2f}")