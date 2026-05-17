from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum, Q, F 
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from .models import Product, Category, Supplier, StockEntry, StockAlert, ProductReview, ReturnRequest, ProductUnit
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test  
from django.http import JsonResponse
from django.db import transaction
from utils.notifications import AdminNotifier 
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods
from django.core.mail import send_mail
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
import traceback
from sales.models import Sale, SaleItem 
import json
import logging
from sales.models import Sale
from django.contrib.auth.models import User, Group
from django.db.models import Sum, Count, Q, F
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
import csv
from django.http import HttpResponse
from django.shortcuts import render
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from datetime import timedelta
from decimal import Decimal
from .models import Product, Category, StockEntry, StockAlert, Supplier
from django.core.paginator import Paginator
from django.db import models
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db import transaction
from django.core.paginator import Paginator
from django.db.models import Sum, Q, F, DecimalField, Case, When
from .models import Product, StockEntry, Category, ProductUnit
from decimal import Decimal
import csv
import logging




logger = logging.getLogger(__name__)
User = get_user_model()



#  manager or admin check for user_passes_test decorator
def is_manager_or_admin(user):
    return user.is_staff or user.groups.filter(name='Manager').exists()


@login_required
def export_statistics(request):
    """Export store statistics to CSV"""
    
    # Create HttpResponse with CSV header
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="store_statistics_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    
    # Write headers
    writer.writerow(['Store Statistics Report', f'Generated: {timezone.now().strftime("%Y-%m-%d %H:%M")}'])
    writer.writerow([])
    
    # Overview Section
    writer.writerow(['OVERVIEW'])
    products = Product.objects.filter(is_active=True)
    total_products = products.count()
    total_items = products.aggregate(total=Sum('quantity'))['total'] or 0
    total_categories = Category.objects.filter(is_active=True).count()
    
    writer.writerow(['Total Products', total_products])
    writer.writerow(['Total Items', total_items])
    writer.writerow(['Total Categories', total_categories])
    writer.writerow([])
    
    # Financial Section
    writer.writerow(['FINANCIAL SUMMARY'])
    total_value = sum(p.selling_price * p.quantity for p in products)
    total_cost = sum(p.buying_price * p.quantity for p in products)
    available_products = products.filter(status='available')
    available_value = sum(p.selling_price * p.quantity for p in available_products)
    available_cost = sum(p.buying_price * p.quantity for p in available_products)
    
    writer.writerow(['Total Value (Selling Price)', f'KES {total_value:,.2f}'])
    writer.writerow(['Total Cost (Buying Price)', f'KES {total_cost:,.2f}'])
    writer.writerow(['Available Items Value', f'KES {available_value:,.2f}'])
    writer.writerow(['Available Items Cost', f'KES {available_cost:,.2f}'])
    writer.writerow(['Potential Profit', f'KES {total_value - total_cost:,.2f}'])
    writer.writerow([])
    
    # Stock Status Section
    writer.writerow(['STOCK STATUS'])
    writer.writerow(['Low Stock Items', products.filter(status='lowstock').count()])
    writer.writerow(['Needs Reorder', products.filter(Q(status='lowstock') | Q(quantity__lte=F('reorder_level'))).distinct().count()])
    writer.writerow(['Out of Stock', products.filter(status='outofstock').count()])
    writer.writerow(['Damaged Items', products.filter(status='damaged').count()])
    writer.writerow([])
    
    # Category Breakdown
    writer.writerow(['CATEGORY BREAKDOWN'])
    writer.writerow(['Category', 'Products', 'Total Items', 'Total Value', 'Total Cost', 'Profit'])
    
    for category in Category.objects.filter(is_active=True):
        cat_products = products.filter(category=category)
        cat_total_items = cat_products.aggregate(total=Sum('quantity'))['total'] or 0
        cat_total_value = sum(p.selling_price * p.quantity for p in cat_products)
        cat_total_cost = sum(p.buying_price * p.quantity for p in cat_products)
        
        writer.writerow([
            category.name,
            cat_products.count(),
            cat_total_items,
            f'KES {cat_total_value:,.2f}',
            f'KES {cat_total_cost:,.2f}',
            f'KES {cat_total_value - cat_total_cost:,.2f}'
        ])
    
    return response


