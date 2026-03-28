from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum, Count, Avg, F
from django.http import JsonResponse
from django.utils import timezone
from decimal import Decimal
import json
import logging
import calendar
from datetime import timedelta, datetime, date
from sales.models import Sale, SaleItem, generate_custom_sale_id, Customer, LoyaltySettings, LoyaltyTransaction
from inventory.models import Product, StockEntry
from django.core.paginator import Paginator
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

# ============================================
# HELPER FUNCTIONS
# ============================================

def calculate_profit(sale):
    """Calculate profit for a single sale"""
    total_profit = Decimal('0.00')
    for item in sale.items.all():
        if item.product and item.product.buying_price:
            item_profit = (item.unit_price - item.product.buying_price) * item.quantity
            total_profit += item_profit
    return total_profit

def get_payment_method_color(method):
    """Get color for payment method"""
    colors = {
        'Cash': 'success',
        'M-Pesa': 'info',
        'Card': 'primary',
        'Points': 'warning',
        'Credit': 'danger',
    }
    return colors.get(method, 'secondary')

def get_day_suffix(day):
    """Get day suffix (st, nd, rd, th)"""
    if 11 <= day <= 13:
        return 'th'
    elif day % 10 == 1:
        return 'st'
    elif day % 10 == 2:
        return 'nd'
    elif day % 10 == 3:
        return 'rd'
    else:
        return 'th'

def get_items_by_date(date_str):
    """Get all items sold on a specific date"""
    try:
        # Parse the date string
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        start_date = timezone.make_aware(timezone.datetime.combine(date_obj, timezone.datetime.min.time()))
        end_date = timezone.make_aware(timezone.datetime.combine(date_obj, timezone.datetime.max.time()))
        
        # Get active sales (not reversed and not returned)
        from inventory.models import ReturnRequest
        
        # Get returned sale IDs
        returned_sale_ids = ReturnRequest.objects.filter(
            ~Q(status='rejected')
        ).exclude(
            Q(sale_id__isnull=True) | Q(sale_id='')
        ).values_list('sale_id', flat=True).distinct()
        
        # Get active sales for the date
        active_sales = Sale.objects.filter(
            sale_date__range=[start_date, end_date],
            is_reversed=False
        ).exclude(
            sale_id__in=returned_sale_ids
        )
        
        # Get all items from these sales
        items = SaleItem.objects.filter(
            sale__in=active_sales
        ).select_related('product', 'sale')
        
        # Aggregate items by product
        product_totals = {}
        for item in items:
            product_key = item.product_code or (item.product.product_code if item.product else 'unknown')
            if product_key not in product_totals:
                product_totals[product_key] = {
                    'product_name': item.product_name or (item.product.display_name if item.product else 'Unknown'),
                    'product_code': product_key,
                    'sku_value': item.sku_value or (item.product.sku_value if item.product else ''),
                    'barcode': item.product.barcode if item.product and item.product.barcode else '',
                    'total_quantity': 0,
                    'total_revenue': 0,
                    'total_profit': 0,
                    'sales_count': 0
                }
            
            product_totals[product_key]['total_quantity'] += item.quantity
            product_totals[product_key]['total_revenue'] += float(item.total_price)
            
            # Calculate profit
            if item.product and item.product.buying_price:
                profit = (item.unit_price - item.product.buying_price) * item.quantity
            else:
                profit = 0
            product_totals[product_key]['total_profit'] += float(profit)
            product_totals[product_key]['sales_count'] += 1
        
        # Convert to list and calculate margins
        items_list = []
        total_revenue = 0
        total_profit = 0
        total_items = 0
        
        for product_data in product_totals.values():
            margin = (product_data['total_profit'] / product_data['total_revenue'] * 100) if product_data['total_revenue'] > 0 else 0
            items_list.append({
                'product_name': product_data['product_name'],
                'product_code': product_data['product_code'],
                'sku_value': product_data['sku_value'],
                'barcode': product_data['barcode'],
                'total_quantity': product_data['total_quantity'],
                'total_revenue': product_data['total_revenue'],
                'total_profit': product_data['total_profit'],
                'margin': margin,
                'has_multiple_sales': product_data['sales_count'] > 1
            })
            total_revenue += product_data['total_revenue']
            total_profit += product_data['total_profit']
            total_items += product_data['total_quantity']
        
        # Sort by quantity sold (descending)
        items_list.sort(key=lambda x: x['total_quantity'], reverse=True)
        
        avg_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        return {
            'success': True,
            'items': items_list,
            'total_items': total_items,
            'total_revenue': total_revenue,
            'total_profit': total_profit,
            'avg_margin': avg_margin
        }
        
    except Exception as e:
        logger.error(f"Error getting items by date {date_str}: {str(e)}")
        return {
            'success': False,
            'message': str(e),
            'items': []
        }

def get_items_by_week(week_number):
    """Get all items sold during a specific week of the current month"""
    today = timezone.now().date()
    current_year = today.year
    current_month = today.month
    
    # Calculate week date range
    last_day = calendar.monthrange(current_year, current_month)[1]
    
    week_ranges = {
        1: (1, 7),
        2: (8, 14),
        3: (15, 21),
        4: (22, 28),
        5: (29, last_day)
    }
    
    if week_number not in week_ranges:
        return {
            'success': False,
            'message': 'Invalid week number',
            'items': []
        }
    
    start_day, end_day = week_ranges[week_number]
    end_day = min(end_day, last_day)
    
    start_date = date(current_year, current_month, start_day)
    end_date = date(current_year, current_month, end_day)
    
    start_date_aware = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end_date_aware = timezone.make_aware(timezone.datetime.combine(end_date, timezone.datetime.max.time()))
    
    # Get returned sale IDs
    from inventory.models import ReturnRequest
    
    returned_sale_ids = ReturnRequest.objects.filter(
        ~Q(status='rejected')
    ).exclude(
        Q(sale_id__isnull=True) | Q(sale_id='')
    ).values_list('sale_id', flat=True).distinct()
    
    # Get active sales for the week
    active_sales = Sale.objects.filter(
        sale_date__range=[start_date_aware, end_date_aware],
        is_reversed=False
    ).exclude(
        sale_id__in=returned_sale_ids
    )
    
    # Get all items from these sales
    items = SaleItem.objects.filter(
        sale__in=active_sales
    ).select_related('product', 'sale')
    
    # Aggregate items by product
    product_totals = {}
    for item in items:
        product_key = item.product_code or (item.product.product_code if item.product else 'unknown')
        if product_key not in product_totals:
            product_totals[product_key] = {
                'product_name': item.product_name or (item.product.display_name if item.product else 'Unknown'),
                'product_code': product_key,
                'sku_value': item.sku_value or (item.product.sku_value if item.product else ''),
                'barcode': item.product.barcode if item.product and item.product.barcode else '',
                'total_quantity': 0,
                'total_revenue': 0,
                'total_profit': 0,
                'sales_count': 0
            }
        
        product_totals[product_key]['total_quantity'] += item.quantity
        product_totals[product_key]['total_revenue'] += float(item.total_price)
        
        # Calculate profit
        if item.product and item.product.buying_price:
            profit = (item.unit_price - item.product.buying_price) * item.quantity
        else:
            profit = 0
        product_totals[product_key]['total_profit'] += float(profit)
        product_totals[product_key]['sales_count'] += 1
    
    # Convert to list and calculate margins
    items_list = []
    total_revenue = 0
    total_profit = 0
    total_items = 0
    
    for product_data in product_totals.values():
        margin = (product_data['total_profit'] / product_data['total_revenue'] * 100) if product_data['total_revenue'] > 0 else 0
        items_list.append({
            'product_name': product_data['product_name'],
            'product_code': product_data['product_code'],
            'sku_value': product_data['sku_value'],
            'barcode': product_data['barcode'],
            'total_quantity': product_data['total_quantity'],
            'total_revenue': product_data['total_revenue'],
            'total_profit': product_data['total_profit'],
            'margin': margin,
            'has_multiple_sales': product_data['sales_count'] > 1
        })
        total_revenue += product_data['total_revenue']
        total_profit += product_data['total_profit']
        total_items += product_data['total_quantity']
    
    # Sort by quantity sold (descending)
    items_list.sort(key=lambda x: x['total_quantity'], reverse=True)
    
    avg_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    return {
        'success': True,
        'items': items_list,
        'total_items': total_items,
        'total_revenue': total_revenue,
        'total_profit': total_profit,
        'avg_margin': avg_margin
    }

