# finance/signals.py
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from decimal import Decimal
import logging

from credit.models import CompanyPayment
from sales.models import Sale, SaleItem
from inventory.models import StockEntry, Product, ProductUnit
from .models import (
    FinancialTransaction, CashAccount, BankAccount, CapitalAccount, 
    CapitalInjection, CapitalInjectionRepayment, StockPurchase, 
    PurchaseAccount, IncomeTransaction, IncomeAccount, ProfitAccount,
    PurchaseTransaction, ProfitTransaction, NetAccount, SavingsAccount
)
from finance import models

logger = logging.getLogger(__name__)


# ============================================
# SALE ACCOUNTING HELPER - FIXED VERSION
# ============================================

class SaleAccountingHelper:
    """Helper to process sale accounting"""
    
    @staticmethod
    def process_sale(sale, user=None):
        """
        Process accounting for a sale:
        1. Record income (selling price) - CREDIT IncomeAccount
        2. Record purchase cost (buying price) - DEBIT PurchaseAccount  
        3. Record profit (selling price - buying price) - CREDIT ProfitAccount
        """
        from decimal import Decimal
        
        # Get or create accounts
        income_account = IncomeAccount.get_or_create_account()
        purchase_account = PurchaseAccount.get_or_create_account()
        profit_account = ProfitAccount.get_or_create_account()
        
        total_income = Decimal('0')
        total_cost = Decimal('0')
        
        # Get sale items
        if hasattr(sale, 'items'):
            items = sale.items.all()
        elif hasattr(sale, 'sale_items'):
            items = sale.sale_items.all()
        else:
            items = []
        
        for item in items:
            # FIXED: Use unit_price, not price
            selling_price = Decimal(str(item.unit_price)) * Decimal(str(item.quantity))
            
            # Get buying price from product
            if hasattr(item, 'product') and item.product:
                buying_price = Decimal(str(item.product.buying_price)) * Decimal(str(item.quantity))
            else:
                buying_price = Decimal('0')
            
            profit = selling_price - buying_price
            
            total_income += selling_price
            total_cost += buying_price
        
        # Only record if there are items
        if total_income > 0:
            # Add total income to IncomeAccount
            income_account.add_income(
                amount=total_income,
                sale_reference=getattr(sale, 'sale_id', str(sale.id)),
                user=user or getattr(sale, 'seller', None)
            )
            
            # Add total purchase cost to PurchaseAccount
            purchase_account.add_purchase_cost(
                amount=total_cost,
                product_reference=getattr(sale, 'sale_id', str(sale.id)),
                user=user or getattr(sale, 'seller', None)
            )
            
            # Record profit
            profit_account.add_profit(
                amount=total_income - total_cost,
                sale_reference=getattr(sale, 'sale_id', str(sale.id)),
                user=user or getattr(sale, 'seller', None)
            )
        
        return {
            'income': total_income,
            'cost': total_cost,
            'profit': total_income - total_cost
        }


# ============================================
# SIGNAL: Company Payment
# ============================================

@receiver(post_save, sender=CompanyPayment)
def create_finance_entry_for_company_payment(sender, instance, created, **kwargs):
    """Automatically create finance entry when a company payment is recorded"""
    if created:
        try:
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
            
            if instance.payment_method == 'cash':
                cash_account, _ = CashAccount.objects.get_or_create(id=1)
                cash_account.balance += instance.amount
                cash_account.save()
            else:
                bank_account, _ = BankAccount.objects.get_or_create(id=1)
                bank_account.balance += instance.amount
                bank_account.save()
                
            logger.info(f"✅ Finance entry created for company payment: {instance.payment_id}")
            
        except Exception as e:
            logger.error(f"Error creating finance entry for company payment: {str(e)}")


# ============================================
# SIGNAL: Sale (Main Accounting) - FIXED
# ============================================