@login_required
def store_statistics(request):
    """Store statistics dashboard"""
    
    from django.db.models import Sum, Q, F
    from django.core.paginator import Paginator
    from decimal import Decimal
    from .models import Product, ProductUnit, Supplier, StockAlert, ReturnRequest, StockEntry
    
    # ============================================
    # PRODUCT COUNTS
    # ============================================
    total_products = Product.objects.filter(is_active=True).count()
    
    # ============================================
    # INVENTORY ITEMS COUNT
    # ============================================
    
    # TOTAL ITEMS (All items ever purchased)
    # Single items: count all ProductUnit records
    total_items_single = ProductUnit.objects.count()
    
    # Bulk items: sum of ALL positive stock entries (purchases only)
    total_items_bulk = StockEntry.objects.filter(
        product_sku__category__item_type='bulk',
        quantity__gt=0  # Only purchase entries
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    total_items = total_items_single + total_items_bulk
    
    # AVAILABLE ITEMS (Current stock)
    # Single items: count available status
    available_single = ProductUnit.objects.filter(status='available').count()
    
    # Bulk items: sum of bulk_quantity from Product (current stock)
    available_bulk = Product.objects.filter(
        category__item_type='bulk',
        is_active=True
    ).aggregate(total=Sum('bulk_quantity'))['total'] or 0
    
    available_items = available_single + available_bulk
    
    # SOLD ITEMS (Single items only)
    sold_items = ProductUnit.objects.filter(status='sold').count()
    
    # DAMAGED ITEMS
    damaged_single = ProductUnit.objects.filter(status='damaged').count()
    damaged_bulk = Product.objects.filter(
        category__item_type='bulk'
    ).aggregate(total=Sum('damaged_quantity'))['total'] or 0
    damaged_items = damaged_single + damaged_bulk
    
    # STOLEN & LOST ITEMS
    stolen_items = ProductUnit.objects.filter(status='stolen').count()
    lost_items = ProductUnit.objects.filter(status='lost').count()
    
    # RESERVED ITEMS
    reserved_single = ProductUnit.objects.filter(status='reserved').count()
    reserved_bulk = Product.objects.filter(
        category__item_type='bulk'
    ).aggregate(total=Sum('reserved_quantity'))['total'] or 0
    reserved_items = reserved_single + reserved_bulk
    
    # RETURNED UNITS
    returned_units = ProductUnit.objects.filter(status='returned').count()
    written_off_items = ProductUnit.objects.filter(status='writeoff').count()
    
    # ============================================
    # VALUE CALCULATIONS - TOTAL ITEMS (Historical)
    # ============================================
    
    # TOTAL ITEMS VALUE (All items ever purchased)
    # Single items: sum of unit_selling_price for ALL units
    total_items_value_single = ProductUnit.objects.aggregate(
        total=Sum(F('unit_selling_price'))
    )['total'] or Decimal('0.00')
    
    # Bulk items: sum of (selling_price * quantity) from ALL purchase stock entries
    total_items_value_bulk = Decimal('0.00')
    bulk_purchase_entries = StockEntry.objects.filter(
        product_sku__category__item_type='bulk',
        quantity__gt=0
    ).select_related('product_sku')
    
    for entry in bulk_purchase_entries:
        if entry.product_sku and entry.product_sku.selling_price:
            total_items_value_bulk += entry.product_sku.selling_price * entry.quantity
    
    total_items_value = total_items_value_single + total_items_value_bulk
    
    # TOTAL ITEMS COST
    total_items_cost_single = ProductUnit.objects.aggregate(
        total=Sum(F('unit_buying_price'))
    )['total'] or Decimal('0.00')
    
    total_items_cost_bulk = Decimal('0.00')
    for entry in bulk_purchase_entries:
        if entry.product_sku and entry.product_sku.buying_price:
            total_items_cost_bulk += entry.product_sku.buying_price * entry.quantity
    
    total_items_cost = total_items_cost_single + total_items_cost_bulk
    
    # ============================================
    # VALUE CALCULATIONS - AVAILABLE ITEMS ONLY (Current Stock)
    # ============================================
    
    # AVAILABLE ITEMS VALUE (Only items currently in stock)
    available_value_single = ProductUnit.objects.filter(
        status='available'
    ).aggregate(
        total=Sum(F('unit_selling_price'))
    )['total'] or Decimal('0.00')
    
    available_value_bulk = Product.objects.filter(
        category__item_type='bulk',
        is_active=True,
        bulk_quantity__gt=0
    ).aggregate(
        total=Sum(F('selling_price') * F('bulk_quantity'))
    )['total'] or Decimal('0.00')
    
    available_items_value = available_value_single + available_value_bulk
    
    # AVAILABLE ITEMS COST
    available_cost_single = ProductUnit.objects.filter(
        status='available'
    ).aggregate(
        total=Sum(F('unit_buying_price'))
    )['total'] or Decimal('0.00')
    
    available_cost_bulk = Product.objects.filter(
        category__item_type='bulk',
        is_active=True,
        bulk_quantity__gt=0
    ).aggregate(
        total=Sum(F('buying_price') * F('bulk_quantity'))
    )['total'] or Decimal('0.00')
    
    available_items_cost = available_cost_single + available_cost_bulk
    
    # ============================================
    # TOTAL PRODUCTS VALUE & COST (Current stock value)
    # ============================================
    
    # This should equal available_items_value and available_items_cost
    total_products_value = available_items_value
    total_products_cost = available_items_cost
    
    # ============================================
    # LOSS CALCULATIONS
    # ============================================
    damaged_items_cost = ProductUnit.objects.filter(
        status='damaged'
    ).aggregate(
        total=Sum(F('unit_buying_price'))
    )['total'] or Decimal('0.00')
    
    stolen_items_cost = ProductUnit.objects.filter(
        status='stolen'
    ).aggregate(
        total=Sum(F('unit_buying_price'))
    )['total'] or Decimal('0.00')
    
    lost_items_cost = ProductUnit.objects.filter(
        status='lost'
    ).aggregate(
        total=Sum(F('unit_buying_price'))
    )['total'] or Decimal('0.00')
    
    # ============================================
    # SOLD ITEMS VALUE (Revenue from single items)
    # ============================================
    sold_items_value = ProductUnit.objects.filter(
        status='sold'
    ).aggregate(
        total=Sum('sold_at_price')
    )['total'] or Decimal('0.00')
    
    # ============================================
    # DEBUG OUTPUT
    # ============================================
    print(f"=== INVENTORY STATISTICS DEBUG ===")
    print(f"Total Active Products: {total_products}")
    print(f"---")
    print(f"Single Items - Total Units (all time): {total_items_single}")
    print(f"Single Items - Total Value: {total_items_value_single}")
    print(f"Single Items - Total Cost: {total_items_cost_single}")
    print(f"Single Items - Available Units: {available_single}")
    print(f"Single Items - Available Value: {available_value_single}")
    print(f"Single Items - Available Cost: {available_cost_single}")
    print(f"---")
    print(f"Bulk Items - Total Units (from purchases): {total_items_bulk}")
    print(f"Bulk Items - Total Value: {total_items_value_bulk}")
    print(f"Bulk Items - Total Cost: {total_items_cost_bulk}")
    print(f"Bulk Items - Available Units (current): {available_bulk}")
    print(f"Bulk Items - Available Value: {available_value_bulk}")
    print(f"Bulk Items - Available Cost: {available_cost_bulk}")
    print(f"---")
    print(f"TOTAL (Historical) - Items: {total_items}, Value: {total_items_value}, Cost: {total_items_cost}")
    print(f"AVAILABLE (Current) - Items: {available_items}, Value: {available_items_value}, Cost: {available_items_cost}")
    print(f"Difference (Sold/Used/Lost) - Items: {total_items - available_items}")
    print(f"Difference in Value: {total_items_value - available_items_value}")
    print(f"Difference in Cost: {total_items_cost - available_items_cost}")
    print(f"==================================")
    
    # ============================================
    # RETURN REQUESTS
    # ============================================
    all_returns = ReturnRequest.objects.all()
    returned_items = all_returns.count()
    returned_items_value = all_returns.aggregate(
        total=Sum('refund_amount')
    )['total'] or Decimal('0.00')
    
    returned_items_cost = Decimal('0.00')
    for return_req in all_returns.select_related('product', 'product_unit'):
        if return_req.product_unit and return_req.product_unit.unit_buying_price:
            returned_items_cost += return_req.product_unit.unit_buying_price * (return_req.quantity or 1)
        elif return_req.product and return_req.product.buying_price:
            returned_items_cost += return_req.product.buying_price * (return_req.quantity or 1)
        else:
            returned_items_cost += return_req.refund_amount * Decimal('0.7')
    
    damaged_returns = ReturnRequest.objects.filter(status='damaged_loss')
    damaged_returns_count = damaged_returns.count()
    damaged_returns_value = damaged_returns.aggregate(
        total=Sum('refund_amount')
    )['total'] or Decimal('0.00')
    
    damaged_returns_cost = Decimal('0.00')
    for return_req in damaged_returns.select_related('product', 'product_unit'):
        if return_req.loss_amount:
            damaged_returns_cost += return_req.loss_amount
        elif return_req.product_unit and return_req.product_unit.unit_buying_price:
            damaged_returns_cost += return_req.product_unit.unit_buying_price * (return_req.quantity or 1)
        elif return_req.product and return_req.product.buying_price:
            damaged_returns_cost += return_req.product.buying_price * (return_req.quantity or 1)
        else:
            damaged_returns_cost += return_req.refund_amount
    
    pending_returns_count = ReturnRequest.objects.filter(status__in=['submitted', 'verified']).count()
    pending_verification_count = ReturnRequest.objects.filter(status='submitted').count()
    pending_approval_count = ReturnRequest.objects.filter(status='verified').count()
    
    approved_returns_count = ReturnRequest.objects.filter(status='approved').count()
    processed_returns_count = ReturnRequest.objects.filter(status='processed').count()
    rejected_returns_count = ReturnRequest.objects.filter(status='rejected').count()
    
    # ============================================
    # STORE MANAGEMENT
    # ============================================
    from django.contrib.auth.models import Group
    
    store_manager_group = Group.objects.filter(name='store_manager').first()
    if store_manager_group:
        store_managers_count = store_manager_group.user_set.count()
        active_managers_count = store_manager_group.user_set.filter(is_active=True).count()
    else:
        store_managers_count = 0
        active_managers_count = 0
    
    total_suppliers = Supplier.objects.count()
    active_suppliers = Supplier.objects.filter(is_active=True).count()
    
    # ============================================
    # RECENT ITEMS
    # ============================================
    recent_products = Product.objects.select_related('category').filter(
        is_active=True
    ).order_by('-created_at')[:5]
    
    recent_units = ProductUnit.objects.select_related(
        'product', 'created_by'
    ).order_by('-created_at')[:10]
    
    recent_returns = ReturnRequest.objects.select_related(
        'requested_by', 'product', 'product_unit'
    ).order_by('-requested_at')[:5]
    
    recent_suppliers = Supplier.objects.filter(
        is_active=True
    ).order_by('-created_at')[:5]
    
    supplier_list = []
    for supplier in recent_suppliers:
        supplier_list.append({
            'id': supplier.id,
            'name': supplier.name,
            'phone': supplier.phone,
            'contact_person': supplier.contact_person,
            'created_at': supplier.created_at,
            'product_count': supplier.products.count(),
            'is_active': supplier.is_active,
        })
    
    # ============================================
    # STOCK ALERTS
    # ============================================
    alerts_queryset = StockAlert.objects.filter(
        is_active=True,
        is_dismissed=False
    ).select_related('product', 'product__category').order_by(
        '-severity', '-last_alerted'
    )
    
    page_size = request.GET.get('page_size', '20')
    
    if page_size == 'all':
        paginator = Paginator(alerts_queryset, alerts_queryset.count()) if alerts_queryset.exists() else Paginator(alerts_queryset, 1)
    else:
        paginator = Paginator(alerts_queryset, int(page_size))
    
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    total_alerts = alerts_queryset.count()
    
    # ============================================
    # CONTEXT
    # ============================================
    context = {
        # Products
        'total_products': total_products,
        'total_products_value': total_products_value,
        'total_products_cost': total_products_cost,
        
        # Items totals (Historical)
        'total_items': total_items,
        'total_items_value': total_items_value,
        'total_items_cost': total_items_cost,
        
        # Available (Current Stock)
        'available_items': available_items,
        'available_items_value': available_items_value,
        'available_items_cost': available_items_cost,
        
        # Sold
        'sold_items': sold_items,
        'sold_items_value': sold_items_value,
        
        # Damaged
        'damaged_items': damaged_items,
        'damaged_items_cost': damaged_items_cost,
        
        # Stolen & Lost
        'stolen_items': stolen_items,
        'stolen_items_cost': stolen_items_cost,
        'lost_items': lost_items,
        'lost_items_cost': lost_items_cost,
        
        # Other statuses
        'reserved_items': reserved_items,
        'returned_units': returned_units,
        'written_off_items': written_off_items,
        
        # Return Requests
        'returned_items': returned_items,
        'returned_items_value': returned_items_value,
        'returned_items_cost': returned_items_cost,
        
        'damaged_returns_count': damaged_returns_count,
        'damaged_returns_value': damaged_returns_value,
        'damaged_returns_cost': damaged_returns_cost,
        
        'pending_returns_count': pending_returns_count,
        'pending_verification_count': pending_verification_count,
        'pending_approval_count': pending_approval_count,
        
        'approved_returns_count': approved_returns_count,
        'processed_returns_count': processed_returns_count,
        'rejected_returns_count': rejected_returns_count,
        
        # Staff & Suppliers
        'store_managers_count': store_managers_count,
        'active_managers_count': active_managers_count,
        'total_suppliers': total_suppliers,
        'active_suppliers': active_suppliers,
        
        # Recent Items
        'recent_products': recent_products,
        'recent_units': recent_units,
        'recent_returns': recent_returns,
        'recent_suppliers': supplier_list,
        
        # Stock Alerts
        'alerts': page_obj,
        'page_obj': page_obj,
        'page_size': page_size,
        'total_alerts': total_alerts,
    }
    
    return render(request, 'inventory/statistics.html', context)


@login_required
def inventory_report(request):
    """Inventory report page"""
    from decimal import Decimal
    
    # Get all active products
    products = Product.objects.filter(is_active=True, is_discontinued=False).select_related('category')
    
    # ============================================
    # Calculate totals using Python (since we can't use F() with properties)
    # ============================================
    
    total_items = 0
    total_value = Decimal('0.00')
    total_cost = Decimal('0.00')
    low_stock_count = 0
    out_of_stock_count = 0
    top_products_list = []
    
    # Process each product to calculate current stock
    for product in products:
        # Get current stock using the property
        current_stock = product.current_stock
        
        # Add to totals
        total_items += current_stock
        total_value += product.selling_price * current_stock
        total_cost += product.buying_price * current_stock
        
        # Check low stock
        if product.category.is_bulk_item:
            if 0 < product.bulk_quantity <= product.reorder_level:
                low_stock_count += 1
            if product.bulk_quantity == 0:
                out_of_stock_count += 1
        else:  # Single item
            if 0 < product.available_quantity <= 5:
                low_stock_count += 1
            if product.available_quantity == 0:
                out_of_stock_count += 1
        
        # Store for top products (will sort later)
        stock_value = product.selling_price * current_stock
        top_products_list.append({
            'product': product,
            'current_stock': current_stock,
            'stock_value': stock_value
        })
    
    # Get top 10 products by stock value
    top_products_list.sort(key=lambda x: x['stock_value'], reverse=True)
    top_products = [item['product'] for item in top_products_list[:10]]
    
    # Add display attributes to top products
    for product in top_products:
        product.display_stock = product.current_stock
        product.display_value = product.selling_price * product.current_stock
    
    # ============================================
    # Category summary
    # ============================================
    categories = []
    for category in Category.objects.filter(is_active=True):
        cat_products = products.filter(category=category)
        
        cat_total_items = 0
        cat_total_value = Decimal('0.00')
        
        for product in cat_products:
            current_stock = product.current_stock
            cat_total_items += current_stock
            cat_total_value += product.selling_price * current_stock
        
        categories.append({
            'id': category.id,
            'name': category.name,
            'item_type': category.item_type,
            'item_type_display': category.get_item_type_display(),
            'product_count': cat_products.count(),
            'total_items': cat_total_items,
            'total_value': cat_total_value,
            'percentage': (cat_total_value / total_value * 100) if total_value > 0 else 0,
        })
    
    # Sort categories by total value descending
    categories.sort(key=lambda x: x['total_value'], reverse=True)
    
    # ============================================
    # Additional statistics
    # ============================================
    
    # Total SKUs
    total_skus = products.count()
    
    # Discontinued products
    discontinued = Product.objects.filter(is_discontinued=True).count()
    
    # Inactive products
    inactive = Product.objects.filter(is_active=False, is_discontinued=False).count()
    
    # Total units (including sold, damaged, etc.) from ProductUnit model
    from inventory.models import ProductUnit
    total_units_all = ProductUnit.objects.count()
    sold_units = ProductUnit.objects.filter(status='sold').count()
    available_units = ProductUnit.objects.filter(status='available').count()
    damaged_units = ProductUnit.objects.filter(status='damaged').count()
    
    # Available products count (products with stock > 0)
    available_count = sum(1 for p in products if p.current_stock > 0)
    
    # Retail value (same as total_value for now)
    retail_value = total_value
    
    context = {
        # Summary stats
        'total_products': total_skus,
        'total_items': total_items,
        'total_value': total_value,
        'total_cost': total_cost,
        'retail_value': retail_value,
        'low_stock': low_stock_count,
        'out_of_stock': out_of_stock_count,
        'available': available_count,
        'discontinued': discontinued,
        'inactive': inactive,
        
        # Unit stats (for single items)
        'total_units_all': total_units_all,
        'sold_units': sold_units,
        'available_units': available_units,
        'damaged_units': damaged_units,
        
        # Top products and categories
        'top_products': top_products,
        'categories': categories,
        
        # Timestamp
        'now': timezone.now(),
        'report_date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    return render(request, 'inventory/reports/inventory_report.html', context)

@login_required
def category_analysis(request):
    """Category analysis report"""
    from decimal import Decimal
    from django.db.models import Count, Sum, F, Q, Case, When, IntegerField, DecimalField, Value
    from django.db.models.functions import Coalesce
    
    # Annotate products with current stock
    products = Product.objects.filter(is_active=True, is_discontinued=False).annotate(
        current_stock=Case(
            When(category__item_type='bulk', then=F('bulk_quantity')),
            When(category__item_type='single', then=F('available_quantity')),
            output_field=IntegerField()
        )
    ).select_related('category')
    
    # Get categories with aggregated data
    from django.db.models import Sum as DjangoSum
    
    category_data = []
    categories = Category.objects.filter(is_active=True)
    
    for category in categories:
        cat_products = products.filter(category=category)
        
        # Use aggregation for better performance
        aggregated = cat_products.aggregate(
            total_products=Count('id'),
            total_items=DjangoSum('current_stock'),
            total_value=DjangoSum(F('selling_price') * F('current_stock'), output_field=DecimalField(max_digits=15, decimal_places=2)),
            total_cost=DjangoSum(F('buying_price') * F('current_stock'), output_field=DecimalField(max_digits=15, decimal_places=2))
        )
        
        total_products = aggregated['total_products'] or 0
        total_items = aggregated['total_items'] or 0
        total_value = aggregated['total_value'] or Decimal('0.00')
        total_cost = aggregated['total_cost'] or Decimal('0.00')
        
        profit = total_value - total_cost
        margin = (profit / total_value * 100) if total_value > 0 else 0
        
        category_data.append({
            'id': category.id,
            'name': category.name,
            'category_code': category.category_code,
            'item_type': category.item_type,
            'item_type_display': category.get_item_type_display(),
            'total_products': total_products,
            'total_items': total_items,
            'total_value': total_value,
            'total_cost': total_cost,
            'profit': profit,
            'margin': margin,
        })
    
    # Sort categories by total value descending
    category_data.sort(key=lambda x: x['total_value'], reverse=True)
    
    # Calculate totals
    total_products = sum(item['total_products'] for item in category_data)
    total_items = sum(item['total_items'] for item in category_data)
    total_value = sum(item['total_value'] for item in category_data)
    total_cost = sum(item['total_cost'] for item in category_data)
    total_profit = total_value - total_cost
    overall_margin = (total_profit / total_value * 100) if total_value > 0 else 0
    
    # Get top performing category
    top_category = category_data[0] if category_data else None
    
    # Get slow moving categories (lowest total value)
    slow_categories = sorted(category_data, key=lambda x: x['total_value'])[:3] if category_data else []
    
    # Calculate average values
    avg_items_per_category = total_items / len(category_data) if category_data else 0
    avg_value_per_category = total_value / len(category_data) if category_data else 0
    
    # Calculate category distribution percentages
    for cat in category_data:
        cat['percentage_of_total'] = (cat['total_value'] / total_value * 100) if total_value > 0 else 0
    
    context = {
        'categories': category_data,
        'total_products': total_products,
        'total_items': total_items,
        'total_value': total_value,
        'total_cost': total_cost,
        'total_profit': total_profit,
        'overall_margin': overall_margin,
        'top_category': top_category,
        'slow_categories': slow_categories,
        'avg_items_per_category': avg_items_per_category,
        'avg_value_per_category': avg_value_per_category,
        'report_date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    return render(request, 'inventory/reports/category_analysis.html', context)

@login_required
def dashboard(request):
    """Dashboard view with statistics and charts"""
    
    # ============================================
    # BASIC STATS - UPDATED FOR SKU MODEL
    # ============================================
    total_products = Product.objects.filter(is_active=True).count()
    
    # Available products = bulk items with stock > 0 + single items with available units > 0
    available_bulk = Product.objects.filter(
        category__item_type='bulk',
        bulk_quantity__gt=0,
        is_active=True
    ).count()
    
    available_single = Product.objects.filter(
        category__item_type='single',
        available_quantity__gt=0,
        is_active=True
    ).count()
    
    available_products = available_bulk + available_single
    
    # Low stock count (only for bulk items - single items don't have low stock alerts)
    low_stock_count = Product.objects.filter(
        category__item_type='bulk',
        bulk_quantity__gt=0,
        bulk_quantity__lte=F('reorder_level'),
        is_active=True
    ).count()
    
    # Out of stock products
    out_of_stock_bulk = Product.objects.filter(
        category__item_type='bulk',
        bulk_quantity=0,
        is_active=True
    ).count()
    
    out_of_stock_single = Product.objects.filter(
        category__item_type='single',
        available_quantity=0,
        is_active=True
    ).count()
    
    out_of_stock = out_of_stock_bulk + out_of_stock_single
    
    # ============================================
    # RECENT PRODUCTS
    # ============================================
    recent_products = Product.objects.select_related('category').filter(
        is_active=True
    ).order_by('-created_at')[:5]
    
    # ============================================
    # RECENT STOCK MOVEMENTS
    # ============================================
    recent_movements = StockEntry.objects.select_related(
        'product_sku', 'product_unit', 'created_by'
    ).order_by('-created_at')[:5]
    
    # ============================================
    # LOW STOCK ALERTS (Only for bulk items)
    # ============================================
    low_stock_alerts = StockAlert.objects.filter(
        is_active=True,
        is_dismissed=False,
        product__category__item_type='bulk'
    ).select_related('product')[:10]
    
    # ============================================
    # CHART DATA (last 30 days)
    # ============================================
    thirty_days_ago = timezone.now() - timedelta(days=30)
    entries = StockEntry.objects.filter(created_at__gte=thirty_days_ago)
    
    chart_labels = []
    stock_in_data = []
    stock_out_data = []
    
    for i in range(30):
        date = thirty_days_ago + timedelta(days=i)
        day_entries = entries.filter(created_at__date=date.date())
        
        chart_labels.append(date.strftime('%d %b'))
        stock_in_data.append(day_entries.filter(quantity__gt=0).aggregate(s=Sum('quantity'))['s'] or 0)
        stock_out_data.append(abs(day_entries.filter(quantity__lt=0).aggregate(s=Sum('quantity'))['s'] or 0))
    
    # ============================================
    # STOLEN/LOST UNITS COUNT
    # ============================================
    from inventory.models import ProductUnit
    stolen_units = ProductUnit.objects.filter(status='stolen').count()
    lost_units = ProductUnit.objects.filter(status='lost').count()
    
    context = {
        'total_products': total_products,
        'available_products': available_products,
        'low_stock_count': low_stock_count,
        'out_of_stock': out_of_stock,
        'recent_products': recent_products,
        'recent_movements': recent_movements,
        'low_stock_alerts': low_stock_alerts,
        'chart_labels': chart_labels,
        'stock_in_data': stock_in_data,
        'stock_out_data': stock_out_data,
        'stolen_units': stolen_units,
        'lost_units': lost_units,
    }
    
    return render(request, 'inventory/dashboard.html', context)



# ===========================================
# ===========================================
# CATEGORY MANAGEMENT VIEW
# ===========================================
@login_required
def category_list(request):
    """List all categories"""
    categories = Category.objects.all()
    return render(request, 'inventory/categories/list.html', {'categories': categories})

@login_required
def category_add(request):
    """Add new category"""
    if request.method == 'POST':
        name = request.POST.get('name')
        item_type = request.POST.get('item_type')
        identifier_type = request.POST.get('identifier_type')  # Changed from sku_type
        description = request.POST.get('description', '')  # Added description field
        category_code = request.POST.get('category_code')
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            category = Category.objects.create(
                name=name,
                item_type=item_type,
                identifier_type=identifier_type,  # Changed from sku_type
                description=description,  # Added description
                is_active=is_active
            )
            
            # If custom category code provided, update it
            if category_code:
                category.category_code = f"FSL.{category_code.upper()}"
                category.save()
            
            messages.success(request, f'Category "{name}" created successfully with code: {category.category_code}')
            return redirect('inventory:category_list')
            
        except Exception as e:
            messages.error(request, f'Error creating category: {str(e)}')
    
    return render(request, 'inventory/categories/add.html')

@login_required
def category_edit(request, pk):
    """Edit category"""
    category = get_object_or_404(Category, pk=pk)
    
    if request.method == 'POST':
        name = request.POST.get('name')
        item_type = request.POST.get('item_type')
        identifier_type = request.POST.get('identifier_type')  # Changed from sku_type
        description = request.POST.get('description', '')  # Added description
        category_code = request.POST.get('category_code')
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            category.name = name
            category.item_type = item_type
            category.identifier_type = identifier_type  # Changed from sku_type
            category.description = description
            category.is_active = is_active
            
            if category_code:
                category.category_code = f"FSL.{category_code.upper()}"
            category.save()
            
            messages.success(request, f'Category "{name}" updated successfully.')
            return redirect('inventory:category_list')
            
        except Exception as e:
            messages.error(request, f'Error updating category: {str(e)}')
    
    context = {
        'category': category,
    }
    return render(request, 'inventory/categories/edit.html', context)

@login_required
def category_delete(request, pk):
    """Delete a category"""
    category = get_object_or_404(Category, pk=pk)
    
    if request.method == 'POST':
        category_name = category.name
        category.delete()
        messages.success(request, f'Category "{category_name}" deleted successfully.')
        return redirect('inventory:category_list')
    
    return render(request, 'inventory/categories/delete.html', {'category': category})



# ===========================================
# ===========================================
# PRODUCT MANAGEMENT VIEW
# ===========================================
@login_required
def product_list(request):
    """List all products with filtering"""
    products = Product.objects.select_related('category').all().order_by('-created_at')
    
    # Apply filters
    category_id = request.GET.get('category')
    if category_id:
        products = products.filter(category_id=category_id)
    
    status = request.GET.get('status')
    if status:
        products = products.filter(status=status)

    owner = request.GET.get('owner')
    if owner:
        if owner == 'none':
            products = products.filter(owner__isnull=True)
        elif owner == 'me':
            products = products.filter(owner=request.user)
        else:
            try:
                products = products.filter(owner_id=int(owner))
            except ValueError:
                pass
    
    brand = request.GET.get('brand')
    if brand:
        products = products.filter(brand__icontains=brand)
    
    # ============================================
    # ENHANCED SEARCH - Including ProductUnit IMEI/Serial
    # ============================================
    search = request.GET.get('search')
    if search:
        # First, find products matching basic criteria
        products = products.filter(
            Q(sku_code__icontains=search) |
            Q(name__icontains=search) |
            Q(brand__icontains=search) |
            Q(model__icontains=search) |
            Q(bulk_serial_number__icontains=search)
        )
        
        # Also search for IMEI/Serial numbers in ProductUnit
        # This finds products that have units matching the search
        from django.db.models import Exists, OuterRef
        from inventory.models import ProductUnit
        
        products_with_matching_units = Product.objects.filter(
            Exists(
                ProductUnit.objects.filter(
                    product=OuterRef('pk')
                ).filter(
                    Q(imei_number__icontains=search) |
                    Q(serial_number__icontains=search)
                )
            )
        )
        
        # Combine both results
        products = products | products_with_matching_units
        products = products.distinct()
    
    # Pagination
    paginator = Paginator(products, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    categories = Category.objects.filter(is_active=True)
    user_groups = list(request.user.groups.values_list('name', flat=True))

    from django.contrib.auth import get_user_model
    User = get_user_model()
    users = User.objects.filter(is_active=True).order_by('first_name', 'username')
    
    authorized_roles = [
        'administrator',
        'store_manager', 
        'inventory_manager',
        'supervisor',
        'sales_manager',
        'admin',
    ]
    
    can_transfer_any = request.user.is_superuser or any(
        group in authorized_roles for group in user_groups
    )
    
    context = {
        'products': page_obj,
        'categories': categories,
        'user_groups': user_groups,
        'is_superuser': request.user.is_superuser,
        'can_transfer_any': can_transfer_any,
        'authorized_roles': authorized_roles, 
        'users': users,
    }
    
    return render(request, 'inventory/products/list.html', context)

@login_required
def product_units_list(request):
    """List all product units with filtering"""
    from django.db.models import Q
    from django.core.paginator import Paginator
    
    # Get all units from single-item categories only (use item_type field)
    units = ProductUnit.objects.filter(
        product__category__item_type='single'  # Use the actual field name
    ).select_related(
        'product', 
        'product__category', 
        'sold_by', 
        'loss_reported_by', 
        'recovered_by', 
        'created_by',
        'supplier'
    ).order_by('-created_at')
    
    # Apply filters
    status_filter = request.GET.get('status')
    if status_filter:
        units = units.filter(status=status_filter)
    
    condition_filter = request.GET.get('condition')
    if condition_filter:
        units = units.filter(condition=condition_filter)
    
    product_filter = request.GET.get('product')
    if product_filter:
        units = units.filter(product_id=product_filter)
    
    search = request.GET.get('search')
    if search:
        units = units.filter(
            Q(imei_number__icontains=search) |
            Q(serial_number__icontains=search) |
            Q(product__sku_code__icontains=search) |
            Q(product__name__icontains=search) |
            Q(product__brand__icontains=search) |
            Q(product__model__icontains=search)
        )
    
    # Calculate statistics
    total_available = units.filter(status='available').count()
    total_sold = units.filter(status='sold').count()
    total_damaged = units.filter(status='damaged').count()
    total_stolen_lost = units.filter(status__in=['stolen', 'lost']).count()
    
    # Pagination
    paginator = Paginator(units, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get all products for filter dropdown (only single item products that have units)
    products = Product.objects.filter(
        units__isnull=False,
        category__item_type='single'  # Use the actual field name
    ).distinct().order_by('sku_code')
    
    context = {
        'units': page_obj,
        'products': products,
        'total_available': total_available,
        'total_sold': total_sold,
        'total_damaged': total_damaged,
        'total_stolen_lost': total_stolen_lost,
    }
    return render(request, 'inventory/product_units_list.html', context)

@login_required
def product_detail(request, pk):
    """View single product details"""
    from django.core.paginator import Paginator
    from django.db import models
    
    product = get_object_or_404(
        Product.objects.select_related('category', 'supplier', 'created_by', 'last_modified_by'), 
        pk=pk
    )
    
    # Get per_page for units from request (default 10)
    per_page = request.GET.get('per_page', 10)
    try:
        per_page = int(per_page)
        if per_page not in [10, 25, 50, 100]:
            per_page = 10
    except ValueError:
        per_page = 10
    
    # Get stock_per_page for stock movements from request (default 10)
    stock_per_page = request.GET.get('stock_per_page', 10)
    try:
        stock_per_page = int(stock_per_page)
        if stock_per_page not in [10, 25, 50, 100]:
            stock_per_page = 10
    except ValueError:
        stock_per_page = 10
    
    # Get stock entries with pagination (includes both product_sku and product_unit entries)
    stock_entries_list = StockEntry.objects.filter(
        models.Q(product_sku=product) | models.Q(product_unit__product=product)
    ).select_related('created_by', 'product_unit', 'product_sku').order_by('-created_at')
    
    stock_paginator = Paginator(stock_entries_list, stock_per_page)
    stock_page_number = request.GET.get('stock_page', 1)
    stock_entries = stock_paginator.get_page(stock_page_number)
    
    # Get units with pagination for single items
    product_units = None
    if product.category.is_single_item:
        product_units_list = product.units.select_related(
            'sold_by', 'created_by'
        ).order_by('-created_at')
        
        units_paginator = Paginator(product_units_list, per_page)
        units_page_number = request.GET.get('page', 1)
        product_units = units_paginator.get_page(units_page_number)
    
    context = {
        'product': product,
        'stock_entries': stock_entries,
        'product_units': product_units,
        'current_stock': product.current_stock,
        'per_page': per_page,
        'stock_per_page': stock_per_page,
    }
    
    return render(request, 'inventory/products/detail.html', context)

@login_required
def product_add(request):
    """Add new product SKU - Supports both Bulk and Single items"""
    if request.method == 'POST':
        try:
            # Get form data
            name = request.POST.get('name')
            category_id = request.POST.get('category')
            brand = request.POST.get('brand', '')
            model = request.POST.get('model', '')
            description = request.POST.get('description', '')
            
            # Get bulk item serial number (only for bulk items)
            bulk_serial_number = request.POST.get('bulk_serial_number', '').strip()
            
            # Pricing - Convert to Decimal
            try:
                buying_price = Decimal(request.POST.get('buying_price', '0'))
                selling_price = Decimal(request.POST.get('selling_price', '0'))
                best_price = request.POST.get('best_price')
                best_price = Decimal(best_price) if best_price else None
            except (ValueError, TypeError, Decimal.InvalidOperation) as e:
                messages.error(request, f'Invalid price format: {str(e)}')
                return redirect('inventory:product_add')
            
            # Inventory settings
            try:
                reorder_level_raw = request.POST.get('reorder_level')
                reorder_level = int(reorder_level_raw) if reorder_level_raw and reorder_level_raw.strip() else 5
                warranty_months = int(request.POST.get('warranty_months', 12))
            except (ValueError, TypeError) as e:
                messages.error(request, f'Invalid number format: {str(e)}')
                return redirect('inventory:product_add')
            
            # For bulk items
            bulk_quantity = int(request.POST.get('bulk_quantity', 0))
            
            # Specifications as JSON
            specifications = {}
            ram = request.POST.get('ram', '')
            storage = request.POST.get('storage', '')
            color = request.POST.get('color', '')
            if ram:
                specifications['ram'] = ram
            if storage:
                specifications['storage'] = storage
            if color:
                specifications['color'] = color
            
            # For bulk items, add serial number to specifications
            if bulk_serial_number:
                specifications['serial_number'] = bulk_serial_number
                specifications['batch_id'] = bulk_serial_number
            
            supplier_id = request.POST.get('supplier')
            
            # Get category
            category = Category.objects.get(id=category_id)
            
            # Validate required fields
            if not name:
                messages.error(request, 'Product name is required.')
                return redirect('inventory:product_add')
            
            # For single items, brand and model are required
            if category.is_single_item:
                if not brand:
                    messages.error(request, 'Brand is required for single items.')
                    return redirect('inventory:product_add')
                if not model:
                    messages.error(request, 'Model is required for single items.')
                    return redirect('inventory:product_add')
                # For single items, at least one specification is required
                has_spec = ram or storage or color
                if not has_spec:
                    messages.error(request, 'At least one specification (RAM, Storage, or Color) is required for single items.')
                    return redirect('inventory:product_add')
            
            if buying_price <= 0 or selling_price <= 0:
                messages.error(request, 'Buying and selling prices must be greater than zero.')
                return redirect('inventory:product_add')
            
            # Create product SKU
            product = Product.objects.create(
                name=name,
                category=category,
                brand=brand,
                model=model,
                description=description,
                buying_price=buying_price,
                selling_price=selling_price,
                best_price=best_price,
                specifications=specifications,
                reorder_level=reorder_level,
                warranty_months=warranty_months,
                created_by=request.user,
                last_modified_by=request.user
            )
            
            # Set supplier if provided
            if supplier_id:
                product.supplier = Supplier.objects.get(id=supplier_id)
                product.save()
            
            # Set bulk serial number for bulk items
            if category.is_bulk_item and bulk_serial_number:
                product.bulk_serial_number = bulk_serial_number
                product.save(update_fields=['bulk_serial_number'])
            
            # Handle inventory based on item type
            if category.is_bulk_item:
                # ============================================
                # BULK ITEM - Single stock entry for all units
                # ============================================
                if bulk_quantity > 0:
                    product.bulk_quantity = bulk_quantity
                    product.save(update_fields=['bulk_quantity'])
                    
                    # Create reference ID with serial number if available
                    if bulk_serial_number:
                        reference_id = f"SKU:{product.sku_code}-BATCH:{bulk_serial_number}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
                        notes = f"Bulk addition: {bulk_quantity} units of {product.name} | Batch/Serial: {bulk_serial_number}"
                    else:
                        reference_id = f"SKU:{product.sku_code}-BULK-ADD-{timezone.now().strftime('%Y%m%d%H%M%S')}"
                        notes = f"Initial stock for SKU: {product.sku_code} - Added {bulk_quantity} units @ KES {buying_price} each"
                    
                    StockEntry.objects.create(
                        product_sku=product,
                        quantity=bulk_quantity,
                        entry_type='purchase',
                        unit_price=buying_price,
                        total_amount=buying_price * bulk_quantity,
                        reference_id=reference_id,
                        notes=notes,
                        created_by=request.user
                    )
                    messages.success(request, f'✅ Bulk product "{name}" created with SKU: {product.sku_code} and {bulk_quantity} units.')
                    if bulk_serial_number:
                        messages.info(request, f'📦 Batch/Serial Number: {bulk_serial_number}')
                else:
                    messages.success(request, f'✅ Bulk product "{name}" created with SKU: {product.sku_code}. Use "Restock" to add quantity.')
            
            else:
                # ============================================
                # SINGLE ITEM - No stock created automatically
                # User must add units with IMEI/Serial later
                # ============================================
                messages.success(request, f'✅ Single item product "{name}" created with SKU: {product.sku_code}')
                messages.info(request, f'📱 You can now add individual units with IMEI/Serial numbers using the "Add Units" button.')
            
            return redirect('inventory:product_detail', pk=product.id)
            
        except Category.DoesNotExist:
            messages.error(request, 'Selected category does not exist.')
            return redirect('inventory:product_add')
        except Exception as e:
            logger.error(f"Error creating product: {str(e)}")
            messages.error(request, f'Error creating product: {str(e)}')
            return redirect('inventory:product_add')

    # GET request - show form
    categories = Category.objects.filter(is_active=True)
    suppliers = Supplier.objects.filter(is_active=True)
    
    context = {
        'categories': categories,
        'suppliers': suppliers,
    }
    return render(request, 'inventory/products/add.html', context)

@login_required
def product_bulk_add_units(request, sku_code=None):
    """Add multiple units to an existing single-item SKU"""
    
    # If no sku_code provided, show search page
    if not sku_code:
        # Handle search form submission
        if request.method == 'POST' and 'search_sku' in request.POST:
            search_sku = request.POST.get('search_sku', '').strip()
            if search_sku: 
                try:
                    product = Product.objects.get(sku_code=search_sku, category__item_type='single')
                    return redirect('inventory:product_bulk_add_units_with_sku', sku_code=product.sku_code)
                except Product.DoesNotExist:
                    messages.error(request, f'No single-item SKU found with code: {search_sku}')
                    return redirect('inventory:product_bulk_add_units')
            else:
                messages.error(request, 'Please enter an SKU code')
                return redirect('inventory:product_bulk_add_units')
        
        # GET request - show search form
        return render(request, 'inventory/products/bulk_add_search.html')
    
    # If sku_code provided, show the bulk add form
    product = get_object_or_404(Product, sku_code=sku_code, category__item_type='single')
    
    if request.method == 'POST':
        imeis_text = request.POST.get('imeis', '')
        serials_text = request.POST.get('serials', '')
        condition = request.POST.get('condition', 'new')
        unit_buying_price = request.POST.get('unit_buying_price', '')
        unit_selling_price = request.POST.get('unit_selling_price', '')
        mark_available = request.POST.get('mark_available') == 'on'
        notes = request.POST.get('notes', f"Added units to {product.sku_code}")
        
        imei_list = [i.strip() for i in imeis_text.split('\n') if i.strip()]
        serial_list = [s.strip() for s in serials_text.split('\n') if s.strip()]
        
        created_count = 0
        errors = []
        created_units = []
        
        # Create IMEI units
        for imei in imei_list:
            if len(imei) != 15 or not imei.isdigit():
                errors.append(f'Invalid IMEI: {imei} (must be 15 digits)')
                continue
            try:
                with transaction.atomic():
                    unit_data = {
                        'product': product,
                        'imei_number': imei,
                        'condition': condition,
                        'status': 'available' if mark_available else 'available',
                        'created_by': request.user
                    }
                    if unit_buying_price:
                        unit_data['unit_buying_price'] = Decimal(unit_buying_price)
                    if unit_selling_price:
                        unit_data['unit_selling_price'] = Decimal(unit_selling_price)
                    
                    unit = ProductUnit.objects.create(**unit_data)
                    created_units.append(unit)
                    
                    # ============================================
                    # CREATE STOCK ENTRY WITH SKU + IDENTIFIER IN REFERENCE
                    # ============================================
                    buying_price = Decimal(unit_buying_price) if unit_buying_price else product.buying_price
                    
                    # Reference ID format: SKU:FSL001-IMEI:355455655766855
                    reference_id = f"SKU:{product.sku_code}-IMEI:{imei}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
                    
                    StockEntry.objects.create(
                        product_unit=unit,
                        quantity=1,
                        entry_type='purchase',
                        unit_price=buying_price,
                        total_amount=buying_price,
                        reference_id=reference_id,
                        notes=f"Added unit - SKU: {product.sku_code} | IMEI: {imei} | Condition: {condition}. {notes}",
                        created_by=request.user
                    )
                    created_count += 1
                    logger.info(f"✅ Unit added: SKU {product.sku_code} | IMEI: {imei}")
                    
            except Exception as e:
                errors.append(f'IMEI {imei}: {str(e)}')
                logger.error(f"Error adding IMEI {imei}: {str(e)}")
        
        # Create Serial units
        for serial in serial_list:
            try:
                with transaction.atomic():
                    unit_data = {
                        'product': product,
                        'serial_number': serial,
                        'condition': condition,
                        'status': 'available' if mark_available else 'available',
                        'created_by': request.user
                    }
                    if unit_buying_price:
                        unit_data['unit_buying_price'] = Decimal(unit_buying_price)
                    if unit_selling_price:
                        unit_data['unit_selling_price'] = Decimal(unit_selling_price)
                    
                    unit = ProductUnit.objects.create(**unit_data)
                    created_units.append(unit)
                    
                    # ============================================
                    # CREATE STOCK ENTRY WITH SKU + IDENTIFIER IN REFERENCE
                    # ============================================
                    buying_price = Decimal(unit_buying_price) if unit_buying_price else product.buying_price
                    
                    # Reference ID format: SKU:FSL001-SN:ABC123456
                    reference_id = f"SKU:{product.sku_code}-SN:{serial}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
                    
                    StockEntry.objects.create(
                        product_unit=unit,
                        quantity=1,
                        entry_type='purchase',
                        unit_price=buying_price,
                        total_amount=buying_price,
                        reference_id=reference_id,
                        notes=f"Added unit - SKU: {product.sku_code} | Serial: {serial} | Condition: {condition}. {notes}",
                        created_by=request.user
                    )
                    created_count += 1
                    logger.info(f"✅ Unit added: SKU {product.sku_code} | Serial: {serial}")
                    
            except Exception as e:
                errors.append(f'Serial {serial}: {str(e)}')
                logger.error(f"Error adding Serial {serial}: {str(e)}")
        
        # Update product quantities
        product.update_quantities()
        
        if created_count > 0:
            messages.success(request, f'✅ Added {created_count} units to SKU: {product.sku_code} - {product.name}')
            logger.info(f"📦 Bulk add complete: {created_count} units added to SKU {product.sku_code}")
        if errors:
            messages.warning(request, f'⚠️ Errors encountered: {", ".join(errors[:5])}')
        
        return redirect('inventory:product_detail', pk=product.id)
    
    # GET request - show form with product info
    context = {
        'product': product,
        'sku_code': product.sku_code,
        'product_name': product.name,
        'current_units': product.units.count(),
        'available_units': product.available_quantity,
    }
    return render(request, 'inventory/products/bulk_add_units.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def product_bulk_edit(request):
    """
    Bulk edit products by model - search and update selling prices
    """
    context = {
        'products': [],
        'search_performed': False,
        'model_searched': '',
        'total_products': 0,
        'current_prices': {},
    }
    
    # If there were recently updated products, fetch them for display
    if request.session.get('bulk_updated_products'):
        from .models import Product
        updated_ids = request.session.get('bulk_updated_products', [])
        context['products_updated'] = Product.objects.filter(id__in=updated_ids)
    
    return render(request, 'inventory/products/bulk_edit.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def product_bulk_search(request):
    """
    AJAX endpoint to search products by model - ONLY AVAILABLE PRODUCTS
    """
    if request.method == 'GET' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        model_search = request.GET.get('model', '').strip()
        
        if not model_search:
            return JsonResponse({'error': 'Please enter a product model'}, status=400)
        
        # Search for products with matching model - ONLY AVAILABLE products
        # For bulk items: check bulk_quantity > 0
        # For single items: check available_quantity > 0
        from django.db.models import Q
        
        products = Product.objects.filter(
            Q(model__icontains=model_search) |
            Q(name__icontains=model_search) |
            Q(brand__icontains=model_search) |
            Q(sku_code__icontains=model_search),  # Also search by SKU
            is_active=True
        ).filter(
            Q(category__item_type='bulk', bulk_quantity__gt=0) |
            Q(category__item_type='single', available_quantity__gt=0)
        ).select_related('category').order_by('brand', 'model', 'sku_code')
        
        # Prepare product data
        products_data = []
        for product in products:
            # Determine current stock based on item type
            if product.category.is_single_item:
                current_stock = product.available_quantity
                stock_display = f"{current_stock} unit(s)"
            else:
                current_stock = product.bulk_quantity
                stock_display = f"{current_stock} units"
            
            products_data.append({
                'id': product.id,
                'name': product.name,
                'sku_code': product.sku_code,
                'brand': product.brand or '-',
                'model': product.model or '-',
                'selling_price': float(product.selling_price),
                'current_price': float(product.selling_price),
                'status': 'available',
                'current_quantity': current_stock,
                'stock_display': stock_display,
                'category': product.category.name if product.category else '-',
                'is_single_item': product.category.is_single_item,
                'reorder_level': product.reorder_level or 5,
            })
        
        return JsonResponse({
            'success': True,
            'products': products_data,
            'total_count': len(products_data),
            'model_searched': model_search,
            'message': f'Found {len(products_data)} available product(s) matching "{model_search}"'
        })
    
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def product_bulk_update(request):
    """
    Update selling prices for all AVAILABLE products of a specific model
    """
    from decimal import Decimal
    from django.db.models import Q
    from django.utils import timezone
    from django.http import JsonResponse
    import logging
    
    logger = logging.getLogger(__name__)
    
    if request.method == 'POST':
        model_search = request.POST.get('model_search', '').strip()
        new_price = request.POST.get('new_price', '').strip()
        update_all = request.POST.get('update_all', 'false') == 'true'
        
        # Validation
        if not model_search:
            return JsonResponse({'error': 'Please enter a product model'}, status=400)
        
        if not new_price:
            return JsonResponse({'error': 'Please enter a new selling price'}, status=400)
        
        try:
            new_price_decimal = Decimal(new_price)
            if new_price_decimal < 0:
                return JsonResponse({'error': 'Price cannot be negative'}, status=400)
        except:
            return JsonResponse({'error': 'Please enter a valid price'}, status=400)
        
        # Get products to update (only available)
        base_queryset = Product.objects.filter(
            Q(model__icontains=model_search) |
            Q(name__icontains=model_search) |
            Q(brand__icontains=model_search),
            is_active=True
        ).filter(
            Q(category__item_type='single', available_quantity__gt=0) |
            Q(category__item_type='bulk', bulk_quantity__gt=0)
        ).select_related('category')
        
        if update_all:
            products_to_update = base_queryset
        else:
            selected_product_ids = request.POST.getlist('selected_products')
            if not selected_product_ids:
                return JsonResponse({'error': 'Please select at least one product'}, status=400)
            products_to_update = base_queryset.filter(id__in=selected_product_ids)
        
        if not products_to_update.exists():
            return JsonResponse({'error': f'No available products found matching "{model_search}"'}, status=404)
        
        # Get old price for message
        first_product = products_to_update.first()
        old_price = float(first_product.selling_price)
        
        # Update prices
        updated_count = 0
        skipped_count = 0
        skipped_products = []
        
        for product in products_to_update:
            try:
                # If best_price exists and is greater than new selling price, set it to None
                if product.best_price and product.best_price > new_price_decimal:
                    old_best_price = product.best_price
                    product.best_price = None
                    logger.info(f"Reset best_price for {product.sku_code} from {old_best_price} to None (was > new price)")
                
                product.selling_price = new_price_decimal
                product.updated_at = timezone.now()
                product.save()
                updated_count += 1
                
            except ValidationError as e:
                skipped_count += 1
                skipped_products.append({
                    'code': product.sku_code,
                    'error': str(e)
                })
                logger.warning(f"Failed to update {product.sku_code}: {str(e)}")
            except Exception as e:
                skipped_count += 1
                skipped_products.append({
                    'code': product.sku_code,
                    'error': str(e)
                })
                logger.error(f"Error updating {product.sku_code}: {str(e)}")
        
        # Store in session for feedback
        if updated_count > 0:
            updated_ids = list(products_to_update.filter(selling_price=new_price_decimal).values_list('id', flat=True))
            request.session['bulk_updated_products'] = updated_ids
            request.session['bulk_updated_model'] = model_search
            request.session['bulk_updated_price'] = float(new_price_decimal)
            request.session['bulk_updated_old_price'] = old_price
        
        # Prepare response message
        if updated_count > 0 and skipped_count == 0:
            message = f'Successfully updated {updated_count} product(s) from KES {old_price:,.2f} to KES {new_price_decimal:,.2f}'
        elif updated_count > 0 and skipped_count > 0:
            message = f'Updated {updated_count} product(s). Skipped {skipped_count} product(s) due to validation errors.'
        else:
            message = f'Failed to update products. Validation errors occurred.'
        
        return JsonResponse({
            'success': updated_count > 0,
            'updated_count': updated_count,
            'skipped_count': skipped_count,
            'old_price': old_price,
            'new_price': float(new_price_decimal),
            'message': message,
            'skipped_products': skipped_products[:5]
        })
    
    return JsonResponse({'error': 'Invalid request method'}, status=400)

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def product_bulk_update_single(request):
    """Update a single product's name or price using direct database update"""
    from decimal import Decimal
    from django.http import JsonResponse
    from django.utils import timezone
    import logging
    
    logger = logging.getLogger(__name__)
    
    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        new_name = request.POST.get('name', '').strip()
        new_price = request.POST.get('selling_price', '').strip()
        
        print("=" * 50)
        print(f"📝 UPDATE REQUEST")
        print(f"   Product ID: {product_id}")
        print(f"   New Name: '{new_name}'")
        print(f"   New Price: '{new_price}'")
        print("=" * 50)
        
        if not product_id:
            return JsonResponse({'error': 'Product ID required'}, status=400)
        
        try:
            product = Product.objects.get(id=product_id, is_active=True)
            
            updates = {}
            
            # Update name if provided
            if new_name:
                print(f"   Updating name from '{product.name}' to '{new_name}'")
                updates['name'] = new_name
            
            # Update price if provided
            if new_price:
                try:
                    price_decimal = Decimal(new_price)
                    if price_decimal < 0:
                        return JsonResponse({'error': 'Price cannot be negative'}, status=400)
                    
                    print(f"   Updating price from {product.selling_price} to {price_decimal}")
                    updates['selling_price'] = price_decimal
                    
                    # Handle best_price validation
                    if product.best_price and product.best_price > price_decimal:
                        print(f"   Clearing best_price (was {product.best_price})")
                        updates['best_price'] = None
                        
                except Exception as e:
                    return JsonResponse({'error': f'Invalid price: {str(e)}'}, status=400)
            
            if updates:
                updates['updated_at'] = timezone.now()
                updated_count = Product.objects.filter(id=product_id).update(**updates)
                print(f"✅ Direct update completed! Rows affected: {updated_count}")
                
                product.refresh_from_db()
                print(f"   Verification - Name: '{product.name}', Price: {product.selling_price}")
                print("=" * 50)
                
                return JsonResponse({
                    'success': True,
                    'message': 'Product updated successfully',
                    'verified_name': product.name,
                    'verified_price': float(product.selling_price)
                })
            else:
                return JsonResponse({'error': 'No changes provided'}, status=400)
                
        except Product.DoesNotExist:
            print(f"❌ Product not found: {product_id}")
            return JsonResponse({'error': 'Product not found'}, status=404)
        except Exception as e:
            print(f"❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Invalid request method'}, status=400)

@login_required
def search_existing_models(request):
    """API endpoint to search for existing product models"""
    query = request.GET.get('q', '').strip()
    
    if not query or len(query) < 2:
        return JsonResponse({'success': True, 'models': []})
    
    # Search for unique models using sku_code instead of product_code
    products = Product.objects.filter(
        Q(model__icontains=query) |
        Q(brand__icontains=query) |
        Q(name__icontains=query)
    ).filter(
        is_active=True
    ).values('id', 'name', 'brand', 'model', 'sku_code', 'category_id').distinct()[:20]
    
    models_list = []
    seen = set()
    
    for product in products:
        key = f"{product['brand']}|{product['model']}"
        if key not in seen:
            seen.add(key)
            models_list.append({
                'id': product['id'],
                'name': product['name'],
                'brand': product['brand'] or '',
                'model': product['model'] or '',
                'sku_code': product['sku_code'],
                'category_id': product['category_id']
            })
    
    return JsonResponse({
        'success': True,
        'models': models_list
    })

@login_required
def get_product_details(request, product_id):
    """Get full product details for auto-fill"""
    try:
        product = Product.objects.get(id=product_id, is_active=True)
        
        return JsonResponse({
            'success': True,
            'product': {
                'id': product.id,
                'name': product.name,
                'brand': product.brand,
                'model': product.model,
                'description': product.description,
                'category_id': product.category_id,
                'specifications': product.specifications,
                'warranty_months': product.warranty_months,
                'buying_price': float(product.buying_price) if product.buying_price else 0,
                'selling_price': float(product.selling_price) if product.selling_price else 0,
                'best_price': float(product.best_price) if product.best_price else None,
            }
        })
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Product not found'}, status=404)

@login_required
def product_edit(request, pk):
    """Edit existing product SKU"""
    product = get_object_or_404(Product, pk=pk)
    
    if request.method == 'POST':
        try:
            # Get form data
            name = request.POST.get('name')
            category_id = request.POST.get('category')
            brand = request.POST.get('brand', '')
            model = request.POST.get('model', '')
            description = request.POST.get('description', '')
            
            # Bulk serial number (for bulk items)
            bulk_serial_number = request.POST.get('bulk_serial_number', '').strip()
            
            # Pricing
            buying_price = Decimal(request.POST.get('buying_price', '0'))
            selling_price = Decimal(request.POST.get('selling_price', '0'))
            best_price = request.POST.get('best_price')
            best_price = Decimal(best_price) if best_price else None
            
            # Inventory settings
            reorder_level = int(request.POST.get('reorder_level', 5))
            warranty_months = int(request.POST.get('warranty_months', 12))
            is_active = request.POST.get('is_active') == 'true'
            
            # Specifications
            specifications = {}
            ram = request.POST.get('ram', '')
            storage = request.POST.get('storage', '')
            color = request.POST.get('color', '')
            if ram:
                specifications['ram'] = ram
            if storage:
                specifications['storage'] = storage
            if color:
                specifications['color'] = color
            
            # For bulk items, add serial number to specifications
            if bulk_serial_number:
                specifications['serial_number'] = bulk_serial_number
                specifications['batch_id'] = bulk_serial_number
            
            # Get category
            category = Category.objects.get(id=category_id)
            
            # Validate
            if not name:
                messages.error(request, 'Product name is required.')
                return redirect('inventory:product_edit', pk=product.pk)
            
            if category.is_single_item:
                if not brand:
                    messages.error(request, 'Brand is required for single items.')
                    return redirect('inventory:product_edit', pk=product.pk)
                if not model:
                    messages.error(request, 'Model is required for single items.')
                    return redirect('inventory:product_edit', pk=product.pk)
                has_spec = ram or storage or color
                if not has_spec:
                    messages.error(request, 'At least one specification is required for single items.')
                    return redirect('inventory:product_edit', pk=product.pk)
            
            if buying_price <= 0 or selling_price <= 0:
                messages.error(request, 'Buying and selling prices must be greater than zero.')
                return redirect('inventory:product_edit', pk=product.pk)
            
            # Update product
            product.name = name
            product.category = category
            product.brand = brand
            product.model = model
            product.description = description
            product.buying_price = buying_price
            product.selling_price = selling_price
            product.best_price = best_price
            product.specifications = specifications
            product.reorder_level = reorder_level
            product.warranty_months = warranty_months
            product.is_active = is_active
            
            # Update bulk serial number if category is bulk
            if category.is_bulk_item and bulk_serial_number:
                product.bulk_serial_number = bulk_serial_number
            
            # Update supplier
            supplier_id = request.POST.get('supplier')
            if supplier_id:
                product.supplier = Supplier.objects.get(id=supplier_id)
            else:
                product.supplier = None
            
            # Handle image removal
            if request.POST.get('remove_image'):
                if product.image:
                    product.image.delete()
                    product.image = None
            
            # Handle new image upload
            if request.FILES.get('image'):
                if product.image:
                    product.image.delete()
                product.image = request.FILES['image']
            
            product.last_modified_by = request.user
            product.save()
            
            messages.success(request, f'Product "{product.name}" updated successfully.')
            return redirect('inventory:product_detail', pk=product.pk)
            
        except Category.DoesNotExist:
            messages.error(request, 'Selected category does not exist.')
            return redirect('inventory:product_edit', pk=product.pk)
        except Exception as e:
            messages.error(request, f'Error updating product: {str(e)}')
            return redirect('inventory:product_edit', pk=product.pk)
    
    # GET request - show form
    categories = Category.objects.filter(is_active=True)
    suppliers = Supplier.objects.filter(is_active=True)
    
    context = {
        'product': product,
        'categories': categories,
        'suppliers': suppliers,
    }
    return render(request, 'inventory/products/edit.html', context)

@login_required
def product_delete(request, pk):
    """Delete product SKU"""
    product = get_object_or_404(Product, pk=pk)
    
    if request.method == 'POST':
        product_name = product.name
        product.delete()
        messages.success(request, f'Product "{product_name}" deleted successfully.')
        return redirect('inventory:product_list')
    
    return render(request, 'inventory/products/delete.html', {'product': product})



# ===========================================
# ===========================================
# RESTOCK MANAGEMENT VIEW
# ===========================================

class ProductRestockView(LoginRequiredMixin, TemplateView):
    """View for restocking products - search first, then restock"""
    template_name = "inventory/products/restock.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .models import Category
        # Only show bulk item categories
        context['bulk_categories'] = Category.objects.filter(
            is_active=True, 
            item_type='bulk'
        )
        return context

@login_required
def restock_product(request, pk):
    """Mark product as restocked"""
    alert = get_object_or_404(StockAlert, pk=pk)
    if request.method == 'POST':
        # Handle restocking
        pass
    return render(request, 'inventory/stock/restock.html', {'alert': alert})

@login_required
@require_http_methods(["GET"])
def search_product_for_restock(request):
    """Search for a product by name, code, or SKU - only bulk items"""
    search_term = request.GET.get('search', '').strip()
    category_id = request.GET.get('category', '') 
    
    if not search_term:
        return JsonResponse({
            'success': False,
            'message': 'Please enter a product name, SKU code, brand, or model'
        }, status=400)
    
    try:
        # Search in multiple fields - only bulk items
        products = Product.objects.filter(
            Q(name__icontains=search_term) |
            Q(sku_code__icontains=search_term) |
            Q(brand__icontains=search_term) |
            Q(model__icontains=search_term),
            is_active=True,
            category__item_type='bulk'  # Only bulk items
        ).select_related('category')
        
        # Apply category filter if provided
        if category_id:
            products = products.filter(category_id=category_id)

        if not products.exists():
            return JsonResponse({
                'success': False,
                'message': f'No bulk items found matching "{search_term}"'
            }, status=404)
        
        # If multiple products found, return list
        if products.count() > 1:
            product_list = [{
                'id': p.id,
                'name': p.name,
                'display_name': p.display_name,
                'sku_code': p.sku_code,
                'brand': p.brand or 'N/A',
                'model': p.model or 'N/A',
                'category': p.category.name,
                'current_quantity': p.bulk_quantity,
                'buying_price': float(p.buying_price),
                'selling_price': float(p.selling_price),
                'reorder_level': p.reorder_level or 5,
                'is_single_item': False
            } for p in products[:10]]  # Limit to 10 results
            
            return JsonResponse({
                'success': True,
                'multiple': True,
                'products': product_list,
                'count': products.count()
            })
        
        # Single product found
        product = products.first()
        
        return JsonResponse({
            'success': True,
            'multiple': False,
            'product': {
                'id': product.id,
                'name': product.name,
                'display_name': product.display_name,
                'sku_code': product.sku_code,
                'brand': product.brand or 'N/A',
                'model': product.model or 'N/A',
                'category': product.category.name,
                'current_quantity': product.bulk_quantity,
                'buying_price': float(product.buying_price),
                'selling_price': float(product.selling_price),
                'reorder_level': product.reorder_level or 5,
                'is_single_item': False
            }
        })
    
    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'Search error: {str(e)}'
        }, status=500)

@login_required
@require_http_methods(["POST"])
def process_restock(request):
    """Process the restock operation for bulk items"""
    try:
        product_id = request.POST.get('product_id')
        quantity = int(request.POST.get('quantity', 0))
        buying_price = request.POST.get('buying_price', '').strip()
        selling_price = request.POST.get('selling_price', '').strip()
        notes = request.POST.get('notes', '').strip()
        
        if quantity <= 0:
            return JsonResponse({
                'success': False,
                'message': 'Quantity must be greater than 0'
            }, status=400)
        
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product_id, is_active=True)
            
            # Check if it's a bulk item
            if product.category.is_single_item:
                return JsonResponse({
                    'success': False,
                    'message': f'Cannot restock single items. "{product.name}" is a single item (IMEI/Serial tracked).'
                }, status=400)
            
            old_stock = product.bulk_quantity
            
            # Update bulk quantity
            product.bulk_quantity += quantity
            
            # Update prices if provided
            if buying_price:
                buying_price_decimal = Decimal(buying_price)
                if buying_price_decimal < 0:
                    return JsonResponse({'success': False, 'message': 'Buying price cannot be negative'}, status=400)
                product.buying_price = buying_price_decimal
            
            if selling_price:
                selling_price_decimal = Decimal(selling_price)
                if selling_price_decimal < 0:
                    return JsonResponse({'success': False, 'message': 'Selling price cannot be negative'}, status=400)
                product.selling_price = selling_price_decimal
            
            # Update last restocked timestamp
            product.last_restocked = timezone.now()
            product.last_modified_by = request.user
            product.save()
            
            # ============================================
            # CREATE STOCK ENTRY WITH SKU IN REFERENCE FOR BULK RESTOCK
            # ============================================
            # Reference ID format: SKU:FSL001-RESTOCK-20260510143025
            reference_id = f"SKU:{product.sku_code}-RESTOCK-{timezone.now().strftime('%Y%m%d%H%M%S')}"
            
            used_buying_price = Decimal(buying_price) if buying_price else product.buying_price
            stock_entry = StockEntry.objects.create(
                product_sku=product,
                quantity=quantity,
                entry_type='purchase',
                unit_price=used_buying_price,
                total_amount=used_buying_price * quantity,
                created_by=request.user,
                notes=notes or f"Restock by {request.user.username} - Added {quantity} units to SKU: {product.sku_code}",
                reference_id=reference_id
            )
            
            # Update product stock alert
            product.update_quantities()  # This will also trigger stock alert creation
            
            logger.info(f"✅ Restock completed: SKU:{product.sku_code} - Added {quantity} units. New stock: {product.bulk_quantity}")
        
        return JsonResponse({
            'success': True,
            'message': f'✅ Successfully added {quantity} unit(s) to {product.name}',
            'product': {
                'id': product.id,
                'name': product.name,
                'sku_code': product.sku_code,
                'old_stock': old_stock,
                'new_stock': product.bulk_quantity,
                'added_quantity': quantity,
                'buying_price': float(product.buying_price),
                'selling_price': float(product.selling_price),
            }
        })
    
    except Product.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Product not found'}, status=404)
    except ValueError as e:
        logger.error(f"Restock value error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Invalid input: {str(e)}'}, status=400)
    except Exception as e:
        logger.error(f"Restock error: {str(e)}")
        return JsonResponse({'success': False, 'message': f'Error: {str(e)}'}, status=500)


# ===========================================
# ===========================================
# SUPPLIER MANAGEMENT VIEW
# ===========================================
@login_required
def supplier_list(request):
    """List all suppliers"""
    suppliers = Supplier.objects.all()
    return render(request, 'inventory/suppliers/list.html', {'suppliers': suppliers})

@login_required
def supplier_add(request):
    """Add new supplier"""
    if request.method == 'POST':
        try:
            # Get data from form
            name = request.POST.get('name')
            contact_person = request.POST.get('contact_person', '')
            phone = request.POST.get('phone')
            email = request.POST.get('email', '')
            address = request.POST.get('address', '')
            tax_id = request.POST.get('tax_id', '')
            payment_terms = request.POST.get('payment_terms', '')
            is_active = request.POST.get('is_active') == 'on'
            
            # Validate required fields
            if not name:
                messages.error(request, 'Company name is required.')
                return render(request, 'inventory/suppliers/add.html')
            
            if not phone:
                messages.error(request, 'Phone number is required.')
                return render(request, 'inventory/suppliers/add.html')
            
            # Create supplier
            supplier = Supplier.objects.create(
                name=name,
                contact_person=contact_person,
                phone=phone,
                email=email,
                address=address,
                tax_id=tax_id,
                payment_terms=payment_terms,
                is_active=is_active
            )
            
            messages.success(request, f'Supplier "{name}" created successfully.')
            return redirect('inventory:supplier_list')
            
        except Exception as e:
            messages.error(request, f'Error creating supplier: {str(e)}')
            return render(request, 'inventory/suppliers/add.html')
    
    return render(request, 'inventory/suppliers/add.html')

@login_required
def supplier_edit(request, pk):
    """Edit supplier"""
    supplier = get_object_or_404(Supplier, pk=pk)
    
    if request.method == 'POST':
        try:
            # Get data from form
            supplier.name = request.POST.get('name')
            supplier.contact_person = request.POST.get('contact_person', '')
            supplier.phone = request.POST.get('phone')
            supplier.email = request.POST.get('email', '')
            supplier.address = request.POST.get('address', '')
            supplier.tax_id = request.POST.get('tax_id', '')
            supplier.payment_terms = request.POST.get('payment_terms', '')
            supplier.is_active = request.POST.get('is_active') == 'on'
            
            # Validate required fields
            if not supplier.name:
                messages.error(request, 'Company name is required.')
                return render(request, 'inventory/suppliers/edit.html', {'supplier': supplier})
            
            if not supplier.phone:
                messages.error(request, 'Phone number is required.')
                return render(request, 'inventory/suppliers/edit.html', {'supplier': supplier})
            
            # Save supplier
            supplier.save()
            
            messages.success(request, f'Supplier "{supplier.name}" updated successfully.')
            return redirect('inventory:supplier_list')
            
        except Exception as e:
            messages.error(request, f'Error updating supplier: {str(e)}')
            return render(request, 'inventory/suppliers/edit.html', {'supplier': supplier})
    
    context = {
        'supplier': supplier,
    }
    return render(request, 'inventory/suppliers/edit.html', context)

@login_required
def supplier_delete(request, pk):
    """Delete a supplier"""
    supplier = get_object_or_404(Supplier, pk=pk)
    
    if request.method == 'POST':
        supplier_name = supplier.name
        supplier.delete()
        messages.success(request, f'Supplier "{supplier_name}" deleted successfully.')
        return redirect('inventory:supplier_list')
    
    return render(request, 'inventory/suppliers/delete.html', {'supplier': supplier})


# ===========================================
# ===========================================
# STOCK MOVEMENTS VIEW
# ===========================================

@login_required
def stock_movements(request):
    """List all stock movements"""
    # Updated to use product_sku and product_unit instead of product
    entries = StockEntry.objects.select_related(
        'product_sku', 'product_unit', 'created_by'
    ).order_by('-created_at')
    
    # Apply filters
    entry_type = request.GET.get('type')
    if entry_type:
        entries = entries.filter(entry_type=entry_type)
    
    # Date filters
    date_from = request.GET.get('date_from')
    if date_from:
        entries = entries.filter(created_at__date__gte=date_from)
    
    date_to = request.GET.get('date_to')
    if date_to:
        entries = entries.filter(created_at__date__lte=date_to)
    
    # Search filter
    search = request.GET.get('search')
    if search:
        entries = entries.filter(
            Q(reference_id__icontains=search) |
            Q(notes__icontains=search) |
            Q(product_sku__sku_code__icontains=search) |
            Q(product_sku__name__icontains=search) |
            Q(product_unit__imei_number__icontains=search) |
            Q(product_unit__serial_number__icontains=search)
        )
    
    # Pagination
    paginator = Paginator(entries, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'entries': page_obj,
        'entry_types': StockEntry.ENTRY_TYPE_CHOICES,
    }
    return render(request, 'inventory/stock/movements.html', context)

@login_required
def stock_movement_detail(request, pk):
    """View details of a specific stock movement"""
    entry = get_object_or_404(
        StockEntry.objects.select_related(
            'product_sku', 'product_unit', 'created_by',
            'product_sku__category', 'product_unit__product'
        ), 
        pk=pk
    )
    
    # Get product display name
    if entry.product_sku:
        product_display = entry.product_sku.display_name
        product_type = 'Bulk Item'
    elif entry.product_unit:
        product_display = entry.product_unit.product.display_name
        product_type = 'Single Item'
    else:
        product_display = 'Unknown'
        product_type = 'Unknown'
    
    # Get related movements for the same product
    related_movements = StockEntry.objects.none()
    
    if entry.product_sku:
        related_movements = StockEntry.objects.filter(
            product_sku=entry.product_sku
        ).exclude(pk=pk).select_related('product_sku', 'created_by').order_by('-created_at')[:5]
    elif entry.product_unit:
        related_movements = StockEntry.objects.filter(
            product_unit=entry.product_unit
        ).exclude(pk=pk).select_related('product_unit', 'created_by').order_by('-created_at')[:5]
    
    context = {
        'entry': entry,
        'product_display': product_display,
        'product_type': product_type,
        'related_movements': related_movements,
    }
    return render(request, 'inventory/stock/movement_detail.html', context)

@login_required
def stock_entry_reverse(request, pk):
    """Reverse a stock entry"""
    entry = get_object_or_404(StockEntry, pk=pk)
    
    # Prevent reversing already reversed entries
    if entry.entry_type == 'reversal':
        messages.error(request, 'This entry is already a reversal and cannot be reversed again.')
        return redirect('inventory:stock_movements')
    
    if request.method == 'POST':
        with transaction.atomic():
            # Create reversal entry
            reversal = StockEntry.objects.create(
                product_sku=entry.product_sku,
                product_unit=entry.product_unit,
                quantity=-entry.quantity,
                entry_type='reversal',
                unit_price=entry.unit_price,
                total_amount=entry.total_amount,
                reference_id=f"REV-{entry.id}",
                notes=f"Reversal of entry #{entry.id} - {entry.notes or ''}",
                created_by=request.user
            )
            
            # Update product quantities based on reversal
            if entry.product_sku and entry.product_sku.category.is_bulk_item:
                # For bulk items, update bulk_quantity
                entry.product_sku.bulk_quantity -= entry.quantity
                entry.product_sku.save(update_fields=['bulk_quantity', 'updated_at'])
                logger.info(f"Reversed {entry.quantity} units for bulk item {entry.product_sku.sku_code}")
                
            elif entry.product_unit:
                # For single items, just change unit status back to available
                entry.product_unit.status = 'available'
                entry.product_unit.save(update_fields=['status', 'updated_at'])
                entry.product_unit.product.update_quantities()
                logger.info(f"Reversed unit {entry.product_unit.unique_identifier} back to available")
            
            messages.success(request, f'Entry #{entry.id} reversed successfully.')
            return redirect('inventory:stock_movements')
    
    # GET request - show confirmation page
    return render(request, 'inventory/stock/reverse.html', {'entry': entry})

@login_required
def stock_entry_add(request, product_id):
    """Add stock entry for a product"""
    product = get_object_or_404(Product, pk=product_id)
    
    if request.method == 'POST':
        try:
            entry_type = request.POST.get('entry_type')
            quantity = int(request.POST.get('quantity'))
            unit_price = request.POST.get('unit_price')
            reference_id = request.POST.get('reference_id', '')
            notes = request.POST.get('notes', '')
            
            # Handle unit addition for single items
            if product.category.is_single_item:
                # For single items, we need to add units individually
                # This should be handled by a separate unit addition process
                messages.error(request, 'Use "Add Units" button for single items.')
                return redirect('inventory:product_detail', pk=product.id)
            
            # For bulk items
            if entry_type == 'sale':
                quantity = -abs(quantity)  # Negative for stock out
            else:
                quantity = abs(quantity)   # Positive for stock in
            
            total_amount = abs(quantity) * Decimal(str(unit_price))
            
            # Create stock entry using product_sku (for bulk items)
            entry = StockEntry.objects.create(
                product_sku=product,  # Changed from 'product' to 'product_sku'
                quantity=quantity,
                entry_type=entry_type,
                unit_price=Decimal(str(unit_price)),
                total_amount=total_amount,
                reference_id=reference_id,
                notes=notes,
                created_by=request.user
            )
            
            # Update product bulk quantity
            if entry_type in ['purchase', 'adjustment']:
                product.bulk_quantity += abs(quantity)
            elif entry_type == 'sale':
                product.bulk_quantity -= abs(quantity)
            
            product.save(update_fields=['bulk_quantity', 'updated_at'])
            
            messages.success(request, f'Stock entry added successfully for {product.display_name}.')
            return redirect('inventory:product_detail', pk=product.id)
            
        except Exception as e:
            logger.error(f"Error adding stock entry: {str(e)}")
            messages.error(request, f'Error adding stock entry: {str(e)}')
            return render(request, 'inventory/stock/add_entry.html', {'product': product})
    
    # GET request - show form
    return render(request, 'inventory/stock/add_entry.html', {'product': product})

@login_required
def reverse_entry(request, pk):
    """Reverse a stock entry"""
    entry = get_object_or_404(StockEntry, pk=pk)
    
    if request.method == 'POST':
        with transaction.atomic():
            # Create reversal entry
            reversal = StockEntry.objects.create(
                product_sku=entry.product_sku,  # Changed from 'product'
                product_unit=entry.product_unit,
                quantity=-entry.quantity,
                entry_type='reversal',
                unit_price=entry.unit_price,
                total_amount=entry.total_amount,
                reference_id=f"REV-{entry.id}",
                notes=f"Reversal of entry #{entry.id}",
                created_by=request.user
            )
            
            # Update product quantities
            if entry.product_sku and entry.product_sku.category.is_bulk_item:
                # For bulk items, restore bulk quantity
                entry.product_sku.bulk_quantity -= entry.quantity
                entry.product_sku.save(update_fields=['bulk_quantity', 'updated_at'])
                logger.info(f"Reversed {entry.quantity} units for bulk item {entry.product_sku.sku_code}")
                
            elif entry.product_unit:
                # For single items, just change unit status back to available
                entry.product_unit.status = 'available'
                entry.product_unit.save(update_fields=['status', 'updated_at'])
                entry.product_unit.product.update_quantities()
                logger.info(f"Reversed unit {entry.product_unit.unique_identifier} back to available")
            
            messages.success(request, f'Entry #{entry.id} reversed successfully.')
            return redirect('inventory:stock_movements')
    
    return render(request, 'inventory/stock/reverse.html', {'entry': entry})



# ===========================================
# ===========================================
# ALERTS MANAGEMENT VIEW
# ===========================================

@login_required
def stock_alerts(request):
    """List all stock alerts with counts and dismissed alerts"""
    
    # Get page size from request, default to 20
    page_size = request.GET.get('page_size', '20')
    
    # Get ALL active alerts (unpaginated) - for filtering
    all_active_alerts = StockAlert.objects.select_related(
        'product', 
        'product__category',
        'dismissed_by'
    ).filter(
        is_active=True,
        is_dismissed=False,
        product__category__item_type='bulk'  # Only bulk items have alerts
    ).order_by(
        '-severity',
        'alert_type',
        'product__name'
    )
    
    # ============================================
    # PRE-FILTER FOR EACH TAB (BEFORE PAGINATION)
    # ============================================
    needs_reorder_alerts = all_active_alerts.filter(alert_type='needs_reorder')
    lowstock_alerts = all_active_alerts.filter(alert_type='lowstock')
    outofstock_alerts = all_active_alerts.filter(alert_type='outofstock')
    
    # ============================================
    # DAMAGED RETURNS
    # ============================================
    from .models import ReturnRequest
    from django.db.models import Sum
    from decimal import Decimal
    
    # Use refund_amount instead of loss_amount (loss_amount was removed)
    damaged_returns = ReturnRequest.objects.filter(
        status='damaged_loss'
    ).select_related('product', 'requested_by', 'approved_by').order_by('-processed_at')
    
    damaged_returns_count = damaged_returns.count()
    damaged_returns_loss = damaged_returns.aggregate(total=Sum('refund_amount'))['total'] or Decimal('0.00')
    
    # ============================================
    # DISMISSED ALERTS
    # ============================================
    dismissed_alerts = StockAlert.objects.select_related(
        'product',
        'product__category',
        'dismissed_by'
    ).filter(
        is_dismissed=True,
        product__category__item_type='bulk'
    ).order_by('-dismissed_at')[:50]
    
    dismissed_count = StockAlert.objects.filter(
        is_dismissed=True,
        product__category__item_type='bulk'
    ).count()
    
    # ============================================
    # COUNT STATS
    # ============================================
    alert_counts = {
        'needs_reorder': needs_reorder_alerts.count(),
        'lowstock': lowstock_alerts.count(),
        'outofstock': outofstock_alerts.count(),
        'damaged': damaged_returns_count,
        'total': all_active_alerts.count() + damaged_returns_count
    }
    
    # ============================================
    # PAGINATION - Only for the "All Alerts" tab
    # ============================================
    if page_size == 'all':
        paginator = Paginator(all_active_alerts, all_active_alerts.count()) if all_active_alerts.exists() else Paginator(all_active_alerts, 1)
    else:
        paginator = Paginator(all_active_alerts, int(page_size))
    
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    context = {
        # Paginated alerts (for All Alerts tab)
        'alerts': page_obj,
        
        # Pre-filtered alerts for each tab (unpaginated)
        'needs_reorder_alerts': needs_reorder_alerts,
        'lowstock_alerts': lowstock_alerts,
        'outofstock_alerts': outofstock_alerts,
        
        # Damaged returns
        'damaged_returns': damaged_returns,
        'damaged_returns_count': damaged_returns_count,
        'damaged_returns_loss': damaged_returns_loss,
        
        # Dismissed
        'dismissed_alerts': dismissed_alerts,
        'dismissed_count': dismissed_count,
        
        # Counts
        'alert_counts': alert_counts,
        
        # Pagination info
        'page_size': page_size,
        'total_alerts': all_active_alerts.count(),
        'page_obj': page_obj,
    }
    
    return render(request, 'inventory/stock/alerts_list.html', context)

@login_required
def dismiss_alert_page(request, pk):
    """Page for dismissing an alert"""
    alert = get_object_or_404(StockAlert, pk=pk)
    
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        
        # Update the alert fields directly
        alert.is_active = False
        alert.is_dismissed = True
        alert.dismissed_by = request.user
        alert.dismissed_at = timezone.now()
        alert.dismissed_reason = reason
        alert.save()
        
        messages.success(request, f'Alert for {alert.product.display_name} dismissed.')
        
        next_url = request.GET.get('next', 'inventory:stock_alerts')
        return redirect(next_url)
    
    context = {
        'alert': alert,
        'next': request.GET.get('next', 'inventory:stock_alerts'),
    }
    return render(request, 'inventory/stock/dismiss_alert.html', context)

@login_required
def alert_detail(request, pk):
    """View details of a specific alert"""
    alert = get_object_or_404(
        StockAlert.objects.select_related(
            'product', 
            'product__category',
            'dismissed_by'
        ),
        pk=pk
    )
    
    context = {
        'alert': alert,
        'page_title': f'Alert: {alert.product.display_name}'
    }
    
    return render(request, 'inventory/stock/alert_detail.html', context)

@login_required
def reactivate_alert(request, pk):
    """Reactivate a dismissed alert"""
    alert = get_object_or_404(StockAlert, pk=pk, is_dismissed=True)
    
    if request.method == 'POST':
        alert.reactivate()
        messages.success(request, f'Alert for {alert.product.display_name} reactivated.')
        return redirect('inventory:stock_alerts')
    
    return render(request, 'inventory/stock/reactivate_alert.html', {
        'alert': alert
    })

@login_required
def restock_alert_combined(request, pk):
    """Combined view for restocking from alert"""
    alert = get_object_or_404(StockAlert, pk=pk, is_active=True)
    product = alert.product
    
    # Get related alerts for this product
    related_alerts = StockAlert.objects.filter(
        product=alert.product,
        is_active=True,
        is_dismissed=False
    ).exclude(id=alert.id)[:5]
    
    if request.method == 'POST':
        try:
            # Get form data
            quantity = int(request.POST.get('quantity', 0))
            buying_price = request.POST.get('buying_price', '').strip()
            selling_price = request.POST.get('selling_price', '').strip()
            notes = request.POST.get('notes', '')
            auto_dismiss = request.POST.get('auto_dismiss') == 'on'
            
            if quantity <= 0:
                messages.error(request, 'Quantity must be greater than 0.')
                return redirect('inventory:restock_alert_combined', pk=alert.id)
            
            with transaction.atomic():
                # Update bulk quantity
                product.bulk_quantity += quantity
                
                # Update prices if provided
                if buying_price:
                    product.buying_price = Decimal(buying_price)
                if selling_price:
                    product.selling_price = Decimal(selling_price)
                
                product.last_restocked = timezone.now()
                product.save()
                
                # Create stock entry (using product_sku for bulk items)
                StockEntry.objects.create(
                    product_sku=product,
                    quantity=quantity,
                    entry_type='purchase',
                    unit_price=Decimal(buying_price) if buying_price else product.buying_price,
                    total_amount=(Decimal(buying_price) if buying_price else product.buying_price) * quantity,
                    reference_id=f"ALERT-{alert.id}",
                    notes=notes or f"Restocked from alert - {alert.get_alert_type_display()}",
                    created_by=request.user
                )
                
                # Auto-dismiss if enabled and stock is above threshold
                if auto_dismiss and product.bulk_quantity > alert.threshold:
                    # Dismiss the alert by updating fields directly
                    alert.is_active = False
                    alert.is_dismissed = True
                    alert.dismissed_by = request.user
                    alert.dismissed_at = timezone.now()
                    alert.dismissed_reason = f"Restocked with {quantity} units. New stock: {product.bulk_quantity}"
                    alert.save()
                    messages.info(request, 'Alert automatically dismissed.')
                
                messages.success(request, f'✅ Added {quantity} units. New stock: {product.bulk_quantity}')
            
            return redirect('inventory:stock_alerts')
            
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
            return redirect('inventory:restock_alert_combined', pk=alert.id)
    
    # GET request - show form
    context = {
        'alert': alert,
        'related_alerts': related_alerts,
        'product': product,
    }
    return render(request, 'inventory/stock/restock_alert.html', context)

@login_required
def export_alerts(request):
    """Export alerts to CSV"""
    import csv
    from django.http import HttpResponse
    
    # Create HttpResponse with CSV header
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="stock_alerts_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['SKU Code', 'Product Name', 'Category', 'Alert Type', 'Severity', 
                    'Current Stock', 'Threshold', 'Reorder Level', 'Last Alerted', 'Status'])
    
    alerts = StockAlert.objects.select_related('product', 'product__category').filter(is_active=True)
    
    for alert in alerts:
        writer.writerow([
            alert.product.sku_code,  # Use sku_code instead of product_code
            alert.product.display_name,
            alert.product.category.name if alert.product.category else '',
            alert.get_alert_type_display(),
            alert.get_severity_display(),
            alert.current_stock,
            alert.threshold,
            alert.reorder_level or '',
            alert.last_alerted.strftime('%Y-%m-%d %H:%M') if alert.last_alerted else '',
            'Active' if alert.is_active and not alert.is_dismissed else 'Dismissed'
        ])
    
    return response

@login_required
def dismiss_alert(request, pk):
    """Dismiss a stock alert"""
    alert = get_object_or_404(StockAlert, pk=pk)
    
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        
        # Update the alert fields directly (since there's no dismiss() method)
        alert.is_active = False
        alert.is_dismissed = True
        alert.dismissed_by = request.user
        alert.dismissed_at = timezone.now()
        alert.dismissed_reason = reason
        alert.save()
        
        messages.success(request, f'Alert for {alert.product.display_name} dismissed.')
        
        next_url = request.GET.get('next', 'inventory:stock_alerts')
        return redirect(next_url)
    
    # GET request - show confirmation page
    context = {
        'alert': alert,
        'next': request.GET.get('next', 'inventory:stock_alerts'),
    }
    return render(request, 'inventory/stock/dismiss_alert.html', context)

@login_required
def bulk_dismiss_alerts(request):
    """Dismiss multiple alerts at once"""
    if request.method == 'POST':
        alert_ids = request.POST.getlist('alert_ids')
        reason = request.POST.get('reason', 'Bulk dismiss')
        
        if alert_ids:
            alerts = StockAlert.objects.filter(id__in=alert_ids, is_active=True, is_dismissed=False)
            count = alerts.count()
            
            for alert in alerts:
                # Update each alert directly
                alert.is_active = False
                alert.is_dismissed = True
                alert.dismissed_by = request.user
                alert.dismissed_at = timezone.now()
                alert.dismissed_reason = reason
                alert.save()
            
            messages.success(request, f'Successfully dismissed {count} alerts.')
        else:
            messages.warning(request, 'No alerts selected.')
        
        return redirect('inventory:stock_alerts')
    
    # GET request - show selection page
    alerts = StockAlert.objects.filter(is_active=True, is_dismissed=False).select_related('product')
    
    return render(request, 'inventory/stock/bulk_dismiss.html', {
        'alerts': alerts
    })

@login_required
def product_reviews(request):
    """List all product reviews"""
    reviews = ProductReview.objects.select_related('product').order_by('-created_at')
    return render(request, 'inventory/reviews/list.html', {'reviews': reviews})

@login_required
def search_users(request):
    """AJAX endpoint to search users by username, email, or full name"""
    query = request.GET.get('q', '').strip()
    users = []
    
    if query and len(query) >= 2:
        users_qs = User.objects.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        ).filter(is_active=True)[:20]
        
        for user in users_qs:
            users.append({
                'id': user.id,
                'username': user.username,
                'full_name': user.get_full_name() or user.username,
                'email': user.email,
            })
    
    return JsonResponse(users, safe=False)

@login_required
def search_products_for_price_check(request):
    """API endpoint for price check - search products by SKU, code, or name"""
    from django.db.models import Q
    from decimal import Decimal
    
    query = request.GET.get('q', '').strip()
    
    if not query or len(query) < 2:
        return JsonResponse([], safe=False)
    
    try:
        # Search in multiple fields - USE CORRECT FIELD NAMES
        products = Product.objects.filter(
            Q(sku_code__icontains=query) |
            Q(name__icontains=query) |  # Use 'name' not 'display_name'
            Q(brand__icontains=query) |
            Q(model__icontains=query),
            is_active=True,
            is_discontinued=False
        ).select_related('category')[:20]
        
        results = []
        for product in products:
            # Calculate stock based on category
            if product.category and product.category.is_single_item:
                stock = product.available_quantity
            else:
                stock = product.bulk_quantity or 0
            
            # Handle best_price safely (might be None)
            best_price = None
            if hasattr(product, 'best_price') and product.best_price:
                best_price = float(product.best_price)
            
            results.append({
                'code': product.sku_code,
                'name': product.name,  # Use 'name' not 'display_name'
                'price': float(product.selling_price),
                'best_price': best_price,
                'stock': stock,
                'sku': product.sku_code,
                'is_single': product.category.is_single_item if product.category else False,
                'brand': product.brand or '',
                'category': product.category.name if product.category else '',
            })
        
        return JsonResponse(results, safe=False)
        
    except Exception as e:
        logger.error(f"Price check search error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def product_transfer_page(request):
    """Display transfer page with selected products"""
    # Get SKUs from query string
    skus_param = request.GET.get('skus', '')
    
    if not skus_param:
        messages.warning(request, 'No products selected for transfer.')
        return redirect('inventory:product_list')
    
    # Split SKUs (they come as comma-separated)
    sku_list = [sku.strip() for sku in skus_param.split(',') if sku.strip()]
    
    # Get products by SKU
    products = Product.objects.filter(
        sku_value__in=sku_list,
        is_active=True
    ).select_related('category', 'owner')
    
    # Filter products that belong to current user (or admin)
    is_admin = request.user.is_superuser or request.user.is_staff
    if is_admin:
        user_products = list(products)  # Admins can transfer any products
    else:
        user_products = [p for p in products if p.owner == request.user]
    
    if not user_products:
        messages.error(request, 'No valid products found to transfer.')
        return redirect('inventory:product_list')
    
    # Count single vs bulk items
    single_count = sum(1 for p in user_products if p.category.is_single_item)
    bulk_count = len(user_products) - single_count
    
    # Create SKUs string for form
    skus_string = '\n'.join([p.sku_value for p in user_products])
    
    context = {
        'selected_products': user_products,
        'single_count': single_count,
        'bulk_count': bulk_count,
        'skus_string': skus_string,
    }
    
    return render(request, 'inventory/products/transfer.html', context)

@login_required
def product_transfer(request):
    """Transfer multiple products from current user to another user"""
    if request.method == 'POST':
        try:
            # Get receiver user ID
            receiver_id = request.POST.get('receiver_id')
            if not receiver_id:
                messages.error(request, 'Please select a receiver user.')
                return redirect('inventory:product_list')
            
            # Get SKUs from textarea (one per line)
            skus_text = request.POST.get('skus', '')
            sku_list = [sku.strip() for sku in skus_text.split('\n') if sku.strip()]
            
            if not sku_list:
                messages.error(request, 'Please enter at least one SKU.')
                return redirect('inventory:product_list')
            
            # Get receiver user
            try:
                receiver = User.objects.get(id=receiver_id, is_active=True)
            except User.DoesNotExist:
                messages.error(request, 'Selected user does not exist.')
                return redirect('inventory:product_list')
            
            # Check if receiver is the same as sender
            if receiver.id == request.user.id:
                messages.error(request, 'You cannot transfer products to yourself.')
                return redirect('inventory:product_list')
            
            # Find products by SKU
            products_to_transfer = []
            not_found_skus = []
            not_owned_skus = []
            sold_skus = []
            out_of_stock_skus = []
            
            with transaction.atomic():
                for sku in sku_list:
                    try:
                        # Get product with related data
                        product = Product.objects.select_related('category', 'owner').get(
                            sku_value=sku,
                            is_active=True
                        )
                        
                        # Check if current user owns this product (or is admin)
                        is_admin = request.user.is_superuser or request.user.is_staff
                        if not is_admin and product.owner != request.user:
                            not_owned_skus.append(sku)
                            continue
                        
                        # ========================================
                        # SINGLE ITEM TRANSFER
                        # ========================================
                        if product.category.is_single_item:
                            if product.status == 'sold':
                                sold_skus.append(sku)
                                continue
                            
                            # For single items, quantity must be 1
                            if product.quantity != 1:
                                # This should never happen, but just in case
                                out_of_stock_skus.append(sku)
                                continue
                            
                            products_to_transfer.append({
                                'product': product,
                                'quantity': 1,
                                'is_single': True
                            })
                        
                        # ========================================
                        # BULK ITEM TRANSFER (Only full transfers allowed)
                        # ========================================
                        else:
                            current_qty = product.quantity or 0
                            
                            if current_qty == 0:
                                out_of_stock_skus.append(sku)
                                continue
                            
                            # Bulk items must be transferred fully
                            products_to_transfer.append({
                                'product': product,
                                'quantity': current_qty,
                                'is_single': False
                            })
                        
                    except Product.DoesNotExist:
                        not_found_skus.append(sku)
                
                # Show warnings for problematic SKUs
                if not_found_skus:
                    messages.warning(
                        request,
                        f'❌ SKUs not found: {", ".join(not_found_skus[:5])}' +
                        (f' and {len(not_found_skus)-5} more' if len(not_found_skus) > 5 else '')
                    )
                
                if not_owned_skus:
                    messages.warning(
                        request,
                        f'⛔ SKUs not owned by you: {", ".join(not_owned_skus[:5])}' +
                        (f' and {len(not_owned_skus)-5} more' if len(not_owned_skus) > 5 else '')
                    )
                
                if sold_skus:
                    messages.warning(
                        request,
                        f'💰 Sold items cannot be transferred: {", ".join(sold_skus[:5])}' +
                        (f' and {len(sold_skus)-5} more' if len(sold_skus) > 5 else '')
                    )
                
                if out_of_stock_skus:
                    messages.warning(
                        request,
                        f'📦 Out of stock items: {", ".join(out_of_stock_skus[:5])}' +
                        (f' and {len(out_of_stock_skus)-5} more' if len(out_of_stock_skus) > 5 else '')
                    )
                
                if not products_to_transfer:
                    messages.error(request, 'No valid products found to transfer.')
                    return redirect('inventory:product_list')
                
                # Process transfers
                transferred_count = 0
                transferred_products = []
                transferred_skus = []
                
                for item in products_to_transfer:
                    product = item['product']
                    old_owner = product.owner.username if product.owner else "FIELDMAX"
                    
                    # Transfer to new owner (ALLOWS RE-TRANSFER)
                    product.owner = receiver
                    product.save()
                    
                    # Log the transfer
                    logger.info(
                        f"[PRODUCT TRANSFER] {product.product_code} | "
                        f"{old_owner} → {receiver.username} | "
                        f"Type: {'Single' if item['is_single'] else 'Bulk'} | "
                        f"By: {request.user.username}"
                    )
                    
                    transferred_count += 1
                    transferred_products.append(product)
                    transferred_skus.append(product.sku_value)
                
                # Success message
                messages.success(
                    request,
                    f'✅ Successfully transferred {transferred_count} products to {receiver.get_full_name() or receiver.username}.'
                )
                
                # Show which SKUs were transferred
                if transferred_skus:
                    messages.info(
                        request,
                        f'📋 Transferred SKUs: {", ".join(transferred_skus[:5])}' +
                        (f' and {len(transferred_skus)-5} more' if len(transferred_skus) > 5 else '')
                    )
            
            return redirect('inventory:product_list')
            
        except Exception as e:
            logger.error(f"Error transferring products: {str(e)}")
            messages.error(request, f'Error transferring products: {str(e)}')
            return redirect('inventory:product_list')
    
    # GET request - redirect to product list
    return redirect('inventory:product_list')

@login_required
def return_product(request):
    """Search for product to return"""
    if request.method == 'POST':
        search_term = request.POST.get('search_term', '').strip()
        
        if not search_term:
            messages.error(request, 'Please enter ETR number, product code, or SKU.')
            return redirect('inventory:return_product')
        
        # Search by various identifiers
        product = None
        sale = None
        
        # Try to find by product code or SKU
        try:
            product = Product.objects.filter(
                Q(product_code__iexact=search_term) |
                Q(sku_value__iexact=search_term)
            ).first()
        except:
            pass
        
        # Try to find sale by ETR number or sale ID
        try:
            sale = Sale.objects.filter(
                Q(etr_receipt_number__iexact=search_term) |
                Q(sale_id__iexact=search_term)
            ).first()
        except:
            pass
        
        # If product found, get its latest sale
        sale_info = None
        if product:
            latest_sale_item = SaleItem.objects.filter(
                product=product,
                sale__is_reversed=False
            ).select_related('sale').order_by('-sale__sale_date').first()
            
            if latest_sale_item:
                sale_info = latest_sale_item.sale
        
        context = {
            'search_term': search_term,
            'product': product,
            'sale': sale or sale_info,
        }
        
        return render(request, 'inventory/returns/search_result.html', context)
    
    return render(request, 'inventory/returns/add.html')

@login_required
def return_submit(request):
    """Submit a return request"""
    print("=" * 50)
    print("RETURN SUBMIT VIEW CALLED")
    print(f"Method: {request.method}")
    print("=" * 50)
    
    if request.method == 'POST':
        print("POST data received:")
        for key, value in request.POST.items():
            print(f"  {key}: {value}")
        
        try:
            # Get basic required fields
            product_id = request.POST.get('product_id')
            reason = request.POST.get('reason')
            sale_id = request.POST.get('sale_id', '')  # Get the sale_id from form
            etr_number = request.POST.get('etr_number', '')  # Get ETR number
            quantity = request.POST.get('quantity', 1)
            refund_amount = request.POST.get('refund_amount', '')
            
            print(f"Product ID: {product_id}")
            print(f"Reason: {reason}")
            print(f"Sale ID: {sale_id}")  # Now captured
            print(f"ETR Number: {etr_number}")  # Now captured
            print(f"Quantity: {quantity}")
            
            if not product_id:
                messages.error(request, 'Product ID is required.')
                return redirect('inventory:return_product')
            
            if not reason:
                messages.error(request, 'Reason is required.')
                return redirect('inventory:return_product')
            
            # Get the product
            try:
                product = Product.objects.get(id=product_id)
                print(f"Product found: {product.product_code} - {product.display_name}")
            except Product.DoesNotExist:
                print(f"ERROR: Product with ID {product_id} not found")
                messages.error(request, 'Product not found.')
                return redirect('inventory:return_product')
            
            # Handle file uploads
            product_photo_1 = request.FILES.get('product_photo_1')
            product_photo_2 = request.FILES.get('product_photo_2')
            damage_photo = request.FILES.get('damage_photo')
            receipt_photo = request.FILES.get('receipt_photo')
            
            # Prepare return data with ALL fields
            return_data = {
                'product': product,
                'product_code': product.product_code,
                'product_name': product.display_name,
                'sku_value': product.sku_value,
                'quantity': int(quantity),
                'reason': reason,
                'reason_text': request.POST.get('reason_text', ''),
                'reported_condition': request.POST.get('reported_condition', 'good'),
                'refund_amount': Decimal(refund_amount) if refund_amount else product.selling_price,
                'etr_number': etr_number,  # Save ETR number
                'sale_id': sale_id,  # Save Sale ID - THIS IS KEY!
                'requested_by': request.user,
                'status': 'submitted',
                'verification_status': 'pending',
            }
            
            print(f"Return data prepared: {return_data}")
            
            # Create return request
            from inventory.models import ReturnRequest
            return_request = ReturnRequest.objects.create(**return_data)
            
            # Save photos if uploaded
            if product_photo_1:
                return_request.product_photo_1 = product_photo_1
            if product_photo_2:
                return_request.product_photo_2 = product_photo_2
            if damage_photo:
                return_request.damage_photo = damage_photo
            if receipt_photo:
                return_request.receipt_photo = receipt_photo
            
            return_request.save()
            
            print(f"✅ RETURN CREATED: ID={return_request.id}, Return ID={return_request.return_id}")
            print(f"✅ SALE ID SAVED: {return_request.sale_id}")
            
            messages.success(
                request, 
                f'Return request #{return_request.return_id} submitted successfully!'
            )
            
            return redirect('inventory:return_list')
            
        except Exception as e:
            print(f"❌ ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            messages.error(request, f'Error: {str(e)}')
            return redirect('inventory:return_product')
    
    print("Not a POST request")
    return redirect('inventory:return_product')

@login_required
def return_list(request):
    """List all return requests"""
    from django.core.paginator import Paginator
    
    returns = ReturnRequest.objects.all().select_related(
        'product', 'requested_by', 'verified_by', 'approved_by'
    ).order_by('-requested_at')
    
    # Filter by status
    status = request.GET.get('status')
    if status:
        returns = returns.filter(status=status)
    
    # Filter by date
    date_from = request.GET.get('date_from')
    if date_from:
        returns = returns.filter(requested_at__date__gte=date_from)
    
    date_to = request.GET.get('date_to')
    if date_to:
        returns = returns.filter(requested_at__date__lte=date_to)
    
    # Search
    search = request.GET.get('search')
    if search:
        returns = returns.filter(
            Q(return_id__icontains=search) |
            Q(product_name__icontains=search) |
            Q(product_code__icontains=search) |
            Q(sku_value__icontains=search)
        )
    
    # Pagination
    paginator = Paginator(returns, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Counts for stats
    total_count = ReturnRequest.objects.count()
    pending_verification_count = ReturnRequest.objects.filter(status='submitted').count()
    approved_count = ReturnRequest.objects.filter(status='approved').count()
    rejected_count = ReturnRequest.objects.filter(status='rejected').count()
    
    context = {
        'returns': page_obj,
        'status_choices': ReturnRequest.RETURN_STATUS_CHOICES,
        'total_count': total_count,
        'pending_verification_count': pending_verification_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
    }
    return render(request, 'inventory/returns/list.html', context)

@login_required
def return_detail(request, pk):
    """View return request details"""
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    context = {
        'return': return_request,
    }
    return render(request, 'inventory/returns/detail.html', context)

@login_required
def return_approve(request, pk):
    """Approve a return request (manager only)"""
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, 'You do not have permission to approve returns.')
        return redirect('inventory:return_list')
    
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'approve':
            return_request.approve(request.user)
            messages.success(request, f'Return #{return_request.return_id} approved.')
            
        elif action == 'reject':
            reason = request.POST.get('rejection_reason', '')
            return_request.reject(request.user, reason)
            messages.success(request, f'Return #{return_request.return_id} rejected.')
        
        return redirect('inventory:return_detail', pk=return_request.id)
    
    context = {
        'return': return_request,
    }
    return render(request, 'inventory/returns/approve.html', context)

@login_required
def return_process(request, pk):
    """Process an approved return (restock product or record as loss)"""
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, 'You do not have permission to process returns.')
        return redirect('inventory:return_list')
    
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    if return_request.status != 'approved':
        messages.error(request, 'Only approved returns can be processed.')
        return redirect('inventory:return_detail', pk=return_request.id)
    
    if request.method == 'POST':
        try:
            # Check if product is damaged
            product_condition = request.POST.get('product_condition', 'good')
            mark_as_damaged = (product_condition == 'damaged')
            
            # Process with damage flag
            return_request.process(request.user, mark_as_damaged=mark_as_damaged)
            
            if mark_as_damaged:
                loss_reason = request.POST.get('loss_reason', 'Not specified')
                messages.warning(
                    request, 
                    f'Return #{return_request.return_id} recorded as LOSS. '
                    f'Reason: {loss_reason}. Cost: KES {return_request.product.buying_price if return_request.product else return_request.refund_amount}'
                )
            else:
                messages.success(
                    request, 
                    f'Return #{return_request.return_id} processed successfully. Product restocked.'
                )
                
        except Exception as e:
            messages.error(request, f'Error processing return: {str(e)}')
        
        return redirect('inventory:return_detail', pk=return_request.id)
    
    context = {
        'return': return_request,
    }
    return render(request, 'inventory/returns/process.html', context)

@login_required
def return_search_api(request):
    """AJAX endpoint for searching by Sale ID or Product Code"""
    query = request.GET.get('q', '').strip()
    
    logger.info(f"🔍 Search API called with query: {query}")
    
    if len(query) < 2:
        return JsonResponse({'results': []})
    
    results = []
    
    # ============================================
    # CASE 1: Search by Sale ID (shows all products in that sale)
    # ============================================
    try:
        # Check if query looks like a Sale ID (starts with SALE- or contains numbers)
        sale = Sale.objects.filter(
            Q(sale_id__icontains=query) |
            Q(etr_receipt_number__icontains=query)
        ).first()
        
        if sale:
            logger.info(f"✅ Found sale: {sale.sale_id}")
            
            # Get all products from this sale
            sale_items = SaleItem.objects.filter(sale=sale).select_related('product')
            
            for item in sale_items:
                if item.product:
                    results.append({
                        'type': 'product_in_sale',
                        'id': item.product.id,
                        'sale_item_id': item.id,
                        'code': item.product.product_code,
                        'name': item.product.display_name,
                        'sku': item.product.sku_value or '',
                        'price': float(item.unit_price),
                        'sale_id': sale.sale_id,
                        'sale_date': sale.sale_date.strftime('%Y-%m-%d'),
                        'sale_time': sale.sale_date.strftime('%H:%M:%S'),
                        'customer': sale.buyer_name or 'Walk-in Customer',
                        'etr_number': sale.etr_receipt_number or '',
                        'quantity_sold': item.quantity,
                    })
    except Exception as e:
        logger.error(f"Error searching by Sale ID: {str(e)}")
    
    # ============================================
    # CASE 2: Search by Product Code (shows all sales where product was sold)
    # ============================================
    if len(results) == 0:
        try:
            # First find the product by code or SKU
            products = Product.objects.filter(
                Q(product_code__icontains=query) |
                Q(name__icontains=query) |
                Q(sku_value__icontains=query)
            )[:5]
            
            for product in products:
                # Find all sales where this product was sold
                sale_items = SaleItem.objects.filter(
                    product=product,
                    sale__is_reversed=False
                ).select_related('sale').order_by('-sale__sale_date')
                
                for item in sale_items:
                    results.append({
                        'type': 'sale_with_product',
                        'product_id': product.id,
                        'sale_item_id': item.id,
                        'product_code': product.product_code,
                        'product_name': product.display_name,
                        'product_sku': product.sku_value or '',
                        'product_price': float(item.unit_price),
                        'sale_id': item.sale.sale_id,
                        'sale_date': item.sale.sale_date.strftime('%Y-%m-%d'),
                        'sale_time': item.sale.sale_date.strftime('%H:%M:%S'),
                        'customer': item.sale.buyer_name or 'Walk-in Customer',
                        'etr_number': item.sale.etr_receipt_number or '',
                        'quantity_sold': item.quantity,
                    })
        except Exception as e:
            logger.error(f"Error searching by product: {str(e)}")
    
    logger.info(f"🔍 Search returned {len(results)} results")
    
    return JsonResponse({'results': results})

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)  # Manager only
def return_verify(request, pk):
    """Manager verification of returned product"""
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    if return_request.status != 'submitted':
        messages.error(request, 'This return is not pending verification.')
        return redirect('inventory:return_detail', pk=return_request.id)
    
    if request.method == 'POST':
        # Collect verification data
        verification_data = {
            'physical_product_seen': request.POST.get('physical_product_seen') == 'on',
            'serial_number_matches': request.POST.get('serial_number_matches') == 'on',
            'condition_matches_report': request.POST.get('condition_matches_report') == 'on',
            'accessories_present': request.POST.get('accessories_present') == 'on',
            'box_present': request.POST.get('box_present') == 'on',
            'receipt_present': request.POST.get('receipt_present') == 'on',
            'actual_sku': request.POST.get('actual_sku', ''),
            'actual_serial': request.POST.get('actual_serial', ''),
            'actual_condition': request.POST.get('actual_condition', ''),
            'notes': request.POST.get('verification_notes', ''),
        }
        
        # Handle photo uploads
        if request.FILES.get('product_photo_1'):
            return_request.product_photo_1 = request.FILES['product_photo_1']
        if request.FILES.get('product_photo_2'):
            return_request.product_photo_2 = request.FILES['product_photo_2']
        if request.FILES.get('product_photo_3'):
            return_request.product_photo_3 = request.FILES['product_photo_3']
        if request.FILES.get('damage_photo'):
            return_request.damage_photo = request.FILES['damage_photo']
        
        # Perform verification
        matches, issues = return_request.verify_product(request.user, verification_data)
        
        if matches:
            messages.success(
                request, 
                f'Product verified successfully. Return #{return_request.return_id} is now awaiting approval.'
            )
        else:
            messages.warning(
                request, 
                f'Product verification failed. Issues: {", ".join(issues)}'
            )
        
        return redirect('inventory:return_detail', pk=return_request.id)
    
    # GET request - show verification form
    from django.contrib.auth import get_user_model
    User = get_user_model()
    users = User.objects.filter(is_active=True).order_by('first_name', 'username')
    
    context = {
        'return': return_request,
        'users': users,  
    }
    return render(request, 'inventory/returns/verify.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def return_reverify(request, pk):
    """Reset verification status and allow re-verification with corrected info"""
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    if return_request.status != 'mismatch':
        messages.error(request, 'This return cannot be re-verified.')
        return redirect('inventory:return_detail', pk=return_request.pk)
    
    if request.method == 'POST':
        # Check if this is the form submission with corrected data
        if 'action' in request.POST and request.POST['action'] == 'reverify':
            try:
                # Collect verification data from form
                verification_data = {
                    'physical_product_seen': request.POST.get('physical_product_seen') == 'on',
                    'serial_number_matches': request.POST.get('serial_number_matches') == 'on',
                    'condition_matches_report': request.POST.get('condition_matches_report') == 'on',
                    'accessories_present': request.POST.get('accessories_present') == 'on',
                    'box_present': request.POST.get('box_present') == 'on',
                    'receipt_present': request.POST.get('receipt_present') == 'on',
                    'actual_sku': request.POST.get('actual_sku', '').strip(),
                    'actual_condition': request.POST.get('actual_condition', ''),
                    'notes': request.POST.get('verification_notes', ''),
                }
                
                # Handle photo uploads if any
                if request.FILES.get('product_photo_1'):
                    return_request.product_photo_1 = request.FILES['product_photo_1']
                if request.FILES.get('product_photo_2'):
                    return_request.product_photo_2 = request.FILES['product_photo_2']
                if request.FILES.get('product_photo_3'):
                    return_request.product_photo_3 = request.FILES['product_photo_3']
                if request.FILES.get('damage_photo'):
                    return_request.damage_photo = request.FILES['damage_photo']
                
                # Perform verification
                matches, issues = return_request.verify_product(request.user, verification_data)
                
                if matches:
                    messages.success(
                        request, 
                        f'Product verified successfully. Return #{return_request.return_id} is now awaiting approval.'
                    )
                else:
                    messages.warning(
                        request, 
                        f'Product verification failed again. Issues: {", ".join(issues)}'
                    )
                
                return redirect('inventory:return_detail', pk=return_request.pk)
                
            except Exception as e:
                messages.error(request, f'Error during re-verification: {str(e)}')
                return redirect('inventory:return_reverify', pk=return_request.pk)
        
        # This is the initial reset (GET would show form, POST here means they confirmed reset)
        else:
            # Reset verification status but keep the form data
            return_request.verification_status = 'pending'
            return_request.status = 'submitted'
            return_request.verified_by = None
            return_request.verified_at = None
            return_request.save()
            
            messages.info(request, f'Return #{return_request.return_id} is ready for re-verification.')
            return redirect('inventory:return_verify', pk=return_request.pk)
    
    # GET request - show the re-verification form
    context = {
        'return': return_request,
    }
    return render(request, 'inventory/returns/reverify.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def return_reject(request, pk):
    """Reject a return request (manager only)"""
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    # Check if return can be rejected (only verified or submitted status)
    if return_request.status not in ['submitted', 'verified']:
        messages.error(request, f'This return cannot be rejected. Current status: {return_request.get_status_display()}')
        return redirect('inventory:return_detail', pk=return_request.id)
    
    if request.method == 'POST':
        reason = request.POST.get('rejection_reason', '')
        
        if not reason:
            messages.error(request, 'Please provide a reason for rejection.')
            return render(request, 'inventory/returns/reject.html', {'return': return_request})
        
        # Update the return request
        return_request.status = 'rejected'
        return_request.verification_status = 'failed'
        return_request.approved_by = request.user
        return_request.approved_at = timezone.now()
        return_request.notes = f"Rejected: {reason}"
        return_request.save()
        
        # Log the rejection
        logger.info(
            f"[RETURN REJECTED] Return #{return_request.return_id} | "
            f"Product: {return_request.product_code} | "
            f"Rejected by: {request.user.username} | "
            f"Reason: {reason}"
        )
        
        messages.success(
            request, 
            f'Return #{return_request.return_id} has been rejected.'
        )
        return redirect('inventory:return_detail', pk=return_request.id)
    
    # GET request - show rejection form
    context = {
        'return': return_request,
    }
    return render(request, 'inventory/returns/reject.html', context)






# ===========================================
# DIAGNOSTIC VIEW - Check product quantities
# ===========================================
@login_required
@user_passes_test(lambda u: u.is_superuser)
def check_product_quantity(request, product_id):
    """Diagnostic view to check product quantity vs stock entries"""
    product = get_object_or_404(Product, pk=product_id)
    
    # Get all stock entries for this product
    entries = StockEntry.objects.filter(product=product).order_by('-created_at')
    
    # Calculate expected quantity
    calculated_total = entries.aggregate(total=Sum('quantity'))['total'] or 0
    
    # Check if they match
    matches = product.quantity == calculated_total
    
    # Prepare entry details
    entry_details = []
    for entry in entries:
        entry_details.append({
            'id': entry.id,
            'created_at': entry.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'entry_type': entry.entry_type,
            'quantity': entry.quantity,
            'reference': entry.reference_id,
            'created_by': entry.created_by.username if entry.created_by else 'System'
        })
    
    return JsonResponse({
        'product_id': product.id,
        'product_code': product.product_code,
        'product_name': product.display_name,
        'current_quantity': product.quantity,
        'calculated_quantity': calculated_total,
        'matches': matches,
        'entries_count': entries.count(),
        'entries': entry_details,
        'suggestion': 'Quantities match!' if matches else f'Expected {calculated_total} but have {product.quantity}'
    })

# ============================================
# RECORD LOSSES PAGE (Like Transfer Page)
# ============================================
@login_required
def record_losses_page(request):
    """Display record losses page with selected products"""
    # Get SKUs from query string (same as transfer)
    skus_param = request.GET.get('skus', '')
    
    if not skus_param:
        messages.warning(request, 'No products selected for loss recording.')
        return redirect('inventory:product_list')
    
    # Split SKUs (they come as comma-separated)
    sku_list = [sku.strip() for sku in skus_param.split(',') if sku.strip()]
    
    # Get products by SKU
    products = Product.objects.filter(
        sku_value__in=sku_list,
        is_active=True
    ).select_related('category', 'owner')
    
    # Filter products that are available (not already stolen/lost)
    available_products = [p for p in products if not p.is_stolen_or_lost]
    
    if not available_products:
        messages.error(request, 'No valid products found to record as loss.')
        return redirect('inventory:product_list')
    
    # Count single vs bulk items
    single_count = sum(1 for p in available_products if p.category.is_single_item)
    bulk_count = len(available_products) - single_count
    
    # Calculate total loss value
    total_loss_value = sum(p.buying_price for p in available_products)
    
    # Create SKUs string for form
    skus_string = '\n'.join([p.sku_value for p in available_products])
    
    context = {
        'selected_products': available_products,
        'single_count': single_count,
        'bulk_count': bulk_count,
        'skus_string': skus_string,
        'total_loss_value': total_loss_value,
    }
    
    return render(request, 'inventory/products/record_losses.html', context)

# ============================================
# PROCESS RECORD LOSSES (Like Transfer POST)
# ============================================
@login_required
def record_losses_process(request):
    """Process recording multiple products as stolen/lost"""
    if request.method == 'POST':
        try:
            # Get form data
            loss_type = request.POST.get('loss_type')  # stolen, lost, damaged
            police_report = request.POST.get('police_report', '')
            police_station = request.POST.get('police_station', '')
            notes = request.POST.get('notes', '')
            file_insurance = request.POST.get('file_insurance') == 'on'
            loss_date = request.POST.get('loss_date')
            
            # Get SKUs from textarea (one per line)
            skus_text = request.POST.get('skus', '')
            sku_list = [sku.strip() for sku in skus_text.split('\n') if sku.strip()]
            
            if not sku_list:
                messages.error(request, 'Please enter at least one SKU.')
                return redirect('inventory:product_list')
            
            if not loss_type:
                messages.error(request, 'Please select a loss type.')
                return redirect('inventory:product_list')
            
            # Find products by SKU
            products_to_mark = []
            not_found_skus = []
            already_marked_skus = []
            sold_skus = []
            
            with transaction.atomic():
                for sku in sku_list:
                    try:
                        # Get product with related data
                        product = Product.objects.select_related('category', 'owner').get(
                            sku_value=sku,
                            is_active=True
                        )
                        
                        # Check if already marked as stolen/lost
                        if product.is_stolen_or_lost:
                            already_marked_skus.append(sku)
                            continue
                        
                        # Check if product is sold (can't mark sold items as stolen)
                        if product.status == 'sold':
                            sold_skus.append(sku)
                            continue
                        
                        products_to_mark.append(product)
                        
                    except Product.DoesNotExist:
                        not_found_skus.append(sku)
                
                # Show warnings for problematic SKUs
                if not_found_skus:
                    messages.warning(
                        request,
                        f'❌ SKUs not found: {", ".join(not_found_skus[:5])}' +
                        (f' and {len(not_found_skus)-5} more' if len(not_found_skus) > 5 else '')
                    )
                
                if already_marked_skus:
                    messages.warning(
                        request,
                        f'⚠️ SKUs already marked as loss: {", ".join(already_marked_skus[:5])}' +
                        (f' and {len(already_marked_skus)-5} more' if len(already_marked_skus) > 5 else '')
                    )
                
                if sold_skus:
                    messages.warning(
                        request,
                        f'💰 Sold items cannot be marked as loss: {", ".join(sold_skus[:5])}' +
                        (f' and {len(sold_skus)-5} more' if len(sold_skus) > 5 else '')
                    )
                
                if not products_to_mark:
                    messages.error(request, 'No valid products found to mark as loss.')
                    return redirect('inventory:product_list')
                
                # Process each product
                processed_count = 0
                processed_skus = []
                
                for product in products_to_mark:
                    if loss_type == 'stolen':
                        product.mark_as_stolen(
                            reported_by=request.user,
                            police_report=police_report,
                            police_station=police_station,
                            notes=notes,
                            insurance_claim=file_insurance
                        )
                    elif loss_type == 'lost':
                        product.mark_as_lost(
                            reported_by=request.user,
                            notes=notes
                        )
                    elif loss_type == 'damaged':
                        product.write_off_as_damaged(
                            reported_by=request.user,
                            notes=notes
                        )
                    
                    # Update loss date if provided
                    if loss_date:
                        product.loss_reported_date = loss_date
                        product.save()
                    
                    processed_count += 1
                    processed_skus.append(product.sku_value)
                    
                    # Log the action
                    logger.warning(
                        f"[LOSS RECORDED] {product.product_code} | "
                        f"Type: {loss_type.upper()} | "
                        f"By: {request.user.username} | "
                        f"Police: {police_report or 'N/A'}"
                    )
                
                # Success message
                loss_type_display = {'stolen': 'STOLEN', 'lost': 'LOST', 'damaged': 'DAMAGED (Written Off)'}
                messages.error(
                    request,
                    f'⚠️ Successfully marked {processed_count} product(s) as {loss_type_display.get(loss_type, loss_type.upper())}.'
                )
                
                # Show which SKUs were processed
                if processed_skus:
                    messages.info(
                        request,
                        f'📋 Processed SKUs: {", ".join(processed_skus[:5])}' +
                        (f' and {len(processed_skus)-5} more' if len(processed_skus) > 5 else '')
                    )
            
            return redirect('inventory:stolen_products_list')
            
        except Exception as e:
            logger.error(f"Error recording losses: {str(e)}")
            messages.error(request, f'Error recording losses: {str(e)}')
            return redirect('inventory:product_list')
    
    # GET request - redirect to product list
    return redirect('inventory:product_list')

# ============================================
# PRODUCT-LEVEL REDIRECT VIEWS (for backward compatibility)
# ============================================

@login_required
@user_passes_test(is_manager_or_admin)
def report_product_stolen(request, product_id):
    """Redirect to first available unit of this product for stolen reporting"""
    product = get_object_or_404(Product, id=product_id)
    
    if not product.category.is_single_item:
        messages.error(request, 'Stolen/loss reporting is only available for single items (phones, electronics)')
        return redirect('inventory:product_detail', pk=product.id)
    
    # Get first available unit
    unit = product.units.filter(status='available').first()
    
    if not unit:
        messages.warning(request, f'No available units found for {product.sku_code}. All units are already sold, damaged, or reported.')
        return redirect('inventory:product_detail', pk=product.id)
    
    # Redirect to unit-level stolen reporting
    return redirect('inventory:report_unit_stolen', unit_id=unit.id)

@login_required
@user_passes_test(is_manager_or_admin)
def report_product_lost(request, product_id):
    """Redirect to first available unit of this product for lost reporting"""
    product = get_object_or_404(Product, id=product_id)
    
    if not product.category.is_single_item:
        messages.error(request, 'Stolen/loss reporting is only available for single items (phones, electronics)')
        return redirect('inventory:product_detail', pk=product.id)
    
    # Get first available unit
    unit = product.units.filter(status='available').first()
    
    if not unit:
        messages.warning(request, f'No available units found for {product.sku_code}')
        return redirect('inventory:product_detail', pk=product.id)
    
    # Redirect to unit-level lost reporting
    return redirect('inventory:report_unit_lost', unit_id=unit.id)

@login_required
@user_passes_test(is_manager_or_admin)
def mark_product_damaged(request, product_id):
    """Redirect to first available unit of this product for damage reporting"""
    product = get_object_or_404(Product, id=product_id)
    
    if not product.category.is_single_item:
        messages.error(request, 'Damage reporting is only available for single items (phones, electronics)')
        return redirect('inventory:product_detail', pk=product.id)
    
    # Get first available unit
    unit = product.units.filter(status='available').first()
    
    if not unit:
        messages.warning(request, f'No available units found for {product.sku_code}')
        return redirect('inventory:product_detail', pk=product.id)
    
    # Redirect to unit-level damage reporting
    return redirect('inventory:mark_unit_damaged', unit_id=unit.id)


# ============================================
# RECOVER STOLEN/LOST UNIT
# ============================================
@login_required
@user_passes_test(is_manager_or_admin)
def recover_unit(request, unit_id):
    """Mark a stolen/lost unit as recovered"""
    unit = get_object_or_404(ProductUnit, id=unit_id, status__in=['stolen', 'lost'])
    
    if request.method == 'POST':
        notes = request.POST.get('notes', '')
        condition = request.POST.get('condition', 'used_good')
        
        try:
            with transaction.atomic():
                unit.mark_as_recovered(
                    recovered_by=request.user,
                    notes=notes
                )
                
                # Update condition if needed
                unit.condition = condition
                unit.save()
                unit.product.update_quantities()
                
                messages.success(
                    request, 
                    f'✅ Unit {unit.unique_identifier} has been RECOVERED and returned to inventory!'
                )
                
                logger.info(f"Unit recovered: {unit.product.sku_code} - {unit.unique_identifier} by {request.user.username}")
                
                return redirect('inventory:product_detail', pk=unit.product.id)
                
        except Exception as e:
            messages.error(request, f'Error recovering unit: {str(e)}')
    
    context = {
        'unit': unit,
        'title': f'Recover Unit: {unit.unique_identifier}',
    }
    return render(request, 'inventory/units/recover_form.html', context)


# ============================================
# FILE INSURANCE CLAIM FOR UNIT
# ============================================
@login_required
@user_passes_test(is_manager_or_admin)
def file_unit_insurance_claim(request, unit_id):
    """File insurance claim for stolen/lost unit"""
    unit = get_object_or_404(
        ProductUnit, 
        id=unit_id, 
        status__in=['stolen', 'lost'],
        insurance_claim_filed=False
    )
    
    if request.method == 'POST':
        claim_number = request.POST.get('claim_number', '').strip()
        claim_amount = request.POST.get('claim_amount', '')
        
        if not claim_number:
            messages.error(request, 'Claim number is required')
            return redirect('inventory:file_unit_insurance_claim', unit_id=unit.id)
        
        try:
            unit.file_insurance_claim(claim_number, Decimal(claim_amount))
            
            messages.success(
                request, 
                f'📄 Insurance claim {claim_number} filed for KES {Decimal(claim_amount):,.2f}'
            )
            
            return redirect('inventory:product_detail', pk=unit.product.id)
            
        except Exception as e:
            messages.error(request, f'Error filing claim: {str(e)}')
    
    context = {
        'unit': unit,
        'title': f'File Insurance Claim: {unit.unique_identifier}',
        'suggested_amount': unit.effective_buying_price,
    }
    return render(request, 'inventory/units/file_insurance_form.html', context)


# ============================================
# LIST STOLEN/LOST UNITS
# ============================================
@login_required
def stolen_units_list(request):
    """Display all stolen and lost product units"""
    
    # Get filter parameters
    loss_type = request.GET.get('loss_type', '')
    insurance_status = request.GET.get('insurance', '')
    recovery_status = request.GET.get('recovery_status', '')
    search = request.GET.get('search', '')
    product_filter = request.GET.get('product', '')
    
    # Base queryset - get units that are stolen or lost
    units = ProductUnit.objects.filter(
        Q(status='stolen') | Q(status='lost')
    ).select_related(
        'product',
        'product__category',
        'loss_reported_by',
        'recovered_by',
        'created_by'
    ).order_by('-loss_reported_date', '-created_at')
    
    # Apply filters
    if loss_type:
        units = units.filter(loss_type=loss_type)
    
    if insurance_status == 'filed':
        units = units.filter(insurance_claim_filed=True)
    elif insurance_status == 'not_filed':
        units = units.filter(insurance_claim_filed=False)
    
    if recovery_status == 'recovered':
        units = units.exclude(recovered_date__isnull=True)
    elif recovery_status == 'unrecovered':
        units = units.filter(recovered_date__isnull=True)
    
    if product_filter:
        units = units.filter(product_id=product_filter)
    
    if search:
        units = units.filter(
            Q(imei_number__icontains=search) |
            Q(serial_number__icontains=search) |
            Q(product__sku_code__icontains=search) |
            Q(product__name__icontains=search) |
            Q(product__brand__icontains=search) |
            Q(product__model__icontains=search) |
            Q(police_report_number__icontains=search)
        )
    
    # Calculate totals
    total_stolen = units.filter(status='stolen').count()
    total_lost = units.filter(status='lost').count()
    total_recovered = units.exclude(recovered_date__isnull=True).count()
    total_unrecovered = (total_stolen + total_lost) - total_recovered
    
    # Calculate financial loss
    total_loss_value = units.filter(
        recovered_date__isnull=True
    ).aggregate(
        total=Sum(
            Case(
                When(unit_buying_price__isnull=False, then=F('unit_buying_price')),
                default=F('product__buying_price'),
                output_field=DecimalField()
            )
        )
    )['total'] or Decimal('0.00')
    
    insurance_recovered = units.filter(
        insurance_payout_amount__isnull=False
    ).aggregate(total=Sum('insurance_payout_amount'))['total'] or Decimal('0.00')
    
    net_loss = total_loss_value - insurance_recovered
    
    # Get distinct products for filter dropdown
    products_with_losses = Product.objects.filter(
        units__status__in=['stolen', 'lost']
    ).distinct()
    
    # Pagination
    paginator = Paginator(units, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'units': page_obj,
        'total_stolen': total_stolen,
        'total_lost': total_lost,
        'total_recovered': total_recovered,
        'total_unrecovered': total_unrecovered,
        'total_loss_value': total_loss_value,
        'insurance_recovered': insurance_recovered,
        'net_loss': net_loss,
        'products': products_with_losses,
        'current_filters': {
            'loss_type': loss_type,
            'insurance': insurance_status,
            'recovery_status': recovery_status,
            'product': product_filter,
            'search': search,
        },
        'title': 'Stolen & Lost Units',
    }
    return render(request, 'inventory/stolen_units_list.html', context)


# ============================================
# STOLEN UNITS REPORT (CSV Export)
# ============================================
@login_required
@user_passes_test(is_manager_or_admin)
def stolen_units_report(request):
    """Export stolen/lost units report as CSV"""
    
    units = ProductUnit.objects.filter(
        Q(status='stolen') | Q(status='lost')
    ).select_related('product', 'loss_reported_by', 'recovered_by')
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="stolen_units_{timezone.now().date()}.csv"'
    
    writer = csv.writer(response)
    
    # Write headers
    writer.writerow([
        'SKU Code', 'Product Name', 'Identifier Type', 'Identifier', 
        'Loss Type', 'Loss Date', 'Reported By', 'Police Report',
        'Buying Price', 'Selling Price', 'Insurance Filed', 'Insurance Claim #',
        'Insurance Payout', 'Recovered Date', 'Status'
    ])
    
    # Write data
    for unit in units:
        writer.writerow([
            unit.product.sku_code,
            unit.product.name,
            'IMEI' if unit.imei_number else 'Serial',
            unit.imei_number or unit.serial_number,
            unit.get_loss_type_display() if unit.loss_type else unit.get_status_display(),
            unit.loss_reported_date.strftime('%Y-%m-%d %H:%M') if unit.loss_reported_date else 'N/A',
            unit.loss_reported_by.username if unit.loss_reported_by else 'N/A',
            unit.police_report_number or 'N/A',
            f"KES {float(unit.effective_buying_price):,.2f}",
            f"KES {float(unit.effective_selling_price):,.2f}",
            'Yes' if unit.insurance_claim_filed else 'No',
            unit.insurance_claim_number or 'N/A',
            f"KES {float(unit.insurance_payout_amount):,.2f}" if unit.insurance_payout_amount else 'N/A',
            unit.recovered_date.strftime('%Y-%m-%d %H:%M') if unit.recovered_date else 'N/A',
            unit.get_status_display(),
        ])
    
    return response

@login_required
@user_passes_test(is_manager_or_admin)
def mark_unit_damaged(request, unit_id):
    """Mark a product unit as damaged"""
    unit = get_object_or_404(ProductUnit, id=unit_id, status='available')
    
    if request.method == 'POST':
        notes = request.POST.get('notes', '')
        
        try:
            unit.mark_as_damaged(notes=notes, reported_by=request.user)
            
            messages.warning(
                request, 
                f'💔 Unit {unit.unique_identifier} has been marked as DAMAGED.'
            )
            
            return redirect('inventory:product_units_list')
            
        except Exception as e:
            messages.error(request, f'Error marking unit as damaged: {str(e)}')
    
    context = {
        'unit': unit,
        'title': f'Mark as Damaged: {unit.unique_identifier}',
    }
    return render(request, 'inventory/units/mark_damaged_form.html', context)

@login_required
@user_passes_test(is_manager_or_admin)
def report_unit_stolen(request, unit_id):
    """Mark a product unit as stolen"""
    unit = get_object_or_404(ProductUnit, id=unit_id, status='available')
    
    if request.method == 'POST':
        police_report = request.POST.get('police_report', '')
        notes = request.POST.get('notes', '')
        file_insurance = request.POST.get('file_insurance') == 'on'
        insurance_amount = request.POST.get('insurance_amount', '')
        
        try:
            unit.mark_as_stolen(
                reported_by=request.user,
                police_report=police_report,
                notes=notes
            )
            
            if file_insurance and insurance_amount:
                claim_number = f"INS-{unit.product.sku_code}-{timezone.now().strftime('%Y%m%d%H%M%S')}"
                unit.file_insurance_claim(claim_number, Decimal(insurance_amount))
                messages.info(request, f'Insurance claim filed with number: {claim_number}')
            
            messages.error(
                request, 
                f'⚠️ Unit {unit.unique_identifier} has been marked as STOLEN.'
            )
            
            return redirect('inventory:product_units_list')
            
        except Exception as e:
            messages.error(request, f'Error marking unit as stolen: {str(e)}')
    
    context = {
        'unit': unit,
        'title': f'Report Stolen: {unit.unique_identifier}',
        'suggested_amount': unit.effective_buying_price,
    }
    return render(request, 'inventory/units/report_stolen_form.html', context)

@login_required
@user_passes_test(is_manager_or_admin)
def report_unit_lost(request, unit_id):
    """Mark a product unit as lost"""
    unit = get_object_or_404(ProductUnit, id=unit_id, status='available')
    
    if request.method == 'POST':
        notes = request.POST.get('notes', '')
        
        try:
            unit.status = 'lost'
            unit.loss_type = 'lost'
            unit.loss_reported_date = timezone.now()
            unit.loss_reported_by = request.user
            unit.loss_notes = notes
            unit.save()
            unit.product.update_quantities()
            
            messages.warning(
                request, 
                f'📍 Unit {unit.unique_identifier} has been marked as LOST.'
            )
            
            return redirect('inventory:product_units_list')
            
        except Exception as e:
            messages.error(request, f'Error marking unit as lost: {str(e)}')
    
    context = {
        'unit': unit,
        'title': f'Report Lost: {unit.unique_identifier}',
    }
    return render(request, 'inventory/units/report_lost_form.html', context)





# ============================================
# BULK REPORT STOLEN UNITS
# ============================================
@login_required
@user_passes_test(is_manager_or_admin)
def bulk_report_stolen_units(request):
    """Report multiple product units as stolen at once"""
    
    if request.method == 'POST':
        unit_ids = request.POST.getlist('unit_ids')
        police_report = request.POST.get('police_report', '')
        notes = request.POST.get('notes', '')
        
        if not unit_ids:
            messages.error(request, 'No units selected')
            return redirect('inventory:bulk_report_stolen_units')
        
        success_count = 0
        error_count = 0
        
        for unit_id in unit_ids:
            try:
                unit = ProductUnit.objects.get(id=unit_id, status='available')
                unit.mark_as_stolen(
                    reported_by=request.user,
                    police_report=police_report,
                    notes=notes
                )
                success_count += 1
            except Exception as e:
                error_count += 1
                logger.error(f"Error marking unit {unit_id} as stolen: {str(e)}")
        
        messages.error(
            request, 
            f'⚠️ {success_count} units marked as stolen. {error_count} failed.'
        )
        
        return redirect('inventory:stolen_units_list')
    
    # GET request - show unit selection (only single items)
    units = ProductUnit.objects.filter(
        status='available'
    ).select_related('product').order_by('product__sku_code')
    
    # Group by product for display
    products_dict = {}
    for unit in units:
        if unit.product.id not in products_dict:
            products_dict[unit.product.id] = {
                'product': unit.product,
                'units': []
            }
        products_dict[unit.product.id]['units'].append(unit)
    
    context = {
        'products_dict': products_dict,
        'title': 'Bulk Report Stolen Units',
    }
    return render(request, 'inventory/units/bulk_report_stolen.html', context)