def get_items_by_month(month_name, year):
    """Get all items sold during a specific month"""
    try:
        # If month_name contains year, extract just the month name
        if ' ' in month_name:
            # This handles cases like "March 2026"
            month_name = month_name.split(' ')[0]
        
        # Convert month name to number
        month_number = datetime.strptime(month_name, '%B').month
        
        # Get date range for the month
        start_date = date(int(year), month_number, 1)
        last_day = calendar.monthrange(int(year), month_number)[1]
        end_date = date(int(year), month_number, last_day)
        
        start_date_aware = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
        end_date_aware = timezone.make_aware(timezone.datetime.combine(end_date, timezone.datetime.max.time()))
        
        # Get returned sale IDs
        from inventory.models import ReturnRequest
        
        returned_sale_ids = ReturnRequest.objects.filter(
            ~Q(status='rejected')
        ).exclude(
            Q(sale_id__isnull=True) | Q(sale_id='')
        ).values_list('sale_id', flat=True).distinct()
        
        # Get active sales for the month
        active_sales = Sale.objects.filter(
            sale_date__range=[start_date_aware, end_date_aware],
            is_reversed=False
        ).exclude(
            sale_id__in=returned_sale_ids
        )
        
        print(f"Month: {month_name} {year}, Date range: {start_date} to {end_date}")
        print(f"Found {active_sales.count()} sales")
        
        # Get all items from these sales
        items = SaleItem.objects.filter(
            sale__in=active_sales
        ).select_related('product', 'sale')
        
        print(f"Found {items.count()} items")
        
        # Aggregate items by product
        product_totals = {}
        for item in items:
            product_key = item.product_code or (item.product.product_code if item.product else 'unknown')
            if product_key not in product_totals:
                product_totals[product_key] = {
                    'product_name': item.product_name or (item.product.display_name if item.product else 'Unknown'),
                    'product_code': product_key,
                    'sku_value': item.sku_value or (item.product.sku_value if item.product else ''),
                    'barcode': item.product.barcode if item.product and item.product.barcode else '',
                    'total_quantity': 0,
                    'total_revenue': 0,
                    'total_profit': 0,
                    'sales_count': 0
                }
            
            product_totals[product_key]['total_quantity'] += item.quantity
            product_totals[product_key]['total_revenue'] += float(item.total_price)
            
            # Calculate profit
            if item.product and item.product.buying_price:
                profit = (item.unit_price - item.product.buying_price) * item.quantity
            else:
                profit = 0
            product_totals[product_key]['total_profit'] += float(profit)
            product_totals[product_key]['sales_count'] += 1
        
        # Convert to list and calculate margins
        items_list = []
        total_revenue = 0
        total_profit = 0
        total_items = 0
        
        for product_data in product_totals.values():
            margin = (product_data['total_profit'] / product_data['total_revenue'] * 100) if product_data['total_revenue'] > 0 else 0
            items_list.append({
                'product_name': product_data['product_name'],
                'product_code': product_data['product_code'],
                'sku_value': product_data['sku_value'],
                'barcode': product_data['barcode'],
                'total_quantity': product_data['total_quantity'],
                'total_revenue': product_data['total_revenue'],
                'total_profit': product_data['total_profit'],
                'margin': margin,
                'has_multiple_sales': product_data['sales_count'] > 1
            })
            total_revenue += product_data['total_revenue']
            total_profit += product_data['total_profit']
            total_items += product_data['total_quantity']
        
        # Sort by quantity sold (descending)
        items_list.sort(key=lambda x: x['total_quantity'], reverse=True)
        
        avg_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        return {
            'success': True,
            'items': items_list,
            'total_items': total_items,
            'total_revenue': total_revenue,
            'total_profit': total_profit,
            'avg_margin': avg_margin
        }
        
    except Exception as e:
        logger.error(f"Error getting items by month {month_name} {year}: {str(e)}")
        return {
            'success': False,
            'message': str(e),
            'items': []
        }

# ============================================
# MAIN SALES STATISTICS VIEW
# ============================================

@login_required
def sales_statistics(request):
    """Sales statistics dashboard"""
    
    # Date ranges
    today = timezone.now().date()
    start_of_day = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
    end_of_day = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.max.time()))
    
    start_of_week = timezone.make_aware(timezone.datetime.combine(today - timedelta(days=today.weekday()), timezone.datetime.min.time()))
    start_of_month = timezone.make_aware(timezone.datetime.combine(today.replace(day=1), timezone.datetime.min.time()))
    start_of_year = timezone.make_aware(timezone.datetime.combine(today.replace(month=1, day=1), timezone.datetime.min.time()))
    
    # ============================================
    # Get IDs of sales that have been returned
    # ============================================
    from inventory.models import ReturnRequest
    
    # Get sale_ids from return requests that are not rejected
    returned_sale_ids = ReturnRequest.objects.filter(
        ~Q(status='rejected')
    ).exclude(
        Q(sale_id__isnull=True) | Q(sale_id='')
    ).values_list('sale_id', flat=True).distinct()
    
    # ============================================
    # Base queryset - exclude reversed AND returned sales
    # ============================================
    active_sales_qs = Sale.objects.filter(
        is_reversed=False
    ).exclude(
        sale_id__in=returned_sale_ids
    )
    
    all_sales_qs = Sale.objects.all()
    
    # ============================================
    # OVERVIEW STATISTICS WITH PROFITS
    # ============================================
    
    total_sales = active_sales_qs.count()
    total_revenue = active_sales_qs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_items_sold = SaleItem.objects.filter(
        sale__is_reversed=False,
        sale__sale_id__in=active_sales_qs.values('sale_id')
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    total_profit = Decimal('0.00')
    for sale in active_sales_qs.select_related().all():
        total_profit += calculate_profit(sale)
    
    profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    # Today's sales
    today_sales = active_sales_qs.filter(sale_date__range=[start_of_day, end_of_day])
    today_count = today_sales.count()
    today_revenue = today_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    today_profit = Decimal('0.00')
    for sale in today_sales.select_related().all():
        today_profit += calculate_profit(sale)
    
    # This week's sales
    week_sales = active_sales_qs.filter(sale_date__gte=start_of_week)
    week_count = week_sales.count()
    week_revenue = week_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    week_profit = Decimal('0.00')
    for sale in week_sales.select_related().all():
        week_profit += calculate_profit(sale)
    
    # This month's sales
    month_sales = active_sales_qs.filter(sale_date__gte=start_of_month)
    month_count = month_sales.count()
    month_revenue = month_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    month_profit = Decimal('0.00')
    for sale in month_sales.select_related().all():
        month_profit += calculate_profit(sale)
    
    # This year's sales
    year_sales = active_sales_qs.filter(sale_date__gte=start_of_year)
    year_count = year_sales.count()
    year_revenue = year_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    year_profit = Decimal('0.00')
    for sale in year_sales.select_related().all():
        year_profit += calculate_profit(sale)
    
    # Average values
    avg_transaction_value = total_revenue / total_sales if total_sales > 0 else 0
    avg_items_per_sale = total_items_sold / total_sales if total_sales > 0 else 0
    avg_profit_per_sale = total_profit / total_sales if total_sales > 0 else 0
    
    # ============================================
    # DAILY BREAKDOWN
    # ============================================
    daily_sales_breakdown = []
    for i in range(7):
        day = start_of_week.date() + timedelta(days=i)
        day_start = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))
        day_end = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.max.time()))
        
        day_sales = active_sales_qs.filter(sale_date__range=[day_start, day_end])
        day_revenue = day_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        day_count = day_sales.count()
        
        day_profit = Decimal('0.00')
        for sale in day_sales.select_related().all():
            day_profit += calculate_profit(sale)
        
        daily_sales_breakdown.append({
            'day': day.strftime('%A'),
            'date': day.strftime('%Y-%m-%d'),
            'revenue': day_revenue,
            'profit': day_profit,
            'margin': (day_profit / day_revenue * 100) if day_revenue > 0 else 0,
            'count': day_count
        })

    daily_totals = {
        'count': sum(day['count'] for day in daily_sales_breakdown),
        'revenue': sum(day['revenue'] for day in daily_sales_breakdown),
        'profit': sum(day['profit'] for day in daily_sales_breakdown),
        'avg_margin': sum(day['margin'] for day in daily_sales_breakdown) / len(daily_sales_breakdown) if daily_sales_breakdown else 0,
    }
    
    # ============================================
    # WEEKLY BREAKDOWN
    # ============================================
    current_year = today.year
    current_month = today.month
    last_day = calendar.monthrange(current_year, current_month)[1]
    
    weekly_ranges = [(1, 7), (8, 14), (15, 21), (22, 28), (29, last_day)]
    weekly_sales_breakdown = []
    
    for week_num, (start_day, end_day) in enumerate(weekly_ranges, 1):
        if start_day > last_day:
            continue
            
        end_day = min(end_day, last_day)
        week_start = date(current_year, current_month, start_day)
        week_end = date(current_year, current_month, end_day)
        
        week_start_aware = timezone.make_aware(timezone.datetime.combine(week_start, timezone.datetime.min.time()))
        week_end_aware = timezone.make_aware(timezone.datetime.combine(week_end, timezone.datetime.max.time()))
        
        week_sales = active_sales_qs.filter(sale_date__range=[week_start_aware, week_end_aware])
        week_revenue = week_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        week_count = week_sales.count()
        
        week_profit = Decimal('0.00')
        for sale in week_sales.select_related().all():
            week_profit += calculate_profit(sale)
        
        month_name = week_start.strftime('%b')
        date_range = f"{month_name} {start_day}{get_day_suffix(start_day)} - {month_name} {end_day}{get_day_suffix(end_day)}"
        
        weekly_sales_breakdown.append({
            'week_number': week_num,
            'week_range': date_range,
            'revenue': week_revenue,
            'profit': week_profit,
            'margin': (week_profit / week_revenue * 100) if week_revenue > 0 else 0,
            'count': week_count
        })
    
    # ============================================
    # MONTHLY BREAKDOWN
    # ============================================
    monthly_sales_breakdown = []
    for i in range(11, -1, -1):
        month_date = today - timedelta(days=30*i)
        month_start = date(month_date.year, month_date.month, 1)
        month_end = date(month_date.year, month_date.month, 
                        calendar.monthrange(month_date.year, month_date.month)[1])
        
        month_start_aware = timezone.make_aware(timezone.datetime.combine(month_start, timezone.datetime.min.time()))
        month_end_aware = timezone.make_aware(timezone.datetime.combine(month_end, timezone.datetime.max.time()))
        
        month_sales = active_sales_qs.filter(sale_date__range=[month_start_aware, month_end_aware])
        month_revenue = month_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        month_count = month_sales.count()
        
        month_profit = Decimal('0.00')
        for sale in month_sales.select_related().all():
            month_profit += calculate_profit(sale)
        
        monthly_sales_breakdown.append({
            'month': month_start.strftime('%B %Y'),
            'month_short': month_start.strftime('%b %Y'),
            'revenue': month_revenue,
            'profit': month_profit,
            'margin': (month_profit / month_revenue * 100) if month_revenue > 0 else 0,
            'count': month_count,
            'year': month_date.year,
            'month_name': month_start.strftime('%B')
        })
    
    # ============================================
    # RECENT SALES
    # ============================================
    recent_sales = active_sales_qs.order_by('-sale_date')[:20]
    for sale in recent_sales:
        sale.items_count = SaleItem.objects.filter(sale=sale).count()
    
    # ============================================
    # TOP PRODUCTS
    # ============================================
    top_products = []
    product_data = SaleItem.objects.filter(
        sale__is_reversed=False,
        sale__sale_id__in=active_sales_qs.values('sale_id')
    ).select_related('product').values(
        'product_code', 'product_name', 'product__buying_price'
    ).annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('total_price'),
        avg_price=Avg('unit_price')
    ).order_by('-total_quantity')[:10]
    
    for item in product_data:
        buying_price = item.get('product__buying_price') or 0
        profit_per_unit = item['avg_price'] - buying_price if buying_price else 0
        total_profit = profit_per_unit * item['total_quantity']
        
        top_products.append({
            'product_code': item['product_code'],
            'product_name': item['product_name'],
            'total_quantity': item['total_quantity'],
            'total_revenue': item['total_revenue'],
            'total_profit': total_profit,
            'margin': (total_profit / item['total_revenue'] * 100) if item['total_revenue'] > 0 else 0
        })
    
    # ============================================
    # TOP SELLERS
    # ============================================
    top_sellers = []
    sellers = User.objects.filter(
        sales_made__is_reversed=False,
        sales_made__sale_id__in=active_sales_qs.values('sale_id')
    ).annotate(
        sales_count=Count('sales_made'),
        total_revenue=Sum('sales_made__total_amount')
    ).order_by('-total_revenue')[:10]
    
    for seller in sellers:
        seller_sales = active_sales_qs.filter(seller=seller)
        seller_profit = Decimal('0.00')
        for sale in seller_sales.select_related().all():
            seller_profit += calculate_profit(sale)
        
        top_sellers.append({
            'id': seller.id,
            'username': seller.username,
            'first_name': seller.first_name,
            'last_name': seller.last_name,
            'get_full_name': seller.get_full_name(),
            'sales_count': seller.sales_count,
            'total_revenue': seller.total_revenue,
            'total_profit': seller_profit,
            'margin': (seller_profit / seller.total_revenue * 100) if seller.total_revenue > 0 else 0
        })
    
    # ============================================
    # PAYMENT METHODS
    # ============================================
    payment_methods = []
    for method, _ in Sale._meta.get_field('payment_method').choices:
        method_sales = active_sales_qs.filter(payment_method=method)
        revenue = method_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        payment_methods.append({
            'name': method,
            'count': method_sales.count(),
            'revenue': revenue,
            'percentage': (revenue / total_revenue * 100) if total_revenue > 0 else 0,
            'color': get_payment_method_color(method)
        })
    
    # ============================================
    # DAILY SALES CHART DATA
    # ============================================
    daily_sales = []
    for i in range(30, 0, -1):
        day = today - timedelta(days=i)
        day_start = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))
        day_end = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.max.time()))
        
        day_sales = active_sales_qs.filter(sale_date__range=[day_start, day_end])
        day_revenue = day_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        daily_sales.append({
            'date': day.strftime('%Y-%m-%d'),
            'display_date': day.strftime('%d %b'),
            'revenue': float(day_revenue),
            'count': day_sales.count()
        })
    
    # ============================================
    # HOURLY SALES
    # ============================================
    hourly_sales = []
    for hour in range(7, 22):
        hour_sales = active_sales_qs.filter(
            sale_date__hour=hour,
            sale_date__date=today
        )
        hour_revenue = hour_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        hourly_sales.append({
            'hour': f"{hour:02d}:00",
            'revenue': float(hour_revenue),
            'count': hour_sales.count()
        })
    
    # ============================================
    # CONTEXT
    # ============================================
    context = {
        'total_sales': total_sales,
        'total_revenue': total_revenue,
        'total_profit': total_profit,
        'profit_margin': profit_margin,
        'total_items_sold': total_items_sold,
        'avg_transaction_value': avg_transaction_value,
        'avg_profit_per_sale': avg_profit_per_sale,
        'avg_items_per_sale': avg_items_per_sale,
        
        'today_count': today_count,
        'today_revenue': today_revenue,
        'today_profit': today_profit,
        'week_count': week_count,
        'week_revenue': week_revenue,
        'week_profit': week_profit,
        'month_count': month_count,
        'month_revenue': month_revenue,
        'month_profit': month_profit,
        'year_count': year_count,
        'year_revenue': year_revenue,
        'year_profit': year_profit,
        
        'recent_sales': recent_sales,
        
        'daily_sales_breakdown': daily_sales_breakdown,
        'weekly_sales_breakdown': weekly_sales_breakdown,
        'monthly_sales_breakdown': monthly_sales_breakdown,
        
        'top_products': top_products,
        'top_sellers': top_sellers,
        'payment_methods': payment_methods,
        
        'daily_sales': daily_sales,
        'daily_totals': daily_totals,
        'hourly_sales': hourly_sales,
        
        'credit_count': 0,
        'credit_revenue': 0,
        'credit_percentage': 0,
        
        'etr_processed': 0,
        'etr_pending': 0,
        'etr_failed': 0,
        
        'reversed_count': 0,
        'reversed_amount': 0,
        'reversal_percentage': 0,
        
        'total_returns': 0,
        'total_refund_amount': 0,
        'returns_by_status': [],
        
        'damaged_returns_count': 0,
        'damaged_returns_value': 0,
        'damaged_returns_cost': 0,
        
        'pending_returns_count': 0,
        'pending_returns_value': 0,
        'pending_verification_count': 0,
        'pending_verification_value': 0,
        'pending_approval_count': 0,
        'pending_approval_value': 0,
        
        'approved_returns_count': 0,
        'approved_returns_value': 0,
        'processed_returns_count': 0,
        'processed_returns_value': 0,
        'rejected_returns_count': 0,
        'rejected_returns_value': 0,
        'mismatch_returns_count': 0,
        'mismatch_returns_value': 0,
        
        'total_original_sales': all_sales_qs.count(),
        'total_original_value': all_sales_qs.aggregate(total=Sum('total_amount'))['total'] or 0,
        'returns_with_sale': 0,
        'active_sales_count': total_sales,
        'active_sales_value': total_revenue,
    }
    
    return render(request, 'sales/statistics.html', context)

