from django.db import models
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum, Count, Avg, F
from django.http import JsonResponse
from django.utils import timezone
from decimal import Decimal
from django.conf import settings
import json
import logging
import calendar
import random  
import africastalking 
from datetime import timedelta, datetime, date
from finance.kopokopo_service import stk_push_request, clean_phone_number
from finance.models import MpesaTransaction
from sales.models import Sale, SaleItem, PaymentRecord, create_sale_safely, generate_sale_id, Customer, LoyaltySettings, LoyaltyTransaction
from inventory.models import Product, StockEntry
from django.core.paginator import Paginator
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from inventory.models import Product, ProductUnit, StockEntry





logger = logging.getLogger(__name__)



# ============================================
# HELPER FUNCTIONS
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
    """Sales statistics dashboard - MATCHES FINANCE CALCULATIONS"""
    from finance.utils import UnifiedFinanceCalculator
    from decimal import Decimal
    from django.db.models import Sum, Q, Count
    from django.utils import timezone
    from datetime import timedelta, datetime
    import calendar
    
    # ============================================
    # HELPER FUNCTION - MUST BE DEFINED FIRST
    # ============================================
    def get_day_suffix(day):
        """Get day suffix (st, nd, rd, th)"""
        if 11 <= day <= 13:
            return 'th'
        if day % 10 == 1:
            return 'st'
        if day % 10 == 2:
            return 'nd'
        if day % 10 == 3:
            return 'rd'
        return 'th'
    
    today = timezone.now().date()
    current_year = today.year
    current_month = today.month
    
    # ============================================
    # USE UNIFIED FINANCE CALCULATOR FOR ACCURATE DATA
    # ============================================
    
    # Get period data
    today_data = UnifiedFinanceCalculator.get_period_data('today')
    week_data = UnifiedFinanceCalculator.get_period_data('week')
    month_data = UnifiedFinanceCalculator.get_period_data('month')
    year_data = UnifiedFinanceCalculator.get_period_data('year')
    
    # Get returned sale IDs to exclude
    from inventory.models import ReturnRequest
    returned_sale_ids = ReturnRequest.objects.filter(
        ~Q(status='rejected')
    ).exclude(
        Q(sale_id__isnull=True) | Q(sale_id='')
    ).values_list('sale_id', flat=True).distinct()
    
    # Base queryset - exclude reversed AND returned sales
    active_sales_qs = Sale.objects.filter(
        is_reversed=False
    ).exclude(
        sale_id__in=returned_sale_ids
    )
    
    # ============================================
    # DAILY BREAKDOWN (Monday - Sunday)
    # ============================================
    # Get start of week (Monday)
    start_of_week = today - timedelta(days=today.weekday())
    daily_sales_breakdown = []
    daily_totals = {'count': 0, 'revenue': Decimal('0'), 'profit': Decimal('0'), 'avg_margin': 0}
    
    for i in range(7):
        day = start_of_week + timedelta(days=i)
        day_revenue = UnifiedFinanceCalculator.calculate_revenue(day, day)
        day_cogs = UnifiedFinanceCalculator.calculate_cogs(day, day)
        day_profit = day_revenue - day_cogs
        day_count = active_sales_qs.filter(sale_date__date=day).count()
        
        margin = (day_profit / day_revenue * 100) if day_revenue > 0 else 0
        
        daily_sales_breakdown.append({
            'day': day.strftime('%A'),
            'date': day.strftime('%Y-%m-%d'),
            'count': day_count,
            'revenue': day_revenue,
            'profit': day_profit,
            'margin': margin,
        })
        
        daily_totals['count'] += day_count
        daily_totals['revenue'] += day_revenue
        daily_totals['profit'] += day_profit
    
    if daily_totals['revenue'] > 0:
        daily_totals['avg_margin'] = (daily_totals['profit'] / daily_totals['revenue']) * 100
    
    # ============================================
    # WEEKLY BREAKDOWN (Current Month)
    # ============================================
    month_start = today.replace(day=1)
    last_day = calendar.monthrange(current_year, current_month)[1]
    month_end = today.replace(day=last_day)
    
    weekly_sales_breakdown = []
    month_total_revenue = Decimal('0')
    month_total_count = 0
    month_total_profit = Decimal('0')
    
    # Define week ranges
    week_ranges = [
        (1, 7), (8, 14), (15, 21), (22, 28), (29, last_day)
    ]
    
    for week_num, (start_day, end_day) in enumerate(week_ranges, 1):
        if start_day > last_day:
            continue
        
        end_day = min(end_day, last_day)
        week_start = datetime(current_year, current_month, start_day).date()
        week_end = datetime(current_year, current_month, end_day).date()
        
        week_revenue = UnifiedFinanceCalculator.calculate_revenue(week_start, week_end)
        week_cogs = UnifiedFinanceCalculator.calculate_cogs(week_start, week_end)
        week_profit = week_revenue - week_cogs
        week_count = active_sales_qs.filter(
            sale_date__date__gte=week_start,
            sale_date__date__lte=week_end
        ).count()
        
        margin = (week_profit / week_revenue * 100) if week_revenue > 0 else 0
        
        # Format date range - NOW get_day_suffix is defined
        month_name = week_start.strftime('%b')
        date_range = f"{month_name} {start_day}{get_day_suffix(start_day)} - {month_name} {end_day}{get_day_suffix(end_day)}"
        
        weekly_sales_breakdown.append({
            'week_number': week_num,
            'week_range': date_range,
            'count': week_count,
            'revenue': week_revenue,
            'profit': week_profit,
            'margin': margin,
        })
        
        month_total_revenue += week_revenue
        month_total_count += week_count
        month_total_profit += week_profit
    
    month_margin = (month_total_profit / month_total_revenue * 100) if month_total_revenue > 0 else 0
    
    # ============================================
    # MONTHLY BREAKDOWN (Last 12 Months)
    # ============================================
    monthly_sales_breakdown = []
    year_total_revenue = Decimal('0')
    year_total_count = 0
    year_total_profit = Decimal('0')
    
    for i in range(11, -1, -1):
        month_date = today - timedelta(days=30 * i)
        month_start = month_date.replace(day=1)
        if month_date.month == 12:
            month_end = month_date.replace(day=31)
        else:
            next_month = month_date.replace(month=month_date.month + 1, day=1)
            month_end = next_month - timedelta(days=1)
        
        month_revenue = UnifiedFinanceCalculator.calculate_revenue(month_start, month_end)
        month_cogs = UnifiedFinanceCalculator.calculate_cogs(month_start, month_end)
        month_profit = month_revenue - month_cogs
        month_count = active_sales_qs.filter(
            sale_date__date__gte=month_start,
            sale_date__date__lte=month_end
        ).count()
        
        margin = (month_profit / month_revenue * 100) if month_revenue > 0 else 0
        
        monthly_sales_breakdown.append({
            'month': month_start.strftime('%B %Y'),
            'month_name': month_start.strftime('%B'),
            'year': month_start.year,
            'count': month_count,
            'revenue': month_revenue,
            'profit': month_profit,
            'margin': margin,
        })
        
        year_total_revenue += month_revenue
        year_total_count += month_count
        year_total_profit += month_profit
    
    year_margin = (year_total_profit / year_total_revenue * 100) if year_total_revenue > 0 else 0
    
    # ============================================
    # CHART DATA (Last 30 days)
    # ============================================
    daily_sales = []
    thirty_days_ago = today - timedelta(days=29)
    
    for i in range(30):
        day = thirty_days_ago + timedelta(days=i)
        day_revenue = UnifiedFinanceCalculator.calculate_revenue(day, day)
        
        daily_sales.append({
            'date': day.strftime('%Y-%m-%d'),
            'display_date': day.strftime('%d %b'),
            'revenue': float(day_revenue),
        })
    
    # ============================================
    # HOURLY SALES (Today)
    # ============================================
    hourly_sales = []
    today_start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    
    for hour in range(6, 22):  # 6 AM to 9 PM
        hour_start = today_start.replace(hour=hour)
        hour_end = today_start.replace(hour=hour, minute=59, second=59)
        
        hour_revenue = active_sales_qs.filter(
            sale_date__range=[hour_start, hour_end]
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        
        hourly_sales.append({
            'hour': f"{hour:02d}:00",
            'revenue': float(hour_revenue),
        })
    
    # ============================================
    # PAYMENT METHODS
    # ============================================
    payment_methods = []
    for method in ['Cash', 'M-Pesa', 'Card', 'Points', 'Credit']:
        method_revenue = active_sales_qs.filter(payment_method=method).aggregate(
            total=Sum('total_amount')
        )['total'] or Decimal('0')
        
        method_count = active_sales_qs.filter(payment_method=method).count()
        
        if year_total_revenue > 0:
            percentage = (method_revenue / year_total_revenue) * 100
        else:
            percentage = 0
        
        payment_methods.append({
            'name': method,
            'revenue': float(method_revenue),
            'count': method_count,
            'percentage': float(percentage),
        })
    
    # ============================================
    # TOP PRODUCTS (with profit using COGS)
    # ============================================
    from inventory.models import StockEntry
    
    top_products_raw = SaleItem.objects.filter(
        sale__in=active_sales_qs,
        sale__is_reversed=False
    ).values('product_code', 'product_name').annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('total_price'),
    ).order_by('-total_revenue')[:10]
    
    top_products = []
    for product in top_products_raw:
        # Calculate COGS for this product
        product_cogs = Decimal('0')
        product_entries = StockEntry.objects.filter(
            entry_type='sale',
            quantity__lt=0,
            reference_id__in=active_sales_qs.values_list('sale_id', flat=True),
            product_sku__sku_code=product['product_code']
        )
        for entry in product_entries:
            product_cogs += abs(entry.quantity) * entry.unit_price
        
        product_profit = (product['total_revenue'] or Decimal('0')) - product_cogs
        product_margin = (product_profit / (product['total_revenue'] or 1)) * 100 if product['total_revenue'] > 0 else 0
        
        top_products.append({
            'product_code': product['product_code'],
            'product_name': product['product_name'],
            'total_quantity': product['total_quantity'] or 0,
            'total_revenue': product['total_revenue'] or Decimal('0'),
            'total_profit': product_profit,
            'margin': product_margin,
        })
    
    # ============================================
    # TOP SELLERS (with profit)
    # ============================================
    from django.contrib.auth.models import User
    
    top_sellers_raw = User.objects.filter(
        sales_made__in=active_sales_qs,
        sales_made__is_reversed=False
    ).annotate(
        sales_count=Count('sales_made'),
        total_revenue=Sum('sales_made__total_amount')
    ).order_by('-total_revenue')[:10]
    
    top_sellers = []
    for seller in top_sellers_raw:
        seller_sales = active_sales_qs.filter(seller=seller)
        seller_cogs = Decimal('0')
        for sale in seller_sales:
            sale_cogs = UnifiedFinanceCalculator.calculate_cogs(sale.sale_date, sale.sale_date)
            seller_cogs += sale_cogs
        
        seller_profit = (seller.total_revenue or Decimal('0')) - seller_cogs
        seller_margin = (seller_profit / (seller.total_revenue or 1)) * 100 if seller.total_revenue > 0 else 0
        
        top_sellers.append({
            'id': seller.id,
            'username': seller.username,
            'first_name': seller.first_name,
            'last_name': seller.last_name,
            'get_full_name': seller.get_full_name(),
            'sales_count': seller.sales_count or 0,
            'total_revenue': seller.total_revenue or Decimal('0'),
            'total_profit': seller_profit,
            'margin': seller_margin,
        })
    
    # ============================================
    # ADDITIONAL STATS
    # ============================================
    credit_sales = active_sales_qs.filter(is_credit=True)
    credit_count = credit_sales.count()
    credit_revenue = credit_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
    credit_percentage = (credit_revenue / year_total_revenue * 100) if year_total_revenue > 0 else 0
    
    etr_processed = active_sales_qs.filter(etr_receipt_number__isnull=False).count()
    etr_pending = active_sales_qs.filter(etr_receipt_number__isnull=True).count()
    etr_failed = 0
    
    reversed_sales = Sale.objects.filter(is_reversed=True)
    reversed_count = reversed_sales.count()
    reversed_amount = reversed_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
    reversal_percentage = (reversed_count / (active_sales_qs.count() + reversed_count) * 100) if (active_sales_qs.count() + reversed_count) > 0 else 0
    
    # ============================================
    # CONTEXT
    # ============================================
    context = {
        # Summary Cards
        'total_sales': active_sales_qs.count(),
        'total_revenue': float(year_total_revenue),
        'year_profit': float(year_total_profit),
        'profit_margin': float((year_total_profit / year_total_revenue * 100) if year_total_revenue > 0 else 0),
        'avg_transaction_value': float((year_total_revenue / active_sales_qs.count()) if active_sales_qs.count() > 0 else 0),
        'avg_items_per_sale': 0,
        'avg_profit_per_sale': float((year_total_profit / active_sales_qs.count()) if active_sales_qs.count() > 0 else 0),
        
        # Daily breakdown
        'daily_sales_breakdown': daily_sales_breakdown,
        'daily_totals': daily_totals,
        
        # Weekly breakdown
        'weekly_sales_breakdown': weekly_sales_breakdown,
        'month_revenue': float(month_data['revenue']),
        'month_count': month_data.get('sales_count', 0),
        'month_profit': float(month_data['net_profit']),
        'month_margin': float((month_data['net_profit'] / month_data['revenue'] * 100) if month_data['revenue'] > 0 else 0),
        
        # Monthly breakdown
        'monthly_sales_breakdown': monthly_sales_breakdown,
        'year_revenue': float(year_total_revenue),
        'year_count': year_total_count,
        'year_profit': float(year_total_profit),
        'year_margin': float(year_margin),
        
        # Period profit cards
        'today_revenue': float(today_data['revenue']),
        'today_count': today_data.get('sales_count', 0),
        'today_profit': float(today_data['net_profit']),
        
        # Charts
        'daily_sales': daily_sales,
        'hourly_sales': hourly_sales,
        'payment_methods': payment_methods,
        
        # Top products and sellers
        'top_products': top_products,
        'top_sellers': top_sellers,
        
        # Additional stats
        'credit_count': credit_count,
        'credit_revenue': float(credit_revenue),
        'credit_percentage': float(credit_percentage),
        'etr_processed': etr_processed,
        'etr_pending': etr_pending,
        'etr_failed': etr_failed,
        'reversed_count': reversed_count,
        'reversed_amount': float(reversed_amount),
        'reversal_percentage': reversal_percentage,
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


# ========================================
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
    """API endpoint to get sale details with items (SKU-based model)"""
    try:
        from inventory.models import StockEntry, ProductUnit
        
        sale = Sale.objects.get(sale_id=sale_id)
        items = SaleItem.objects.filter(sale=sale).select_related(
            'product', 
            'product__category',
            'product_unit'
        )
        
        total_profit = Decimal('0.00')
        items_data = []
        
        for item in items:
            # Get product display name
            product_name = item.product_name or (item.product.display_name if item.product else 'Unknown')
            
            # Get buying price (either from product or from unit override)
            buying_price = Decimal('0.00')
            if item.product_unit and item.product_unit.unit_buying_price:
                buying_price = item.product_unit.unit_buying_price
            elif item.product and item.product.buying_price:
                buying_price = item.product.buying_price
            
            # Calculate profit
            profit = (item.unit_price - buying_price) * item.quantity if buying_price > 0 else Decimal('0.00')
            total_profit += profit
            
            # Get identifier if it's a single item
            identifier = None
            identifier_type = None
            if item.product_unit:
                if item.product_unit.imei_number:
                    identifier = item.product_unit.imei_number
                    identifier_type = 'IMEI'
                elif item.product_unit.serial_number:
                    identifier = item.product_unit.serial_number
                    identifier_type = 'Serial'
            
            # Get stock entry reference
            stock_entry = StockEntry.objects.filter(
                models.Q(product_sku=item.product) | 
                models.Q(product_unit=item.product_unit),
                entry_type='sale',
                reference_id=sale.sale_id
            ).first()
            
            items_data.append({
                'product_name': product_name,
                'product_sku': item.product.sku_code if item.product else None,
                'quantity': item.quantity,
                'unit_price': float(item.unit_price),
                'total_price': float(item.total_price),
                'buying_price': float(buying_price),
                'profit': float(profit),
                'profit_margin': float((profit / (item.unit_price * item.quantity) * 100)) if item.unit_price > 0 else 0,
                'is_single_item': item.product.category.is_single_item if item.product and item.product.category else False,
                'identifier': identifier,
                'identifier_type': identifier_type,
                'sku_type': item.product.category.identifier_type if item.product and item.product.category else None,
            })
        
        # Get customer info
        customer_name = sale.buyer_name or 'Walk-in Customer'
        if sale.customer:
            customer_name = sale.customer.full_name
        
        # Get payment method badge color
        payment_colors = {
            'Cash': 'success',
            'M-Pesa': 'info',
            'Card': 'primary',
            'Points': 'warning',
            'Credit': 'danger',
            'Split': 'secondary'
        }
        
        sale_data = {
            'success': True,
            'sale': {
                'id': sale.id,
                'sale_id': sale.sale_id,
                'sequence_number': sale.sequence_number,
                'created_at': sale.sale_date.strftime('%Y-%m-%d %H:%M:%S'),
                'customer_name': customer_name,
                'customer_phone': sale.buyer_phone or '',
                'customer_id_number': sale.buyer_id_number or '',
                'seller_name': sale.seller.get_full_name() if sale.seller else (sale.seller.username if sale.seller else 'System'),
                'payment_method': sale.payment_method,
                'payment_method_color': payment_colors.get(sale.payment_method, 'secondary'),
                'status': 'completed' if not sale.is_reversed else 'reversed',
                'status_badge': 'success' if not sale.is_reversed else 'danger',
                'is_credit': sale.is_credit,
                'is_reversed': sale.is_reversed,
                'subtotal': float(sale.subtotal),
                'tax_amount': float(sale.tax_amount),
                'discount': float(sale.points_discount) if sale.points_discount else 0,
                'total_amount': float(sale.total_amount),
                'amount_paid': float(sale.amount_paid),
                'change': float(sale.change),
                'balance': float(sale.balance),
                'total_profit': float(total_profit),
                'items_count': items.count(),
                'profit_margin': float((total_profit / sale.total_amount * 100)) if sale.total_amount > 0 else 0,
                'points_redeemed': sale.points_redeemed,
                'points_discount': float(sale.points_discount) if sale.points_discount else 0,
                'points_earned': float(sale.points_earned) if sale.points_earned else 0,
                'items': items_data,
                'receipt_url': f'/sales/receipt/{sale.sale_id}/'
            }
        }
        
        # Add credit sale info if applicable
        if sale.is_credit and sale.credit_sale_id:
            sale_data['sale']['credit_sale_id'] = sale.credit_sale_id
            sale_data['sale']['credit_url'] = f'/credit/detail/{sale.credit_sale_id}/'
        
        # Add ETR info
        if sale.etr_receipt_number:
            sale_data['sale']['etr_receipt_number'] = sale.etr_receipt_number
            sale_data['sale']['etr_status'] = sale.etr_status
        
        return JsonResponse(sale_data)
        
    except Sale.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Sale not found'}, status=404)
    except Exception as e:
        logger.error(f"Error getting sale details: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
def search_products(request):
    """AJAX endpoint to search products - FIXED for SKU model"""
    from django.db.models import Q
    
    query = request.GET.get('q', '').strip()
    
    if not query or len(query) < 2:
        return JsonResponse([], safe=False)
    
    try:
        # Search by sku_code, name, brand, model
        products = Product.objects.filter(
            Q(sku_code__icontains=query) |
            Q(name__icontains=query) |
            Q(display_name__icontains=query) |
            Q(brand__icontains=query) |
            Q(model__icontains=query),
            is_active=True,
            is_discontinued=False
        ).select_related('category')[:20]
        
        results = []
        for product in products:
            # Calculate available stock
            if product.category and product.category.is_single_item:
                stock = product.units.filter(status='available').count()
            else:
                stock = product.bulk_quantity or 0
            
            results.append({
                'code': product.sku_code,
                'name': product.display_name,
                'price': float(product.selling_price),
                'stock': stock,
                'is_single': product.category.is_single_item if product.category else False,
                'sku': product.sku_code,
                'brand': product.brand or '',
                'category': product.category.name if product.category else '',
            })
        
        return JsonResponse(results, safe=False)
        
    except Exception as e:
        logger.error(f"Error searching products: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)

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
    
    # Recent sales - DON'T try to set item_count, it's already a property!
    recent_sales = Sale.objects.order_by('-sale_date')[:5]
    # REMOVE THIS LINE:
    # for sale in recent_sales:
    #     sale.item_count = sale.items.count()
    
    # Top selling products
    top_products = SaleItem.objects.values(
        'product__name', 
        'product__category__item_type'
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
    
    # ============================================
    # HOURLY SALES DATA
    # ============================================
    hourly_labels = []
    hourly_data = []
    
    # Get today's date range
    today_start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
    today_end = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.max.time()))
    
    # Query sales for today (only non-reversed sales)
    today_sales_qs = Sale.objects.filter(
        sale_date__range=[today_start, today_end],
        is_reversed=False
    )
    
    # Create hour labels from 7 AM to 10 PM (14 hours)
    for hour in range(7, 22):  # 7 AM to 9 PM
        hourly_labels.append(f"{hour:02d}:00")
        
        # Get sales for this hour
        hour_start = today_start.replace(hour=hour, minute=0, second=0, microsecond=0)
        hour_end = today_start.replace(hour=hour, minute=59, second=59, microsecond=999999)
        
        hour_sales = today_sales_qs.filter(
            sale_date__range=[hour_start, hour_end]
        ).aggregate(total=Sum('total_amount'))['total'] or 0
        
        hourly_data.append(float(hour_sales))
    
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
        'hourly_labels': hourly_labels,
        'hourly_data': hourly_data,     
    }
    
    return render(request, 'sales/dashboard.html', context)

@login_required
def sale_list(request):
    """List all sales with filtering"""
    from django.db.models import Q, Sum, Count
    from django.core.paginator import Paginator
    from datetime import timedelta
    from django.utils import timezone
    
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
    # PAYMENT METHOD FILTER
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
    
    # Status filter
    status_filter = request.GET.get('status')
    if status_filter == 'reversed':
        sales = sales.filter(is_reversed=True)
    elif status_filter == 'completed':
        sales = sales.filter(is_reversed=False)
    
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
            Q(buyer_phone__icontains=search) |
            Q(buyer_id_number__icontains=search)
        )
    
    # ============================================
    # Get per_page parameter (default 20)
    # ============================================
    per_page = request.GET.get('per_page', '20')
    if per_page == 'all':
        # For 'all', use a large number or handle differently
        per_page = sales.count() if sales.count() > 0 else 20
    else:
        try:
            per_page = int(per_page)
            if per_page not in [10, 20, 25, 50, 100]:
                per_page = 20
        except ValueError:
            per_page = 20
    
    # ============================================
    # Calculate summary statistics
    # ============================================
    # Total sales count (filtered)
    total_sales_count = sales.count()
    
    # Total revenue (filtered)
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    
    # Today's revenue
    today = timezone.now().date()
    today_revenue = Sale.objects.filter(
        sale_date__date=today,
        is_reversed=False
    ).aggregate(total=Sum('total_amount'))['total'] or 0
    
    # Today's sales count
    today_sales_count = Sale.objects.filter(
        sale_date__date=today,
        is_reversed=False
    ).count()
    
    # Total items sold (from filtered sales - limit for performance)
    total_items_sold = 0
    for sale in sales[:500]:  # Limit to last 500 sales for performance
        total_items_sold += sale.items.count()
    
    # Get available payment methods for dropdown
    available_methods = Sale.objects.filter(
        is_reversed=False
    ).values_list('payment_method', flat=True).distinct().order_by('payment_method')
    
    # ============================================
    # Pagination
    # ============================================
    paginator = Paginator(sales, per_page)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Calculate date shortcuts
    week_ago = timezone.now().date() - timedelta(days=7)
    month_ago = timezone.now().date() - timedelta(days=30)
    year_ago = timezone.now().date() - timedelta(days=365)
    
    # ============================================
    # Context
    # ============================================
    context = {
        'sales': page_obj,
        'available_methods': available_methods,
        'per_page': per_page,
        
        # Summary stats
        'total_sales_count': total_sales_count,
        'total_revenue': total_revenue,
        'today_revenue': today_revenue,
        'today_sales_count': today_sales_count,
        'total_items_sold': total_items_sold,
        
        # Date shortcuts
        'today': today,
        'week_ago': week_ago,
        'month_ago': month_ago,
        'year_ago': year_ago,
        
        # Current filters for maintaining selections
        'current_filters': {
            'date_from': date_from,
            'date_to': date_to,
            'payment_method': payment_method,
            'sale_type': sale_type,
            'status': status_filter,
            'search': search,
        }
    }
    return render(request, 'sales/list.html', context)

