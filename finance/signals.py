# finance/signals.py
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
    PurchaseTransaction, ProfitTransaction
)
from finance import models

logger = logging.getLogger(__name__)


# ============================================
# SALE ACCOUNTING HELPER (moved here from models)
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
            # Calculate selling price total
            selling_price = Decimal(str(item.price)) * Decimal(str(item.quantity))
            
            # Get buying price from product (CORRECTED price)
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
                
            logger.info(f"✅ Finance entry created for company payment: {instance.payment_id}")
            
        except Exception as e:
            logger.error(f"Error creating finance entry for company payment: {str(e)}")


# ============================================
# SIGNAL: Sale
# ============================================

@receiver(post_save, sender=Sale)
def process_sale_accounting(sender, instance, created, **kwargs):
    """
    Process accounting when a sale is completed:
    1. Create IncomeTransaction for capital tracking
    2. Process sale accounting (income, cost, profit)
    """
    # Only process when sale is completed and not reversed
    if instance.is_reversed:
        return
    
    # Check if sale has a status field and it's completed
    if hasattr(instance, 'status') and instance.status != 'completed':
        return
    
    try:
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
            logger.info(f"✅ Auto-created IncomeTransaction for sale {instance.sale_id}")
        
        # STEP 2: Process sale accounting (Income, COGS, Profit)
        result = SaleAccountingHelper.process_sale(instance, instance.seller)
        logger.info(f"Sale {instance.sale_id} accounted: Income={result['income']}, Cost={result['cost']}, Profit={result['profit']}")
        
    except Exception as e:
        logger.error(f"Error processing sale accounting for {instance.sale_id}: {str(e)}")


# ============================================
# SIGNAL: StockEntry (when prices are corrected)
# ============================================

@receiver(post_save, sender=StockEntry)
def update_purchase_account_on_stock_entry(sender, instance, created, **kwargs):
    """
    Update purchase account when stock entry is created or updated
    IMPORTANT: This ensures finance accounts stay in sync with corrected inventory prices
    """
    # Only process purchase entries
    if instance.entry_type != 'purchase' or instance.quantity <= 0:
        return
    
    try:
        purchase_account = PurchaseAccount.get_or_create_account()
        
        # Calculate total cost for this entry (using the current unit_price)
        total_cost = instance.unit_price * instance.quantity
        
        # Add to purchase account
        purchase_account.add_purchase_cost(
            amount=total_cost,
            product_reference=instance.reference_id or f"SKU:{instance.product_sku.sku_code if instance.product_sku else 'N/A'}",
            user=instance.created_by
        )
        
        # Also update the total purchases value
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
            logger.info(f"✅ Capital account updated after injection {instance.injection_id}: Net={capital_account.net_capital}")
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
        logger.info(f"✅ Capital account updated after repayment: Net={capital_account.net_capital}")
    except Exception as e:
        logger.error(f"Error updating capital account for repayment: {str(e)}")


# ============================================
# SIGNAL: Stock Purchase (Finance model)
# ============================================

@receiver(post_save, sender=StockPurchase)
def update_capital_on_stock_purchase(sender, instance, created, **kwargs):
    """Update capital account when stock is purchased"""
    if created:
        try:
            capital_account = CapitalAccount.get_or_create_account()
            # Refresh from database to get latest values
            capital_account.refresh_from_db()
            logger.info(f"💰 Stock purchase recorded: KES {instance.total_amount:,.2f} for {instance.sku_code}")
        except Exception as e:
            logger.error(f"Error updating capital for stock purchase: {str(e)}")


# ============================================
# SIGNAL: Income Transaction
# ============================================

@receiver(post_save, sender=IncomeTransaction)
def add_sales_revenue_to_capital(sender, instance, created, **kwargs):
    """Add sales revenue to capital account when a sale is recorded"""
    if created and instance.transaction_type == 'sale':
        try:
            capital_account = CapitalAccount.get_or_create_account()
            capital_account.refresh_from_db()
            logger.info(f"💰 Sales revenue added to capital: KES {instance.amount:,.2f}")
        except Exception as e:
            logger.error(f"Error updating capital for income transaction: {str(e)}")


# ============================================
# SIGNAL: Product Price Update (via StockEntry)
# ============================================

@receiver(post_save, sender=StockEntry)
def sync_finance_on_price_correction(sender, instance, **kwargs):
    """
    CRITICAL: When stock entries are updated with corrected prices,
    this signal ensures finance accounts are updated accordingly
    """
    # Check if this is a price correction (quantity=0 entry)
    if instance.quantity == 0 and 'PRICE-CHANGE' in (instance.reference_id or ''):
        try:
            # This is a price correction record - need to update related finance entries
            purchase_account = PurchaseAccount.get_or_create_account()
            
            # Recalculate total purchases from all stock entries (using corrected prices)
            from django.db.models import Sum, F
            total_purchases = StockEntry.objects.filter(
                entry_type='purchase',
                quantity__gt=0
            ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or Decimal('0')
            
            # Update purchase account
            purchase_account.balance = total_purchases
            purchase_account.total_purchases = total_purchases
            purchase_account.save()
            
            logger.info(f"💰 Purchase account corrected to KES {total_purchases:,.2f} after price update")
            
        except Exception as e:
            logger.error(f"Error syncing finance on price correction: {str(e)}")