@receiver(post_save, sender=Sale)
def process_sale_accounting(sender, instance, created, **kwargs):
    """
    Process accounting when a sale is completed:
    Update Net and Savings accounts
    """
    # Only process when sale is not reversed
    if instance.is_reversed:
        return
    
    try:
        net_account = NetAccount.get_account()
        savings_account = SavingsAccount.get_account()
        
        total_cogs = Decimal('0')
        total_profit = Decimal('0')
        
        for item in instance.items.all():
            if item.product:
                buying_price = item.product.buying_price or Decimal('0')
                cogs_for_item = buying_price * item.quantity
                profit_for_item = item.total_price - cogs_for_item
                
                total_cogs += cogs_for_item
                total_profit += profit_for_item
        
        if total_cogs > 0:
            net_account.add_cogs(amount=total_cogs, sale_reference=instance.sale_id, user=instance.seller)
            logger.info(f"📈 NET: Added COGS KES {total_cogs} from sale {instance.sale_id}")
        
        if total_profit > 0:
            savings_account.add_profit(amount=total_profit, sale_reference=instance.sale_id, user=instance.seller)
            logger.info(f"💰 SAVINGS: Added profit KES {total_profit} from sale {instance.sale_id}")
        
    except Exception as e:
        logger.error(f"Error processing sale accounting for {instance.sale_id}: {str(e)}")


# ============================================
# SIGNAL: StockEntry (Purchase entries only)
# ============================================

@receiver(post_save, sender=StockEntry)
def update_purchase_account_on_stock_entry(sender, instance, created, **kwargs):
    """Update purchase account when stock entry is created or updated"""
    if instance.entry_type != 'purchase' or instance.quantity <= 0:
        return
    
    try:
        purchase_account = PurchaseAccount.get_or_create_account()
        total_cost = instance.unit_price * instance.quantity
        
        purchase_account.add_purchase_cost(
            amount=total_cost,
            product_reference=instance.reference_id or f"SKU:{instance.product_sku.sku_code if instance.product_sku else 'N/A'}",
            user=instance.created_by
        )
        
        purchase_account.total_purchases = PurchaseTransaction.objects.filter(
            transaction_type='cogs'
        ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
        purchase_account.save()
        
        logger.info(f"✅ Purchase account updated for stock entry {instance.id}: KES {total_cost:,.2f}")
        
    except Exception as e:
        logger.error(f"Error updating purchase account for stock entry {instance.id}: {str(e)}")


# ============================================
# SIGNAL: Capital Injection
# ============================================

@receiver(post_save, sender=CapitalInjection)
def update_capital_account_on_injection(sender, instance, created, **kwargs):
    """Auto-update capital account when injection is completed"""
    if instance.status == 'completed':
        try:
            capital_account = CapitalAccount.get_or_create_account()
            capital_account.refresh_from_db()
            logger.info(f"✅ Capital account updated after injection {instance.injection_id}")
        except Exception as e:
            logger.error(f"Error updating capital account for injection: {str(e)}")


# ============================================
# SIGNAL: Capital Injection Repayment
# ============================================

@receiver(post_save, sender=CapitalInjectionRepayment)
def update_capital_account_on_repayment(sender, instance, created, **kwargs):
    """Auto-update capital account on loan repayment"""
    try:
        capital_account = CapitalAccount.get_or_create_account()
        capital_account.refresh_from_db()
        logger.info(f"✅ Capital account updated after repayment")
    except Exception as e:
        logger.error(f"Error updating capital account for repayment: {str(e)}")

# ============================================
# SIGNAL: AccountTransaction Expense for Net Account
# ============================================

@receiver(post_save, sender='finance.AccountTransaction')
def process_expense_for_net(sender, instance, created, **kwargs):
    """When an expense is recorded, deduct from Net Account"""
    if not created or instance.transaction_type != 'expense':
        return
    
    try:
        net_account = NetAccount.get_account()
        expense_type_map = {'cash': 'Cash Expense', 'bank': 'Bank Expense', 'credit': 'Credit Expense'}
        expense_type = expense_type_map.get(instance.account_type, 'Operational Expense')
        
        net_account.deduct_operational_expense(
            amount=instance.amount,
            expense_type=expense_type,
            reference=instance.reference or f"EXP-{instance.id}",
            user=instance.created_by
        )
        logger.info(f"📉 NET: Deducted expense KES {instance.amount} ({expense_type})")
    except Exception as e:
        logger.error(f"Failed to process expense for Net: {str(e)}")