@login_required
def sale_create(request):
    """Create a new sale with loyalty points and M-Pesa support"""

    # ============================================
    # GET USER'S ASSIGNED SHOP FROM STAFF MODEL
    # ============================================
    current_shop = None
    try:
        from staff.models import Staff
        staff = Staff.objects.filter(user=request.user).first()
        if staff and staff.assigned_shop:
            current_shop = staff.assigned_shop
            logger.info(f"User {request.user.username} is assigned to shop: {current_shop.name} ({current_shop.code})")
        else:
            logger.warning(f"No staff record or assigned shop found for user {request.user.username}")
    except Exception as e:
        logger.error(f"Error getting user's shop from Staff model: {str(e)}")
    
    # Fallback to first active shop if no shop assigned
    if not current_shop:
        try:
            from shops.models import ShopBranch
            current_shop = ShopBranch.objects.filter(is_active=True).first()
            if current_shop:
                logger.info(f"Using fallback shop: {current_shop.name}")
        except Exception as e:
            logger.error(f"Error getting fallback shop: {str(e)}")

    if request.method == 'POST':
        # Check if it's an AJAX request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Get data based on request type
        if is_ajax:
            try:
                data = json.loads(request.body)
                buyer_phone = data.get('buyer_phone', '').strip()
                payment_method = data.get('payment_method', 'Cash')
                is_credit = data.get('is_credit', False)
                amount_paid = Decimal(str(data.get('amount_paid', '0')))
                points_redeemed = int(data.get('points_redeemed', '0'))
                verified_customer_id = data.get('verified_customer_id')
                cash_amount = Decimal(str(data.get('cash_amount', '0')))
                mpesa_amount = Decimal(str(data.get('mpesa_amount', '0')))
                bank_amount = Decimal(str(data.get('bank_amount', '0')))
                skip_cart_clear = data.get('skip_cart_clear', False)
                
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
        else:
            buyer_phone = request.POST.get('buyer_phone', '').strip()
            payment_method = request.POST.get('payment_method', 'Cash')
            is_credit = request.POST.get('is_credit') == 'on'
            points_redeemed = int(request.POST.get('points_redeemed', '0'))
            verified_customer_id = request.POST.get('verified_customer_id')
            cash_amount = Decimal(request.POST.get('cash_amount', '0'))
            mpesa_amount = Decimal(request.POST.get('mpesa_amount', '0'))
            bank_amount = Decimal(request.POST.get('bank_amount', '0'))
            skip_cart_clear = request.POST.get('skip_cart_clear') == 'true'
            
            if is_credit:
                amount_paid = Decimal('0.00')
            else:
                amount_paid = Decimal(request.POST.get('amount_paid', '0'))
        
        # If this is a split payment, use the total from split amounts
        if payment_method == 'Split':
            total_paid = cash_amount + mpesa_amount + bank_amount + Decimal(str(points_redeemed))
            amount_paid = total_paid
        
        # Get cart items from session
        cart = request.session.get('sales_cart', [])
        
        if not cart:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'No items in cart.'})
            messages.error(request, 'No items in cart.')
            return redirect('sales:sale_create')
        
        try:
            with transaction.atomic():
                # Normalize phone number
                def normalize_phone(phone):
                    if not phone:
                        return ''
                    phone = ''.join(filter(str.isdigit, phone))
                    if phone.startswith('0') and len(phone) == 10:
                        return '254' + phone[1:]
                    if phone.startswith('254') and len(phone) == 12:
                        return phone
                    if len(phone) == 9:
                        return '254' + phone
                    return phone
                
                normalized_phone = normalize_phone(buyer_phone)
                logger.info(f"Phone normalized: '{buyer_phone}' -> '{normalized_phone}'")
                
                # Calculate original subtotal
                original_subtotal = Decimal('0.00')
                for item in cart:
                    original_subtotal += Decimal(str(item.get('total', 0)))
                
                # Loyalty points redemption
                points_discount = Decimal('0.00')
                final_amount = original_subtotal
                customer = None
                is_registered_customer = False
                
                if verified_customer_id:
                    try:
                        customer = Customer.objects.get(id=verified_customer_id, is_active=True)
                        is_registered_customer = True
                        logger.info(f"✅ Registered customer found by ID: {customer.phone_number} - {customer.full_name}")
                    except Customer.DoesNotExist:
                        logger.warning(f"Customer with ID {verified_customer_id} not found")
                
                if not is_registered_customer and normalized_phone:
                    try:
                        customer = Customer.objects.get(phone_number=normalized_phone, is_active=True)
                        is_registered_customer = True
                        logger.info(f"✅ Registered customer found by phone: {customer.phone_number} - {customer.full_name}")
                    except Customer.DoesNotExist:
                        logger.info(f"⚠️ Unregistered customer: {normalized_phone} - no points awarded")
                
                if is_registered_customer and points_redeemed > 0:
                    if customer.points_balance < points_redeemed:
                        raise ValueError(f"Insufficient points. Available: {customer.points_balance}, Requested: {points_redeemed}")
                    
                    points_discount = Decimal(str(points_redeemed))
                    if points_discount > original_subtotal:
                        points_discount = original_subtotal
                        points_redeemed = int(original_subtotal)
                    
                    final_amount = original_subtotal - points_discount
                    if amount_paid > final_amount:
                        amount_paid = final_amount
                    
                    logger.info(f"💰 Points redemption: {points_redeemed} points = KSH {points_discount} discount")
                elif points_redeemed > 0 and not is_registered_customer:
                    raise ValueError(f"Cannot redeem points. Customer {buyer_phone} is not registered.")
                
                # Create the sale
                sale = Sale.objects.create(
                    seller=request.user,
                    buyer_name=customer.full_name if is_registered_customer and customer else 'Walk-in Customer',
                    buyer_phone=normalized_phone,
                    buyer_id_number=customer.id_number if is_registered_customer and customer else '',
                    nok_name='',
                    nok_phone='',
                    payment_method=payment_method,
                    amount_paid=amount_paid,
                    total_amount=final_amount,
                    subtotal=original_subtotal,
                    is_credit=is_credit,
                    points_redeemed=points_redeemed if is_registered_customer else 0,
                    points_discount=points_discount if is_registered_customer else Decimal('0.00'),
                    original_subtotal=original_subtotal
                )
                
                # Process each cart item
                for item in cart:
                    # Get product by SKU code
                    product = Product.objects.select_for_update().get(sku_code=item['sku_code'], is_active=True)
                    product.refresh_from_db()
                    
                    # Check stock based on item type
                    if product.category.is_single_item:
                        # Check available units
                        available_units = product.units.filter(status='available').count()
                        if available_units <= 0:
                            raise ValueError(f"No available units for {product.display_name}")
                        
                        # Get first available unit
                        unit = product.units.filter(status='available').first()
                        
                        # Check if already sold
                        active_sale_exists = SaleItem.objects.filter(
                            sku_value=product.sku_code,
                            sale__is_reversed=False
                        ).exists()
                        if active_sale_exists:
                            raise ValueError(f"This {product.display_name} (SKU: {product.sku_code}) has already been sold!")
                        
                        # Mark unit as sold
                        unit.mark_as_sold(
                            customer=customer if is_registered_customer else None,
                            price=Decimal(str(item['price'])),
                            sold_by=request.user
                        )
                        
                        # Create sale item
                        SaleItem.objects.create(
                            sale=sale,
                            product=product,
                            product_code=product.sku_code,
                            product_name=product.display_name,
                            sku_value=product.sku_code,
                            quantity=1,
                            unit_price=Decimal(str(item['price'])),
                            total_price=Decimal(str(item['total']))
                        )
                        
                        # Create stock entry for unit
                        StockEntry.objects.create(
                            product_unit=unit,
                            quantity=-1,
                            entry_type='sale',
                            unit_price=Decimal(str(item['price'])),
                            total_amount=Decimal(str(item['total'])),
                            reference_id=sale.sale_id,
                            notes=f"Sale #{sale.sale_id} - {product.display_name}",
                            created_by=request.user
                        )
                        
                    else:
                        # Bulk item
                        if product.bulk_quantity < item['quantity']:
                            raise ValueError(f"Insufficient stock for {product.display_name}. Available: {product.bulk_quantity}")
                        
                        product.bulk_quantity -= item['quantity']
                        product.save()
                        
                        SaleItem.objects.create(
                            sale=sale,
                            product=product,
                            product_code=product.sku_code,
                            product_name=product.display_name,
                            sku_value=product.sku_code,
                            quantity=item['quantity'],
                            unit_price=Decimal(str(item['price'])),
                            total_price=Decimal(str(item['total']))
                        )
                        
                        StockEntry.objects.create(
                            product_sku=product,
                            quantity=-item['quantity'],
                            entry_type='sale',
                            unit_price=Decimal(str(item['price'])),
                            total_amount=Decimal(str(item['total'])),
                            reference_id=sale.sale_id,
                            notes=f"Sale #{sale.sale_id} - {product.display_name}",
                            created_by=request.user
                        )
                
                # Loyalty points earning
                points_earned = 0
                if is_registered_customer and customer:
                    if points_redeemed > 0:
                        customer.redeem_points(points_redeemed, sale=sale, description=f"Redeemed for sale #{sale.sale_id}")
                    
                    customer.total_purchases += 1
                    customer.total_spent += original_subtotal
                    customer.last_purchase_date = timezone.now()
                    customer.save()
                    
                    points_to_add = customer.calculate_points_to_earn(float(final_amount))
                    points_earned = customer.add_points(points_to_add, sale=sale, description=f"Purchase #{sale.sale_id}")
                    
                    logger.info(f"💰 Registered customer {customer.phone_number}: Earned {points_earned} points")
                
                # Clear the cart
                if not skip_cart_clear:
                    request.session['sales_cart'] = []
                
                # Handle credit sale if needed
                if is_credit:
                    try:
                        from credit.models import CreditSale
                        CreditSale.objects.create(
                            sale_id=sale.sale_id,
                            customer_name=customer.full_name if is_registered_customer and customer else "Walk-in Customer",
                            customer_phone=normalized_phone,
                            customer_id_number=customer.id_number if is_registered_customer and customer else '',
                            nok_name='',
                            nok_phone='',
                            total_amount=final_amount,
                            created_by=request.user,
                        )
                    except ImportError:
                        logger.warning(f"Credit app not found for sale #{sale.sale_id}")
                    except Exception as e:
                        logger.error(f"Credit record creation failed: {str(e)}")
                
                # Return response
                if is_ajax:
                    response_data = {
                        'success': True,
                        'sale_id': sale.sale_id,
                        'message': 'Sale completed successfully!'
                    }
                    
                    if is_registered_customer and customer:
                        response_data['points'] = {
                            'earned': int(points_earned),
                            'redeemed': points_redeemed,
                            'balance': customer.points_balance,
                            'discount': float(points_discount) if points_discount > 0 else 0
                        }
                    elif normalized_phone and not is_registered_customer:
                        response_data['warning'] = f'Phone {normalized_phone} is not registered. No points awarded.'
                    
                    return JsonResponse(response_data)
                else:
                    if is_registered_customer and points_earned > 0:
                        messages.success(request, f'Sale #{sale.sale_id} completed! You earned {int(points_earned)} loyalty points!')
                    elif points_redeemed > 0 and is_registered_customer:
                        messages.success(request, f'Sale #{sale.sale_id} completed! Redeemed {points_redeemed} points for KSH {points_discount} discount!')
                    elif normalized_phone and not is_registered_customer:
                        messages.warning(request, f'Sale completed but NO POINTS awarded. Phone {normalized_phone} is not registered.')
                        messages.info(request, f'<a href="/sales/customer/register/?phone={normalized_phone}" class="alert-link">Click here to register</a> and start earning points!')
                    else:
                        messages.success(request, f'Sale #{sale.sale_id} completed successfully!')
                    
                    return redirect('staff:cashier_dashboard')
                
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
        'current_shop': current_shop, 
    }
    return render(request, 'sales/create.html', context)