# ============================================
# PERIOD DETAILS VIEW
# ============================================

@login_required
def period_details(request):
    """Display items sold during a specific period"""
    period_type = request.GET.get('type')
    context = {}
    
    if period_type == 'day':
        date = request.GET.get('date')
        context['period_title'] = f"Sales for {date}"
        result = get_items_by_date(date)
        context['items'] = result.get('items', [])
        context['total_items'] = result.get('total_items', 0)
        context['total_revenue'] = result.get('total_revenue', 0)
        context['total_profit'] = result.get('total_profit', 0)
        context['avg_margin'] = result.get('avg_margin', 0)
        
    elif period_type == 'week':
        week = request.GET.get('week')
        week_range = request.GET.get('range')
        context['period_title'] = f"Sales for Week {week}: {week_range}"
        result = get_items_by_week(int(week))
        context['items'] = result.get('items', [])
        context['total_items'] = result.get('total_items', 0)
        context['total_revenue'] = result.get('total_revenue', 0)
        context['total_profit'] = result.get('total_profit', 0)
        context['avg_margin'] = result.get('avg_margin', 0)
        
    elif period_type == 'month':
        month = request.GET.get('month')
        year = request.GET.get('year')
        context['period_title'] = f"Sales for {month} {year}"
        result = get_items_by_month(month, year)
        context['items'] = result.get('items', [])
        context['total_items'] = result.get('total_items', 0)
        context['total_revenue'] = result.get('total_revenue', 0)
        context['total_profit'] = result.get('total_profit', 0)
        context['avg_margin'] = result.get('avg_margin', 0)
    
    return render(request, 'sales/period_details.html', context)

# ============================================
# API ENDPOINTS
# ============================================

@login_required
def items_by_date_api(request):
    """API endpoint to get items by date"""
    date = request.GET.get('date')
    if not date:
        return JsonResponse({'success': False, 'message': 'Date parameter required'})
    
    result = get_items_by_date(date)
    return JsonResponse(result)

@login_required
def items_by_week_api(request):
    """API endpoint to get items by week"""
    week = request.GET.get('week')
    if not week:
        return JsonResponse({'success': False, 'message': 'Week parameter required'})
    
    result = get_items_by_week(int(week))
    return JsonResponse(result)

@login_required
def items_by_month_api(request):
    """API endpoint to get items by month"""
    month = request.GET.get('month')
    year = request.GET.get('year')
    if not month or not year:
        return JsonResponse({'success': False, 'message': 'Month and year parameters required'})
    
    result = get_items_by_month(month, year)
    return JsonResponse(result)

