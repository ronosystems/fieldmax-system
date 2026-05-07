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
from sales.models import Sale, SaleItem, PaymentRecord, generate_sale_id, Customer, LoyaltySettings, LoyaltyTransaction
from inventory.models import Product, StockEntry
from django.core.paginator import Paginator
from django.contrib.auth.models import User
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


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
    """Sales statistics dashboard - OPTIMIZED VERSION"""
    
    from django.db.models import Sum, Count, Avg, Q, F, Value, DecimalField, Case, When
    from django.db.models.functions import TruncDate, TruncMonth, ExtractHour, ExtractWeekDay
    from decimal import Decimal
    
    today = timezone.now().date()
    
    # ============================================
    # Get IDs of sales that have been returned (once only)
    # ============================================
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
    # OPTIMIZED: Calculate profit using database aggregation
    # ============================================
    def get_profit_for_sales(sales_queryset):
        """Calculate profit using database aggregation - FAST"""
        result = SaleItem.objects.filter(
            sale__in=sales_queryset,
            sale__is_reversed=False,
            product__buying_price__isnull=False
        ).annotate(
            profit_per_item=F('unit_price') - F('product__buying_price')
        ).aggregate(
            total_profit=Sum(F('profit_per_item') * F('quantity'), output_field=DecimalField(max_digits=15, decimal_places=2))
        )
        return result['total_profit'] or Decimal('0.00')
    
    # ============================================
    # Get all period querysets once
    # ============================================
    today_start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
    today_end = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.max.time()))
    week_start = timezone.make_aware(timezone.datetime.combine(today - timedelta(days=today.weekday()), timezone.datetime.min.time()))
    month_start = timezone.make_aware(timezone.datetime.combine(today.replace(day=1), timezone.datetime.min.time()))
    year_start = timezone.make_aware(timezone.datetime.combine(today.replace(month=1, day=1), timezone.datetime.min.time()))
    
    # Get all filtered querysets (using sale_id instead of id)
    today_qs = active_sales_qs.filter(sale_date__range=[today_start, today_end])
    week_qs = active_sales_qs.filter(sale_date__gte=week_start)
    month_qs = active_sales_qs.filter(sale_date__gte=month_start)
    year_qs = active_sales_qs.filter(sale_date__gte=year_start)
    all_qs = active_sales_qs
    
    # ============================================
    # OPTIMIZED: Single aggregation queries
    # ============================================
    # Overview stats - use Count('sale_id') instead of Count('id')
    overview_stats = all_qs.aggregate(
        total_sales=Count('sale_id'),
        total_revenue=Sum('total_amount'),
        total_items=Sum('items__quantity')
    )
    
    # Period stats using single queries
    period_stats = {
        'today': today_qs.aggregate(count=Count('sale_id'), revenue=Sum('total_amount')),
        'week': week_qs.aggregate(count=Count('sale_id'), revenue=Sum('total_amount')),
        'month': month_qs.aggregate(count=Count('sale_id'), revenue=Sum('total_amount')),
        'year': year_qs.aggregate(count=Count('sale_id'), revenue=Sum('total_amount')),
    }
    
    # Get profits (only 4 queries instead of 30+)
    total_profit = get_profit_for_sales(all_qs)
    today_profit = get_profit_for_sales(today_qs)
    week_profit = get_profit_for_sales(week_qs)
    month_profit = get_profit_for_sales(month_qs)
    year_profit = get_profit_for_sales(year_qs)
    
    # Extract values
    total_sales = overview_stats['total_sales'] or 0
    total_revenue = overview_stats['total_revenue'] or Decimal('0.00')
    total_items_sold = overview_stats['total_items'] or 0
    profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    today_count = period_stats['today']['count'] or 0
    today_revenue = period_stats['today']['revenue'] or Decimal('0.00')
    week_count = period_stats['week']['count'] or 0
    week_revenue = period_stats['week']['revenue'] or Decimal('0.00')
    month_count = period_stats['month']['count'] or 0
    month_revenue = period_stats['month']['revenue'] or Decimal('0.00')
    year_count = period_stats['year']['count'] or 0
    year_revenue = period_stats['year']['revenue'] or Decimal('0.00')
    
    # Calculate margins
    month_margin = (month_profit / month_revenue * 100) if month_revenue > 0 else 0
    year_margin = (year_profit / year_revenue * 100) if year_revenue > 0 else 0
    
    # Averages
    avg_transaction_value = total_revenue / total_sales if total_sales > 0 else 0
    avg_items_per_sale = total_items_sold / total_sales if total_sales > 0 else 0
    avg_profit_per_sale = total_profit / total_sales if total_sales > 0 else 0
    
    # ============================================
    # OPTIMIZED: Daily breakdown using database aggregation (1 query)
    # ============================================
    from django.db.models.functions import TruncDate
    
    daily_breakdown = all_qs.filter(
        sale_date__gte=week_start
    ).annotate(
        sale_date_only=TruncDate('sale_date')
    ).values('sale_date_only').annotate(
        count=Count('sale_id'),
        revenue=Sum('total_amount')
    ).order_by('sale_date_only')
    
    # Build daily breakdown list
    daily_sales_breakdown = []
    daily_profits = {}
    
    # Get profits for each day (one query per day - but limited to 7 days)
    for day_data in daily_breakdown:
        date_obj = day_data['sale_date_only']
        day_qs = all_qs.filter(sale_date__date=date_obj)
        day_profit = get_profit_for_sales(day_qs)
        daily_profits[date_obj] = day_profit
        
        daily_sales_breakdown.append({
            'day': date_obj.strftime('%A'),
            'date': date_obj.strftime('%Y-%m-%d'),
            'revenue': day_data['revenue'] or Decimal('0.00'),
            'profit': day_profit,
            'margin': (day_profit / day_data['revenue'] * 100) if day_data['revenue'] else 0,
            'count': day_data['count'] or 0
        })
    
    daily_totals = {
        'count': sum(d['count'] for d in daily_sales_breakdown),
        'revenue': sum(d['revenue'] for d in daily_sales_breakdown),
        'profit': sum(d['profit'] for d in daily_sales_breakdown),
        'avg_margin': sum(d['margin'] for d in daily_sales_breakdown) / len(daily_sales_breakdown) if daily_sales_breakdown else 0,
    }
    
    # ============================================
    # OPTIMIZED: Weekly breakdown
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
        
        week_qs_filtered = all_qs.filter(sale_date__range=[week_start_aware, week_end_aware])
        
        week_stats = week_qs_filtered.aggregate(
            count=Count('sale_id'),
            revenue=Sum('total_amount')
        )
        week_profit_calc = get_profit_for_sales(week_qs_filtered)
        
        month_name = week_start.strftime('%b')
        date_range = f"{month_name} {start_day}{get_day_suffix(start_day)} - {month_name} {end_day}{get_day_suffix(end_day)}"
        
        weekly_sales_breakdown.append({
            'week_number': week_num,
            'week_range': date_range,
            'revenue': week_stats['revenue'] or Decimal('0.00'),
            'profit': week_profit_calc,
            'margin': (week_profit_calc / (week_stats['revenue'] or 1) * 100) if week_stats['revenue'] else 0,
            'count': week_stats['count'] or 0
        })
    
    # ============================================
    # OPTIMIZED: Monthly breakdown (1 query)
    # ============================================
    monthly_breakdown = all_qs.annotate(
        month_year=TruncMonth('sale_date')
    ).values('month_year').annotate(
        count=Count('sale_id'),
        revenue=Sum('total_amount')
    ).order_by('-month_year')[:12]
    
    monthly_sales_breakdown = []
    for month_data in monthly_breakdown:
        month_date = month_data['month_year'].date()
        month_qs_filtered = all_qs.filter(sale_date__year=month_date.year, sale_date__month=month_date.month)
        month_profit_calc = get_profit_for_sales(month_qs_filtered)
        
        monthly_sales_breakdown.append({
            'month': month_date.strftime('%B %Y'),
            'month_short': month_date.strftime('%b %Y'),
            'revenue': month_data['revenue'] or Decimal('0.00'),
            'profit': month_profit_calc,
            'margin': (month_profit_calc / (month_data['revenue'] or 1) * 100) if month_data['revenue'] else 0,
            'count': month_data['count'] or 0,
            'year': month_date.year,
            'month_name': month_date.strftime('%B')
        })
    
    # ============================================
    # OPTIMIZED: Daily chart (1 query instead of 30)
    # ============================================
    thirty_days_ago = today - timedelta(days=30)
    thirty_days_ago_aware = timezone.make_aware(timezone.datetime.combine(thirty_days_ago, timezone.datetime.min.time()))
    
    chart_data = all_qs.filter(
        sale_date__gte=thirty_days_ago_aware
    ).annotate(
        date_only=TruncDate('sale_date')
    ).values('date_only').annotate(
        revenue=Sum('total_amount'),
        count=Count('sale_id')
    ).order_by('date_only')
    
    # Create a dictionary for quick lookup
    chart_dict = {item['date_only']: item for item in chart_data}
    
    daily_sales = []
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        day_data = chart_dict.get(day)
        daily_sales.append({
            'date': day.strftime('%Y-%m-%d'),
            'display_date': day.strftime('%d %b'),
            'revenue': float(day_data['revenue']) if day_data else 0,
            'count': day_data['count'] if day_data else 0
        })
    
    # ============================================
    # OPTIMIZED: Hourly sales (1 query)
    # ============================================
    hourly_data = today_qs.annotate(
        hour=ExtractHour('sale_date')
    ).values('hour').annotate(
        revenue=Sum('total_amount'),
        count=Count('sale_id')
    ).order_by('hour')
    
    hourly_dict = {item['hour']: item for item in hourly_data}
    
    hourly_sales = []
    for hour in range(7, 22):
        hour_data = hourly_dict.get(hour)
        hourly_sales.append({
            'hour': f"{hour:02d}:00",
            'revenue': float(hour_data['revenue']) if hour_data else 0,
            'count': hour_data['count'] if hour_data else 0
        })
    
    # ============================================
    # Top Products (optimized with profit calculation)
    # ============================================
    top_products = SaleItem.objects.filter(
        sale__in=all_qs,
        sale__is_reversed=False
    ).select_related('product').values(
        'product_code', 'product_name'
    ).annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('total_price'),
        avg_price=Avg('unit_price')
    ).order_by('-total_quantity')[:10]
    
    # Calculate profit for each product
    products_with_profit = []
    for product in top_products:
        # Get profit for this product
        profit_data = SaleItem.objects.filter(
            sale__in=all_qs,
            product_code=product['product_code'],
            sale__is_reversed=False
        ).annotate(
            profit_per_item=F('unit_price') - F('product__buying_price')
        ).aggregate(
            total_profit=Sum(F('profit_per_item') * F('quantity'), output_field=DecimalField(max_digits=15, decimal_places=2))
        )
        total_profit_val = profit_data['total_profit'] or Decimal('0.00')
        
        products_with_profit.append({
            'product_code': product['product_code'],
            'product_name': product['product_name'],
            'total_quantity': product['total_quantity'] or 0,
            'total_revenue': product['total_revenue'] or Decimal('0.00'),
            'total_profit': total_profit_val,
            'margin': (total_profit_val / (product['total_revenue'] or 1) * 100) if product['total_revenue'] else 0
        })
    
    # ============================================
    # Top Sellers
    # ============================================
    top_sellers = User.objects.filter(
        sales_made__in=all_qs,
        sales_made__is_reversed=False
    ).annotate(
        sales_count=Count('sales_made'),
        total_revenue=Sum('sales_made__total_amount')
    ).order_by('-total_revenue')[:10]
    
    sellers_with_profit = []
    for seller in top_sellers:
        seller_sales = all_qs.filter(seller=seller)
        seller_profit = get_profit_for_sales(seller_sales)
        sellers_with_profit.append({
            'id': seller.id,
            'username': seller.username,
            'first_name': seller.first_name,
            'last_name': seller.last_name,
            'get_full_name': seller.get_full_name(),
            'sales_count': seller.sales_count or 0,
            'total_revenue': seller.total_revenue or Decimal('0.00'),
            'total_profit': seller_profit,
            'margin': (seller_profit / (seller.total_revenue or 1) * 100) if seller.total_revenue else 0
        })
    
    # ============================================
    # Payment Methods
    # ============================================
    payment_methods = []
    for method, _ in Sale._meta.get_field('payment_method').choices:
        method_sales = all_qs.filter(payment_method=method)
        revenue = method_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        payment_methods.append({
            'name': method,
            'count': method_sales.count(),
            'revenue': revenue,
            'percentage': (revenue / total_revenue * 100) if total_revenue > 0 else 0,
            'color': get_payment_method_color(method)
        })
    
    # ============================================
    # Additional Stats
    # ============================================
    credit_sales = all_qs.filter(is_credit=True)
    credit_count = credit_sales.count()
    credit_revenue = credit_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    credit_percentage = (credit_revenue / total_revenue * 100) if total_revenue > 0 else 0
    
    etr_processed = all_qs.filter(etr_receipt_number__isnull=False).count()
    etr_pending = all_qs.filter(etr_receipt_number__isnull=True).count()
    etr_failed = 0
    
    reversed_sales = Sale.objects.filter(is_reversed=True)
    reversed_count = reversed_sales.count()
    reversed_amount = reversed_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    reversal_percentage = (reversed_amount / total_revenue * 100) if total_revenue > 0 else 0
    
    # Recent sales (limit to 20)
    recent_sales = all_qs.order_by('-sale_date')[:20]
    for sale in recent_sales:
        sale.items_count = sale.items.count()
    
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
        'month_margin': month_margin,
        'year_count': year_count,
        'year_revenue': year_revenue,
        'year_profit': year_profit,
        'year_margin': year_margin,
        
        'recent_sales': recent_sales,
        'daily_sales_breakdown': daily_sales_breakdown,
        'weekly_sales_breakdown': weekly_sales_breakdown,
        'monthly_sales_breakdown': monthly_sales_breakdown,
        'top_products': products_with_profit,
        'top_sellers': sellers_with_profit,
        'payment_methods': payment_methods,
        'daily_sales': daily_sales,
        'daily_totals': daily_totals,
        'hourly_sales': hourly_sales,
        
        'credit_count': credit_count,
        'credit_revenue': credit_revenue,
        'credit_percentage': credit_percentage,
        'etr_processed': etr_processed,
        'etr_pending': etr_pending,
        'etr_failed': etr_failed,
        'reversed_count': reversed_count,
        'reversed_amount': reversed_amount,
        'reversal_percentage': reversal_percentage,
        
        # Placeholders for return stats
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
        'total_original_sales': Sale.objects.count(),
        'total_original_value': Sale.objects.aggregate(total=Sum('total_amount'))['total'] or 0,
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
    from django.db.models import Q
    from inventory.models import Product
    
    query = request.GET.get('q', '').strip()
    products = []
    
    try:
        # Base queryset - only show active products with stock
        queryset = Product.objects.filter(is_active=True, quantity__gt=0)
        
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
    """Create a new sale with loyalty points and M-Pesa support"""

    # ============================================
    # GET USER'S ASSIGNED SHOP FROM STAFF MODEL
    # ============================================
    current_shop = None
    try:
        from staff.models import Staff  # This should work if app is named 'staff'
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
            # Handle JSON data from AJAX
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
            # Handle traditional form POST
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
                # ============================================
                # NORMALIZE PHONE NUMBER FOR CONSISTENCY
                # ============================================
                def normalize_phone(phone):
                    """Convert phone numbers to international format (254XXXXXXXXX)"""
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
                
                # Calculate original subtotal before any discounts
                original_subtotal = Decimal('0.00')
                for item in cart:
                    original_subtotal += Decimal(str(item.get('total', 0)))
                
                # =========================================================
                # LOYALTY POINTS REDEMPTION - ONLY FOR REGISTERED CUSTOMERS
                # =========================================================
                points_discount = Decimal('0.00')
                final_amount = original_subtotal
                customer = None
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
                    product = Product.objects.select_for_update().get(product_code=item['product_code'])
                    product.refresh_from_db()
                    
                    if product.quantity < item['quantity']:
                        raise ValueError(f"Insufficient stock for {product.display_name}. Available: {product.quantity}")
                    
                    if product.category and product.category.is_single_item:
                        active_sale_exists = SaleItem.objects.filter(
                            sku_value=product.sku_value, sale__is_reversed=False
                        ).exists()
                        if active_sale_exists:
                            raise ValueError(f"This {product.display_name} (SKU: {product.sku_value}) has already been sold!")
                    
                    SaleItem.objects.create(
                        sale=sale,
                        product=product,
                        product_code=product.product_code,
                        product_name=product.display_name,
                        sku_value=product.sku_value,
                        quantity=item['quantity'],
                        unit_price=Decimal(str(item['price'])),
                        total_price=Decimal(str(item['total']))
                    )
                    
                    product.quantity -= item['quantity']
                    if product.category and product.category.is_single_item:
                        product.status = 'sold'
                        product.quantity = 0
                    product.save()
                    
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
                
                # Loyalty points earning
                points_earned = 0
                if is_registered_customer and customer:
                    if points_redeemed > 0:
                        customer.redeem_points(points_redeemed, sale=sale, description=f"Redeemed for sale #{sale.sale_id}")
                    
                    customer.total_purchases += 1
                    customer.total_spent += original_subtotal
                    customer.last_purchase_date = timezone.now()
                    customer.save()
                    # Calculate points as 1% of sale value
                    points_to_add = customer.calculate_points_to_earn(float(final_amount))
                    points_earned = customer.add_points(points_to_add, sale=sale, description=f"Purchase #{sale.sale_id}")
                    
                    logger.info(f"💰 Registered customer {customer.phone_number}: Earned {points_earned} points")
                
                # Clear the cart (unless skip_cart_clear is True for M-Pesa)
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
                
                # Return appropriate response
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
    
    # ============================================
    # GET request - show the sale form with cart
    # ============================================
    
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
            
            # Calculate original subtotal
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
                    # ✅ NO NEED TO DEDUCT HERE - will deduct after sale creation
                else:
                    raise ValueError(f"Insufficient points. Available: {customer.points_balance}, Requested: {points_redeemed}")
            
            # Create sale
            sale = Sale.objects.create(
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
            
            # ✅ ADD THIS: Deduct points AFTER sale is created (needs sale ID)
            if is_registered_customer and points_redeemed > 0:
                customer.redeem_points(points_redeemed, sale=sale, description=f"Redeemed {points_redeemed} points for sale #{sale.sale_id}")
                logger.info(f"💰 Points redeemed: {points_redeemed} points deducted from customer {customer.phone_number}")
            
            # Process items
            for item in cart:
                product = Product.objects.select_for_update().get(product_code=item['product_code'])
                if product.quantity < item['quantity']:
                    raise ValueError(f"Insufficient stock for {product.display_name}")
                
                SaleItem.objects.create(
                    sale=sale,
                    product=product,
                    product_code=product.product_code,
                    product_name=product.display_name,
                    sku_value=product.sku_value,
                    quantity=item['quantity'],
                    unit_price=Decimal(str(item['price'])),
                    total_price=Decimal(str(item['total']))
                )
                
                product.quantity -= item['quantity']
                if product.category and product.category.is_single_item:
                    product.status = 'sold'
                    product.quantity = 0
                product.save()
                
                StockEntry.objects.create(
                    product=product,
                    quantity=-item['quantity'],
                    entry_type='sale',
                    unit_price=Decimal(str(item['price'])),
                    total_amount=Decimal(str(item['total'])),
                    reference_id=sale.sale_id,
                    notes=f"Sale #{sale.sale_id}",
                    created_by=request.user
                )
            
            # Award points (only if no points were redeemed)
            points_earned = 0
            if is_registered_customer and customer and points_redeemed == 0 and points_to_award > 0:
                points_earned = customer.add_points(points_to_award, sale=sale, description=f"Points earned for sale #{sale.sale_id}")
                customer.total_purchases += 1
                customer.total_spent += original_subtotal
                customer.last_purchase_date = timezone.now()
                customer.save()
            elif is_registered_customer and customer and points_redeemed > 0:
                # Still update purchase stats even when redeeming points
                customer.total_purchases += 1
                customer.total_spent += original_subtotal
                customer.last_purchase_date = timezone.now()
                customer.save()
            
            # Clear cart
            request.session['sales_cart'] = []
            
            # Return JSON response
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
            
            return JsonResponse(response_data)
            
    except Exception as e:
        logger.error(f"Sale API error: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})







from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse

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
            finalize = data.get('finalize', False)  # NEW: Check if we should finalize
            
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
                from inventory.models import StockEntry
                for item in sale.items.all():
                    if item.product:
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
            # Check status
            if product.status == 'sold':
                return JsonResponse({
                    'success': False,
                    'error': 'This item has already been sold'
                })
            
            # Check quantity
            if product.quantity <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Product out of stock'
                })
            
            # Check if already in an active sale
            from sales.models import SaleItem
            active_sale_exists = SaleItem.objects.filter(
                product=product,
                sale__is_reversed=False
            ).exists()
            
            if active_sale_exists:
                return JsonResponse({
                    'success': False,
                    'error': 'This item has already been sold in another transaction'
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
    
    # Migrate old cart items to include sku_value
    for item in cart:
        if 'sku_value' not in item:
            # Try to get product from database to fill missing sku_value
            try:
                from inventory.models import Product
                product = Product.objects.get(product_code=item['product_code'])
                item['sku_value'] = product.sku_value or ''
            except:
                item['sku_value'] = ''
    
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
            # FIX: Check if single item is already sold
            # ============================================
            if product.category and product.category.is_single_item:
                # Check if the product is already marked as sold
                if product.status == 'sold':
                    return JsonResponse({
                        'success': False,
                        'error': f'❌ {product.display_name} has already been sold and cannot be added to cart.'
                    })
                
                # Check if quantity is 0 or less
                if product.quantity <= 0:
                    return JsonResponse({
                        'success': False,
                        'error': f'❌ {product.display_name} is out of stock and cannot be sold.'
                    })
                
                # Check if already sold in an ACTIVE sale (not reversed)
                from sales.models import SaleItem
                active_sale_exists = SaleItem.objects.filter(
                    product=product,
                    sale__is_reversed=False
                ).exists()
                
                if active_sale_exists:
                    return JsonResponse({
                        'success': False,
                        'error': f'❌ {product.display_name} (SKU: {product.sku_value}) has already been sold in another transaction!'
                    })
                
                # Check if already in cart
                cart = request.session.get('sales_cart', [])
                for item in cart:
                    if item.get('product_code') == product_code:
                        return JsonResponse({
                            'success': False,
                            'error': f'❌ {product.display_name} is already in the cart'
                        })
                
                # Single items must have quantity = 1
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
                    'sku_value': product.sku_value or '',
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



from datetime import timedelta

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
    """
    Handle split payment sales with multiple payment methods
    Integration with existing Sale, SaleItem, and Customer models
    """
    
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
            # Generate sale ID using your existing system
            from .models import Sale, PaymentRecord
            sale_id = generate_sale_id ()
            
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
            
            # Create sale record with CORRECT customer name
            sale = Sale.objects.create(
                sale_id=generate_sale_id(),
                seller=request.user if request.user.is_authenticated else None,
                buyer_name=buyer_name,  # NOW USING CUSTOMER NAME
                buyer_phone=buyer_phone,  # NOW USING CUSTOMER PHONE
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
            from inventory.models import StockEntry
            from .models import SaleItem
            
            for item in cart_items:
                from inventory.models import Product
                product = Product.objects.select_for_update().get(
                    product_code=item.get('product_code')
                )
                
                quantity = item.get('quantity', 1)
                unit_price = Decimal(str(item.get('price', 0)))
                total_price = unit_price * quantity
                
                # Create sale item
                sale_item = SaleItem.objects.create(
                    sale=sale,
                    product=product,
                    product_code=product.product_code,
                    product_name=product.display_name or product.name,
                    sku_value=product.sku_value or '',
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=total_price
                )
                
                # Process the sale (deduct stock)
                sale_item.process_sale()
            
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
            
            # Return success response with customer info
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