@login_required
def sale_create_api(request):
    """API endpoint for POS sale creation - ALWAYS returns JSON"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    
    try:
        data = json.loads(request.body)
        
        # Get cart from session
        cart = request.session.get('sales_cart', [])
        
        if not cart:
            return JsonResponse({'success': False, 'error': 'No items in cart'})
        
        # ============================================
        # DUPLICATE PREVENTION - Check if sale already processing
        # ============================================
        import hashlib
        from django.core.cache import cache
        
        # Create unique hash from cart contents
        cart_hash = hashlib.md5(json.dumps(cart, sort_keys=True).encode()).hexdigest()
        cache_key = f"sale_processing_{cart_hash}"
        
        if cache.get(cache_key):
            print(f"⚠️ DUPLICATE SALE DETECTED! Cart hash: {cart_hash}")
            return JsonResponse({
                'success': False, 
                'error': 'Sale already being processed. Please wait.',
                'duplicate': True
            })
        
        # Set cache to prevent duplicate (15 second timeout)
        cache.set(cache_key, True, 15)
        
        # ============================================
        # CRITICAL: Generate a unique request ID to prevent duplicate sale creation
        # ============================================
        import uuid
        request_id = str(uuid.uuid4())
        idempotency_key = f"sale_idempotent_{request_id}"
        
        if cache.get(idempotency_key):
            print(f"⚠️ DUPLICATE REQUEST DETECTED! ID: {request_id}")
            cache.delete(cache_key)
            return JsonResponse({
                'success': False,
                'error': 'Duplicate request detected. Please wait.',
                'duplicate': True
            })
        
        cache.set(idempotency_key, True, 60)  # 1 minute
        
        # Debug: Print cart contents
        print("=" * 60)
        print(f"🔍 SALE CREATE API - Request ID: {request_id}")
        for idx, item in enumerate(cart):
            print(f"Item {idx}:")
            print(f"  sku_code: {item.get('sku_code')}")
            print(f"  unit_id: {item.get('unit_id')}")
            print(f"  is_single: {item.get('is_single')}")
            print(f"  identifier: {item.get('identifier')}")
            print(f"  quantity: {item.get('quantity')}")
            print(f"  selling_price: {item.get('price')}")
        print("=" * 60)
        
        with transaction.atomic():
            # Normalize phone
            def normalize_phone(phone):
                if not phone:
                    return ''
                phone = ''.join(filter(str.isdigit, phone))
                if phone.startswith('0') and len(phone) == 10:
                    return '254' + phone[1:]
                if phone.startswith('254') and len(phone) == 12:
                    return phone
                if len(phone) == 9:
                    return '254' + phone
                return phone
            
            buyer_phone = data.get('buyer_phone', '').strip()
            normalized_phone = normalize_phone(buyer_phone)
            
            payment_method = data.get('payment_method', 'Cash')
            amount_paid = Decimal(str(data.get('amount_paid', '0')))
            points_redeemed = int(data.get('points_redeemed', '0'))
            points_to_award = int(data.get('points_to_award', '0'))
            verified_customer_id = data.get('verified_customer_id')
            cash_amount = Decimal(str(data.get('cash_amount', '0')))
            mpesa_amount = Decimal(str(data.get('mpesa_amount', '0')))
            bank_amount = Decimal(str(data.get('bank_amount', '0')))
            
            # Calculate original subtotal (using selling prices from cart)
            original_subtotal = Decimal('0.00')
            for item in cart:
                original_subtotal += Decimal(str(item.get('total', 0)))
            
            # Customer lookup
            customer = None
            is_registered_customer = False
            
            if verified_customer_id:
                try:
                    customer = Customer.objects.get(id=verified_customer_id, is_active=True)
                    is_registered_customer = True
                except Customer.DoesNotExist:
                    pass
            
            if not is_registered_customer and normalized_phone:
                try:
                    customer = Customer.objects.get(phone_number=normalized_phone, is_active=True)
                    is_registered_customer = True
                except Customer.DoesNotExist:
                    pass
            
            # Points discount
            points_discount = Decimal('0.00')
            final_amount = original_subtotal
            
            if is_registered_customer and points_redeemed > 0:
                if customer.points_balance >= points_redeemed:
                    points_discount = Decimal(str(points_redeemed))
                    if points_discount > original_subtotal:
                        points_discount = original_subtotal
                        points_redeemed = int(original_subtotal)
                    final_amount = original_subtotal - points_discount
                else:
                    raise ValueError(f"Insufficient points. Available: {customer.points_balance}, Requested: {points_redeemed}")
            
            # ============================================
            # CRITICAL FIX: Check for existing sale with same cart BEFORE creating
            # ============================================
            existing_sale_key = f"temp_sale_{cart_hash}"
            if cache.get(existing_sale_key):
                print(f"⚠️ DUPLICATE SALE DETECTED! Sale already in progress for cart: {cart_hash}")
                cache.delete(cache_key)
                cache.delete(idempotency_key)
                return JsonResponse({
                    'success': False,
                    'error': 'This sale is already being processed. Please wait.',
                    'duplicate': True
                })
            
            # Mark this cart as having a sale in progress
            cache.set(existing_sale_key, True, 30)
            
            print("📝 Creating sale...")
            # Create sale
            sale = create_sale_safely(
                seller=request.user,
                buyer_name=customer.full_name if is_registered_customer and customer else data.get('buyer_name', 'Walk-in Customer'),
                buyer_phone=normalized_phone,
                payment_method=payment_method,
                amount_paid=amount_paid,
                total_amount=final_amount,
                subtotal=original_subtotal,
                is_credit=False,
                points_redeemed=points_redeemed if is_registered_customer else 0,
                points_discount=points_discount if is_registered_customer else Decimal('0.00'),
                original_subtotal=original_subtotal
            )
            print(f"✅ Sale created: {sale.sale_id}")
            
            # ============================================
            # DOUBLE CHECK: Verify sale wasn't already processed (use select_for_update)
            # ============================================
            from finance.models import NetTransaction
            
            # Use select_for_update to lock the row and prevent race conditions
            already_processed = NetTransaction.objects.select_for_update().filter(
                description__icontains=sale.sale_id,
                category='cogs'
            ).exists()
            
            if already_processed:
                print(f"⚠️ Sale {sale.sale_id} already processed! Rolling back...")
                cache.delete(cache_key)
                cache.delete(idempotency_key)
                cache.delete(existing_sale_key)
                # Rollback the transaction
                raise transaction.TransactionManagementError("Sale already processed")
            
            # Deduct points AFTER sale is created (needs sale ID)
            if is_registered_customer and points_redeemed > 0:
                customer.redeem_points(points_redeemed, sale=sale, description=f"Redeemed {points_redeemed} points for sale #{sale.sale_id}")
                logger.info(f"💰 Points redeemed: {points_redeemed} points deducted from customer {customer.phone_number}")
            
            # Track COGS total for reporting
            total_cogs = Decimal('0.00')
            
            # Process items
            for idx, item in enumerate(cart):
                print(f"\n📦 Processing item {idx}...")
                # Get product by SKU code
                sku_code = item.get('sku_code') or item.get('product_code')
                product = Product.objects.select_for_update().get(sku_code=sku_code, is_active=True)
                
                # Get selling price (what customer pays)
                selling_price = Decimal(str(item.get('price', 0)))
                quantity = item.get('quantity', 1)
                total_selling = selling_price * quantity
                
                if product.category.is_single_item:
                    # ============================================
                    # SINGLE ITEM (Phones, Electronics with unique ID)
                    # ============================================
                    print(f"   Single item - product: {product.sku_code}")
                    unit_id = item.get('unit_id')
                    
                    if unit_id:
                        unit = ProductUnit.objects.select_for_update().get(id=unit_id, product=product)
                        print(f"   Found unit by ID {unit_id}: Status={unit.status}")
                    else:
                        unit = product.units.filter(status='available').first()
                        print(f"   No unit_id, using first available: ID={unit.id if unit else 'None'}")
                    
                    if not unit:
                        raise ValueError(f"No available units for {product.display_name}")
                    
                    if unit.status != 'available':
                        raise ValueError(f"Unit {unit.unique_identifier} is not available (status: {unit.status}")
                    
                    # Get buying price (cost) for COGS
                    buying_price = unit.unit_buying_price or unit.product.buying_price
                    if not buying_price or buying_price == 0:
                        raise ValueError(f"No buying price set for {product.display_name}")
                    
                    print(f"   Selling Price: {selling_price} | Buying Price (COGS): {buying_price}")
                    
                    # ============================================
                    # 1. CREATE STOCK ENTRY FOR COGS (USING BUYING PRICE)
                    # ============================================
                    print(f"   Creating StockEntry for COGS...")
                    StockEntry.objects.create(
                        product_unit=unit,
                        quantity=-1,
                        entry_type='sale',
                        unit_price=buying_price,  # ← BUYING PRICE for COGS!
                        total_amount=buying_price,  # ← BUYING PRICE total!
                        reference_id=sale.sale_id,
                        notes=f"Sale #{sale.sale_id} - COGS (cost: {buying_price})",
                        created_by=request.user
                    )
                    print(f"   ✅ COGS StockEntry created (cost: {buying_price})")
                    total_cogs += buying_price
                    
                    # ============================================
                    # 2. CREATE SALE ITEM (USING SELLING PRICE)
                    # ============================================
                    print(f"   Creating SaleItem for revenue...")
                    SaleItem.objects.create(
                        sale=sale,
                        product=product,
                        product_code=product.sku_code,
                        product_name=product.display_name,
                        sku_value=product.sku_code,
                        quantity=1,
                        unit_price=selling_price,  # ← SELLING PRICE for revenue
                        total_price=selling_price,  # ← SELLING PRICE total
                        product_unit=unit
                    )
                    print(f"   ✅ SaleItem created (revenue: {selling_price})")
                    
                    # ============================================
                    # 3. MARK UNIT AS SOLD
                    # ============================================
                    print(f"   Marking unit {unit.id} as sold...")
                    unit.mark_as_sold(
                        customer=customer if is_registered_customer else None,
                        price=selling_price,
                        sold_by=request.user
                    )
                    print(f"   ✅ Unit {unit.id} marked as sold")
                    
                else:
                    # ============================================
                    # BULK ITEM (Cables, Accessories without unique ID)
                    # ============================================
                    print(f"   Bulk item - product: {product.sku_code}")
                    quantity = item.get('quantity', 1)
                    
                    if product.bulk_quantity < quantity:
                        raise ValueError(f"Insufficient stock for {product.display_name}. Available: {product.bulk_quantity}")
                    
                    # Get buying price (cost) for COGS
                    buying_price = product.buying_price
                    if not buying_price or buying_price == 0:
                        raise ValueError(f"No buying price set for {product.display_name}")
                    
                    print(f"   Selling Price: {selling_price} | Buying Price (COGS): {buying_price}")
                    print(f"   Quantity: {quantity}")
                    
                    # ============================================
                    # 1. CREATE STOCK ENTRY FOR COGS (USING BUYING PRICE)
                    # ============================================
                    print(f"   Creating StockEntry for COGS...")
                    StockEntry.objects.create(
                        product_sku=product,
                        quantity=-quantity,
                        entry_type='sale',
                        unit_price=buying_price,  # ← BUYING PRICE for COGS!
                        total_amount=buying_price * quantity,  # ← BUYING PRICE total!
                        reference_id=sale.sale_id,
                        notes=f"Sale #{sale.sale_id} - COGS (cost: {buying_price} each)",
                        created_by=request.user
                    )
                    print(f"   ✅ COGS StockEntry created (cost: {buying_price} x {quantity} = {buying_price * quantity})")
                    total_cogs += buying_price * quantity
                    
                    # ============================================
                    # 2. UPDATE BULK QUANTITY
                    # ============================================
                    product.bulk_quantity -= quantity
                    product.save(update_fields=['bulk_quantity', 'updated_at'])
                    print(f"   ✅ Bulk quantity updated: {product.bulk_quantity} remaining")
                    
                    # ============================================
                    # 3. CREATE SALE ITEM (USING SELLING PRICE)
                    # ============================================
                    print(f"   Creating SaleItem for revenue...")
                    SaleItem.objects.create(
                        sale=sale,
                        product=product,
                        product_code=product.sku_code,
                        product_name=product.display_name,
                        sku_value=product.sku_code,
                        quantity=quantity,
                        unit_price=selling_price,  # ← SELLING PRICE for revenue
                        total_price=selling_price * quantity,  # ← SELLING PRICE total
                    )
                    print(f"   ✅ SaleItem created (revenue: {selling_price} x {quantity} = {selling_price * quantity})")
            
            print(f"\n💰 Total COGS for this sale: {total_cogs}")
            print(f"💰 Total Revenue for this sale: {final_amount}")
            print(f"💰 Gross Profit for this sale: {final_amount - total_cogs}")
            
            # ============================================
            # UPDATE FINANCE ACCOUNTS (Net and Savings)
            # ============================================
            from finance.models import NetAccount, SavingsAccount, InventoryAsset
            
            net = NetAccount.get_account()
            savings = SavingsAccount.get_account()
            inventory_asset = InventoryAsset.get_account()
            
            profit = final_amount - total_cogs
            
            print(f"\n💰 UPDATING FINANCE ACCOUNTS:")
            print(f"   Total Revenue: KES {final_amount:,.2f}")
            print(f"   Total COGS: KES {total_cogs:,.2f}")
            print(f"   Profit: KES {profit:,.2f}")
            
            # Add COGS to Net Account (recouped cost)
            if total_cogs > 0:
                net.add_cogs(amount=total_cogs, sale_reference=sale.sale_id, user=request.user)
                print(f"   ✅ NET: +KES {total_cogs:,.2f} (COGS recouped)")
            
            # Add Profit to Savings Account
            if profit > 0:
                savings.add_profit(amount=profit, sale_reference=sale.sale_id, user=request.user)
                print(f"   ✅ SAVINGS: +KES {profit:,.2f} (Profit)")
            
            # Update Inventory Asset (deduct COGS)
            if total_cogs > 0:
                inventory_asset.deduct_cogs(
                    amount=total_cogs,
                    sku_code="MULTIPLE",
                    quantity=0,
                    unit_price=0,
                    sale_reference=sale.sale_id,
                    user=request.user
                )
                print(f"   ✅ INVENTORY ASSET: -KES {total_cogs:,.2f} (COGS deducted)")
            
            # Update Net balance display
            net_balance = net.balance
            savings_balance = savings.balance
            print(f"\n📊 Updated Balances:")
            print(f"   Net Account: KES {net_balance:,.2f}")
            print(f"   Savings Account: KES {savings_balance:,.2f}")
            
            # Award points
            print("\n💰 Awarding points...")
            points_earned = 0
            if is_registered_customer and customer:
                # Only award points if no points were redeemed
                if points_redeemed == 0:
                    # Calculate points to award (1 point per 100 KES spent)
                    points_to_award = points_to_award or int(final_amount / 100)
                    if points_to_award > 0:
                        points_earned = customer.add_points(
                            points_to_award, 
                            sale=sale, 
                            description=f"Points earned for sale #{sale.sale_id}"
                        )
                        print(f"   ✅ Points earned: {points_earned}")
                else:
                    print(f"   ℹ️ No points awarded because points were redeemed")
                
                # Update customer purchase statistics
                customer.total_purchases += 1
                customer.total_spent += original_subtotal
                customer.last_purchase_date = timezone.now()
                customer.save(update_fields=['total_purchases', 'total_spent', 'last_purchase_date', 'updated_at'])
                print(f"   ✅ Customer stats updated")
            
            # Clear the cart from session
            request.session['sales_cart'] = []
            
            # Clear all cache keys
            cache.delete(cache_key)
            cache.delete(idempotency_key)
            cache.delete(existing_sale_key)
            print("\n✅ Cart cleared and cache removed")
            
            # Prepare response data
            response_data = {
                'success': True,
                'sale_id': sale.sale_id,
                'message': 'Sale completed successfully!',
                'total_revenue': float(final_amount),
                'total_cogs': float(total_cogs),
                'gross_profit': float(final_amount - total_cogs)
            }
            
            # Add points information if customer is registered
            if is_registered_customer and customer:
                response_data['points'] = {
                    'earned': int(points_earned),
                    'redeemed': points_redeemed,
                    'balance': customer.points_balance,
                    'discount': float(points_discount) if points_discount > 0 else 0
                }
            elif normalized_phone and not is_registered_customer:
                response_data['warning'] = f'Phone {normalized_phone} is not registered. No points awarded.'
            
            print("\n🎉 Sale completed successfully!\n")
            return JsonResponse(response_data)
            
    except Product.DoesNotExist as e:
        print(f"\n❌ Product not found: {str(e)}")
        logger.error(f"Product not found: {str(e)}")
        if 'cache_key' in locals():
            cache.delete(cache_key)
        if 'idempotency_key' in locals():
            cache.delete(idempotency_key)
        if 'existing_sale_key' in locals():
            cache.delete(existing_sale_key)
        return JsonResponse({'success': False, 'error': f'Product not found: {str(e)}'})
    
    except ProductUnit.DoesNotExist as e:
        print(f"\n❌ Product unit not found: {str(e)}")
        logger.error(f"Product unit not found: {str(e)}")
        if 'cache_key' in locals():
            cache.delete(cache_key)
        if 'idempotency_key' in locals():
            cache.delete(idempotency_key)
        if 'existing_sale_key' in locals():
            cache.delete(existing_sale_key)
        return JsonResponse({'success': False, 'error': f'Product unit not found: {str(e)}'})
    
    except transaction.TransactionManagementError as e:
        print(f"\n⚠️ Transaction error: {str(e)}")
        if 'cache_key' in locals():
            cache.delete(cache_key)
        if 'idempotency_key' in locals():
            cache.delete(idempotency_key)
        if 'existing_sale_key' in locals():
            cache.delete(existing_sale_key)
        return JsonResponse({'success': False, 'error': str(e)})
    
    except ValueError as e:
        print(f"\n❌ Validation error: {str(e)}")
        logger.error(f"Validation error: {str(e)}")
        if 'cache_key' in locals():
            cache.delete(cache_key)
        if 'idempotency_key' in locals():
            cache.delete(idempotency_key)
        if 'existing_sale_key' in locals():
            cache.delete(existing_sale_key)
        return JsonResponse({'success': False, 'error': str(e)})
    
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        logger.error(f"Sale API error: {str(e)}", exc_info=True)
        if 'cache_key' in locals():
            cache.delete(cache_key)
        if 'idempotency_key' in locals():
            cache.delete(idempotency_key)
        if 'existing_sale_key' in locals():
            cache.delete(existing_sale_key)
        return JsonResponse({'success': False, 'error': str(e)})




@login_required
@csrf_exempt
def award_points_to_sale(request, sale_id):
    """Award points to a customer for a completed sale"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    
    try:
        data = json.loads(request.body)
        customer_id = data.get('customer_id')
        points = data.get('points', 0)
        
        sale = get_object_or_404(Sale, sale_id=sale_id)
        customer = get_object_or_404(Customer, id=customer_id, is_active=True)
        
        if points <= 0:
            return JsonResponse({'success': False, 'error': 'Invalid points amount'})
        
        # Award points to customer
        points_earned = customer.add_points(
            points,
            sale=sale,
            description=f"Points earned for M-Pesa sale #{sale.sale_id}"
        )
        
        # Update sale with customer info
        sale.buyer_name = customer.full_name
        sale.buyer_phone = customer.phone_number
        sale.save()
        
        return JsonResponse({
            'success': True,
            'message': f'{points} points awarded to {customer.full_name}',
            'points': points_earned
        })
        
    except Exception as e:
        logger.error(f"Error awarding points: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def update_sale_payment(request, sale_id):
    """Update sale payment status without finalizing (for M-Pesa)"""
    from decimal import Decimal
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            sale = get_object_or_404(Sale, sale_id=sale_id)
            
            amount = Decimal(str(data.get('amount_paid', 0)))
            payment_method = data.get('payment_method', 'M-Pesa')
            points_to_award = data.get('points_to_award', 0)
            verified_customer_id = data.get('verified_customer_id')
            buyer_phone = data.get('buyer_phone', '')
            points_redeemed = data.get('points_redeemed', 0)
            finalize = data.get('finalize', False)
            
            logger.info(f"📦 UPDATING SALE {sale_id}")
            logger.info(f"   Amount: {amount}, Payment: {payment_method}")
            logger.info(f"   Finalize: {finalize}")
            
            # Update sale with payment info
            sale.amount_paid = amount
            sale.payment_method = payment_method
            
            # Update customer info if provided
            if verified_customer_id:
                try:
                    from sales.models import Customer
                    customer = Customer.objects.get(id=verified_customer_id)
                    sale.buyer_name = customer.full_name
                    sale.buyer_phone = buyer_phone or customer.phone_number
                    logger.info(f"✅ Linked customer {customer.full_name} to sale {sale_id}")
                except Customer.DoesNotExist:
                    logger.warning(f"Customer {verified_customer_id} not found")
            
            sale.save()
            
            # If finalize is True, complete the sale
            if finalize:
                # Award points if any
                if points_to_award > 0 and verified_customer_id:
                    try:
                        customer = Customer.objects.get(id=verified_customer_id)
                        customer.add_points(
                            points_to_award,
                            sale=sale,
                            description=f"Points earned for sale #{sale.sale_id}"
                        )
                        logger.info(f"✅ Awarded {points_to_award} points to customer")
                    except Exception as e:
                        logger.error(f"Failed to award points: {str(e)}")
                
                # Deduct stock if not already deducted
                for item in sale.items.all():
                    if item.product:
                        stock_entry_exists = StockEntry.objects.filter(
                            reference_id=sale.sale_id,
                            entry_type='sale'
                        ).exists()
                        
                        if not stock_entry_exists:
                            product = item.product
                            
                            if product.category.is_single_item:
                                # For single items, mark the unit as sold
                                unit = ProductUnit.objects.filter(
                                    product=product,
                                    status='available'
                                ).first()
                                if unit:
                                    unit.mark_as_sold(
                                        customer=None,
                                        price=item.unit_price,
                                        sold_by=request.user
                                    )
                            else:
                                # For bulk items, deduct from bulk_quantity
                                product.bulk_quantity -= item.quantity
                                product.save()
                            
                            StockEntry.objects.create(
                                product_sku=product if not product.category.is_single_item else None,
                                product_unit=unit if product.category.is_single_item else None,
                                quantity=-item.quantity,
                                entry_type='sale',
                                unit_price=item.unit_price,
                                total_amount=item.total_price,
                                reference_id=sale.sale_id,
                                notes=f"Sale #{sale.sale_id} - Finalized",
                                created_by=request.user
                            )
                
                # Clear cart from session
                request.session['sales_cart'] = []
                
                return JsonResponse({
                    'success': True,
                    'sale_id': sale.sale_id,
                    'message': 'Sale completed successfully!',
                    'points_awarded': points_to_award
                })
            
            return JsonResponse({
                'success': True,
                'message': 'Payment recorded. Complete sale to award points.',
                'points_to_award': points_to_award,
                'customer_name': sale.buyer_name
            })
                
        except Exception as e:
            logger.error(f"Error updating sale payment: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})

@login_required
def sale_detail(request, sale_id):
    """View sale details with actual product information"""
    
    from decimal import Decimal
    from inventory.models import StockEntry, ProductUnit
    from django.db.models import Q
    
    # Get sale with related data
    sale = get_object_or_404(
        Sale.objects.select_related('seller', 'customer', 'reversed_by'),
        sale_id=sale_id
    )
    
    # Get items with product info
    items = sale.items.select_related('product', 'product__category').all()
    
    # Get all stock entries for this sale in ONE query
    stock_entries = StockEntry.objects.filter(
        Q(reference_id=sale.sale_id) | 
        Q(reference_id__icontains=sale.sale_id),
        entry_type='sale'
    ).select_related('product_unit', 'product_sku')
    
    # Create a mapping for quick lookup
    stock_map = {}
    for entry in stock_entries:
        if entry.product_unit:
            stock_map[entry.product_unit.product_id] = entry
        elif entry.product_sku:
            stock_map[entry.product_sku_id] = entry
    
    # Create a list to hold enhanced item data
    enhanced_items = []
    total_profit = Decimal('0.00')
    
    for item in items:
        if not item.product:
            continue
            
        # Calculate profit for this item
        if item.product.buying_price:
            item_profit = (item.unit_price - item.product.buying_price) * item.quantity
        else:
            item_profit = Decimal('0.00')
        
        total_profit += item_profit
        
        # Calculate margin percentage
        if item.total_price > 0:
            margin_percentage = (item_profit / item.total_price * 100)
        else:
            margin_percentage = Decimal('0.00')
        
        # Create item data dictionary
        item_data = {
            'item': item,
            'profit': item_profit,
            'margin_percentage': margin_percentage,
            'imei_number': None,
            'serial_number': None,
            'sold_date': None,
            'unit_buying_price': None,
            'unit_selling_price': None,
            'is_in_warranty': False,
            'warranty_remaining_days': 0,
            'item_type_display': '',
            'item_icon': '',
        }
        
        if item.product.category.is_single_item:
            # Try to get stock entry from the map
            stock_entry = stock_map.get(item.product_id)
            
            if stock_entry and stock_entry.product_unit:
                item_data['imei_number'] = stock_entry.product_unit.imei_number
                item_data['serial_number'] = stock_entry.product_unit.serial_number
                item_data['sold_date'] = stock_entry.product_unit.sold_date
                item_data['unit_buying_price'] = stock_entry.product_unit.unit_buying_price
                item_data['unit_selling_price'] = stock_entry.product_unit.unit_selling_price
                item_data['is_in_warranty'] = stock_entry.product_unit.is_in_warranty
                item_data['warranty_remaining_days'] = stock_entry.product_unit.warranty_remaining_days
            else:
                # Fallback
                unit = ProductUnit.objects.filter(
                    product=item.product,
                    status='sold',
                    sold_date__date=sale.sale_date.date()
                ).select_related('product').first()
                
                if unit:
                    item_data['imei_number'] = unit.imei_number
                    item_data['serial_number'] = unit.serial_number
                    item_data['sold_date'] = unit.sold_date
                    item_data['unit_buying_price'] = unit.unit_buying_price
                    item_data['unit_selling_price'] = unit.unit_selling_price
                    item_data['is_in_warranty'] = unit.is_in_warranty
                    item_data['warranty_remaining_days'] = unit.warranty_remaining_days
            
            item_data['item_type_display'] = 'Single Item'
            item_data['item_icon'] = '📱'
        else:
            # Bulk item
            item_data['item_type_display'] = 'Bulk Item'
            item_data['item_icon'] = '📦'
        
        enhanced_items.append(item_data)
    
    # Calculate change and balance
    amount_paid = sale.amount_paid or Decimal('0.00')
    total_amount = sale.total_amount or Decimal('0.00')
    
    change = amount_paid - total_amount
    balance = total_amount - amount_paid if amount_paid < total_amount else Decimal('0.00')
    
    # Calculate overall profit margin
    overall_margin = (total_profit / total_amount * 100) if total_amount > 0 else Decimal('0.00')
    
    context = {
        'sale': sale,
        'enhanced_items': enhanced_items,
        'change': change,
        'balance': balance,
        'amount_paid': amount_paid,
        'total_amount': total_amount,
        'items_count': items.count(),
        'total_profit': total_profit,
        'profit_margin': overall_margin,
    }
    
    return render(request, 'sales/detail.html', context)

@login_required
def sale_receipt(request, sale_id):
    """View/print sale receipt with loyalty points and VAT calculation"""
    from decimal import Decimal
    from inventory.models import StockEntry, ProductUnit
    from django.db.models import Q
    
    # Get sale with related data
    sale = get_object_or_404(
        Sale.objects.select_related('seller', 'customer'),
        sale_id=sale_id
    )
    
    # Get items with product and unit info
    items = sale.items.select_related(
        'product', 
        'product__category',
        'product_unit'
    ).all()
    
    # Enhance items with identifier information
    enhanced_items = []
    for item in items:
        item_data = {
            'product_name': item.product_name or (item.product.display_name if item.product else 'Unknown'),
            'product_code': item.product_code,
            'sku_value': item.sku_value,
            'sku_code': item.product.sku_code if item.product else None,
            'quantity': item.quantity,
            'unit_price': item.unit_price,
            'total_price': item.total_price,
            'is_single_item': item.product.category.is_single_item if item.product and item.product.category else False,
            'imei_number': None,
            'serial_number': None,
        }
        
        # Get identifier from product_unit if available
        if item.product_unit:
            item_data['imei_number'] = item.product_unit.imei_number
            item_data['serial_number'] = item.product_unit.serial_number
        elif item.product and item.product.category.is_single_item:
            # Try to find the unit via StockEntry
            stock_entry = StockEntry.objects.filter(
                Q(product_unit__product=item.product),
                entry_type='sale',
                reference_id=sale.sale_id
            ).select_related('product_unit').first()
            
            if stock_entry and stock_entry.product_unit:
                item_data['imei_number'] = stock_entry.product_unit.imei_number
                item_data['serial_number'] = stock_entry.product_unit.serial_number
        
        enhanced_items.append(item_data)
    
    # Calculate change
    amount_paid = sale.amount_paid or Decimal('0.00')
    total_amount = sale.total_amount or Decimal('0.00')
    change = amount_paid - total_amount
    balance = total_amount - amount_paid if amount_paid < total_amount else Decimal('0.00')
    
    # Get VAT amount from sale if available, otherwise calculate
    if sale.tax_amount and sale.tax_amount > 0:
        vat_amount = sale.tax_amount
        subtotal_excl_vat = total_amount - vat_amount
    else:
        # Calculate VAT (16%)
        vat_rate = Decimal('0.16')
        if total_amount > 0:
            vat_amount = (total_amount * vat_rate) / (1 + vat_rate)
            subtotal_excl_vat = total_amount - vat_amount
        else:
            vat_amount = Decimal('0.00')
            subtotal_excl_vat = Decimal('0.00')
    
    vat_amount_display = vat_amount.quantize(Decimal('0.01'))
    subtotal_excl_vat_display = subtotal_excl_vat.quantize(Decimal('0.01'))
    
    # Get customer data for loyalty points
    customer = None
    previous_points = 0
    points_earned_today = 0
    
    # Try to get customer from sale.customer first, then by phone
    if sale.customer:
        customer = sale.customer
        logger.info(f"✅ Customer from sale.customer: {customer.full_name}")
    elif sale.buyer_phone:
        try:
            customer = Customer.objects.get(phone_number=sale.buyer_phone, is_active=True)
            logger.info(f"✅ Customer found by phone: {customer.full_name}")
        except Customer.DoesNotExist:
            logger.info(f"ℹ️ No customer found with phone {sale.buyer_phone}")
        except Exception as e:
            logger.error(f"Error getting customer: {str(e)}")
    
    # Get points earned for this sale
    if customer:
        earned_trans = LoyaltyTransaction.objects.filter(
            customer=customer,
            sale=sale,
            transaction_type='earned'
        ).first()
        
        if earned_trans:
            points_earned_today = int(earned_trans.points)
        else:
            # Calculate points as 1% of total (minimum 100 KSH to earn)
            if total_amount >= 100:
                points_earned_today = int(total_amount / 100)
        
        # Calculate previous points balance
        previous_points = max(0, (customer.points_balance or 0) - points_earned_today)
        
        logger.info(f"✅ Receipt customer: {customer.full_name}, Previous: {previous_points}, Earned today: {points_earned_today}")
    
    # Prepare context
    context = {
        'sale': sale,
        'items': enhanced_items,
        'change': change,
        'balance': balance,
        'amount_paid': amount_paid,
        'customer': customer,
        'previous_points': previous_points,
        'points_earned_today': points_earned_today,
        'vat_amount': vat_amount_display,
        'subtotal_excl_vat': subtotal_excl_vat_display,
        'grand_total': total_amount,
        'vat_rate': 16,
        'items_count': len(enhanced_items),
        'has_identifiers': any(item['imei_number'] or item['serial_number'] for item in enhanced_items),
    }
    
    return render(request, 'sales/receipt.html', context)

@login_required
def sale_reverse(request, sale_id):
    """Reverse a sale and restore stock"""
    sale = get_object_or_404(Sale, sale_id=sale_id)
    
    if sale.is_reversed:
        messages.error(request, 'This sale has already been reversed.')
        return redirect('sales:sale_detail', sale_id=sale_id)
    
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        
        try:
            with transaction.atomic():
                # Reverse each sale item to restore stock
                for item in sale.items.all():
                    product = item.product
                    
                    if product.category.is_single_item:
                        # For single items, find the sold unit and mark as available
                        unit = ProductUnit.objects.filter(
                            product=product,
                            status='sold',
                            sold_date__isnull=False
                        ).order_by('-sold_date').first()
                        
                        if unit:
                            unit.mark_as_available()
                            unit.notes = f"Returned from sale reversal: {reason}"
                            unit.save()
                    else:
                        # For bulk items, restore quantity
                        product.bulk_quantity += item.quantity
                        product.save()
                    
                    # Create reversal stock entry
                    StockEntry.objects.create(
                        product_sku=product if not product.category.is_single_item else None,
                        product_unit=unit if product.category.is_single_item else None,
                        quantity=item.quantity,
                        entry_type='reversal',
                        unit_price=item.unit_price,
                        total_amount=item.total_price,
                        reference_id=f"REV-{sale.sale_id}",
                        notes=f"Sale reversal: {reason}",
                        created_by=request.user
                    )
                
                # Mark sale as reversed
                sale.is_reversed = True
                sale.reversal_reason = reason
                sale.reversed_by = request.user
                sale.reversed_at = timezone.now()
                sale.save()
                
                # Reverse points if any were awarded
                if sale.points_redeemed > 0:
                    # Return points that were redeemed
                    if sale.buyer_phone:
                        try:
                            customer = Customer.objects.get(phone_number=sale.buyer_phone)
                            customer.add_points(
                                sale.points_redeemed,
                                sale=sale,
                                description=f"Points refunded from sale reversal #{sale.sale_id}"
                            )
                            logger.info(f"💰 Reversed {sale.points_redeemed} points to customer {customer.phone_number}")
                        except Customer.DoesNotExist:
                            pass
                
                messages.success(request, f'Sale #{sale.sale_id} has been reversed successfully. Stock has been restored.')
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


    """AJAX endpoint to get product details by SKU code"""
    try:
        # Search by SKU code (primary identifier now)
        product = Product.objects.get(sku_code=sku_code, is_active=True)
        
        # Check if single item is available
        if product.category.is_single_item:
            # Check available units count
            available_units = product.units.filter(status='available').count()
            
            if available_units <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'This item has already been sold or no units available'
                })
            
            # Check if already in an active sale
            from sales.models import SaleItem
            active_sale_exists = SaleItem.objects.filter(
                sku_value=product.sku_code,  # Use sku_code
                sale__is_reversed=False
            ).exists()
            
            if active_sale_exists:
                return JsonResponse({
                    'success': False,
                    'error': 'This item has already been sold in another transaction'
                })
            
            # Get the first available unit's price (if overridden)
            unit = product.units.filter(status='available').first()
            selling_price = float(unit.effective_selling_price) if unit else float(product.selling_price)
            
        else:
            # Bulk items - check bulk quantity
            if product.bulk_quantity <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Product out of stock'
                })
            selling_price = float(product.selling_price)
        
        return JsonResponse({
            'success': True,
            'product': {
                'sku_code': product.sku_code,
                'name': product.display_name,
                'price': selling_price,
                'stock': product.bulk_quantity if product.category.is_bulk_item else product.units.filter(status='available').count(),
                'is_single': product.category.is_single_item,
            }
        })
        
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': f'Product with SKU "{sku_code}" not found'
        })
    except Exception as e:
        logger.error(f"Error getting product details: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def get_product_details(request, sku_code):
    """AJAX endpoint to get product details by SKU code - IMPROVED ERROR HANDLING"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Try to find product by sku_code
        product = Product.objects.filter(
            Q(sku_code=sku_code) | 
            Q(product_code=sku_code),
            is_active=True
        ).select_related('category').first()
        
        if not product:
            return JsonResponse({
                'success': False,
                'error': f'Product with SKU "{sku_code}" not found',
                'debug': 'Product does not exist or is inactive'
            }, status=404)
        
        # Check stock based on category
        if product.category and product.category.is_single_item:
            available_units = product.units.filter(status='available').count()
            stock = available_units
            is_single = True
            
            # Get first available unit for price
            unit = product.units.filter(status='available').first()
            selling_price = float(unit.effective_selling_price) if unit else float(product.selling_price)
            
            if available_units <= 0:
                return JsonResponse({
                    'success': False,
                    'error': f'{product.display_name} is out of stock (no available units)',
                    'product': {
                        'name': product.display_name,
                        'stock': 0,
                        'is_single': True
                    }
                }, status=400)
        else:
            # Bulk item
            stock = product.bulk_quantity or 0
            is_single = False
            selling_price = float(product.selling_price)
            
            if stock <= 0:
                return JsonResponse({
                    'success': False,
                    'error': f'{product.display_name} is out of stock',
                    'product': {
                        'name': product.display_name,
                        'stock': 0,
                        'is_single': False
                    }
                }, status=400)
        
        # Return success response
        return JsonResponse({
            'success': True,
            'product': {
                'sku_code': product.sku_code,
                'name': product.display_name,
                'price': selling_price,
                'stock': stock,
                'is_single': is_single,
                'category': product.category.name if product.category else None,
                'brand': product.brand or '',
                'model': product.model or '',
            }
        })
        
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': f'Product with SKU "{sku_code}" not found'
        }, status=404)
        
    except Exception as e:
        logger.error(f"Error in get_product_details for SKU '{sku_code}': {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)
    
@login_required
def get_product_by_identifier(request, identifier):
    """Alternative endpoint to search by sku_code or old product_code"""
    try:
        # Try by sku_code first
        try:
            product = Product.objects.get(sku_code=identifier, is_active=True)
        except Product.DoesNotExist:
            # Try by old product_code field (if it exists) or barcode
            from django.db.models import Q
            product = Product.objects.get(
                Q(product_code=identifier) if hasattr(Product, 'product_code') else Q(sku_code=identifier),
                is_active=True
            )
        
        # ... rest of the logic same as above
        if product.category.is_single_item:
            available_units = product.units.filter(status='available').count()
            if available_units <= 0:
                return JsonResponse({'success': False, 'error': 'Item not available'})
            
            unit = product.units.filter(status='available').first()
            selling_price = float(unit.effective_selling_price) if unit else float(product.selling_price)
            stock = available_units
        else:
            if product.bulk_quantity <= 0:
                return JsonResponse({'success': False, 'error': 'Out of stock'})
            selling_price = float(product.selling_price)
            stock = product.bulk_quantity
        
        return JsonResponse({
            'success': True,
            'product': {
                'sku_code': product.sku_code,
                'name': product.display_name,
                'price': selling_price,
                'stock': stock,
                'is_single': product.category.is_single_item,
            }
        })
        
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': f'Product "{identifier}" not found'
        })




# ====================================
# VIEWS FOR CART MANAGEMENT
# ====================================
@login_required
def add_to_cart(request):
    """AJAX endpoint to add item to cart with custom price and identifier for single items"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            sku_code = data.get('sku_code') or data.get('product_code')
            quantity = int(data.get('quantity', 1))
            custom_price = data.get('custom_price')
            allow_price_edit = data.get('allow_price_edit', False)
            identifier = data.get('identifier')  # IMEI or Serial number
            identifier_type = data.get('identifier_type')  # 'imei' or 'serial'
            
            if not sku_code:
                return JsonResponse({'success': False, 'error': 'Product SKU is required'})
            
            try:
                product = Product.objects.get(sku_code=sku_code, is_active=True)
            except Product.DoesNotExist:
                return JsonResponse({'success': False, 'error': f'Product with SKU "{sku_code}" not found'})
            
            # ============================================
            # CHECK SINGLE ITEM AVAILABILITY
            # ============================================
            if product.category and product.category.is_single_item:
                # Find the specific unit by identifier
                unit = None
                if identifier_type == 'imei' and identifier:
                    unit = product.units.filter(imei_number=identifier, status='available').first()
                elif identifier_type == 'serial' and identifier:
                    unit = product.units.filter(serial_number=identifier, status='available').first()
                
                if not unit:
                    # If identifier not provided, return product info to get it
                    if not identifier:
                        return JsonResponse({
                            'success': True,
                            'is_single': True,
                            'requires_identifier': True,
                            'product_data': {
                                'product_code': product.sku_code,
                                'sku_code': product.sku_code,
                                'name': product.display_name,
                                'identifier_type': product.category.identifier_type,
                                'custom_price': custom_price if allow_price_edit else None,
                                'allow_price_edit': allow_price_edit
                            }
                        })
                    else:
                        return JsonResponse({
                            'success': False,
                            'error': f'{identifier_type.upper()} {identifier} not found or already sold'
                        })
                
                # Check if already in cart
                cart = request.session.get('sales_cart', [])
                for item in cart:
                    if item.get('unit_id') == unit.id:
                        return JsonResponse({
                            'success': False,
                            'error': f'❌ {product.display_name} with {identifier_type.upper()}: {identifier} is already in the cart'
                        })
                
                # Single items must have quantity = 1
                if quantity != 1:
                    return JsonResponse({'success': False, 'error': 'Single items can only be sold one at a time'})
                
                # Determine price
                if custom_price is not None and custom_price and allow_price_edit:
                    price = float(custom_price)
                else:
                    price = float(unit.effective_selling_price)
                
                # Add to cart with unit info
                cart.append({
                    'unit_id': unit.id,
                    'product_id': product.id,
                    'sku_code': product.sku_code,
                    'name': product.display_name,
                    'identifier': identifier,
                    'identifier_type': identifier_type,
                    'price': price,
                    'original_price': float(product.selling_price),
                    'quantity': 1,
                    'total': price,
                    'is_single': True,
                    'price_editable': allow_price_edit,
                    'unique_id': f"{sku_code}_{identifier}_{price}"
                })
                
                request.session['sales_cart'] = cart
                request.session.modified = True
                
                return JsonResponse({
                    'success': True,
                    'cart': cart,
                    'message': f'{product.display_name} ({identifier_type.upper()}: {identifier}) added to cart'
                })
                
            else:
                # BULK ITEMS - existing logic
                if product.bulk_quantity < quantity:
                    return JsonResponse({'success': False, 'error': f'Insufficient stock. Available: {product.bulk_quantity}'})
                
                # Determine price
                if custom_price is not None and custom_price and allow_price_edit:
                    price = float(custom_price)
                else:
                    price = float(product.selling_price)
                
                cart = request.session.get('sales_cart', [])
                
                # Check for existing item
                found = False
                for item in cart:
                    if item.get('sku_code') == sku_code and item.get('price') == price and not item.get('is_single'):
                        new_quantity = item['quantity'] + quantity
                        if product.bulk_quantity < new_quantity:
                            return JsonResponse({'success': False, 'error': f'Only {product.bulk_quantity} available'})
                        item['quantity'] = new_quantity
                        item['total'] = item['price'] * new_quantity
                        found = True
                        break
                
                if not found:
                    cart.append({
                        'product_id': product.id,
                        'sku_code': product.sku_code,
                        'name': product.display_name,
                        'price': price,
                        'original_price': float(product.selling_price),
                        'quantity': quantity,
                        'total': price * quantity,
                        'is_single': False,
                        'price_editable': allow_price_edit,
                        'unique_id': f"{sku_code}_{price}_{len(cart)}"
                    })
                
                request.session['sales_cart'] = cart
                request.session.modified = True
                
                return JsonResponse({
                    'success': True,
                    'cart': cart,
                    'message': f'{product.display_name} added to cart'
                })
            
        except Exception as e:
            logger.error(f"Error adding to cart: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@login_required
def get_cart(request):
    """AJAX endpoint to get current cart contents"""
    cart = request.session.get('sales_cart', [])
    
    # Migrate old cart items to use sku_code
    for item in cart:
        if 'sku_code' not in item and 'product_code' in item:
            # Try to get product from database to fill missing sku_code
            try:
                from inventory.models import Product
                product = Product.objects.get(sku_code=item.get('sku_code') or item.get('product_code'))
                item['sku_code'] = product.sku_code
            except:
                # If can't find, keep the old product_code as identifier
                item['sku_code'] = item.get('product_code', '')
        
        # Ensure all required fields exist
        if 'is_single' not in item:
            item['is_single'] = False
    
    subtotal = sum(item.get('total', 0) for item in cart)
    
    return JsonResponse({
        'success': True,
        'cart': cart,
        'subtotal': subtotal,
        'cart_count': len(cart)
    })

def validate_single_items_in_cart(cart):
    """
    Validate that no single items in cart have been sold already
    """
    from inventory.models import Product, ProductUnit
    from sales.models import SaleItem
    
    for item in cart:
        if item.get('is_single'):
            try:
                # Use sku_code to find product
                sku_code = item.get('sku_code') or item.get('product_code')
                product = Product.objects.get(sku_code=sku_code, is_active=True)
                
                # Check if any available units exist
                available_units = product.units.filter(status='available').count()
                if available_units <= 0:
                    return False, f"Item {product.display_name} has already been sold"
                
                # Check if this SKU appears in any active sale
                if SaleItem.objects.filter(
                    sku_value=product.sku_code, 
                    sale__is_reversed=False
                ).exists():
                    return False, f"Item {product.display_name} (SKU: {product.sku_code}) has already been sold"
                    
            except Product.DoesNotExist:
                return False, f"Product with SKU {item.get('sku_code', item.get('product_code'))} not found"
    
    return True, "All items are available"

@login_required
def remove_from_cart(request):
    """AJAX endpoint to remove item from cart by unique_id"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            unique_id = data.get('unique_id')  # Use unique_id instead of row_id
            
            if not unique_id:
                return JsonResponse({'success': False, 'error': 'Unique ID required'})
            
            cart = request.session.get('sales_cart', [])
            
            # Remove the specific item with matching unique_id
            new_cart = [item for item in cart if item.get('unique_id') != unique_id]
            
            request.session['sales_cart'] = new_cart
            request.session.modified = True
            
            subtotal = sum(item.get('total', 0) for item in new_cart)
            
            return JsonResponse({
                'success': True,
                'cart': new_cart,
                'subtotal': subtotal,
                'cart_count': len(new_cart)
            })
            
        except Exception as e:
            logger.error(f"Error removing from cart: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def update_cart(request):
    """AJAX endpoint to update item quantity in cart"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            sku_code = data.get('sku_code') or data.get('product_code')  # Support both
            quantity = int(data.get('quantity', 1))
            price = float(data.get('price', 0))
            
            cart = request.session.get('sales_cart', [])
            
            if quantity < 1:
                return JsonResponse({
                    'success': False,
                    'error': 'Quantity must be at least 1'
                })
            
            # Find the specific item with matching SKU AND price
            found = False
            for item in cart:
                item_sku = item.get('sku_code') or item.get('product_code')
                if item_sku == sku_code and item.get('price') == price:
                    # Check stock for bulk items
                    if not item.get('is_single', False):
                        try:
                            from inventory.models import Product
                            product = Product.objects.get(sku_code=sku_code, is_active=True)
                            if product.bulk_quantity < quantity:
                                return JsonResponse({
                                    'success': False,
                                    'error': f'Only {product.bulk_quantity} available'
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
            sku_code = data.get('sku_code') or data.get('product_code')
            old_price = float(data.get('old_price', 0))
            new_price = float(data.get('price', 0))
            
            if new_price < 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Price cannot be negative'
                })
            
            cart = request.session.get('sales_cart', [])
            
            # Find the specific item with matching SKU AND old price
            found = False
            for item in cart:
                item_sku = item.get('sku_code') or item.get('product_code')
                if item_sku == sku_code and item.get('price') == old_price:
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
        request.session.modified = True
        return JsonResponse({
            'success': True,
            'message': 'Cart cleared'
        })
    return JsonResponse({'success': False, 'error': 'Invalid request'})

@login_required
def sold_items_list(request):
    """List all sold items with details matching SKU model"""
    from django.db.models import Q, Sum
    from django.core.paginator import Paginator
    from datetime import timedelta
    from django.utils import timezone
    from inventory.models import Category, ProductUnit, StockEntry
    
    # Get all sold items with related data
    sold_items = SaleItem.objects.select_related(
        'sale', 
        'product',
        'product__category',
    ).filter(
        sale__is_reversed=False  # Exclude reversed sales
    ).order_by('-sale__sale_date')
    
    # ============================================
    # Apply filters
    # ============================================
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    search = request.GET.get('search', '').strip()
    category_id = request.GET.get('category')
    
    if date_from:
        sold_items = sold_items.filter(sale__sale_date__date__gte=date_from)
    
    if date_to:
        sold_items = sold_items.filter(sale__sale_date__date__lte=date_to)
    
    if category_id:
        sold_items = sold_items.filter(product__category_id=category_id)
    
    if search:
        sold_items = sold_items.filter(
            Q(sale__sale_id__icontains=search) |
            Q(product__name__icontains=search) |
            Q(product__sku_code__icontains=search) |
            Q(product__brand__icontains=search) |
            Q(product__model__icontains=search) |
            Q(sale__buyer_name__icontains=search) |
            Q(sale__buyer_phone__icontains=search)
        )
    
    # ============================================
    # Calculate summary statistics
    # ============================================
    total_sold = sold_items.aggregate(total=Sum('quantity'))['total'] or 0
    total_revenue = sold_items.aggregate(total=Sum('total_price'))['total'] or 0
    
    # Calculate total profit manually
    total_profit = 0
    for item in sold_items[:1000]:
        if item.product and item.product.buying_price:
            total_profit += (item.unit_price - item.product.buying_price) * item.quantity
    
    # ============================================
    # Per page pagination
    # ============================================
    per_page = request.GET.get('per_page', '50')
    try:
        per_page = int(per_page)
        if per_page not in [10, 25, 50, 100]:
            per_page = 50
    except ValueError:
        per_page = 50
    
    paginator = Paginator(sold_items, per_page)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # ============================================
    # Get all sale IDs from current page
    # ============================================
    sale_ids = [item.sale.sale_id for item in page_obj]
    
    # ============================================
    # Get stock entries for these sales (by reference_id)
    # Since product_sku is None, we need to use product_unit directly
    # ============================================
    stock_entries = StockEntry.objects.filter(
        reference_id__in=sale_ids,
        entry_type='sale'
    ).select_related('product_unit')
    
    # Create mapping from sale_id to the stock entry's product_unit
    sale_unit_map = {}
    for entry in stock_entries:
        if entry.product_unit:
            sale_unit_map[entry.reference_id] = entry.product_unit
    
    # ============================================
    # Create a list of item dictionaries with additional data
    # ============================================
    items_with_details = []
    
    for item in page_obj:
        # Calculate profit
        if item.product and item.product.buying_price:
            profit = (item.unit_price - item.product.buying_price) * item.quantity
        else:
            profit = 0
        
        # Get the unit from the stock entry mapping
        product_unit = sale_unit_map.get(item.sale.sale_id)
        
        imei_number = None
        serial_number = None
        
        if product_unit:
            imei_number = product_unit.imei_number
            serial_number = product_unit.serial_number
        
        # Add to list
        items_with_details.append({
            'item': item,
            'profit': profit,
            'imei_number': imei_number,
            'serial_number': serial_number,
            'product_unit': product_unit,
        })
    
    # ============================================
    # Get categories for filter dropdown
    # ============================================
    categories = Category.objects.filter(is_active=True).order_by('name')
    
    # ============================================
    # Date shortcuts
    # ============================================
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    year_ago = today - timedelta(days=365)
    
    # ============================================
    # Context
    # ============================================
    context = {
        'items_with_details': items_with_details,
        'page_obj': page_obj,
        'total_sold': total_sold,
        'total_revenue': total_revenue,
        'total_profit': total_profit,
        'search': search,
        'date_from': date_from,
        'date_to': date_to,
        'category_id': category_id,
        'categories': categories,
        'today': today,
        'week_ago': week_ago,
        'month_ago': month_ago,
        'year_ago': year_ago,
        'per_page': per_page,
    }
    
    return render(request, 'sales/sold_items_list.html', context)

@login_required
def export_sold_items(request):
    """Export sold items to Excel"""
    import csv
    from django.http import HttpResponse
    from django.utils import timezone
    
    # Get filtered queryset (same as above)
    sold_items = SaleItem.objects.select_related(
        'sale', 'product', 'product__category', 'product_unit'
    ).filter(sale__is_reversed=False).order_by('-sale__sale_date')
    
    # Apply filters (same as above)
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    search = request.GET.get('search', '').strip()
    category_id = request.GET.get('category')
    
    if date_from:
        sold_items = sold_items.filter(sale__sale_date__date__gte=date_from)
    if date_to:
        sold_items = sold_items.filter(sale__sale_date__date__lte=date_to)
    if category_id:
        sold_items = sold_items.filter(product__category_id=category_id)
    if search:
        sold_items = sold_items.filter(
            Q(sale__sale_id__icontains=search) |
            Q(product__name__icontains=search) |
            Q(product__sku_code__icontains=search) |
            Q(product_unit__imei_number__icontains=search)
        )
    
    # Create CSV response
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="sold_items_{timezone.now().date()}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Sale ID', 'Date', 'Product SKU', 'Product Name', 'Identifier',
        'Quantity', 'Unit Price', 'Total', 'Profit', 'Sold By', 'Customer', 'Customer Phone'
    ])
    
    for item in sold_items:
        # Get identifier
        if item.product_unit:
            identifier = item.product_unit.imei_number or item.product_unit.serial_number or '-'
        else:
            identifier = 'Bulk Item'
        
        # Calculate profit
        buying_price = item.product_unit.effective_buying_price if item.product_unit else item.product.buying_price if item.product else 0
        profit = (item.unit_price - buying_price) * item.quantity if buying_price else 0
        
        writer.writerow([
            item.sale.sale_id,
            item.sale.sale_date.strftime('%Y-%m-%d %H:%M'),
            item.product.sku_code if item.product else '-',
            item.product.name if item.product else '-',
            identifier,
            item.quantity,
            f"{item.unit_price:.2f}",
            f"{item.total_price:.2f}",
            f"{profit:.2f}",
            item.sale.seller.username,
            item.sale.buyer_name or 'Walk-in Customer',
            item.sale.buyer_phone or '-',
        ])
    
    return response