@login_required
def sale_details_api(request, sale_id):
    """API endpoint to get sale details with items"""
    try:
        sale = Sale.objects.get(sale_id=sale_id)
        items = SaleItem.objects.filter(sale=sale).select_related('product')
        
        total_profit = Decimal('0.00')
        for item in items:
            if item.product and item.product.buying_price:
                profit = (item.unit_price - item.product.buying_price) * item.quantity
                total_profit += profit
        
        sale_data = {
            'success': True,
            'sale': {
                'id': sale.id,
                'sale_id': sale.sale_id,
                'created_at': sale.sale_date.strftime('%Y-%m-%d %H:%M:%S'),
                'customer_name': sale.buyer_name or 'Walk-in Customer',
                'seller_name': sale.seller.get_full_name() if sale.seller else sale.seller.username,
                'payment_method': sale.payment_method,
                'status': 'completed' if not sale.is_reversed else 'reversed',
                'notes': '',
                'subtotal': float(sale.subtotal),
                'discount': 0,
                'total_amount': float(sale.total_amount),
                'total_profit': float(total_profit),
                'items_count': items.count(),
                'profit_margin': (total_profit / sale.total_amount * 100) if sale.total_amount > 0 else 0,
                'items': [
                    {
                        'product_name': item.product_name or (item.product.display_name if item.product else 'Unknown'),
                        'quantity': item.quantity,
                        'unit_price': float(item.unit_price),
                        'total_price': float(item.total_price),
                        'profit': float((item.unit_price - (item.product.buying_price if item.product and item.product.buying_price else 0)) * item.quantity) if item.product else 0,
                    } for item in items
                ]
            }
        }
        return JsonResponse(sale_data)
    except Sale.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Sale not found'})
    except Exception as e:
        logger.error(f"Error getting sale details: {str(e)}")
        return JsonResponse({'success': False, 'message': str(e)})








