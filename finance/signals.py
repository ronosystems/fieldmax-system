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
    PurchaseTransaction, ProfitTransaction, NetAccount, SavingsAccount, InventoryAsset
)
from finance import models

logger = logging.getLogger(__name__)




# ============================================
# SIGNAL: StockEntry - Track Inventory Asset
# ============================================

@receiver(post_save, sender=StockEntry)
def track_inventory_asset(sender, instance, created, **kwargs):
    """Track inventory asset value when stock moves"""
    if not created:
        return
    
    inventory_asset = InventoryAsset.get_account()
    
    # Calculate total cost
    total_cost = abs(instance.quantity) * instance.unit_price
    
    # Get product info
    sku_code = ""
    quantity = abs(instance.quantity)
    unit_price = instance.unit_price
    
    if instance.product_sku:
        sku_code = instance.product_sku.sku_code
    elif instance.product_unit:
        sku_code = instance.product_unit.product.sku_code
    
    # Handle different entry types
    if instance.entry_type == 'purchase' and instance.quantity > 0:
        # Stock purchase - INCREASE asset
        inventory_asset.add_purchase(
            amount=total_cost,
            sku_code=sku_code,
            quantity=quantity,
            unit_price=unit_price,
            user=instance.created_by
        )
        
    elif instance.entry_type == 'sale' and instance.quantity < 0:
        # Sale - DECREASE asset (COGS)
        # Note: This might double-count if you already deduct in sale_create_api
        # Consider commenting this out if you already deduct there
        inventory_asset.deduct_cogs(
            amount=total_cost,
            sku_code=sku_code,
            quantity=quantity,
            unit_price=unit_price,
            sale_reference=instance.reference_id,
            user=instance.created_by
        )
    
    elif instance.entry_type == 'reversal':
        # Reversal - reverse the effect
        if instance.quantity > 0:
            # Positive reversal (return) - INCREASE asset
            inventory_asset.add_purchase(
                amount=total_cost,
                sku_code=sku_code,
                quantity=quantity,
                unit_price=unit_price,
                user=instance.created_by
            )
        else:
            # Negative reversal - DECREASE asset
            inventory_asset.deduct_cogs(
                amount=total_cost,
                sku_code=sku_code,
                quantity=quantity,
                unit_price=unit_price,
                user=instance.created_by
            )



# ============================================
# DISABLED: SaleAccountingHelper - Use only sale_create_api for accounting
# ============================================
# Comment out or remove this entire class to prevent duplicates
# The sale_create_api already handles Net and Savings accounts correctly

class SaleAccountingHelper:
    """DEPRECATED: Use sale_create_api instead. This class is disabled to prevent duplicates."""
    
    @staticmethod
    def process_sale(sale, user=None):
        """DISABLED: This would create duplicate records. Use sale_create_api instead."""
        logger.warning(f"⚠️ SaleAccountingHelper.process_sale called but DISABLED for sale {getattr(sale, 'sale_id', 'unknown')}")
        return {'income': 0, 'cost': 0, 'profit': 0}


# ============================================
# SIGNAL: Company Payment
# ============================================

@receiver(post_save, sender=CompanyPayment)
def create_finance_entry_for_company_payment(sender, instance, created, **kwargs):
    """Automatically create finance entry when a company payment is recorded"""
    if created:
        try:
            # Check for duplicate first
            if hasattr(instance, 'financial_transaction') and instance.financial_transaction:
                logger.info(f"⚠️ Company payment {instance.payment_id} already has financial transaction")
                return
            
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
# FIXED SIGNAL: Sale (Only for FinancialTransaction, NOT for Net/Savings)
# ============================================

@receiver(post_save, sender=Sale)
def process_sale_accounting(sender, instance, created, **kwargs):
    """
    ONLY create FinancialTransaction for the sale.
    Net and Savings accounts are handled by sale_create_api.
    """
    # Only process when sale is not reversed
    if instance.is_reversed:
        return
    
    # Skip if this is a split payment sale (handled separately)
    if instance.is_split_payment:
        logger.info(f"Split payment sale {instance.sale_id} - skipping signal")
        return
    
    # ============================================
    # CHECK IF FINANCIAL TRANSACTION ALREADY EXISTS
    # ============================================
    from .models import FinancialTransaction
    
    existing = FinancialTransaction.objects.filter(
        description__icontains=instance.sale_id,
        transaction_type='income'
    ).exists()
    
    if existing:
        logger.info(f"⚠️ FinancialTransaction already exists for sale {instance.sale_id} - skipping")
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
        
        # ONLY create FinancialTransaction here
        # Net and Savings updates should ONLY happen in sale_create_api
        if instance.total_amount > 0:
            FinancialTransaction.objects.create(
                transaction_type='income',
                category='other',
                amount=instance.total_amount,
                description=f"Sale {instance.sale_id} - {instance.buyer_name or 'Walk-in Customer'}",
                payment_method=instance.payment_method.lower() if instance.payment_method else 'cash',
                payment_reference=instance.sale_id,
                recipient_name=instance.buyer_name or 'Walk-in Customer',
                transaction_date=instance.sale_date,
                created_by=instance.seller,
                notes=f"Items: {instance.items.count()} | Paid via: {instance.payment_method}"
            )
            logger.info(f"📝 FinancialTransaction created for sale {instance.sale_id}")
        else:
            logger.warning(f"⚠️ Sale {instance.sale_id} has zero amount - no transaction created")
        
    except Exception as e:
        logger.error(f"Error processing sale accounting for {instance.sale_id}: {str(e)}")


# ============================================
# DISABLED: StockEntry Purchase Signal - Inventory is ASSET, not expense
# ============================================
# Stock purchases should NOT create expenses. They are assets.
# Only COGS when items are sold should be expenses.

@receiver(post_save, sender=StockEntry)
def update_purchase_account_on_stock_entry(sender, instance, created, **kwargs):
    """
    DISABLED: Stock purchases are ASSETS, not expenses.
    Do NOT add to PurchaseAccount (which tracks expenses).
    """
    # Skip purchase entries - they are assets, not expenses
    if instance.entry_type == 'purchase' and instance.quantity > 0:
        logger.info(f"📦 Inventory asset: {instance.quantity} units of {instance.product_sku.sku_code if instance.product_sku else 'product'} - NOT an expense")
        return
    
    # For other entry types if needed
    logger.debug(f"StockEntry {instance.id} - type: {instance.entry_type} - no action needed")


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
# FIXED SIGNAL: AccountTransaction Expense for Net Account
# ============================================

@receiver(post_save, sender='finance.AccountTransaction')
def process_expense_for_net(sender, instance, created, **kwargs):
    """When an expense is recorded, deduct from Net Account"""
    if not created or instance.transaction_type != 'expense':
        return
    
    # Skip if this expense was already processed
    if hasattr(instance, '_processed') and instance._processed:
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
        
        # Mark as processed to prevent duplicates
        instance._processed = True
        logger.info(f"📉 NET: Deducted expense KES {instance.amount} ({expense_type})")
    except Exception as e:
        logger.error(f"Failed to process expense for Net: {str(e)}")