@login_required
def imei_suggestions(request):
    """API endpoint to get IMEI suggestions for autocomplete - FILTERED BY PRODUCT"""
    query = request.GET.get('q', '').strip()
    product_sku = request.GET.get('product_sku', '').strip()  # ← ADD THIS
    
    if not query or len(query) < 2:
        return JsonResponse({'success': True, 'suggestions': []})
    
    # Get current cart from session to exclude items already in cart
    cart = request.session.get('sales_cart', [])
    cart_unit_ids = [item.get('unit_id') for item in cart if item.get('unit_id')]
    
    # Base queryset
    units = ProductUnit.objects.filter(
        imei_number__icontains=query,
        status='available'
    ).exclude(
        id__in=cart_unit_ids
    )
    
    # ✅ FILTER BY PRODUCT SKU if provided
    if product_sku:
        units = units.filter(product__sku_code=product_sku)
    
    units = units.select_related('product')[:10]
    
    suggestions = []
    for unit in units:
        suggestions.append({
            'imei_number': unit.imei_number,
            'product_name': unit.product.name,
            'sku_code': unit.product.sku_code,
            'status': unit.status,
            'unit_id': unit.id,
            'sold_date': unit.sold_date.isoformat() if unit.sold_date else None,
        })
    
    return JsonResponse({'success': True, 'suggestions': suggestions})