@login_required
def search_products(request):
    """AJAX endpoint to search products from inventory"""
    query = request.GET.get('q', '').strip()
    products = []
    
    try:
        from inventory.models import Product
        
        # Base queryset - only show available products with stock
        queryset = Product.objects.filter(
            status='available',
            quantity__gt=0,
            is_active=True
        )
        
        if query and len(query) >= 2:
            # Search by product_code, name, brand, model, or sku_value
            queryset = queryset.filter(
                Q(product_code__icontains=query) |
                Q(name__icontains=query) |
                Q(brand__icontains=query) |
                Q(model__icontains=query) |
                Q(sku_value__icontains=query) |
                Q(barcode__icontains=query)
            )
        
        # Limit to 30 results for performance
        results = queryset[:30]
        
        for product in results:
            # Build display name
            display_name = product.display_name
            
            # Add SKU info for single items
            sku_info = ""
            if product.category and product.category.is_single_item and product.sku_value:
                sku_info = f" | {product.category.sku_type}: {product.sku_value}"
            
            products.append({
                'code': product.product_code,
                'name': display_name,
                'price': float(product.selling_price),
                'best_price': float(product.best_price) if product.best_price else None,
                'stock': product.quantity,
                'sku': product.sku_value,
                'sku_type': product.category.sku_type if product.category else None,
                'is_single': product.category.is_single_item if product.category else False,
                'display_text': f"{display_name} ({product.product_code}){sku_info}"
            })
            
    except Exception as e:
        logger.error(f"Error searching products: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse(products, safe=False)







@login_required
def sales_dashboard(request):
    """Sales dashboard with statistics and charts"""
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Sum, Count
    from .models import Sale, SaleItem
    
    today = timezone.now().date()
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    # Basic stats
    total_sales = Sale.objects.count()
    today_sales = Sale.objects.filter(
        sale_date__date=today
    ).aggregate(total=Sum('total_amount'))['total'] or 0
    
    today_transactions = Sale.objects.filter(sale_date__date=today).count()
    
    items_sold_today = SaleItem.objects.filter(
        sale__sale_date__date=today
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    avg_sale_today = today_sales / today_transactions if today_transactions > 0 else 0
    
    # Recent sales
    recent_sales = Sale.objects.order_by('-sale_date')[:5]
    
    # Top selling products - FIXED: removed is_single_item from values()
    top_products = SaleItem.objects.values(
        'product__name', 
        'product__category__item_type'  # Use item_type instead of is_single_item
    ).annotate(
        total_sold=Sum('quantity'),
        total_revenue=Sum('total_price')
    ).order_by('-total_sold')[:5]
    
    # Convert item_type to boolean for template
    for product in top_products:
        product['is_single_item'] = (product['product__category__item_type'] == 'single')
    
    # Chart data (last 30 days)
    chart_labels = []
    sales_data = []
    
    for i in range(30):
        date = thirty_days_ago.date() + timedelta(days=i)
        day_sales = Sale.objects.filter(
            sale_date__date=date
        ).aggregate(total=Sum('total_amount'))['total'] or 0
        
        chart_labels.append(date.strftime('%d %b'))
        sales_data.append(float(day_sales))
    
    # Payment method distribution
    payment_data = [
        Sale.objects.filter(payment_method='Cash').count(),
        Sale.objects.filter(payment_method='M-Pesa').count(),
        Sale.objects.filter(payment_method='Card').count(),
        Sale.objects.filter(payment_method='Points').count(),
    ]
    
    context = {
        'total_sales': total_sales,
        'today_sales': today_sales,
        'today_transactions': today_transactions,
        'items_sold_today': items_sold_today,
        'avg_sale_today': avg_sale_today,
        'recent_sales': recent_sales,
        'top_products': top_products,
        'chart_labels': chart_labels,
        'sales_data': sales_data,
        'payment_data': payment_data,
    }
    
    return render(request, 'sales/dashboard.html', context)






@login_required
def sale_list(request):
    """List all sales with filtering"""
    from django.db.models import Q, Count
    from django.core.paginator import Paginator
    
    # Base queryset
    sales = Sale.objects.all().order_by('-sale_date')
    
    # ============================================
    # Apply filters
    # ============================================
    
    # Date filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    if date_from:
        sales = sales.filter(sale_date__date__gte=date_from)
    if date_to:
        sales = sales.filter(sale_date__date__lte=date_to)
    
    # ============================================
    # PAYMENT METHOD FILTER - FIXED: More robust
    # ============================================
    payment_method = request.GET.get('payment_method')
    if payment_method:
        if payment_method == 'M-Pesa':
            # Handle both 'M-Pesa' and 'Mpesa' variations
            sales = sales.filter(
                Q(payment_method__iexact='M-Pesa') | 
                Q(payment_method__iexact='Mpesa')
            )
        else:
            # For other methods, use case-insensitive exact match
            sales = sales.filter(payment_method__iexact=payment_method)
    
    # Sale type filter (cash vs credit)
    sale_type = request.GET.get('sale_type')
    if sale_type == 'cash':
        sales = sales.filter(is_credit=False)
    elif sale_type == 'credit':
        sales = sales.filter(is_credit=True)
    
    # Search filter
    search = request.GET.get('search')
    if search:
        sales = sales.filter(
            Q(sale_id__icontains=search) |
            Q(buyer_name__icontains=search) |
            Q(buyer_phone__icontains=search)
        )
    
    # ============================================
    # Get distinct payment methods for dropdown
    # ============================================
    available_methods = Sale.objects.values_list('payment_method', flat=True).distinct().order_by('payment_method')
    
    # ============================================
    # Pagination
    # ============================================
    paginator = Paginator(sales, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Pass the current filter values to template for maintaining selections
    context = {
        'sales': page_obj,
        'available_methods': available_methods,  # Add this for dynamic dropdown
        'current_filters': {
            'date_from': date_from,
            'date_to': date_to,
            'payment_method': payment_method,
            'sale_type': sale_type,
            'search': search,
        }
    }
    return render(request, 'sales/list.html', context)




@login_required
def sale_create(request):
    """Create a new sale with loyalty points"""
    if request.method == 'POST':
        # Check if it's an AJAX request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Get data based on request type
        if is_ajax:
            # Handle JSON data from AJAX
            try:
                data = json.loads(request.body)
                buyer_phone = data.get('buyer_phone', '').strip()
                payment_method = data.get('payment_method', 'Cash')
                is_credit = data.get('is_credit', False)
                amount_paid = Decimal(str(data.get('amount_paid', '0')))
                points_redeemed = int(data.get('points_redeemed', '0'))
                
                # Get verified customer ID if provided
                verified_customer_id = data.get('verified_customer_id')
                
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
        else:
            # Handle traditional form POST
            buyer_phone = request.POST.get('buyer_phone', '').strip()
            payment_method = request.POST.get('payment_method', 'Cash')
            is_credit = request.POST.get('is_credit') == 'on'
            points_redeemed = int(request.POST.get('points_redeemed', '0'))
            verified_customer_id = request.POST.get('verified_customer_id')
            
            if is_credit:
                amount_paid = Decimal('0.00')
            else:
                amount_paid = Decimal(request.POST.get('amount_paid', '0'))
        
        # Get cart items from session
        cart = request.session.get('sales_cart', [])
        
        if not cart:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'No items in cart.'})
            messages.error(request, 'No items in cart.')
            return redirect('sales:sale_create')
        
        try:
            with transaction.atomic():
                # ============================================
                # NORMALIZE PHONE NUMBER FOR CONSISTENCY
                # ============================================
                def normalize_phone(phone):
                    """Convert phone numbers to international format (254XXXXXXXXX)"""
                    if not phone:
                        return ''
                    # Remove all non-digit characters
                    phone = ''.join(filter(str.isdigit, phone))
                    
                    # If it starts with 0 (local format like 0722...)
                    if phone.startswith('0') and len(phone) == 10:
                        return '254' + phone[1:]  # Remove leading 0 and add 254
                    
                    # If it starts with 254 and is 12 digits, it's already correct
                    if phone.startswith('254') and len(phone) == 12:
                        return phone
                    
                    # If it's 9 digits (like 722...), add 254
                    if len(phone) == 9:
                        return '254' + phone
                    
                    return phone
                
                normalized_phone = normalize_phone(buyer_phone)
                logger.info(f"Phone normalized: '{buyer_phone}' -> '{normalized_phone}'")
                
                # Calculate original subtotal before any discounts
                original_subtotal = Decimal('0.00')
                for item in cart:
                    original_subtotal += Decimal(str(item.get('total', 0)))
                
                # ============================================
                # LOYALTY POINTS REDEMPTION - ONLY FOR REGISTERED CUSTOMERS
                # ============================================
                points_discount = Decimal('0.00')
                final_amount = original_subtotal
                customer = None
                
                # Check if this is a registered customer
                is_registered_customer = False
                
                # First try by verified_customer_id if provided
                if verified_customer_id:
                    try:
                        customer = Customer.objects.get(id=verified_customer_id, is_active=True)
                        is_registered_customer = True
                        logger.info(f"✅ Registered customer found by ID: {customer.phone_number} - {customer.full_name}")
                    except Customer.DoesNotExist:
                        logger.warning(f"Customer with ID {verified_customer_id} not found")
                
                # If not found by ID, try by normalized phone number
                if not is_registered_customer and normalized_phone:
                    try:
                        customer = Customer.objects.get(phone_number=normalized_phone, is_active=True)
                        is_registered_customer = True
                        logger.info(f"✅ Registered customer found by phone: {customer.phone_number} - {customer.full_name}")
                    except Customer.DoesNotExist:
                        logger.info(f"⚠️ Unregistered customer: {normalized_phone} - no points awarded")
                        is_registered_customer = False
                        customer = None
                
                # Only process points for registered customers
                if is_registered_customer and points_redeemed > 0:
                    # Check if customer has enough points
                    if customer.points_balance < points_redeemed:
                        raise ValueError(
                            f"Insufficient points. Available: {customer.points_balance}, "
                            f"Requested: {points_redeemed}"
                        )
                    
                    # Points value (1 point = KSH 1)
                    points_discount = Decimal(str(points_redeemed))
                    
                    # Ensure discount doesn't exceed subtotal
                    if points_discount > original_subtotal:
                        points_discount = original_subtotal
                        points_redeemed = int(original_subtotal)
                    
                    # Calculate final amount after points discount
                    final_amount = original_subtotal - points_discount
                    
                    # Adjust amount_paid if it was based on original total
                    if amount_paid > final_amount:
                        amount_paid = final_amount
                    
                    logger.info(
                        f"💰 Points redemption: {points_redeemed} points = KSH {points_discount} discount "
                        f"for registered customer {customer.phone_number}"
                    )
                elif points_redeemed > 0 and not is_registered_customer:
                    # Trying to redeem points without registration - block it
                    raise ValueError(
                        f"Cannot redeem points. Customer {buyer_phone} is not registered. "
                        f"Please register first to use loyalty points."
                    )
                
                # Create the sale with final amount
                sale = Sale.objects.create(
                    seller=request.user,
                    buyer_name=customer.full_name if is_registered_customer and customer else 'Walk-in Customer',
                    buyer_phone=normalized_phone,  # Store normalized phone
                    buyer_id_number=customer.id_number if is_registered_customer and customer else '',
                    nok_name='',
                    nok_phone='',
                    payment_method=payment_method,
                    amount_paid=amount_paid,
                    total_amount=final_amount,  # Use amount after points discount
                    subtotal=original_subtotal,  # Store original subtotal
                    is_credit=is_credit,
                    points_redeemed=points_redeemed if is_registered_customer else 0,
                    points_discount=points_discount if is_registered_customer else Decimal('0.00'),
                    original_subtotal=original_subtotal
                )
                
                # Process each cart item
                items_processed = []
                for item in cart:
                    product = Product.objects.select_for_update().get(
                        product_code=item['product_code']
                    )
                    
                    # refresh from database
                    product.refresh_from_db()

                    # Check stock availability
                    if product.quantity < item['quantity']:
                        raise ValueError(
                            f"Insufficient stock for {product.display_name}. "
                            f"Available: {product.quantity}, Requested: {item['quantity']}"
                        )
                    
                    # For single items, validate they haven't been sold in an ACTIVE sale
                    if product.category and product.category.is_single_item:
                        active_sale_exists = SaleItem.objects.filter(
                            sku_value=product.sku_value,
                            sale__is_reversed=False
                        ).exists()
                        
                        if active_sale_exists:
                            raise ValueError(
                                f"This {product.display_name} (SKU: {product.sku_value}) has already been sold in another transaction!"
                            )
                    
                    # Create sale item
                    sale_item = SaleItem.objects.create(
                        sale=sale,
                        product=product,
                        product_code=product.product_code,
                        product_name=product.display_name,
                        sku_value=product.sku_value,
                        quantity=item['quantity'],
                        unit_price=Decimal(str(item['price'])),
                        total_price=Decimal(str(item['total']))
                    )
                    
                    # Update product quantity
                    product.quantity -= item['quantity']
                    
                    # For single items, mark as sold and set status
                    if product.category and product.category.is_single_item:
                        product.status = 'sold'
                        product.quantity = 0
                    
                    product.save()
                    
                    # Create stock entry for audit trail
                    StockEntry.objects.create(
                        product=product,
                        quantity=-item['quantity'],
                        entry_type='sale',
                        unit_price=Decimal(str(item['price'])),
                        total_amount=Decimal(str(item['total'])),
                        reference_id=sale.sale_id,
                        notes=f"Sale #{sale.sale_id} - {product.display_name}",
                        created_by=request.user
                    )
                    
                    items_processed.append({
                        'name': product.display_name,
                        'code': product.product_code,
                        'quantity': item['quantity'],
                        'price': Decimal(str(item['price']))
                    })
                
                # ============================================
                # LOYALTY POINTS EARNING - ONLY FOR REGISTERED CUSTOMERS
                # ============================================
                points_earned = 0
                
                if is_registered_customer and customer:
                    # Process points redemption if any
                    if points_redeemed > 0:
                        customer.redeem_points(
                            points_redeemed,
                            sale=sale,
                            description=f"Redeemed for sale #{sale.sale_id}"
                        )
                    
                    # Update customer stats
                    customer.total_purchases += 1
                    customer.total_spent += original_subtotal
                    customer.last_purchase_date = timezone.now()
                    customer.save()
                    
                    # Update customer tier based on spending
                    customer.update_tier()
                    
                    # Award loyalty points based on amount spent (after points discount)
                    points_earned = customer.add_points(
                        final_amount,
                        sale=sale,
                        description=f"Purchase #{sale.sale_id}"
                    )
                    
                    logger.info(
                        f"💰 Registered customer {customer.phone_number}: "
                        f"Earned {points_earned} points | "
                        f"Redeemed {points_redeemed} points | "
                        f"New balance: {customer.points_balance} points"
                    )
                else:
                    logger.info(f"ℹ️ Unregistered customer {normalized_phone or 'No phone'} - no points awarded")
                
                # Clear the cart
                request.session['sales_cart'] = []
                
                # Handle credit sale if needed
                if is_credit:
                    try:
                        from credit.models import CreditSale
                        credit_sale = CreditSale.objects.create(
                            sale_id=sale.sale_id,
                            customer_name=customer.full_name if is_registered_customer and customer else "Walk-in Customer",
                            customer_phone=normalized_phone,
                            customer_id_number=customer.id_number if is_registered_customer and customer else '',
                            nok_name='',
                            nok_phone='',
                            total_amount=final_amount,
                            created_by=request.user,
                        )
                        sale.credit_sale_id = credit_sale.id
                        sale.save(update_fields=['credit_sale_id'])
                    except ImportError:
                        logger.warning(f"Credit app not found for sale #{sale.sale_id}")
                    except Exception as e:
                        logger.error(f"Credit record creation failed: {str(e)}")
                
                # Return appropriate response
                if is_ajax:
                    response_data = {
                        'success': True,
                        'sale_id': sale.sale_id,
                        'message': 'Sale completed successfully!'
                    }
                    
                    # Include points info only for registered customers
                    if is_registered_customer and customer:
                        response_data['points'] = {
                            'earned': int(points_earned),
                            'redeemed': points_redeemed,
                            'balance': customer.points_balance,
                            'discount': float(points_discount) if points_discount > 0 else 0
                        }
                        response_data['message'] = f'Sale completed! Earned {int(points_earned)} points!'
                    elif normalized_phone and not is_registered_customer:
                        response_data['warning'] = f'Phone {normalized_phone} is not registered. No points awarded.'
                    
                    return JsonResponse(response_data)
                else:
                    if is_registered_customer and points_earned > 0:
                        messages.success(
                            request, 
                            f'Sale #{sale.sale_id} completed! You earned {int(points_earned)} loyalty points!'
                        )
                    elif points_redeemed > 0 and is_registered_customer:
                        messages.success(
                            request,
                            f'Sale #{sale.sale_id} completed! Redeemed {points_redeemed} points for KSH {points_discount} discount!'
                        )
                    elif normalized_phone and not is_registered_customer:
                        messages.warning(
                            request,
                            f'Sale completed but NO POINTS awarded. Phone {normalized_phone} is not registered.'
                        )
                        messages.info(
                            request,
                            f'<a href="/sales/customer/register/?phone={normalized_phone}" class="alert-link">Click here to register</a> and start earning points!'
                        )
                    else:
                        messages.success(request, f'Sale #{sale.sale_id} completed successfully!')
                    
                    return redirect('sales:sale_detail', sale_id=sale.sale_id)
                
        except Customer.DoesNotExist:
            error_msg = f"Customer with phone {normalized_phone} not found. Please register first."
            logger.error(f"Error processing sale: {error_msg}")
            if is_ajax:
                return JsonResponse({'success': False, 'error': error_msg})
            messages.error(request, error_msg)
            return redirect('sales:sale_create')
            
        except Exception as e:
            logger.error(f"Error processing sale: {str(e)}")
            if is_ajax:
                return JsonResponse({'success': False, 'error': str(e)})
            messages.error(request, f'Error processing sale: {str(e)}')
            return redirect('sales:sale_create')
    
    # GET request - show the sale form with cart
    cart = request.session.get('sales_cart', [])
    subtotal = Decimal('0.00')
    for item in cart:
        subtotal += Decimal(str(item.get('total', 0)))
    
    context = {
        'cart': cart,
        'subtotal': subtotal,
        'cart_count': len(cart),
        'now': timezone.now(),
    }
    return render(request, 'sales/create.html', context)







@login_required
def sale_detail(request, sale_id):
    """View sale details"""
    sale = get_object_or_404(Sale.objects.prefetch_related('items__product'), sale_id=sale_id)
    
    # Calculate change and balance in the view
    change = sale.amount_paid - sale.total_amount
    balance = sale.total_amount - sale.amount_paid if sale.amount_paid < sale.total_amount else 0
    
    context = {
        'sale': sale,
        'items': sale.items.all(),
        'change': change,
        'balance': balance,
    }
    return render(request, 'sales/detail.html', context)






@login_required
def sale_receipt(request, sale_id):
    """View/print sale receipt with loyalty points and VAT calculation"""
    sale = get_object_or_404(Sale.objects.prefetch_related('items__product'), sale_id=sale_id)
    
    # Calculate change
    change = sale.amount_paid - sale.total_amount if sale.amount_paid else 0
    
    # ============================================
    # VAT CALCULATION
    # ============================================
    # VAT rate is 16%
    vat_rate = Decimal('0.16')
    
    # Grand total is the total amount of the sale (including VAT)
    grand_total = sale.total_amount
    
    # Calculate VAT amount (16% of grand total)
    # If grand total is inclusive of VAT, then VAT = grand_total - (grand_total / 1.16)
    # OR directly: VAT = grand_total * 16/116
    if grand_total > 0:
        vat_amount = (grand_total * vat_rate) / (1 + vat_rate)
        subtotal_excl_vat = grand_total - vat_amount
    else:
        vat_amount = Decimal('0.00')
        subtotal_excl_vat = Decimal('0.00')
    
    # Format for display
    vat_amount_display = vat_amount.quantize(Decimal('0.01'))
    subtotal_excl_vat_display = subtotal_excl_vat.quantize(Decimal('0.01'))
    
    # ============================================
    # GET CUSTOMER DATA FOR LOYALTY POINTS
    # ============================================
    customer = None
    previous_points = 0
    points_earned_today = 0
    
    if sale.buyer_phone:
        try:
            # Find customer by phone number
            customer = Customer.objects.get(phone_number=sale.buyer_phone, is_active=True)
            
            # Get points earned in this sale from LoyaltyTransaction
            earned_trans = LoyaltyTransaction.objects.filter(
                customer=customer,
                sale=sale,
                transaction_type='earned'
            ).first()
            
            if earned_trans:
                points_earned_today = earned_trans.points
            else:
                # If no transaction record, calculate from amount (1 point per 100 KSH)
                points_earned_today = int(sale.total_amount / 100)
            
            # Calculate previous points (current balance - points earned today)
            previous_points = customer.points_balance - points_earned_today
            if previous_points < 0:
                previous_points = 0
                
            logger.info(f"✅ Receipt customer: {customer.full_name}, Previous: {previous_points}, Earned today: {points_earned_today}")
            
        except Customer.DoesNotExist:
            logger.info(f"ℹ️ No customer found with phone {sale.buyer_phone}")
        except Exception as e:
            logger.error(f"Error getting customer for receipt: {str(e)}")
    
    context = {
        'sale': sale,
        'items': sale.items.all(),
        'change': change,
        'customer': customer,
        'previous_points': previous_points,
        'points_earned_today': points_earned_today,
        'vat_amount': vat_amount_display,
        'subtotal_excl_vat': subtotal_excl_vat_display,
        'grand_total': grand_total,
        'vat_rate': 16,
    }
    
    return render(request, 'sales/receipt.html', context)







@login_required
def sale_reverse(request, sale_id):
    """Reverse a sale"""
    sale = get_object_or_404(Sale, sale_id=sale_id)
    
    if sale.is_reversed:
        messages.error(request, 'This sale has already been reversed.')
        return redirect('sales:sale_detail', sale_id=sale_id)
    
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        
        try:
            with transaction.atomic():
                # Reverse the sale - PASS THE REASON!
                result = sale.reverse_sale(reversed_by=request.user, reason=reason)
                
                messages.success(request, result)
                return redirect('sales:sale_detail', sale_id=sale_id)
                
        except Exception as e:
            logger.error(f"Error reversing sale: {str(e)}")
            messages.error(request, f'Error reversing sale: {str(e)}')
            return redirect('sales:sale_detail', sale_id=sale_id)
    
    context = {
        'sale': sale,
        'items': sale.items.all(),
    }
    return render(request, 'sales/reverse.html', context)







# ====================================
# API VIEWS FOR CART MANAGEMENT
# ====================================

@login_required
def get_product_details(request, product_code):
    """AJAX endpoint to get product details by code or barcode"""
    try:
        # Search by product_code or barcode
        product = Product.objects.get(
            Q(product_code=product_code) | Q(barcode=product_code)
        )
        
        # Check if single item is already sold
        if product.category.is_single_item:
            if product.status == 'sold' or product.quantity <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'This item has already been sold'
                })
            if product.quantity <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Product out of stock'
                })
        else:
            # Bulk items check quantity
            if product.quantity <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Product out of stock'
                })
        
        return JsonResponse({
            'success': True,
            'product': {
                'product_code': product.product_code,
                'name': product.display_name,
                'price': float(product.selling_price),
                'stock': product.quantity,
                'sku': product.sku_value,
                'is_single': product.category.is_single_item,
                'status': product.status
            }
        })
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Product not found'
        })






