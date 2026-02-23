from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from inventory.models import Product, StockEntry
from sales.models import Sale, SaleItem, SaleReversal
import logging
from collections import defaultdict
from datetime import timedelta
from django.db.models import Sum, Q
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.timezone import make_aware
from django.core.exceptions import ObjectDoesNotExist
from django.db import models

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Check and fix sales data consistency with inventory'

    def add_arguments(self, parser):
        parser.add_argument(
            '--sale-id',
            type=str,
            help='Check specific sale by ID'
        )
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Fix inconsistencies found'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output'
        )

    def handle(self, *args, **options):
        self.verbose = options['verbose']
        self.fix = options['fix']
        sale_id = options['sale_id']

        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write(self.style.SUCCESS('SALES DATA CONSISTENCY CHECK'))
        self.stdout.write(self.style.SUCCESS('=' * 80))

        if sale_id:
            self.check_single_sale(sale_id)
        else:
            self.check_all_sales()

    def check_all_sales(self):
        """Check all sales in the database"""
        total_sales = Sale.objects.count()
        self.stdout.write(f"\nTotal Sales Found: {total_sales}")
        
        # Statistics
        stats = {
            'total': total_sales,
            'reversed': 0,
            'pending': 0,
            'inconsistent': 0,
            'fixed': 0
        }

        for sale in Sale.objects.all().order_by('-sale_date'):
            self.stdout.write("\n" + "-" * 60)
            result = self.analyze_sale(sale)
            
            if result['status'] == 'reversed':
                stats['reversed'] += 1
            elif result['status'] == 'pending':
                stats['pending'] += 1
            
            if result['inconsistent']:
                stats['inconsistent'] += 1
                if self.fix:
                    if self.fix_sale(sale, result):
                        stats['fixed'] += 1

        self.print_summary(stats)

    def check_single_sale(self, sale_id):
        """Check a specific sale"""
        try:
            sale = Sale.objects.get(sale_id=sale_id)
            self.stdout.write(f"\nAnalyzing Sale: {sale_id}")
            result = self.analyze_sale(sale)
            
            if result['inconsistent'] and self.fix:
                self.fix_sale(sale, result)
                
        except Sale.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Sale {sale_id} not found"))

    def analyze_sale(self, sale):
        """Analyze a single sale for consistency"""
        self.stdout.write(f"\nSale ID: {sale.sale_id}")
        self.stdout.write(f"Date: {sale.sale_date}")
        self.stdout.write(f"Status: {'REVERSED' if sale.is_reversed else 'ACTIVE'}")
        self.stdout.write(f"Items: {sale.items.count()}")
        self.stdout.write(f"Total: KSH {sale.total_amount}")

        inconsistent = False
        issues = []
        items_data = []

        for item in sale.items.all():
            self.stdout.write(f"\n  Item: {item.product_name}")
            self.stdout.write(f"    Quantity: {item.quantity}")
            self.stdout.write(f"    Unit Price: KSH {item.unit_price}")
            self.stdout.write(f"    Total: KSH {item.total_price}")

            # Check product exists
            if not item.product:
                issues.append(f"Item {item.id}: Product missing")
                inconsistent = True
                continue

            product = item.product
            self.stdout.write(f"    Product: {product.product_code}")
            self.stdout.write(f"    Current Stock: {product.quantity}")
            self.stdout.write(f"    Current Status: {product.status}")

            # Check stock entries for this item
            stock_entries = StockEntry.objects.filter(
                product=product,
                reference_id__contains=sale.sale_id
            )

            if self.verbose:
                self.stdout.write(f"    Stock Entries Found: {stock_entries.count()}")
                for entry in stock_entries:
                    self.stdout.write(f"      - {entry.entry_type}: {entry.quantity}")

            # Verify stock consistency
            item_check = self.verify_item_stock(item, product, sale)
            if item_check['inconsistent']:
                inconsistent = True
                issues.extend(item_check['issues'])

            items_data.append({
                'item': item,
                'product': product,
                'stock_entries': stock_entries,
                'check': item_check
            })

        # Verify sale totals
        total_check = self.verify_sale_totals(sale)
        if total_check['inconsistent']:
            inconsistent = True
            issues.extend(total_check['issues'])

        # Check reversal if applicable
        if sale.is_reversed:
            reversal_check = self.verify_reversal(sale)
            if reversal_check['inconsistent']:
                inconsistent = True
                issues.extend(reversal_check['issues'])

        if issues:
            self.stdout.write(self.style.WARNING("\n  ISSUES FOUND:"))
            for issue in issues:
                self.stdout.write(self.style.WARNING(f"    - {issue}"))

        return {
            'sale': sale,
            'inconsistent': inconsistent,
            'issues': issues,
            'items_data': items_data,
            'status': 'reversed' if sale.is_reversed else 'pending'
        }

    def verify_item_stock(self, item, product, sale):
        """Verify stock consistency for a single item"""
        issues = []
        inconsistent = False

        # For single items
        if product.category.is_single_item:
            if not sale.is_reversed:
                # Sale should mark as sold
                if product.status != 'sold' and product.quantity != 0:
                    issues.append(
                        f"Single item {product.product_code} should be SOLD "
                        f"(Current: {product.status}, Qty: {product.quantity})"
                    )
                    inconsistent = True
            else:
                # Reversal should mark as available
                if product.status != 'available' and product.quantity != 1:
                    issues.append(
                        f"Reversed single item {product.product_code} should be AVAILABLE with Qty 1 "
                        f"(Current: {product.status}, Qty: {product.quantity})"
                    )
                    inconsistent = True

        # For bulk items
        else:
            # Check if stock entries match quantity changes
            sale_entries = StockEntry.objects.filter(
                product=product,
                entry_type='sale',
                reference_id__contains=sale.sale_id
            ).aggregate(total=models.Sum('quantity'))['total'] or 0

            expected_change = -item.quantity
            if abs(sale_entries) != item.quantity:
                issues.append(
                    f"Stock entry mismatch for {product.product_code}: "
                    f"Expected change: {expected_change}, Actual: {sale_entries}"
                )
                inconsistent = True

        return {
            'inconsistent': inconsistent,
            'issues': issues
        }

    def verify_sale_totals(self, sale):
        """Verify sale totals match items"""
        issues = []
        inconsistent = False

        # Calculate from items
        calculated_subtotal = sum(item.total_price for item in sale.items.all())
        calculated_total = calculated_subtotal + sale.tax_amount

        if abs(calculated_subtotal - sale.subtotal) > Decimal('0.01'):
            issues.append(
                f"Subtotal mismatch: Calculated {calculated_subtotal}, "
                f"Recorded {sale.subtotal}"
            )
            inconsistent = True

        if abs(calculated_total - sale.total_amount) > Decimal('0.01'):
            issues.append(
                f"Total mismatch: Calculated {calculated_total}, "
                f"Recorded {sale.total_amount}"
            )
            inconsistent = True

        return {
            'inconsistent': inconsistent,
            'issues': issues
        }

    def verify_reversal(self, sale):
        """Verify reversal consistency"""
        issues = []
        inconsistent = False

        if not hasattr(sale, 'reversal'):
            issues.append("Sale marked as reversed but no reversal record found")
            inconsistent = True
            return {'inconsistent': inconsistent, 'issues': issues}

        reversal = sale.reversal
        self.stdout.write(f"\n  Reversal Info:")
        self.stdout.write(f"    Date: {reversal.reversed_at}")
        self.stdout.write(f"    By: {reversal.reversed_by.username if reversal.reversed_by else 'System'}")
        self.stdout.write(f"    Reason: {reversal.reason or 'Not specified'}")
        self.stdout.write(f"    Items Processed: {reversal.items_processed}")
        self.stdout.write(f"    Amount: KSH {reversal.total_amount_reversed}")

        # Verify reversal entries
        reversal_entries = StockEntry.objects.filter(
            entry_type='reversal',
            reference_id__contains=sale.sale_id
        )

        if reversal_entries.count() != sale.items.count():
            issues.append(
                f"Reversal entries mismatch: Expected {sale.items.count()}, "
                f"Found {reversal_entries.count()}"
            )
            inconsistent = True

        return {
            'inconsistent': inconsistent,
            'issues': issues
        }

    @transaction.atomic
    def fix_sale(self, sale, analysis):
        """Attempt to fix inconsistencies"""
        self.stdout.write(self.style.WARNING(f"\n  ATTEMPTING TO FIX SALE {sale.sale_id}..."))

        fixes_applied = []

        try:
            # Fix sale totals if needed
            if self.verify_sale_totals(sale)['inconsistent']:
                sale.recalculate_totals()
                fixes_applied.append("Recalculated sale totals")

            # Fix each item
            for item_data in analysis['items_data']:
                item = item_data['item']
                product = item_data['product']
                
                # Fix single item status
                if product.category.is_single_item:
                    if sale.is_reversed:
                        if product.status != 'available' or product.quantity != 1:
                            product.status = 'available'
                            product.quantity = 1
                            product.save()
                            fixes_applied.append(f"Restored {product.product_code} to AVAILABLE")
                    else:
                        if product.status != 'sold' or product.quantity != 0:
                            product.status = 'sold'
                            product.quantity = 0
                            product.save()
                            fixes_applied.append(f"Marked {product.product_code} as SOLD")

                # Create missing stock entries
                entry_count = StockEntry.objects.filter(
                    product=product,
                    reference_id__contains=sale.sale_id
                ).count()

                if entry_count == 0:
                    # Create missing stock entry
                    StockEntry.objects.create(
                        product=product,
                        quantity=-item.quantity if not sale.is_reversed else item.quantity,
                        entry_type='sale' if not sale.is_reversed else 'reversal',
                        unit_price=item.unit_price,
                        total_amount=item.total_price,
                        reference_id=f"FIX-{sale.sale_id}",
                        notes=f"Auto-fix for sale {sale.sale_id}",
                        created_at=sale.sale_date
                    )
                    fixes_applied.append(f"Created missing stock entry for {product.product_code}")

            if fixes_applied:
                self.stdout.write(self.style.SUCCESS("    FIXES APPLIED:"))
                for fix in fixes_applied:
                    self.stdout.write(self.style.SUCCESS(f"      ✓ {fix}"))
                return True
            else:
                self.stdout.write("    No fixes needed")
                return False

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    Error fixing sale: {str(e)}"))
            return False

    def print_summary(self, stats):
        """Print summary statistics"""
        self.stdout.write(self.style.SUCCESS('\n' + '=' * 80))
        self.stdout.write(self.style.SUCCESS('SUMMARY'))
        self.stdout.write(self.style.SUCCESS('=' * 80))
        
        self.stdout.write(f"Total Sales: {stats['total']}")
        self.stdout.write(f"  - Active: {stats['pending']}")
        self.stdout.write(f"  - Reversed: {stats['reversed']}")
        
        if stats['inconsistent'] > 0:
            self.stdout.write(self.style.WARNING(f"\nInconsistent Sales Found: {stats['inconsistent']}"))
            if self.fix:
                self.stdout.write(self.style.SUCCESS(f"Fixed: {stats['fixed']}"))
            else:
                self.stdout.write(self.style.WARNING("Run with --fix to attempt fixes"))
        else:
            self.stdout.write(self.style.SUCCESS("\n✓ All sales are consistent!"))