# inventory/signals.py - COMPLETE FIXED VERSION
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender='inventory.StockEntry')
def create_finance_transaction_for_stock_entry(sender, instance, created, **kwargs):
    """
    Auto-create finance transaction when stock is purchased
    """
    from finance.models import PurchaseAccount, PurchaseTransaction, StockPurchase, FinancialTransaction, AccountTransaction
    from decimal import Decimal
    
    print(f"\n🔔 SIGNAL CHECK - StockEntry ID: {instance.id}")
    print(f"   Created: {created}")
    print(f"   Entry Type: {instance.entry_type}")
    print(f"   Quantity: {instance.quantity}")
    
    # Only process NEW purchase entries
    if not created:
        print(f"   ⏭️ Skipping - not a new entry")
        return
    
    if instance.entry_type != 'purchase':
        print(f"   ⏭️ Skipping - not a purchase entry")
        return
    
    if instance.quantity <= 0:
        print(f"   ⏭️ Skipping - negative quantity")
        return
    
    # Check if already processed
    from finance.models import StockPurchase
    if StockPurchase.objects.filter(stock_entry=instance).exists():
        print(f"   ⏭️ Skipping - already has StockPurchase record")
        return
    
    print(f"   ✅ Processing purchase...")
    
    try:
        with transaction.atomic():
            # Get product info
            if instance.product_sku:
                sku_code = instance.product_sku.sku_code
                product_name = instance.product_sku.name
                supplier_name = instance.product_sku.supplier.name if instance.product_sku.supplier else ""
            elif instance.product_unit:
                sku_code = instance.product_unit.product.sku_code
                product_name = instance.product_unit.product.name
                supplier_name = instance.product_unit.product.supplier.name if instance.product_unit.product.supplier else ""
            else:
                sku_code = "UNKNOWN"
                product_name = "Unknown Product"
                supplier_name = ""
            
            amount = instance.total_amount or (instance.unit_price * instance.quantity)
            
            print(f"   Product: {product_name} ({sku_code})")
            print(f"   Amount: KES {amount}")
            
            # Create FinancialTransaction
            fin_trans = FinancialTransaction.objects.create(
                transaction_type='expense',
                category='operational',
                amount=amount,
                description=f"Stock Purchase: {product_name} ({sku_code}) - {instance.quantity} units @ KES {instance.unit_price}",
                payment_method='bank',
                payment_reference=instance.reference_id or f"STOCK-{instance.id}",
                recipient_name=supplier_name,
                created_by=instance.created_by,
                notes=f"Stock Entry #{instance.id} - Added {instance.quantity} units"
            )
            
            # Create AccountTransaction
            acc_trans = AccountTransaction.objects.create(
                account_type='bank',
                transaction_type='expense',
                amount=amount,
                description=f"Stock Purchase: {product_name} ({sku_code})",
                reference=instance.reference_id or f"STOCK-{instance.id}",
                created_by=instance.created_by,
                notes=f"Stock Entry #{instance.id} - {instance.quantity} units @ KES {instance.unit_price}"
            )
            
            # Update PurchaseAccount
            purchase_account = PurchaseAccount.get_or_create_account()
            purchase_account.add_purchase_cost(
                amount=amount,
                product_reference=sku_code,
                user=instance.created_by
            )
            
            # Create StockPurchase record
            StockPurchase.objects.create(
                stock_entry=instance,
                product_name=product_name,
                sku_code=sku_code,
                quantity=instance.quantity,
                unit_price=instance.unit_price,
                total_amount=amount,
                purchase_date=instance.created_at,
                reference_id=instance.reference_id or f"STOCK-{instance.id}",
                notes=instance.notes or "",
                financial_transaction=fin_trans,
                account_transaction=acc_trans,
                created_by=instance.created_by
            )
            
            print(f"   ✅ SUCCESS! Added KES {amount} to Purchase Account")
            print(f"   New balance: KES {purchase_account.balance}")
            
    except Exception as e:
        print(f"   ❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()