@login_required
def get_cart(request):
    """AJAX endpoint to get current cart contents"""
    cart = request.session.get('sales_cart', [])
    subtotal = sum(item.get('total', 0) for item in cart)
    
    return JsonResponse({
        'success': True,
        'cart': cart,
        'subtotal': subtotal,
        'cart_count': len(cart)
    })





@login_required
def add_to_cart(request):
    """AJAX endpoint to add item to cart with custom price"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_code = data.get('product_code')
            quantity = int(data.get('quantity', 1))
            custom_price = data.get('custom_price')
            allow_price_edit = data.get('allow_price_edit', False)
            
            try:
                product = Product.objects.get(product_code=product_code)
            except Product.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': f'Product with code "{product_code}" not found'
                })
            
            # ============================================
            # FIXED: Check if single item is already sold in an ACTIVE sale
            # ============================================
            if product.category and product.category.is_single_item:
                # Check if already sold in an active sale (not reversed)
                from sales.models import SaleItem
                active_sale_exists = SaleItem.objects.filter(
                    product=product,
                    sale__is_reversed=False  # Only check non-reversed sales
                ).exists()
                
                if active_sale_exists:
                    return JsonResponse({
                        'success': False,
                        'error': f'This item ({product.display_name}) has already been sold and cannot be added to cart'
                    })
                
                # Check if already in cart
                cart = request.session.get('sales_cart', [])
                for item in cart:
                    if item.get('product_code') == product_code:
                        return JsonResponse({
                            'success': False,
                            'error': 'This item is already in the cart'
                        })
                
                # Check if quantity is more than 1 for single items
                if quantity != 1:
                    return JsonResponse({
                        'success': False,
                        'error': 'Single items can only be sold one at a time'
                    })
            
            # Check stock for bulk items
            if not product.category.is_single_item and product.quantity < quantity:
                return JsonResponse({
                    'success': False,
                    'error': f'Insufficient stock. Available: {product.quantity}'
                })
            
            # Determine the price
            if custom_price is not None and custom_price and allow_price_edit:
                try:
                    price = float(custom_price)
                except (ValueError, TypeError):
                    price = float(product.selling_price)
            else:
                price = float(product.selling_price)
            
            # Get or create cart in session
            cart = request.session.get('sales_cart', [])
            
            # Check if product with SAME PRICE already exists in cart (for bulk items)
            found = False
            for item in cart:
                # Only combine if same product code AND same price (for bulk items)
                if item.get('product_code') == product_code and item.get('price') == price:
                    # Don't combine single items
                    if product.category and product.category.is_single_item:
                        continue
                    
                    # Same product with same price - combine quantities
                    new_quantity = item['quantity'] + quantity
                    if product.quantity < new_quantity:
                        return JsonResponse({
                            'success': False,
                            'error': f'Only {product.quantity} available'
                        })
                    
                    item['quantity'] = new_quantity
                    item['total'] = item['price'] * item['quantity']
                    found = True
                    break
            
            if not found:
                # Add as new row
                cart.append({
                    'product_id': product.id,
                    'product_code': product.product_code,
                    'name': product.display_name,
                    'price': price,
                    'original_price': float(product.selling_price),
                    'quantity': quantity,
                    'total': price * quantity,
                    'is_single': product.category.is_single_item if product.category else False,
                    'price_editable': allow_price_edit,
                    'unique_id': f"{product_code}_{price}_{len(cart)}"
                })
            
            # Save cart to session
            request.session['sales_cart'] = cart
            request.session.modified = True
            
            # Calculate new totals
            subtotal = sum(item['total'] for item in cart)
            cart_count = len(cart)
            
            return JsonResponse({
                'success': True,
                'cart': cart,
                'subtotal': subtotal,
                'cart_count': cart_count,
                'message': f'{product.display_name} added to cart' + 
                          (f' at KSH {price}' if custom_price else '')
            })
            
        except Exception as e:
            logger.error(f"Error adding to cart: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})




def validate_single_items_in_cart(cart):
    """
    Validate that no single items in cart have been sold already
    """
    for item in cart:
        if item.get('is_single'):
            try:
                product = Product.objects.get(product_code=item['product_code'])
                if product.status == 'sold' or product.quantity <= 0:
                    return False, f"Item {product.display_name} has already been sold"
                
                # Check if this SKU appears in any sale
                if SaleItem.objects.filter(sku_value=product.sku_value).exists():
                    return False, f"Item {product.display_name} (SKU: {product.sku_value}) has already been sold"
                    
            except Product.DoesNotExist:
                return False, f"Product {item['product_code']} not found"
    
    return True, "All items are available"





@login_required
def remove_from_cart(request):
    """AJAX endpoint to remove item from cart"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_code = data.get('product_code')
            price = float(data.get('price', 0))  # Get price to identify specific row
            
            cart = request.session.get('sales_cart', [])
            
            # Remove the specific item with matching code AND price
            new_cart = [item for item in cart 
                       if not (item['product_code'] == product_code and item['price'] == price)]
            
            request.session['sales_cart'] = new_cart
            request.session.modified = True
            
            subtotal = sum(item['total'] for item in new_cart)
            
            return JsonResponse({
                'success': True,
                'cart': new_cart,
                'subtotal': subtotal,
                'cart_count': len(new_cart)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})