@login_required
def serial_suggestions(request):
    """API endpoint to get Serial Number suggestions - FILTERED BY PRODUCT"""
    query = request.GET.get('q', '').strip()
    product_sku = request.GET.get('product_sku', '').strip()  # ← ADD THIS
    
    if not query or len(query) < 2:
        return JsonResponse({'success': True, 'suggestions': []})
    
    # Get current cart from session
    cart = request.session.get('sales_cart', [])
    cart_unit_ids = [item.get('unit_id') for item in cart if item.get('unit_id')]
    
    # Also exclude units already sold
    from sales.models import SaleItem
    sold_unit_ids = SaleItem.objects.filter(
        product_unit__isnull=False,
        sale__is_reversed=False
    ).values_list('product_unit_id', flat=True).distinct()
    
    # Base queryset
    units = ProductUnit.objects.filter(
        serial_number__icontains=query,
        status='available'
    ).exclude(
        id__in=cart_unit_ids
    ).exclude(
        id__in=sold_unit_ids
    )
    
    # ✅ FILTER BY PRODUCT SKU if provided
    if product_sku:
        units = units.filter(product__sku_code=product_sku)
    
    units = units.select_related('product')[:10]
    
    suggestions = []
    for unit in units:
        suggestions.append({
            'serial_number': unit.serial_number,
            'product_name': unit.product.name,
            'sku_code': unit.product.sku_code,
            'status': unit.status,
            'is_available': unit.status == 'available',
            'unit_id': unit.id,
        })
    
    return JsonResponse({'success': True, 'suggestions': suggestions})