@login_required
def update_cart(request):
    """AJAX endpoint to update item quantity in cart"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_code = data.get('product_code')
            quantity = int(data.get('quantity', 1))
            price = float(data.get('price', 0))  # Also get price to identify the specific row
            
            cart = request.session.get('sales_cart', [])
            
            if quantity < 1:
                return JsonResponse({
                    'success': False,
                    'error': 'Quantity must be at least 1'
                })
            
            # Find the specific item with matching code AND price
            found = False
            for item in cart:
                if item['product_code'] == product_code and item['price'] == price:
                    # Check stock
                    try:
                        product = Product.objects.get(product_code=product_code)
                        if product.quantity < quantity:
                            return JsonResponse({
                                'success': False,
                                'error': f'Only {product.quantity} available'
                            })
                    except Product.DoesNotExist:
                        pass
                    
                    item['quantity'] = quantity
                    item['total'] = item['price'] * quantity
                    found = True
                    break
            
            if not found:
                return JsonResponse({
                    'success': False,
                    'error': 'Item not found in cart'
                })
            
            request.session['sales_cart'] = cart
            request.session.modified = True
            
            subtotal = sum(item['total'] for item in cart)
            
            return JsonResponse({
                'success': True,
                'cart': cart,
                'subtotal': subtotal,
                'cart_count': len(cart)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})





@login_required
def update_cart_price(request):
    """AJAX endpoint to update item price in cart"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_code = data.get('product_code')
            old_price = float(data.get('old_price', 0))
            new_price = float(data.get('price', 0))
            
            if new_price < 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Price cannot be negative'
                })
            
            cart = request.session.get('sales_cart', [])
            
            # Find the specific item with matching code AND old price
            found = False
            for item in cart:
                if item['product_code'] == product_code and item['price'] == old_price:
                    if not item.get('price_editable', False):
                        return JsonResponse({
                            'success': False,
                            'error': 'This item price is locked'
                        })
                    
                    item['price'] = new_price
                    item['total'] = new_price * item['quantity']
                    found = True
                    break
            
            if not found:
                return JsonResponse({
                    'success': False,
                    'error': 'Item not found in cart'
                })
            
            request.session['sales_cart'] = cart
            request.session.modified = True
            
            subtotal = sum(item['total'] for item in cart)
            
            return JsonResponse({
                'success': True,
                'cart': cart,
                'subtotal': subtotal,
                'cart_count': len(cart)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


    


@login_required
def clear_cart(request):
    """AJAX endpoint to clear the entire cart"""
    if request.method == 'POST':
        request.session['sales_cart'] = []
        return JsonResponse({
            'success': True,
            'message': 'Cart cleared'
        })
    return JsonResponse({'success': False, 'error': 'Invalid request'})






@login_required
def sold_items_list(request):
    """List all sold items with details"""
    
    # Get all sold items with related data
    sold_items = SaleItem.objects.select_related(
        'sale', 'product'
    ).filter(
        sale__is_reversed=False  # Exclude reversed sales
    ).order_by('-sale__sale_date')
    
    # Apply filters if any
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    search = request.GET.get('search', '').strip()
    
    if date_from:
        sold_items = sold_items.filter(sale__sale_date__date__gte=date_from)
    
    if date_to:
        sold_items = sold_items.filter(sale__sale_date__date__lte=date_to)
    
    if search:
        sold_items = sold_items.filter(
            Q(sale__sale_id__icontains=search) |
            Q(sale__etr_receipt_number__icontains=search) |
            Q(product__name__icontains=search) |
            Q(product__product_code__icontains=search) |
            Q(product__sku_value__icontains=search) |
            Q(sale__buyer_name__icontains=search)
        )
    
    # Create a list of items with profit calculated as a dictionary attribute
    items_with_profit = []
    for item in sold_items:
        # Calculate profit
        if item.product and item.product.buying_price:
            profit_value = (item.unit_price - item.product.buying_price) * item.quantity
        else:
            profit_value = 0
        
        # Add profit as a dictionary key instead of object attribute
        items_with_profit.append({
            'item': item,
            'profit': profit_value
        })
    
    # Pagination - need to paginate the original queryset, then map to our list
    paginator = Paginator(sold_items, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Calculate totals
    total_sold = sold_items.aggregate(total=Sum('quantity'))['total'] or 0
    total_revenue = sold_items.aggregate(total=Sum('total_price'))['total'] or 0
    
    # Calculate total profit
    total_profit = 0
    for item in sold_items:
        if item.product and item.product.buying_price:
            total_profit += (item.unit_price - item.product.buying_price) * item.quantity
    
    context = {
        'page_obj': page_obj,
        'total_sold': total_sold,
        'total_revenue': total_revenue,
        'total_profit': total_profit,
        'search': search,
        'date_from': date_from,
        'date_to': date_to,
    }
    
    return render(request, 'sales/sold_items_list.html', context)




@login_required
def export_sold_items(request):
    """Export sold items to CSV"""
    import csv
    from django.http import HttpResponse
    
    # Get filtered items (same as in sold_items_list)
    sold_items = SaleItem.objects.select_related(
        'sale', 'product'
    ).filter(
        sale__is_reversed=False
    ).order_by('-sale__sale_date')
    
    # Apply same filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    search = request.GET.get('search', '').strip()
    
    if date_from:
        sold_items = sold_items.filter(sale__sale_date__date__gte=date_from)
    if date_to:
        sold_items = sold_items.filter(sale__sale_date__date__lte=date_to)
    if search:
        sold_items = sold_items.filter(
            Q(sale__sale_id__icontains=search) |
            Q(sale__etr_receipt_number__icontains=search) |
            Q(product__name__icontains=search) |
            Q(product__product_code__icontains=search)
        )
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="sold_items_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Sale ID', 'ETR Number', 'Product', 'SKU/Code', 'Category', 
                    'Quantity', 'Unit Price', 'Total Amount', 'Profit', 'Sold By', 'Date Sold', 'Customer'])
    
    for item in sold_items:
        # FIXED: Use unit_price instead of price
        profit = (item.unit_price - item.product.buying_price) * item.quantity if item.product and item.product.buying_price else 0
        writer.writerow([
            item.sale.sale_id,
            item.sale.etr_receipt_number or '',
            item.product.display_name if item.product else item.product_name,
            item.sku_value or (item.product.sku_value if item.product else '') or (item.product.product_code if item.product else ''),
            item.product.category.name if item.product and item.product.category else '',
            item.quantity,
            item.unit_price,  # FIXED: Use unit_price
            item.total_price,
            profit,
            item.sale.seller.get_full_name() or item.sale.seller.username,
            item.sale.sale_date.strftime('%Y-%m-%d %H:%M'),
            item.sale.buyer_name or 'Walk-in Customer'
        ])
    
    return response







@login_required
def customer_register(request):
    """Register a new customer for loyalty points"""
    if request.method == 'POST':
        try:
            # Get form data
            phone_number = request.POST.get('phone_number', '').strip()
            full_name = request.POST.get('full_name', '').strip()
            email = request.POST.get('email', '').strip()
            id_number = request.POST.get('id_number', '').strip()
            
            # ============================================
            # PHONE NUMBER NORMALIZATION FUNCTION
            # ============================================
            def normalize_phone(phone):
                if not phone:
                    return ''
                # Remove all non-digit characters
                cleaned = ''.join(filter(str.isdigit, phone))
                
                # If it starts with 0 and is 10 digits (local format like 0700...)
                if cleaned.startswith('0') and len(cleaned) == 10:
                    return '254' + cleaned[1:]
                
                # If it's already international format (254...)
                if cleaned.startswith('254') and len(cleaned) == 12:
                    return cleaned
                
                # If it's 9 digits (missing leading 0)
                if len(cleaned) == 9:
                    return '254' + cleaned
                
                return cleaned
            
            # NORMALIZE THE PHONE NUMBER
            normalized_phone = normalize_phone(phone_number)
            
            # Validate required fields
            if not normalized_phone:
                messages.error(request, 'Phone number is required')
                return redirect('sales:customer_register')
            
            if not full_name:
                messages.error(request, 'Full name is required')
                return redirect('sales:customer_register')
            
            # Check if customer already exists (check both formats)
            from django.db.models import Q
            existing_customer = Customer.objects.filter(
                Q(phone_number=normalized_phone) | 
                Q(phone_number=phone_number) |
                Q(phone_number__icontains=normalized_phone[-9:])
            ).first()
            
            if existing_customer:
                messages.error(request, f'Customer with phone {existing_customer.phone_number} already exists')
                return redirect('sales:customer_register')
            
            # Create new customer with NORMALIZED phone number
            customer = Customer.objects.create(
                phone_number=normalized_phone,  # Store normalized format
                full_name=full_name,
                email=email,
                id_number=id_number,
                points_balance=0,
                tier='bronze'
            )
            
            # Award welcome points
            settings = LoyaltySettings.get_settings()
            if settings.welcome_points > 0:
                customer.add_points(
                    settings.welcome_points,
                    description="Welcome bonus for registration"
                )
                welcome_msg = f" and received {settings.welcome_points} welcome points"
            else:
                welcome_msg = ""
            
            logger.info(f"✅ New customer registered: {customer.phone_number} - {customer.full_name}{welcome_msg}")
            
            messages.success(
                request, 
                f'Customer {full_name} registered successfully{welcome_msg}!'
            )
            
            # Return JSON for AJAX or redirect for regular form
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'customer': {
                        'id': customer.id,
                        'phone': customer.phone_number,
                        'name': customer.full_name,
                        'points': customer.points_balance,
                        'tier': customer.get_tier_display(),
                    }
                })
            
            return redirect('sales:customer_list')
            
        except Exception as e:
            logger.error(f"Error registering customer: {str(e)}")
            messages.error(request, f'Error registering customer: {str(e)}')
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)})
            
            return redirect('sales:customer_register')
    
    # GET request - show registration form
    context = {
        'settings': LoyaltySettings.get_settings(),
    }
    return render(request, 'sales/customer_register.html', context)





@login_required
def customer_search(request):
    """AJAX endpoint to search customers by phone or name"""
    query = request.GET.get('phone', '').strip()
    
    if not query or len(query) < 3:
        return JsonResponse({'customers': []})
    
    # ============================================
    # NORMALIZE THE SEARCH PHONE NUMBER
    # ============================================
    def normalize_phone(phone):
        if not phone:
            return ''
        cleaned = ''.join(filter(str.isdigit, phone))
        if cleaned.startswith('0') and len(cleaned) == 10:
            return '254' + cleaned[1:]
        if cleaned.startswith('254') and len(cleaned) == 12:
            return cleaned
        if len(cleaned) == 9:
            return '254' + cleaned
        return cleaned
    
    normalized_query = normalize_phone(query)
    
    # Search with both original and normalized formats
    from django.db.models import Q
    customers = Customer.objects.filter(
        Q(phone_number__icontains=normalized_query) |
        Q(phone_number__icontains=query) |
        Q(full_name__icontains=query)
    ).filter(is_active=True)[:10]
    
    settings = LoyaltySettings.get_settings()
    
    data = [{
        'id': c.id,
        'phone': c.phone_number,
        'name': c.full_name or 'Unknown',
        'points': c.points_balance,
        'tier': c.get_tier_display(),
        'tier_class': c.tier,
        'points_value': float(c.points_balance),
        'total_spent': float(c.total_spent),
        'purchases': c.total_purchases,
    } for c in customers]
    
    return JsonResponse({'customers': data})






    

@login_required
def customer_detail(request, pk):
    """Get customer details with transaction history"""
    customer = get_object_or_404(Customer, pk=pk, is_active=True)
    
    # Get recent transactions
    transactions = LoyaltyTransaction.objects.filter(
        customer=customer
    ).select_related('sale').order_by('-created_at')[:20]
    
    # Get recent sales
    recent_sales = Sale.objects.filter(
        buyer_phone=customer.phone_number
    ).order_by('-sale_date')[:10]
    
    data = {
        'id': customer.id,
        'phone': customer.phone_number,
        'name': customer.full_name,
        'email': customer.email,
        'id_number': customer.id_number,
        'points': customer.points_balance,
        'points_value': float(customer.points_balance),  # 1 point = KSH 1
        'tier': customer.get_tier_display(),
        'tier_class': customer.tier,
        'total_spent': float(customer.total_spent),
        'total_purchases': customer.total_purchases,
        'last_purchase': customer.last_purchase_date.isoformat() if customer.last_purchase_date else None,
        'created_at': customer.created_at.isoformat(),
        'transactions': [{
            'id': t.id,
            'date': t.created_at.isoformat(),
            'points': t.points,
            'type': t.transaction_type,
            'description': t.description,
            'sale_id': t.sale.sale_id if t.sale else None,
        } for t in transactions],
        'recent_sales': [{
            'id': s.sale_id,
            'date': s.sale_date.isoformat(),
            'amount': float(s.total_amount),
            'payment_method': s.payment_method,
        } for s in recent_sales],
    }
    
    # For AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(data)
    
    # For regular browser requests
    context = {
        'customer': customer,
        'transactions': transactions,
        'recent_sales': recent_sales,
    }
    return render(request, 'sales/customer_detail.html', context)

@login_required
def customer_transactions(request, pk):
    """Get customer transaction history"""
    customer = get_object_or_404(Customer, pk=pk, is_active=True)
    
    transactions = LoyaltyTransaction.objects.filter(
        customer=customer
    ).select_related('sale').order_by('-created_at')
    
    # Pagination
    paginator = Paginator(transactions, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'customer': customer,
        'transactions': page_obj,
    }
    return render(request, 'sales/customer_transactions.html', context)





@login_required
def customer_list(request):
    """List all customers with loyalty points"""
    customers = Customer.objects.all().order_by('-created_at')
    
    # Search
    search = request.GET.get('search', '')
    if search:
        customers = customers.filter(
            Q(phone_number__icontains=search) |
            Q(full_name__icontains=search) |
            Q(email__icontains=search)
        )
    
    # Filter by tier
    tier = request.GET.get('tier', '')
    if tier:
        customers = customers.filter(tier=tier)
    
    # Sorting
    sort = request.GET.get('sort', '-points_balance')
    customers = customers.order_by(sort)
    
    # Pagination
    paginator = Paginator(customers, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Statistics
    total_customers = Customer.objects.count()
    total_points = Customer.objects.aggregate(total=Sum('points_balance'))['total'] or 0
    total_spent = Customer.objects.aggregate(total=Sum('total_spent'))['total'] or 0
    
    # Tier counts
    platinum_customers = Customer.objects.filter(tier='platinum').count()
    gold_customers = Customer.objects.filter(tier='gold').count()
    
    # New customers this month
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_customers = Customer.objects.filter(created_at__gte=month_start).count()
    
    context = {
        'customers': page_obj,
        'total_customers': total_customers,
        'total_points': total_points,
        'total_points_value': total_points,  # 1 point = KSH 1
        'total_spent': total_spent,
        'avg_spent': total_spent / total_customers if total_customers > 0 else 0,
        'platinum_customers': platinum_customers,
        'gold_customers': gold_customers,
        'new_customers': new_customers,
        'search': search,
        'tier': tier,
        'sort': sort,
        'tier_choices': Customer.TIER_CHOICES,
    }
    return render(request, 'sales/customer_list.html', context)


@login_required
def customer_edit(request, pk):
    """Edit customer information"""
    customer = get_object_or_404(Customer, pk=pk)
    
    if request.method == 'POST':
        try:
            # Get form data
            full_name = request.POST.get('full_name', '').strip()
            email = request.POST.get('email', '').strip()
            id_number = request.POST.get('id_number', '').strip()
            is_active = request.POST.get('is_active') == 'true' if request.user.is_staff else customer.is_active
            
            # Validate
            if not full_name:
                messages.error(request, 'Full name is required')
                return redirect('sales:customer_edit', pk=pk)
            
            # Update customer fields
            customer.full_name = full_name
            customer.email = email
            customer.id_number = id_number
            customer.is_active = is_active
            customer.save()
            
            # Handle points adjustment (admin only)
            if request.user.is_staff or request.user.is_superuser:
                points_adjustment = request.POST.get('points_adjustment')
                if points_adjustment and points_adjustment.strip():
                    points = int(points_adjustment)
                    adjustment_type = request.POST.get('adjustment_type')
                    reason = request.POST.get('adjustment_reason', '').strip()
                    
                    if points > 0 and reason:
                        if adjustment_type == 'add':
                            customer.add_points(
                                points,
                                description=f"Manual adjustment: {reason}"
                            )
                            messages.success(request, f'Added {points} points to customer balance')
                        elif adjustment_type == 'subtract':
                            if points <= customer.points_balance:
                                # Create redemption transaction for points subtraction
                                from sales.models import LoyaltyTransaction
                                LoyaltyTransaction.objects.create(
                                    customer=customer,
                                    points=points,
                                    transaction_type='adjustment',
                                    description=f"Manual adjustment: {reason}"
                                )
                                customer.points_balance -= points
                                customer.save()
                                messages.success(request, f'Subtracted {points} points from customer balance')
                            else:
                                messages.warning(request, f'Cannot subtract {points} points. Customer only has {customer.points_balance} points.')
            
            messages.success(request, f'Customer "{customer.full_name}" updated successfully')
            return redirect('sales:customer_detail', pk=customer.id)
            
        except Exception as e:
            logger.error(f"Error updating customer {pk}: {str(e)}")
            messages.error(request, f'Error updating customer: {str(e)}')
            return redirect('sales:customer_edit', pk=pk)
    
    context = {
        'customer': customer,
    }
    return render(request, 'sales/customer_edit.html', context)


@login_required
def customer_delete(request, pk):
    """Delete a customer (admin only)"""
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, 'You do not have permission to delete customers')
        return redirect('sales:customer_list')
    
    customer = get_object_or_404(Customer, pk=pk)
    
    if request.method == 'POST':
        try:
            customer_name = customer.full_name
            customer.delete()
            messages.success(request, f'Customer "{customer_name}" has been deleted')
            return redirect('sales:customer_list')
        except Exception as e:
            logger.error(f"Error deleting customer {pk}: {str(e)}")
            messages.error(request, f'Error deleting customer: {str(e)}')
            return redirect('sales:customer_detail', pk=pk)
    
    return redirect('sales:customer_detail', pk=pk)