# ============================================
# VIEWS FOR CUSTOMER LOYALTY PROGRAM
# ============================================
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
        'points_value': float(customer.points_balance), 
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
    
    
    # New customers this month
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_customers = Customer.objects.filter(created_at__gte=month_start).count()
    
    context = {
        'customers': page_obj,
        'total_customers': total_customers,
        'total_points': total_points,
        'total_points_value': total_points,  
        'total_spent': total_spent,
        'avg_spent': total_spent / total_customers if total_customers > 0 else 0,
        'new_customers': new_customers,
        'search': search,
        'sort': sort,
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





# ============================================
# OTP FOR POINTS REDEMPTION
# ===========================================

try:
    africastalking.initialize(
        username=settings.AFRICASTALKING_USERNAME,
        api_key=settings.AFRICASTALKING_API_KEY
    )
    sms = africastalking.SMS
except Exception as e:
    sms = None
    print(f"Warning: Failed to initialize Africa's Talking: {e}")

@login_required
def send_otp(request):
    """Send OTP to customer phone for points redemption"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            phone = data.get('phone')
            purpose = data.get('purpose', 'redeem_points')
            points = data.get('points', 0)
            
            if not phone:
                return JsonResponse({'success': False, 'error': 'Phone number required'})
            
            cleaned_phone = normalize_phone(phone)
            
            # ============================================
            # FIX: Format phone number for Africa's Talking
            # ============================================
            def format_for_africastalking(phone):
                """Convert to format expected by Africa's Talking Sandbox"""
                # Remove any non-digit characters
                digits = ''.join(filter(str.isdigit, phone))
                
                # For Sandbox mode, Africa's Talking expects local format (0722xxxxxx)
                # Remove the 254 prefix if present
                if digits.startswith('254') and len(digits) == 12:
                    # Convert 254722527955 -> 0722527955
                    return '0' + digits[3:]  # Remove 254 and add leading 0
                
                # If it starts with 0 and is 10 digits, keep as is
                if digits.startswith('0') and len(digits) == 10:
                    return digits
                
                # If it's 9 digits (missing leading 0), add it
                if len(digits) == 9:
                    return '0' + digits
                
                return digits
            
            # For SMS sending, use local format
            sms_phone = format_for_africastalking(cleaned_phone)
            
            # Generate OTP
            otp = f"{random.randint(1000, 9999)}"
            
            # Store OTP in session (using normalized phone as key)
            request.session[f'otp_{cleaned_phone}'] = {
                'code': otp,
                'expires': (timezone.now() + timedelta(minutes=5)).isoformat(),
                'purpose': purpose,
                'points': points
            }
            
            # Send SMS using settings
            message = f"FIELDMAX: Use OTP {otp} to redeem {points} loyalty points. Valid for 5 minutes."
            
            sms_sent = False
            if settings.SMS_ENABLED and sms:
                try:
                    # Use the formatted phone number for SMS
                    response = sms.send(message, [sms_phone])
                    sms_sent = True
                    logger.info(f"OTP sent to {sms_phone}: {response}")
                    print(f"✅ SMS sent to {sms_phone}")
                except Exception as e:
                    logger.error(f"SMS failed: {str(e)}")
                    print(f"SMS Error: {e}")
            
            if sms_sent:
                return JsonResponse({
                    'success': True,
                    'message': 'OTP sent to customer\'s phone'
                })
            else:
                # Fallback for testing
                print("\n" + "=" * 60)
                print(f"⚠️ SMS FAILED - OTP FOR TESTING ONLY")
                print(f"📞 Customer Phone: {cleaned_phone}")
                print(f"📱 SMS Format: {sms_phone}")
                print(f"🔢 OTP: {otp}")
                print(f"⭐ Points: {points}")
                print("=" * 60 + "\n")
                return JsonResponse({
                    'success': True,
                    'message': 'OTP generated (SMS failed - check console)',
                    'otp': otp if settings.DEBUG else None
                })
                
        except Exception as e:
            logger.error(f"Error sending OTP: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})

@login_required
def verify_otp(request):
    """Verify OTP for points redemption"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            phone = data.get('phone')
            entered_otp = data.get('otp')
            purpose = data.get('purpose', 'redeem_points')
            
            if not phone or not entered_otp:
                return JsonResponse({'success': False, 'error': 'Phone and OTP required'})
            
            cleaned_phone = normalize_phone(phone)
            
            # Get stored OTP data
            stored_data = request.session.get(f'otp_{cleaned_phone}')
            
            if not stored_data:
                return JsonResponse({'success': False, 'error': 'No OTP request found. Please request again.'})
            
            # Check expiry
            expires = datetime.fromisoformat(stored_data['expires'])
            if timezone.now() > expires:
                del request.session[f'otp_{cleaned_phone}']
                return JsonResponse({'success': False, 'error': 'OTP has expired. Please request again.'})
            
            # Verify OTP
            if stored_data['code'] == entered_otp and stored_data['purpose'] == purpose:
                # Clear OTP from session
                del request.session[f'otp_{cleaned_phone}']
                logger.info(f"✅ OTP verified successfully for {cleaned_phone}")
                return JsonResponse({'success': True, 'message': 'OTP verified successfully'})
            else:
                return JsonResponse({'success': False, 'error': 'Invalid OTP. Please try again.'})
                
        except Exception as e:
            logger.error(f"Error verifying OTP: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})





#====================================
# M-PESA PAYMENT INTEGRATION
#====================================

@login_required
def initiate_mpesa_payment(request, sale_id):
    from finance.kopokopo_service import stk_push_request, clean_phone_number, check_pending_transaction
    from finance.models import MpesaTransaction
    
    sale = get_object_or_404(Sale, sale_id=sale_id)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            phone_number = data.get('phone_number', '').strip()
            
            if not phone_number:
                return JsonResponse({
                    'success': False,
                    'error': 'Phone number is required'
                })
            
            cleaned_phone = clean_phone_number(phone_number)
            
            # ============================================
            # CHECK FOR PENDING TRANSACTIONS FIRST
            # ============================================
            if check_pending_transaction(cleaned_phone):
                return JsonResponse({
                    'success': False,
                    'error': 'There is already a pending M-Pesa request for this phone number. Please wait 2-3 minutes.',
                    'error_code': '429'
                })
            
            account_ref = f"SALE{sale.sale_id}"
            
            logger.info(f"Initiating M-Pesa payment for sale {sale.sale_id}, amount: {sale.total_amount}")
            
            # Initiate STK Push
            result = stk_push_request(
                phone_number=cleaned_phone,
                amount=float(sale.total_amount),
                account_reference=account_ref,
                transaction_desc=f"Payment for Sale #{sale.sale_id}"
            )
            
            logger.info(f"STK Push result: {result}")
            
            # Check for 429 error in result
            if result.get('ResponseCode') == '429' or result.get('error_code') == '429':
                return JsonResponse({
                    'success': False,
                    'error': result.get('ResponseDescription', 'There is a pending request for this phone number'),
                    'error_code': '429'
                })
            
            if result.get('ResponseCode') == '0':
                # Save transaction record
                mpesa_trans = MpesaTransaction.objects.create(
                    merchant_request_id=result.get('MerchantRequestID', ''),
                    checkout_request_id=result['CheckoutRequestID'],
                    amount=sale.total_amount,
                    phone_number=cleaned_phone,
                    account_reference=account_ref,
                    transaction_desc=f"Payment for Sale #{sale.sale_id}",
                    sale=sale,
                    created_by=request.user,
                    status='pending'
                )
                
                return JsonResponse({
                    'success': True,
                    'checkout_request_id': result['CheckoutRequestID'],
                    'sale_id': sale.sale_id,
                    'message': 'STK Push sent. Please enter PIN to complete payment.'
                })
            else:
                error_msg = result.get('ResponseDescription', 'Failed to initiate payment')
                return JsonResponse({
                    'success': False,
                    'error': error_msg
                })
                
        except Exception as e:
            logger.error(f"Error initiating M-Pesa payment: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

@login_required
def check_payment_status(request, sale_id):
    """Check if M-Pesa payment has been received for a sale (for direct till payments)"""
    from finance.models import MpesaTransaction
    
    try:
        sale = Sale.objects.get(sale_id=sale_id)
        
        # Check for completed M-Pesa transaction
        mpesa_trans = MpesaTransaction.objects.filter(
            sale=sale,
            status='completed'
        ).order_by('-created_at').first()
        
        if mpesa_trans:
            return JsonResponse({
                'paid': True,
                'amount': float(mpesa_trans.amount),
                'transaction_id': mpesa_trans.checkout_request_id
            })
        
        # Also check if sale already has amount_paid
        if sale.amount_paid >= sale.total_amount:
            return JsonResponse({
                'paid': True,
                'amount': float(sale.amount_paid),
                'transaction_id': None
            })
        
        return JsonResponse({'paid': False})
        
    except Sale.DoesNotExist:
        return JsonResponse({'paid': False, 'error': 'Sale not found'})
    except Exception as e:
        logger.error(f"Error checking payment status: {str(e)}")
        return JsonResponse({'paid': False, 'error': str(e)})

@login_required
def check_payment_by_phone(request):
    """Check if customer has made a direct payment to till number by phone and amount"""
    from finance.models import MpesaTransaction
    from decimal import Decimal
    
    try:
        phone_number = request.GET.get('phone', '').strip()
        expected_amount = request.GET.get('amount', '').strip()
        
        if not phone_number:
            return JsonResponse({'success': False, 'error': 'Phone number required'})
        
        # Clean phone number
        cleaned_phone = normalize_phone(phone_number)
        
        # Parse expected amount
        expected = Decimal(expected_amount) if expected_amount else None
        
        # Check for completed transactions in the last 10 minutes
        time_threshold = timezone.now() - timedelta(minutes=10)
        
        # Look for payment by phone number
        query = MpesaTransaction.objects.filter(
            phone_number__icontains=cleaned_phone,
            status='completed',
            created_at__gte=time_threshold
        ).order_by('-created_at')
        
        # If amount specified, filter by amount
        if expected:
            # Allow small tolerance (within 1 KSH)
            amount_min = expected - Decimal('1.00')
            amount_max = expected + Decimal('1.00')
            query = query.filter(amount__gte=amount_min, amount__lte=amount_max)
        
        recent_payment = query.first()
        
        if recent_payment:
            return JsonResponse({
                'success': True,
                'paid': True,
                'amount': float(recent_payment.amount),
                'transaction_id': recent_payment.checkout_request_id,
                'phone': recent_payment.phone_number,
                'matches': float(recent_payment.amount) == float(expected) if expected else False
            })
        
        return JsonResponse({'success': True, 'paid': False})
        
    except Exception as e:
        logger.error(f"Error checking payment by phone: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def record_direct_payment(request, sale_id):
    """Manually record a direct till payment"""
    from finance.models import MpesaTransaction
    import uuid
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            amount = Decimal(str(data.get('amount', 0)))
            phone_number = data.get('phone_number', '')
            
            sale = get_object_or_404(Sale, sale_id=sale_id)
            
            if amount <= 0:
                return JsonResponse({'success': False, 'error': 'Invalid amount'})
            
            if sale.amount_paid + amount > sale.total_amount:
                return JsonResponse({'success': False, 'error': 'Amount exceeds total due'})
            
            # Update sale
            sale.amount_paid += amount
            if sale.amount_paid >= sale.total_amount:
                sale.payment_method = 'M-Pesa'
            sale.save()
            
            # Generate a unique checkout ID with DIRECT prefix
            checkout_id = f"DIRECT-{sale.sale_id}-{uuid.uuid4().hex[:8].upper()}"
            
            # Create M-Pesa transaction record
            mpesa_trans = MpesaTransaction.objects.create(
                merchant_request_id=checkout_id,
                checkout_request_id=checkout_id,
                amount=amount,
                phone_number=phone_number,
                account_reference=f"SALE{sale.sale_id}",
                transaction_desc=f"Manual direct payment for Sale #{sale.sale_id}",
                sale=sale,
                created_by=request.user,
                status='completed',
                result_code=0,
                result_desc="Manual payment recorded by cashier"
            )
            
            logger.info(f"Manual direct payment recorded: {amount} for sale {sale.sale_id}")
            
            return JsonResponse({
                'success': True, 
                'message': 'Payment recorded',
                'amount_paid': float(sale.amount_paid)
            })
            
        except Exception as e:
            logger.error(f"Error recording direct payment: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})

@login_required
def complete_sale_payment(request, sale_id):
    """Complete a pending sale after M-Pesa payment confirmation - PRESERVE LOYALTY DATA"""
    from django.db import transaction
    from decimal import Decimal
    import json
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        sale = get_object_or_404(Sale, sale_id=sale_id)
        
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount_paid', 0)))
        payment_method = data.get('payment_method', 'M-Pesa')
        points_to_award = data.get('points_to_award', 0)
        verified_customer_id = data.get('verified_customer_id')
        buyer_phone = data.get('buyer_phone', '')
        points_redeemed = data.get('points_redeemed', 0)
        
        logger.info(f"📦 COMPLETING SALE {sale_id}")
        logger.info(f"   Amount: {amount}, Points to award: {points_to_award}")
        logger.info(f"   Customer ID: {verified_customer_id}, Phone: {buyer_phone}")
        logger.info(f"   Points redeemed: {points_redeemed}")
        
        with transaction.atomic():
            # Update sale with payment info
            sale.amount_paid = amount
            sale.payment_method = payment_method
            
            # IMPORTANT: Preserve customer/loyalty data
            customer = None
            if verified_customer_id:
                try:
                    from sales.models import Customer
                    customer = Customer.objects.get(id=verified_customer_id)
                    sale.buyer_name = customer.full_name
                    sale.buyer_phone = buyer_phone or customer.phone_number
                    logger.info(f"✅ Linked sale to customer: {customer.full_name} (ID: {customer.id})")
                except Customer.DoesNotExist:
                    logger.warning(f"⚠️ Customer {verified_customer_id} not found")
            
            # Handle points redeemed (if customer used points to pay)
            if points_redeemed > 0 and customer:
                # Points were already redeemed when sale was created
                # Just log it
                logger.info(f"💰 Customer redeemed {points_redeemed} points for this sale")
            
            sale.save()
            
            # Award loyalty points if any (for earning points, not redeeming)
            points_earned = 0
            if points_to_award > 0 and customer:
                try:
                    points_earned = customer.add_points(
                        points_to_award,
                        sale=sale,
                        description=f"Points earned for sale #{sale.sale_id}"
                    )
                    logger.info(f"✅ Awarded {points_earned} points to customer {customer.phone_number}")
                except Exception as e:
                    logger.error(f"Failed to award points: {str(e)}")
            
            # Now deduct stock (since payment is confirmed)
            from inventory.models import StockEntry
            
            for item in sale.items.all():
                if item.product:
                    # Skip if stock already deducted (check if already processed)
                    stock_entry_exists = StockEntry.objects.filter(
                        reference_id=sale.sale_id,
                        entry_type='sale'
                    ).exists()
                    
                    if not stock_entry_exists:
                        item.product.quantity -= item.quantity
                        if item.product.category and item.product.category.is_single_item:
                            item.product.status = 'sold'
                            item.product.quantity = 0
                        item.product.save()
                        
                        StockEntry.objects.create(
                            product=item.product,
                            quantity=-item.quantity,
                            entry_type='sale',
                            unit_price=item.unit_price,
                            total_amount=item.total_price,
                            reference_id=sale.sale_id,
                            notes=f"Sale #{sale.sale_id} - Payment confirmed",
                            created_by=request.user
                        )
            
            # Clear cart from session
            request.session['sales_cart'] = []
            
            return JsonResponse({
                'success': True, 
                'message': 'Sale completed',
                'points_awarded': points_earned,
                'points_redeemed': points_redeemed,
                'customer_id': customer.id if customer else None
            })
            
    except Exception as e:
        logger.error(f"Error completing sale: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def delete_pending_sale(request, sale_id):
    """Delete a pending sale if payment failed"""
    try:
        sale = get_object_or_404(Sale, sale_id=sale_id)
        
        # Only allow deletion if no payment was made
        if sale.amount_paid == 0:
            sale.delete()
            return JsonResponse({'success': True, 'message': 'Pending sale deleted'})
        else:
            return JsonResponse({'success': False, 'error': 'Cannot delete completed sale'})
            
    except Exception as e:
        logger.error(f"Error deleting pending sale: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def check_mpesa_pending(request):
    """Check if there's a pending M-Pesa transaction for a phone number"""
    try:
        phone_number = request.GET.get('phone', '')
        if not phone_number:
            return JsonResponse({'has_pending': False})
        
        cleaned_phone = normalize_phone(phone_number)
        
        from finance.models import MpesaTransaction
        from datetime import timedelta
        
        # Find pending transaction in last 5 minutes
        time_threshold = timezone.now() - timedelta(minutes=5)
        pending_trans = MpesaTransaction.objects.filter(
            phone_number__icontains=cleaned_phone,
            status='pending',
            created_at__gte=time_threshold
        ).first()
        
        if pending_trans:
            # Calculate seconds remaining (2 minutes total from creation)
            elapsed = (timezone.now() - pending_trans.created_at).total_seconds()
            remaining = max(0, 120 - elapsed)
            
            return JsonResponse({
                'has_pending': True,
                'seconds_remaining': remaining,
                'checkout_id': pending_trans.checkout_request_id
            })
        
        return JsonResponse({'has_pending': False})
        
    except Exception as e:
        logger.error(f"Error checking pending M-Pesa: {str(e)}")
        return JsonResponse({'has_pending': False})

@login_required
def cancel_pending_mpesa(request):
    """Cancel/clear pending M-Pesa transaction for a phone number"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            phone_number = data.get('phone_number', '')
            
            if not phone_number:
                return JsonResponse({'success': False, 'error': 'Phone number required'})
            
            cleaned_phone = normalize_phone(phone_number)
            
            # Find pending transactions for this phone
            from finance.models import MpesaTransaction
            pending_transactions = MpesaTransaction.objects.filter(
                phone_number__icontains=cleaned_phone,
                status='pending',
                created_at__gte=timezone.now() - timedelta(minutes=30)
            )
            
            # Mark them as cancelled/expired
            count = pending_transactions.update(
                status='expired',
                result_desc='Cancelled by user',
                updated_at=timezone.now()
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Cancelled {count} pending transaction(s)',
                'count': count
            })
            
        except Exception as e:
            logger.error(f"Error cancelling pending M-Pesa: {str(e)}")
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})

@require_http_methods(["POST"])
@csrf_exempt
def create_split_payment_sale(request):
    """Handle split payment sales with multiple payment methods"""
    
    try:
        data = json.loads(request.body)
        
        # Extract data
        cart_items = data.get('cart_items', [])
        split_payments = data.get('split_payments', [])
        total_amount = Decimal(str(data.get('cart_total', 0)))
        total_paid = Decimal(str(data.get('amount_paid', 0)))
        points_redeemed_total = int(data.get('points_redeemed', 0))
        points_redeemed_customer_id = data.get('points_redeemed_customer_id')
        
        # Validate payment totals
        calculated_total = sum(Decimal(str(p.get('amount', 0))) for p in split_payments)
        if abs(calculated_total - total_paid) > 0.01:
            return JsonResponse({
                'error': f'Payment total mismatch: {calculated_total} vs {total_paid}'
            }, status=400)
        
        # Start database transaction
        with transaction.atomic():
            # ============================================
            # FIRST: Get customer info for points redemption
            # ============================================
            points_customer = None
            buyer_name = data.get('buyer_name', 'Walk-in Customer')
            buyer_phone = data.get('buyer_phone', '')
            points_customer_id = None
            
            if points_redeemed_total > 0 and points_redeemed_customer_id:
                from .models import Customer
                try:
                    points_customer = Customer.objects.select_for_update().get(id=points_redeemed_customer_id)
                    points_customer_id = points_customer.id
                    
                    # Check if customer has enough points
                    if points_customer.points_balance < points_redeemed_total:
                        raise ValueError(f"Insufficient points. Available: {points_customer.points_balance}, Requested: {points_redeemed_total}")
                    
                    # USE THE CUSTOMER'S NAME AND PHONE FOR THE SALE
                    buyer_name = points_customer.full_name
                    buyer_phone = points_customer.phone_number
                    
                    logger.info(f"✅ Points redemption by customer: {points_customer.full_name} ({points_customer.phone_number})")
                    logger.info(f"   Redeeming {points_redeemed_total} points, current balance: {points_customer.points_balance}")
                    
                except Customer.DoesNotExist:
                    logger.warning(f"Customer {points_redeemed_customer_id} not found for points redemption")
            
            # Also check for regular customer lookup (without points redemption)
            verified_customer_id = data.get('verified_customer_id')
            if not points_customer and verified_customer_id:
                from .models import Customer
                try:
                    regular_customer = Customer.objects.get(id=verified_customer_id)
                    buyer_name = regular_customer.full_name
                    buyer_phone = regular_customer.phone_number
                    logger.info(f"✅ Regular customer: {regular_customer.full_name}")
                except Customer.DoesNotExist:
                    pass
            
            # Calculate original subtotal (before points discount)
            original_subtotal = total_amount + Decimal(str(points_redeemed_total))
            
            # Create sale record - LET THE MODEL GENERATE THE ID
            sale = Sale.objects.create(
                seller=request.user if request.user.is_authenticated else None,
                buyer_name=buyer_name,
                buyer_phone=buyer_phone,
                buyer_id_number=points_customer.id_number if points_customer else data.get('buyer_id_number', ''),
                total_amount=total_amount,
                amount_paid=total_paid,
                payment_method='Split',
                is_split_payment=True,
                is_credit=False,
                points_redeemed=points_redeemed_total,
                points_discount=Decimal(str(points_redeemed_total)),
                original_subtotal=original_subtotal,
                subtotal=original_subtotal,
            )
            
            logger.info(f"✅ Split payment sale created: {sale.sale_id}")
            
            # Track change amount for cash payments
            total_cash = sum(p.get('amount', 0) for p in split_payments if p.get('method') == 'Cash')
            change_amount = max(Decimal('0'), Decimal(str(total_cash)) - total_amount)
            
            # ============================================
            # Handle points redemption - DEDUCT POINTS
            # ============================================
            if points_redeemed_total > 0 and points_customer:
                # Deduct points
                points_customer.points_balance -= points_redeemed_total
                points_customer.total_spent += original_subtotal
                points_customer.total_purchases += 1
                points_customer.last_purchase_date = timezone.now()
                points_customer.save()
                
                # Record the redemption
                from .models import LoyaltyTransaction
                LoyaltyTransaction.objects.create(
                    customer=points_customer,
                    points=-points_redeemed_total,
                    transaction_type='redeemed',
                    sale=sale,
                    description=f"Redeemed {points_redeemed_total} points for sale #{sale.sale_id}"
                )
                
                logger.info(f"✅ Points redeemed: {points_redeemed_total} deducted from customer {points_customer.phone_number}")
                logger.info(f"   New balance: {points_customer.points_balance}")
            
            # Create individual payment records
            for payment in split_payments:
                method = payment['method']
                amount = Decimal(str(payment['amount']))
                
                payment_record = PaymentRecord.objects.create(
                    sale=sale,
                    method=method,
                    amount=amount,
                    processed_by=request.user if request.user.is_authenticated else None,
                )
                
                # Set method-specific fields
                if method == 'Cash':
                    payment_record.cash_tendered = amount
                    payment_record.cash_change = change_amount if payment == split_payments[-1] else Decimal('0')
                    
                elif method == 'M-Pesa':
                    payment_record.mpesa_phone = payment.get('phone', '')
                    payment_record.mpesa_transaction_id = payment.get('transactionId', '')
                    payment_record.mpesa_checkout_request_id = payment.get('checkout_request_id', '')
                    
                elif method == 'Card':
                    payment_record.bank_name = payment.get('bank', '')
                    payment_record.card_last_four = payment.get('card_last_four', '')
                    
                elif method == 'Points':
                    payment_record.points_redeemed = payment.get('points', 0)
                    payment_record.customer = points_customer
                
                payment_record.save()
            
            # Store payment breakdown as JSON
            sale.payment_breakdown = {
                'payments': [
                    {
                        'method': p.method,
                        'amount': float(p.amount),
                        'details': {
                            'bank': p.bank_name,
                            'mpesa_transaction': p.mpesa_transaction_id,
                            'points': p.points_redeemed
                        }
                    }
                    for p in sale.payment_records.all()
                ]
            }
            sale.save(update_fields=['payment_breakdown'])
            
            # Create sale items and process inventory
            from inventory.models import Product
            from .models import SaleItem
            
            for item in cart_items:
                product = Product.objects.select_for_update().get(
                    sku_code=item.get('sku_code') or item.get('product_code')
                )
                
                quantity = item.get('quantity', 1)
                unit_price = Decimal(str(item.get('price', 0)))
                total_price = unit_price * quantity
                
                # Create sale item
                sale_item = SaleItem.objects.create(
                    sale=sale,
                    product=product,
                    product_code=product.sku_code,
                    product_name=product.display_name,
                    sku_value=product.sku_code,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=total_price
                )
                
                # For single items, handle stock
                if product.category.is_single_item:
                    unit = product.units.filter(status='available').first()
                    if unit:
                        unit.mark_as_sold(
                            customer=points_customer if points_customer else None,
                            price=unit_price,
                            sold_by=request.user
                        )
                        
                        StockEntry.objects.create(
                            product_unit=unit,
                            quantity=-quantity,
                            entry_type='sale',
                            unit_price=unit_price,
                            total_amount=total_price,
                            reference_id=sale.sale_id,
                            notes=f"Sale #{sale.sale_id}",
                            created_by=request.user
                        )
                else:
                    # Bulk items - reduce quantity
                    product.bulk_quantity -= quantity
                    product.save()
                    
                    StockEntry.objects.create(
                        product_sku=product,
                        quantity=-quantity,
                        entry_type='sale',
                        unit_price=unit_price,
                        total_amount=total_price,
                        reference_id=sale.sale_id,
                        notes=f"Sale #{sale.sale_id}",
                        created_by=request.user
                    )
            
            # Award loyalty points ONLY if points were NOT redeemed
            points_earned = 0
            new_balance = points_customer.points_balance if points_customer else 0
            
            if points_redeemed_total == 0 and points_customer:
                # Award points (1% of sale value)
                points_to_award = int(total_amount / 100)
                if points_to_award > 0:
                    points_customer.points_balance += points_to_award
                    points_customer.save()
                    
                    from .models import LoyaltyTransaction
                    LoyaltyTransaction.objects.create(
                        customer=points_customer,
                        points=points_to_award,
                        transaction_type='earned',
                        sale=sale,
                        description=f"Points earned from split payment sale"
                    )
                    points_earned = points_to_award
                    new_balance = points_customer.points_balance
                    logger.info(f"✅ Points awarded: {points_earned} to customer {points_customer.phone_number}")
            
            # Return success response
            return JsonResponse({
                'success': True,
                'sale_id': sale.sale_id,
                'sale_number': sale.sale_id,
                'message': 'Split payment sale completed successfully',
                'payment_breakdown': [
                    {'method': p.method, 'amount': float(p.amount)} 
                    for p in sale.payment_records.all()
                ],
                'points_earned': points_earned,
                'points_redeemed': points_redeemed_total,
                'new_points_balance': new_balance,
                'customer_name': buyer_name,
                'customer_phone': buyer_phone,
                'change_amount': float(change_amount) if change_amount > 0 else 0
            })
            
    except Exception as e:
        logger.error(f"Split payment sale error: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'error': f'Sale failed: {str(e)}'}, status=500)

@require_http_methods(["GET"])
def get_sale_payment_details(request, sale_id):
    """Get detailed payment breakdown for a sale"""
    
    try:
        from .models import Sale
        sale = Sale.objects.get(sale_id=sale_id)
        
        payment_records = sale.payment_records.all()
        
        return JsonResponse({
            'success': True,
            'sale_id': sale.sale_id,
            'total_amount': float(sale.total_amount),
            'amount_paid': float(sale.amount_paid),
            'change_amount': float(sale.change),
            'is_split_payment': sale.is_split_payment,
            'payments': [
                {
                    'method': record.method,
                    'amount': float(record.amount),
                    'bank_name': record.bank_name,
                    'mpesa_phone': record.mpesa_phone,
                    'mpesa_transaction_id': record.mpesa_transaction_id,
                    'points_redeemed': record.points_redeemed,
                    'created_at': record.created_at.isoformat()
                }
                for record in payment_records
            ]
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)