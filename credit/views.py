from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum, Count, DecimalField, Value, ExpressionWrapper, F, FloatField, Case, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import datetime, timedelta, date
from decimal import Decimal
import logging
import calendar
import json
from django.http import JsonResponse
from django.conf import settings
from django.core.paginator import Paginator
from django.urls import reverse
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import (
    CreditCompany, CreditCustomer, CreditTransaction, 
    CompanyPayment, CreditTransactionLog,
    # Commission models
    SellerCommission, SellerCommissionSummary
)
from inventory.models import Product
from django.contrib.auth import get_user_model





User = get_user_model()
logger = logging.getLogger(__name__)





# ====================================
# HELPER FUNCTIONS
# ====================================

def get_payment_method_color(method):
    """Get color for payment method"""
    colors = {
        'mpesa': 'success',
        'bank': 'primary',
        'cheque': 'warning',
        'cash': 'info',
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

def get_commission_status_color(status):
    """Get color for commission status"""
    colors = {
        'pending': 'warning',
        'paid': 'success',
        'cancelled': 'danger',
    }
    return colors.get(status, 'secondary')





# ====================================
# STATISTICS VIEW (UPDATED WITH COMMISSION)
# ====================================

@login_required
def credit_statistics(request):
    """Credit statistics dashboard with daily, weekly, and monthly breakdowns"""
    
    # Date ranges
    today = timezone.now().date()
    start_of_day = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    end_of_day = timezone.make_aware(datetime.combine(today, datetime.max.time()))
    
    start_of_week = timezone.make_aware(datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time()))
    start_of_month = timezone.make_aware(datetime.combine(today.replace(day=1), datetime.min.time()))
    start_of_year = timezone.make_aware(datetime.combine(today.replace(month=1, day=1), datetime.min.time()))
    
    # Base queryset - exclude reversed transactions
    transactions_qs = CreditTransaction.objects.exclude(payment_status='reversed')
    
    # ============================================
    # OVERVIEW STATISTICS
    # ============================================
    
    # All time totals
    total_transactions = transactions_qs.count()
    total_value = transactions_qs.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
    
    # Pending payments (company hasn't paid yet)
    pending_transactions = transactions_qs.filter(payment_status='pending')
    pending_count = pending_transactions.count()
    pending_value = pending_transactions.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
    
    # Paid transactions
    paid_transactions = transactions_qs.filter(payment_status='paid')
    paid_count = paid_transactions.count()
    paid_value = paid_transactions.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
    
    # Cancelled transactions
    cancelled_count = CreditTransaction.objects.filter(payment_status='cancelled').count()
    reversed_count = CreditTransaction.objects.filter(payment_status='reversed').count()
    
    # Today's transactions
    today_transactions = transactions_qs.filter(transaction_date__range=[start_of_day, end_of_day])
    today_count = today_transactions.count()
    today_value = today_transactions.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
    
    # This month's transactions
    month_transactions = transactions_qs.filter(transaction_date__gte=start_of_month)
    month_count = month_transactions.count()
    month_value = month_transactions.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
    
    # Average values
    avg_transaction_value = total_value / total_transactions if total_transactions > 0 else 0
    
    # ============================================
    # COMMISSION STATISTICS (NEW)
    # ============================================
    total_commission = paid_transactions.aggregate(
        total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    paid_commission = paid_transactions.filter(
        commission_status='paid'
    ).aggregate(
        total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    pending_commission = paid_transactions.filter(
        commission_status='pending'
    ).aggregate(
        total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    # ============================================
    # DAILY BREAKDOWN - Monday to Sunday
    # ============================================
    daily_credit_breakdown = []
    daily_credit_total_commission = 0
    
    for i in range(7):
        day = start_of_week.date() + timedelta(days=i)
        day_start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
        day_end = timezone.make_aware(datetime.combine(day, datetime.max.time()))
        
        day_transactions = transactions_qs.filter(transaction_date__range=[day_start, day_end])
        day_value = day_transactions.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
        day_count = day_transactions.count()
        
        # Calculate collection rate for the day
        day_paid = day_transactions.filter(payment_status='paid').aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
        day_collection_rate = (day_paid / day_value * 100) if day_value > 0 else 0
        
        # Calculate commission for the day
        day_commission = day_transactions.filter(payment_status='paid').aggregate(
            total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
        )['total']
        daily_credit_total_commission += day_commission
        
        daily_credit_breakdown.append({
            'day': day.strftime('%A'),
            'date': day.strftime('%Y-%m-%d'),
            'value': day_value,
            'count': day_count,
            'collection_rate': day_collection_rate,
            'commission': day_commission,
        })

    # After the daily_credit_breakdown loop — compute true Mon-Sun totals
    daily_credit_total_value = sum(d['value'] for d in daily_credit_breakdown)
    daily_credit_total_count = sum(d['count'] for d in daily_credit_breakdown)

    # Weighted collection rate (paid / total), not an average of rates
    daily_credit_paid = sum(
        d['value'] * d['collection_rate'] / 100
        for d in daily_credit_breakdown
        if d['value'] > 0
    )
    daily_credit_totals = {
        'count': daily_credit_total_count,
        'value': daily_credit_total_value,
        'collection_rate': (daily_credit_paid / daily_credit_total_value * 100)
                       if daily_credit_total_value > 0 else 0,
        'commission': daily_credit_total_commission,
    }
    
    # Week totals for collection rate
    week_transactions = transactions_qs.filter(transaction_date__gte=start_of_week)
    week_credit_value = week_transactions.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
    week_paid = week_transactions.filter(payment_status='paid').aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
    week_collection_rate = (week_paid / week_credit_value * 100) if week_credit_value > 0 else 0
    week_commission = week_transactions.filter(payment_status='paid').aggregate(
        total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    # ============================================
    # WEEKLY BREAKDOWN - By Date Ranges of Current Month
    # ============================================
    current_year = today.year
    current_month = today.month
    
    # Get last day of month
    last_day = calendar.monthrange(current_year, current_month)[1]
    
    # Define weekly date ranges
    weekly_ranges = [
        (1, 7),      # Week 1: 1st - 7th
        (8, 14),     # Week 2: 8th - 14th
        (15, 21),    # Week 3: 15th - 21st
        (22, 28),    # Week 4: 22nd - 28th
        (29, last_day) # Week 5: 29th - last day (if exists)
    ]
    
    weekly_credit_breakdown = []
    
    for week_num, (start_day, end_day) in enumerate(weekly_ranges, 1):
        # Skip if start day is beyond month
        if start_day > last_day:
            continue
            
        # Adjust end day if beyond month
        end_day = min(end_day, last_day)
        
        week_start = date(current_year, current_month, start_day)
        week_end = date(current_year, current_month, end_day)
        
        week_start_aware = timezone.make_aware(datetime.combine(week_start, datetime.min.time()))
        week_end_aware = timezone.make_aware(datetime.combine(week_end, datetime.max.time()))
        
        week_trans = transactions_qs.filter(transaction_date__range=[week_start_aware, week_end_aware])
        week_value = week_trans.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
        week_count = week_trans.count()
        
        # Calculate collection rate for the week
        week_paid = week_trans.filter(payment_status='paid').aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
        week_collection = (week_paid / week_value * 100) if week_value > 0 else 0
        
        # Calculate commission for the week
        week_commission_value = week_trans.filter(payment_status='paid').aggregate(
            total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
        )['total']
        
        # Format date range
        month_name = week_start.strftime('%b')
        date_range = f"{month_name} {start_day}{get_day_suffix(start_day)} - {month_name} {end_day}{get_day_suffix(end_day)}"
        if start_day == end_day:
            date_range = f"{month_name} {start_day}{get_day_suffix(start_day)}"
        
        weekly_credit_breakdown.append({
            'week_number': week_num,
            'week_range': date_range,
            'value': week_value,
            'count': week_count,
            'collection_rate': week_collection,
            'commission': week_commission_value,
        })
    
    # Month totals
    month_credit_value = month_transactions.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
    month_paid = month_transactions.filter(payment_status='paid').aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
    month_collection_rate = (month_paid / month_credit_value * 100) if month_credit_value > 0 else 0
    month_commission = month_transactions.filter(payment_status='paid').aggregate(
        total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    # ============================================
    # MONTHLY BREAKDOWN - Last 12 months
    # ============================================
    monthly_credit_breakdown = []
    for i in range(11, -1, -1):
        month_date = today - timedelta(days=30*i)
        month_start = date(month_date.year, month_date.month, 1)
        month_end = date(month_date.year, month_date.month, 
                        calendar.monthrange(month_date.year, month_date.month)[1])
        
        month_start_aware = timezone.make_aware(datetime.combine(month_start, datetime.min.time()))
        month_end_aware = timezone.make_aware(datetime.combine(month_end, datetime.max.time()))
        
        month_trans = transactions_qs.filter(transaction_date__range=[month_start_aware, month_end_aware])
        month_value = month_trans.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
        month_count = month_trans.count()
        
        # Calculate paid amount for the month
        month_paid_amount = month_trans.filter(payment_status='paid').aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
        month_collection = (month_paid_amount / month_value * 100) if month_value > 0 else 0
        
        # Calculate commission for the month
        month_commission_value = month_trans.filter(payment_status='paid').aggregate(
            total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
        )['total']
        
        monthly_credit_breakdown.append({
            'month': month_start.strftime('%B %Y'),
            'month_short': month_start.strftime('%b %Y'),
            'value': month_value,
            'count': month_count,
            'paid_value': month_paid_amount,
            'collection_rate': month_collection,
            'commission': month_commission_value,
        })
    
    # Year totals
    year_transactions = transactions_qs.filter(transaction_date__gte=start_of_year)
    year_credit_value = year_transactions.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
    year_paid_value = year_transactions.filter(payment_status='paid').aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
    year_collection_rate = (year_paid_value / year_credit_value * 100) if year_credit_value > 0 else 0
    year_count = year_transactions.count()
    year_commission = year_transactions.filter(payment_status='paid').aggregate(
        total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    # ============================================
    # COMPANY BREAKDOWN
    # ============================================
    
    company_stats = []
    for company in CreditCompany.objects.filter(is_active=True):
        company_transactions = transactions_qs.filter(credit_company=company)
        company_pending = company_transactions.filter(payment_status='pending')
        company_paid = company_transactions.filter(payment_status='paid')
        
        total = company_transactions.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
        pending = company_pending.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
        paid = company_paid.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
        
        # Company commission
        company_commission_value = company_paid.aggregate(
            total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
        )['total']
        
        company_stats.append({
            'name': company.name,
            'code': company.code,
            'total_count': company_transactions.count(),
            'total_value': total,
            'pending_count': company_pending.count(),
            'pending_value': pending,
            'paid_count': company_paid.count(),
            'paid_value': paid,
            'pending_percentage': (pending / total * 100) if total > 0 else 0,
            'paid_percentage': (paid / total * 100) if total > 0 else 0,
            'commission': company_commission_value,
        })
    
    # Sort by total value descending
    company_stats.sort(key=lambda x: x['total_value'], reverse=True)
    
    # ============================================
    # TOP CUSTOMERS 
    # ============================================
    
    top_customers = CreditCustomer.objects.filter(
        transactions__payment_status__in=['pending', 'paid']
    ).annotate(
        txn_count=Count('transactions'),
        total_credit_value=Coalesce(
            Sum('transactions__ceiling_price', output_field=DecimalField()), 
            Value(0, output_field=DecimalField())
        ),
        pending_credit_value=Coalesce(
            Sum('transactions__ceiling_price', 
                filter=Q(transactions__payment_status='pending'),
                output_field=DecimalField()), 
            Value(0, output_field=DecimalField())
        ),
        paid_credit_value=Coalesce(
            Sum('transactions__ceiling_price', 
                filter=Q(transactions__payment_status='paid'),
                output_field=DecimalField()), 
            Value(0, output_field=DecimalField())
        )
    ).order_by('-total_credit_value')[:10]
    
    # ============================================
    # TOP SELLERS (DEALERS) - UPDATED WITH COMMISSION
    # ============================================
    
    # First, get the base queryset with annotations for counts and sums
    top_sellers_base = User.objects.filter(
        credit_transactions__payment_status__in=['pending', 'paid']
    ).annotate(
        sales_count=Count('credit_transactions'),
        total_credit=Coalesce(
            Sum('credit_transactions__ceiling_price', output_field=DecimalField()),
            Value(0, output_field=DecimalField())
        ),
        pending_credit=Coalesce(
            Sum('credit_transactions__ceiling_price', 
                filter=Q(credit_transactions__payment_status='pending'),
                output_field=DecimalField()),
            Value(0, output_field=DecimalField())
        ),
        paid_credit=Coalesce(
            Sum('credit_transactions__ceiling_price', 
                filter=Q(credit_transactions__payment_status='paid'),
                output_field=DecimalField()),
            Value(0, output_field=DecimalField())
        ),
        # Commission annotations
        total_commission=Coalesce(
            Sum('credit_transactions__commission_amount',
                filter=Q(credit_transactions__payment_status='paid'),
                output_field=DecimalField()),
            Value(0, output_field=DecimalField())
        ),
        paid_commission=Coalesce(
            Sum('credit_transactions__commission_amount',
                filter=Q(credit_transactions__commission_status='paid'),
                output_field=DecimalField()),
            Value(0, output_field=DecimalField())
        )
    ).order_by('-total_credit')[:10]
    
    # Format top sellers for template - calculate collection rate in Python
    top_sellers_list = []
    for seller in top_sellers_base:
        # Calculate collection rate safely in Python
        if seller.total_credit and seller.total_credit > 0:
            collection_rate = float(seller.paid_credit * 100 / seller.total_credit)
        else:
            collection_rate = 0
        
        # Build the seller dictionary with all needed fields
        top_sellers_list.append({
            'id': seller.id,
            'username': seller.username,
            'first_name': seller.first_name,
            'last_name': seller.last_name,
            'get_full_name': seller.get_full_name(),
            'sales_count': seller.sales_count,
            'total_credit': seller.total_credit,
            'pending_credit': seller.pending_credit,
            'paid_credit': seller.paid_credit,
            'collection_rate': collection_rate,
            'total_commission': seller.total_commission,
            'paid_commission': seller.paid_commission,
            'pending_commission': seller.total_commission - seller.paid_commission,
        })
    
    # ============================================
    # MONTHLY TREND (Last 6 months) - for chart
    # ============================================
    
    monthly_trend = []
    for i in range(5, -1, -1):
        month_date = today.replace(day=1) - timedelta(days=30*i)
        month_start = timezone.make_aware(datetime.combine(month_date, datetime.min.time()))
        
        if i > 0:
            next_month = month_date.replace(day=28) + timedelta(days=4)
            month_end = timezone.make_aware(datetime.combine(next_month.replace(day=1) - timedelta(days=1), datetime.max.time()))
        else:
            month_end = end_of_day
        
        month_trans = transactions_qs.filter(transaction_date__range=[month_start, month_end])
        month_paid = paid_transactions.filter(transaction_date__range=[month_start, month_end])
        
        monthly_trend.append({
            'month': month_date.strftime('%b %Y'),
            'total_value': month_trans.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total'],
            'total_count': month_trans.count(),
            'paid_value': month_paid.aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total'],
            'paid_count': month_paid.count(),
        })
    
    # ============================================
    # PAYMENT METHOD BREAKDOWN
    # ============================================
    
    payment_methods = []
    payments_qs = CompanyPayment.objects.all()
    total_payments = payments_qs.aggregate(total=Coalesce(Sum('amount'), Value(0, output_field=DecimalField())))['total']
    
    for method, _ in CompanyPayment.PAYMENT_METHODS:
        method_payments = payments_qs.filter(payment_method=method)
        amount = method_payments.aggregate(total=Coalesce(Sum('amount'), Value(0, output_field=DecimalField())))['total']
        count = method_payments.count()
        percentage = (amount / total_payments * 100) if total_payments > 0 else 0
        
        payment_methods.append({
            'name': method,
            'amount': amount,
            'count': count,
            'percentage': percentage,
            'color': get_payment_method_color(method)
        })
    
    # ============================================
    # AGING ANALYSIS (How long pending)
    # ============================================
    
    aging = {
        '0_30': 0,
        '31_60': 0,
        '61_90': 0,
        '90_plus': 0,
        'total': 0
    }
    
    for transaction in pending_transactions:
        days = (today - transaction.transaction_date.date()).days
        if days <= 30:
            aging['0_30'] += 1
        elif days <= 60:
            aging['31_60'] += 1
        elif days <= 90:
            aging['61_90'] += 1
        else:
            aging['90_plus'] += 1
        aging['total'] += 1
    
    # ============================================
    # CONTEXT DICTIONARY - UPDATED WITH COMMISSION
    # ============================================
    
    context = {
        # Overview
        'total_transactions': total_transactions,
        'total_value': total_value,
        'pending_count': pending_count,
        'pending_value': pending_value,
        'paid_count': paid_count,
        'paid_value': paid_value,
        'cancelled_count': cancelled_count,
        'reversed_count': reversed_count,
        'avg_transaction_value': avg_transaction_value,
        
        # Commission overview
        'total_commission': total_commission,
        'paid_commission': paid_commission,
        'pending_commission': pending_commission,
        
        # Time periods
        'today_count': today_count,
        'today_value': today_value,
        'month_count': month_count,
        'month_value': month_value,
        
        # Daily breakdown (Mon-Sun)
        'daily_credit_breakdown': daily_credit_breakdown,
        'week_credit_value': week_credit_value,
        'week_collection_rate': week_collection_rate,
        'week_commission': week_commission,
        'daily_credit_totals': daily_credit_totals,
        
        # Weekly breakdown (Week 1-4)
        'weekly_credit_breakdown': weekly_credit_breakdown,
        'month_credit_value': month_credit_value,
        'month_collection_rate': month_collection_rate,
        'month_commission': month_commission,
        
        # Monthly breakdown (Last 12 months)
        'monthly_credit_breakdown': monthly_credit_breakdown,
        'year_credit_value': year_credit_value,
        'year_paid_value': year_paid_value,
        'year_collection_rate': year_collection_rate,
        'year_count': year_count,
        'year_commission': year_commission,
        
        # Companies
        'company_stats': company_stats,
        'total_companies': CreditCompany.objects.filter(is_active=True).count(),
        
        # Customers
        'top_customers': top_customers,
        'total_customers': CreditCustomer.objects.filter(is_active=True).count(),
        
        # Top sellers (dealers) - UPDATED
        'top_sellers': top_sellers_list,
        
        # Trends
        'monthly_trend': monthly_trend,
        
        # Payments
        'payment_methods': payment_methods,
        'total_payments': total_payments,
        'payment_count': payments_qs.count(),
        
        # Aging
        'aging': aging,
    }
    
    return render(request, 'credit/statistics.html', context)


# ====================================
# DASHBOARD VIEW (UPDATED WITH COMMISSION)
# ====================================

@login_required
def dashboard(request):
    """Credit dashboard with overview - UPDATED WITH COMMISSION"""
    
    # Summary stats
    total_pending = CreditTransaction.objects.filter(payment_status='pending').aggregate(
        total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField()))
    )['total']
    
    total_paid = CreditTransaction.objects.filter(payment_status='paid').aggregate(
        total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField()))
    )['total']
    
    pending_count = CreditTransaction.objects.filter(payment_status='pending').count()
    paid_count = CreditTransaction.objects.filter(payment_status='paid').count()
    cancelled_count = CreditTransaction.objects.filter(payment_status='cancelled').count()
    
    # Commission stats
    total_commission = CreditTransaction.objects.filter(payment_status='paid').aggregate(
        total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    pending_commission = CreditTransaction.objects.filter(
        payment_status='paid', 
        commission_status='pending'
    ).aggregate(
        total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    # Companies summary
    companies = CreditCompany.objects.filter(is_active=True)[:5]
    
    # Recent transactions
    recent_transactions = CreditTransaction.objects.select_related(
        'customer', 'credit_company', 'product'
    ).order_by('-transaction_date')[:10]
    
    # Commission summary for current user if seller
    user_commission_summary = None
    if request.user.credit_transactions.exists():
        summary, created = SellerCommissionSummary.objects.get_or_create(seller=request.user)
        user_commission_summary = summary
    
    # Chart data (last 30 days) - include commission
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)
    
    chart_labels = []
    credit_data = []
    payment_data = []
    commission_data = []
    
    for i in range(30):
        day = thirty_days_ago + timedelta(days=i)
        next_day = day + timedelta(days=1)
        
        # Credit created on this day
        day_credit = CreditTransaction.objects.filter(
            transaction_date__date=day
        ).aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
        
        # Payments on this day (when transactions were marked as paid)
        day_payments = CreditTransaction.objects.filter(
            paid_date__date=day,
            payment_status='paid'
        ).aggregate(total=Coalesce(Sum('ceiling_price'), Value(0, output_field=DecimalField())))['total']
        
        # Commission earned on this day
        day_commission = CreditTransaction.objects.filter(
            paid_date__date=day,
            payment_status='paid'
        ).aggregate(total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField())))['total']
        
        chart_labels.append(day.strftime('%d %b'))
        credit_data.append(float(day_credit))
        payment_data.append(float(day_payments))
        commission_data.append(float(day_commission))
    
    context = {
        'total_pending': total_pending,
        'total_paid': total_paid,
        'pending_count': pending_count,
        'paid_count': paid_count,
        'cancelled_count': cancelled_count,
        'total_commission': total_commission,
        'pending_commission': pending_commission,
        'companies': companies,
        'recent_transactions': recent_transactions,
        'user_commission_summary': user_commission_summary,
        'chart_labels': json.dumps(chart_labels),
        'credit_data': json.dumps(credit_data),
        'payment_data': json.dumps(payment_data),
        'commission_data': json.dumps(commission_data),
    }
    
    return render(request, 'credit/dashboard.html', context)


# ====================================
# COMPANY VIEWS
# ====================================

@login_required
def company_list(request):
    """List all credit companies"""
    companies = CreditCompany.objects.all()
    
    # Optional: Filter by status if needed
    status = request.GET.get('status')
    if status == 'active':
        companies = companies.filter(is_active=True)
    elif status == 'inactive':
        companies = companies.filter(is_active=False)
    
    # Optional: Search
    search = request.GET.get('search')
    if search:
        companies = companies.filter(
            Q(name__icontains=search) |
            Q(code__icontains=search) |
            Q(email__icontains=search)
        )
    
    context = {
        'companies': companies,
    }
    return render(request, 'credit/companies/list.html', context)


@login_required
def company_add(request):
    """Add a new credit company"""
    if request.method == 'POST':
        try:
            company = CreditCompany.objects.create(
                name=request.POST.get('name'),
                email=request.POST.get('email'),
                phone=request.POST.get('phone', ''),
                contact_person=request.POST.get('contact_person', ''),
                address=request.POST.get('address', ''),
                payment_terms=request.POST.get('payment_terms', ''),
                is_active=request.POST.get('is_active') == 'on',
                created_by=request.user
            )
            messages.success(request, f'Company "{company.name}" added successfully.')
            return redirect('credit:company_list')
        except Exception as e:
            messages.error(request, f'Error adding company: {str(e)}')
    
    return render(request, 'credit/companies/add.html')

@login_required
def company_detail(request, pk):
    """View company details - UPDATED WITH COMMISSION"""
    company = get_object_or_404(CreditCompany, pk=pk)
    
    # Get transactions
    pending_transactions = company.transactions.filter(payment_status='pending').order_by('-transaction_date')
    paid_transactions = company.transactions.filter(payment_status='paid').order_by('-transaction_date')
    
    # Company commission summary
    company_commission = paid_transactions.aggregate(
        total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    context = {
        'company': company,
        'pending_transactions': pending_transactions,
        'paid_transactions': paid_transactions,
        'company_commission': company_commission,
    }
    return render(request, 'credit/companies/detail.html', context)

@login_required
def company_edit(request, pk):
    """Edit company details"""
    company = get_object_or_404(CreditCompany, pk=pk)
    
    if request.method == 'POST':
        try:
            company.name = request.POST.get('name')
            company.email = request.POST.get('email')
            company.phone = request.POST.get('phone', '')
            company.contact_person = request.POST.get('contact_person', '')
            company.address = request.POST.get('address', '')
            company.payment_terms = request.POST.get('payment_terms', '')
            company.is_active = request.POST.get('is_active') == 'on'
            company.save()
            
            messages.success(request, f'Company "{company.name}" updated successfully.')
            return redirect('credit:company_detail', pk=company.pk)
        except Exception as e:
            messages.error(request, f'Error updating company: {str(e)}')
    
    context = {'company': company}
    return render(request, 'credit/companies/edit.html', context)


# ====================================
# CUSTOMER VIEWS
# ====================================

@login_required
def customer_list(request):
    """List all credit customers"""
    customers = CreditCustomer.objects.all()
    
    # Apply filters
    search = request.GET.get('search')
    if search:
        customers = customers.filter(
            Q(full_name__icontains=search) |
            Q(id_number__icontains=search) |
            Q(phone_number__icontains=search)
        )
    
    county = request.GET.get('county')
    if county:
        customers = customers.filter(county__icontains=county)
    
    status = request.GET.get('status')
    if status == 'active':
        customers = customers.filter(is_active=True)
    elif status == 'inactive':
        customers = customers.filter(is_active=False)
    
    context = {
        'customers': customers,
    }
    return render(request, 'credit/customers/list.html', context)


@login_required
def customer_add(request):
    """Add a new credit customer with photo uploads"""
    if request.method == 'POST':
        try:
            # Check if this is an AJAX request
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            
            # Get form data
            full_name = request.POST.get('full_name')
            id_number = request.POST.get('id_number')
            phone_number = request.POST.get('phone_number')
            nok_name = request.POST.get('nok_name', '')
            nok_phone = request.POST.get('nok_phone', '')
            email = request.POST.get('email', '')
            alternate_phone = request.POST.get('alternate_phone', '')
            county = request.POST.get('county', '')
            town = request.POST.get('town', '')
            physical_address = request.POST.get('physical_address', '')
            
            # Check if customer with this ID already exists
            existing_customer = CreditCustomer.objects.filter(id_number=id_number).first()
            if existing_customer:
                # Check if this customer has any active credit transactions
                active_transactions = CreditTransaction.objects.filter(
                    customer=existing_customer,
                    payment_status__in=['pending', 'Active']
                ).exists()
                
                if active_transactions:
                    error_message = f"⚠️ CUSTOMER WITH ID {id_number} HAS AN ACTIVE LOAN: {existing_customer.full_name} - Please verify before adding a new customer with the same ID."
                else:
                    error_message = f"Customer with ID {id_number} already exists: {existing_customer.full_name} - No active loans found, but please verify before adding a new customer with the same ID."
                
                if is_ajax:
                    return JsonResponse({
                        'success': False,
                        'error': error_message,
                        'existing_customer': {
                            'id': existing_customer.id,
                            'full_name': existing_customer.full_name,
                            'phone_number': existing_customer.phone_number,
                            'has_active_credit': active_transactions
                        }
                    })
                else:
                    messages.error(request, error_message)
                    return render(request, 'credit/customers/add.html')
            
            # Handle file uploads
            passport_photo = request.FILES.get('passport_photo')
            id_front_photo = request.FILES.get('id_front_photo')
            id_back_photo = request.FILES.get('id_back_photo')
            additional_document = request.FILES.get('additional_document')
            
            # Create new customer
            customer = CreditCustomer.objects.create(
                full_name=full_name,
                id_number=id_number,
                phone_number=phone_number,
                nok_name=nok_name,
                nok_phone=nok_phone,
                email=email,
                alternate_phone=alternate_phone,
                county=county,
                town=town,
                physical_address=physical_address,
                passport_photo=passport_photo,
                id_front_photo=id_front_photo,
                id_back_photo=id_back_photo,
                additional_document=additional_document,
                is_active=True,
                created_by=request.user
            )
            
            if is_ajax:
                # Return JSON response for AJAX requests
                return JsonResponse({
                    'success': True,
                    'customer': {
                        'id': customer.id,
                        'full_name': customer.full_name,
                        'phone_number': customer.phone_number,
                        'id_number': customer.id_number,
                        'nok_name': customer.nok_name,
                        'nok_phone': customer.nok_phone,
                        'has_photos': customer.has_photos
                    }
                })
            else:
                # Regular form submission
                messages.success(request, f'Customer "{customer.full_name}" added successfully with photos.')
                # Check if there's a next parameter
                next_url = request.POST.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect('credit:customer_list')
                
        except Exception as e:
            logger.error(f"Error adding customer: {str(e)}")
            if is_ajax:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                })
            else:
                messages.error(request, f'Error adding customer: {str(e)}')
                return render(request, 'credit/customers/add.html')
    
    # GET request - show form
    return render(request, 'credit/customers/add.html')


@login_required
def customer_detail(request, pk):
    """View customer details"""
    customer = get_object_or_404(CreditCustomer, pk=pk)
    
    # Get transactions
    transactions = customer.transactions.all().order_by('-transaction_date')
    
    context = {
        'customer': customer,
        'transactions': transactions,
    }
    return render(request, 'credit/customers/detail.html', context)


@login_required
def customer_edit(request, pk):
    """Edit customer details"""
    customer = get_object_or_404(CreditCustomer, pk=pk)
    
    if request.method == 'POST':
        try:
            # Get form data
            full_name = request.POST.get('full_name')
            phone_number = request.POST.get('phone_number')
            email = request.POST.get('email', '')
            alternate_phone = request.POST.get('alternate_phone', '')
            county = request.POST.get('county', '')
            town = request.POST.get('town', '')
            physical_address = request.POST.get('physical_address', '')
            nok_name = request.POST.get('nok_name', '')
            nok_phone = request.POST.get('nok_phone', '')
            is_active = request.POST.get('is_active') == 'on'
            notes = request.POST.get('notes', '')
            
            # IMPORTANT: Do NOT update id_number - it should remain unchanged
            # Only update the editable fields
            customer.full_name = full_name
            customer.phone_number = phone_number
            customer.email = email
            customer.alternate_phone = alternate_phone
            customer.county = county
            customer.town = town
            customer.physical_address = physical_address
            customer.nok_name = nok_name
            customer.nok_phone = nok_phone
            customer.is_active = is_active
            customer.notes = notes
            
            customer.save()
            
            messages.success(request, f'Customer "{customer.full_name}" updated successfully.')
            return redirect('credit:customer_detail', pk=customer.pk)
            
        except Exception as e:
            messages.error(request, f'Error updating customer: {str(e)}')
    
    context = {'customer': customer}
    return render(request, 'credit/customers/edit.html', context)


# ====================================
# TRANSACTION VIEWS - UPDATED WITH COMMISSION
# ====================================

@login_required
def transaction_list(request):
    """List all credit transactions - UPDATED WITH COMMISSION FILTERS"""
    transactions = CreditTransaction.objects.select_related(
        'customer', 'credit_company', 'product', 'dealer'
    ).order_by('-transaction_date')
    
    # Filters
    status = request.GET.get('status')
    if status:
        transactions = transactions.filter(payment_status=status)
    
    company_id = request.GET.get('company')
    if company_id:
        transactions = transactions.filter(credit_company_id=company_id)
    
    # Commission status filter
    commission_status = request.GET.get('commission_status')
    if commission_status:
        transactions = transactions.filter(commission_status=commission_status)
    
    # Seller filter
    seller_id = request.GET.get('seller')
    if seller_id:
        transactions = transactions.filter(dealer_id=seller_id)
    
    context = {
        'transactions': transactions,
        'commission_status_choices': CreditTransaction.COMMISSION_STATUS,
    }
    return render(request, 'credit/transactions/list.html', context)


@login_required
def transaction_create(request):
    """Create a new credit transaction - UPDATED WITH COMMISSION"""
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Get form data
                company_id = request.POST.get('company')
                customer_id = request.POST.get('customer')
                product_id = request.POST.get('product')
                ceiling_price = Decimal(request.POST.get('ceiling_price', '0'))
                imei = request.POST.get('imei', '')
                notes = request.POST.get('notes', '')
                
                # Commission fields
                commission_type = request.POST.get('commission_type', 'percentage')
                commission_value = Decimal(request.POST.get('commission_value', '0'))
                
                # Get related objects
                company = CreditCompany.objects.get(id=company_id)
                customer = CreditCustomer.objects.get(id=customer_id)
                product = Product.objects.get(id=product_id)
                
                # Check if product is available for credit
                can_use, message = product.can_be_used_for_credit
                if not can_use:
                    messages.error(request, message)
                    return redirect('credit:transaction_create')
                
                # Check if this product already has ANY credit transaction
                existing_transaction = CreditTransaction.objects.filter(
                    product=product
                ).exists()
                
                if existing_transaction:
                    messages.error(
                        request, 
                        f'Product {product.product_code} already has a credit transaction. '
                        f'Each product can only be used once for credit.'
                    )
                    return redirect('credit:transaction_create')
                
                # Calculate commission amount
                if commission_type == 'percentage':
                    commission_amount = (ceiling_price * commission_value) / Decimal('100.00')
                else:
                    commission_amount = commission_value
                
                # Create transaction with commission
                credit_transaction = CreditTransaction.objects.create(
                    credit_company=company,
                    customer=customer,
                    dealer=request.user,
                    product=product,
                    ceiling_price=ceiling_price,
                    imei=imei,
                    notes=notes,
                    # Commission fields
                    commission_type=commission_type,
                    commission_value=commission_value,
                    commission_amount=round(commission_amount, 2),
                )
                
                # Create commission record
                SellerCommission.objects.create(
                    seller=request.user,
                    transaction=credit_transaction,
                    amount=round(commission_amount, 2)
                )
                
                # ============================================
                # UPDATE PRODUCT STATUS (Single item only)
                # ============================================
                if product.category.is_single_item:
                    product.status = 'sold'
                    product.quantity = 0
                    product.save()
                    
                    # Create stock entry for inventory tracking
                    from inventory.models import StockEntry
                    StockEntry.objects.create(
                        product=product,
                        quantity=-1,
                        entry_type='sale',
                        unit_price=ceiling_price,
                        total_amount=ceiling_price,
                        reference_id=credit_transaction.transaction_id,
                        notes=f'Credit sale - {customer.full_name} via {company.name} (Commission: KSH {commission_amount})',
                        created_by=request.user
                    )
                
                # Create log
                CreditTransactionLog.objects.create(
                    transaction=credit_transaction,
                    action='created',
                    performed_by=request.user,
                    notes=f'Product {product.product_code} - Commission: KSH {commission_amount}'
                )
                
                # Update seller commission summary
                summary, _ = SellerCommissionSummary.objects.get_or_create(seller=request.user)
                summary.update_from_transactions()
                
                logger.info(
                    f"[CREDIT TRANSACTION] Created: {credit_transaction.transaction_id} | "
                    f"Product: {product.product_code} | "
                    f"Commission: KSH {commission_amount}"
                )
                
                messages.success(
                    request, 
                    f'Credit transaction #{credit_transaction.transaction_id} created successfully. '
                    f'Commission of KSH {commission_amount} will be paid when company pays.'
                )
                return redirect('credit:transaction_receipt', pk=credit_transaction.pk)
                
        except Exception as e:
            logger.error(f"Error creating credit transaction: {str(e)}")
            messages.error(request, f'Error creating transaction: {str(e)}')
            return redirect('credit:transaction_create')
    
    # GET request - show form
    companies = CreditCompany.objects.filter(is_active=True)
    customers = CreditCustomer.objects.filter(is_active=True)
    
    # Get IDs of products that already have ANY credit transaction
    products_with_credit = CreditTransaction.objects.values_list('product_id', flat=True).distinct()
    
    # Filter products:
    products = Product.objects.filter(
        category__item_type='single',
        status='available',
        quantity__gt=0
    ).exclude(
        id__in=products_with_credit
    ).select_related('category').order_by('-created_at')
    
    # Log for debugging
    logger.info(f"Credit product selection - Single items available: {products.count()}")
    
    # If no products available, show warning
    if products.count() == 0:
        messages.warning(
            request, 
            'No single items available for credit. All available items either:\n'
            '- Have existing credit transactions\n'
            '- Are out of stock\n'
            '- Have status other than "available"'
        )
    
    context = {
        'companies': companies,
        'customers': customers,
        'products': products,
        'commission_types': CreditTransaction._meta.get_field('commission_type').choices,
    }
    return render(request, 'credit/transactions/create.html', context)


@login_required
def transaction_receipt(request, pk):
    """View transaction receipt"""
    transaction = get_object_or_404(
        CreditTransaction.objects.select_related('customer', 'credit_company', 'product', 'dealer'),
        pk=pk
    )
    
    context = {
        'transaction': transaction,
    }
    return render(request, 'credit/transactions/receipt.html', context)


@login_required
def transaction_detail(request, pk):
    """View transaction details - UPDATED WITH COMMISSION"""
    transaction = get_object_or_404(
        CreditTransaction.objects.select_related('customer', 'credit_company', 'product', 'dealer'),
        pk=pk
    )
    logs = transaction.logs.all().order_by('-created_at')
    
    # Get commission record
    try:
        commission_record = transaction.seller_commission_record
    except SellerCommission.DoesNotExist:
        commission_record = None
    
    context = {
        'transaction': transaction,
        'logs': logs,
        'commission_record': commission_record,
    }
    return render(request, 'credit/transactions/detail.html', context)


@login_required
def transaction_pay(request, pk):
    """Mark a transaction as paid - UPDATED WITH COMMISSION"""
    transaction = get_object_or_404(CreditTransaction, pk=pk)
    
    if request.method == 'POST':
        try:
            payment_ref = request.POST.get('payment_reference', '')
            transaction.mark_as_paid(payment_ref=payment_ref, paid_by=request.user)
            
            messages.success(
                request, 
                f'Transaction #{transaction.transaction_id} marked as paid. '
                f'Commission of KSH {transaction.commission_amount} is now pending for seller.'
            )
        except Exception as e:
            messages.error(request, f'Error marking transaction as paid: {str(e)}')
        
        return redirect('credit:transaction_detail', pk=pk)
    
    return render(request, 'credit/transactions/pay.html', {'transaction': transaction})


@login_required
def transaction_cancel(request, pk):
    """Cancel a transaction - UPDATED WITH COMMISSION"""
    transaction = get_object_or_404(CreditTransaction, pk=pk)
    
    if request.method == 'POST':
        try:
            reason = request.POST.get('reason', '')
            transaction.cancel(reason=reason, cancelled_by=request.user)
            messages.success(request, f'Transaction #{transaction.transaction_id} cancelled.')
        except Exception as e:
            messages.error(request, f'Error cancelling transaction: {str(e)}')
        
        return redirect('credit:transaction_detail', pk=pk)
    
    return render(request, 'credit/transactions/cancel.html', {'transaction': transaction})


@login_required
def transaction_reverse(request, pk):
    """Reverse a credit transaction - UPDATED WITH COMMISSION"""
    transaction = get_object_or_404(CreditTransaction, pk=pk)
    
    if request.method == 'POST':
        try:
            reason = request.POST.get('reason', '')
            
            # Check if transaction can be reversed
            if transaction.payment_status == 'reversed':
                messages.error(request, 'Transaction is already reversed.')
                return redirect('credit:transaction_detail', pk=pk)
            
            if transaction.payment_status == 'paid':
                messages.error(request, 'Paid transactions cannot be reversed. Please contact admin.')
                return redirect('credit:transaction_detail', pk=pk)
            
            # Reverse the transaction (commission will be cancelled automatically)
            transaction.reverse_transaction(
                reversed_by=request.user,
                reason=reason
            )
            
            messages.success(
                request, 
                f'Transaction #{transaction.transaction_id} reversed successfully. '
                f'Commission has been cancelled.'
            )
            return redirect('credit:transaction_detail', pk=pk)
            
        except Exception as e:
            messages.error(request, f'Error reversing transaction: {str(e)}')
            return redirect('credit:transaction_detail', pk=pk)
    
    return render(request, 'credit/transactions/reverse.html', {'transaction': transaction})


# ====================================
# PAYMENT VIEWS
# ====================================

@login_required
def payment_list(request):
    """List all company payments"""
    payments = CompanyPayment.objects.select_related('credit_company').order_by('-payment_date')
    
    context = {'payments': payments}
    return render(request, 'credit/payments/list.html', context)


@login_required
def payment_add(request):
    """Add a new company payment - UPDATED WITH COMMISSION"""
    if request.method == 'POST':
        try:
            with transaction.atomic():
                company_id = request.POST.get('company')
                amount = Decimal(request.POST.get('amount', '0'))
                payment_method = request.POST.get('payment_method')
                payment_reference = request.POST.get('payment_reference')
                payment_date = request.POST.get('payment_date')
                transaction_ids = request.POST.getlist('transactions')
                
                # Create payment
                payment = CompanyPayment.objects.create(
                    credit_company_id=company_id,
                    amount=amount,
                    payment_method=payment_method,
                    payment_reference=payment_reference,
                    payment_date=payment_date,
                    created_by=request.user
                )
                
                # Add transactions
                if transaction_ids:
                    transactions = CreditTransaction.objects.filter(
                        id__in=transaction_ids,
                        payment_status='pending'
                    )
                    payment.transactions.set(transactions)
                
                # Process payment (this will mark transactions as paid and create commission records)
                payment.process_payment()
                
                # Calculate total commission generated from these transactions
                total_commission = transactions.aggregate(
                    total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
                )['total']
                
                messages.success(
                    request, 
                    f'Payment #{payment.payment_id} recorded and processed. '
                    f'Total commission generated: KSH {total_commission}'
                )
                return redirect('credit:payment_detail', pk=payment.pk)
                
        except Exception as e:
            messages.error(request, f'Error recording payment: {str(e)}')
    
    # GET request
    companies = CreditCompany.objects.filter(is_active=True)
    pending_transactions = CreditTransaction.objects.filter(
        payment_status='pending'
    ).select_related('customer', 'product')
    
    context = {
        'companies': companies,
        'pending_transactions': pending_transactions,
    }
    return render(request, 'credit/payments/add.html', context)


@login_required
def payment_detail(request, pk):
    """View payment details - UPDATED WITH COMMISSION"""
    payment = get_object_or_404(
        CompanyPayment.objects.select_related('credit_company', 'created_by'),
        pk=pk
    )
    transactions = payment.transactions.all()
    
    # Calculate total commission from this payment
    total_commission = transactions.aggregate(
        total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    context = {
        'payment': payment,
        'transactions': transactions,
        'total_commission': total_commission,
    }
    return render(request, 'credit/payments/detail.html', context)


# ====================================
# SALES INTEGRATION API - UPDATED WITH COMMISSION
# ====================================

@login_required
def convert_sale_to_credit(request, sale_id):
    """
    API endpoint called from Sales app when a credit sale is created
    """
    try:
        from sales.models import Sale
        
        sale = Sale.objects.get(sale_id=sale_id)
        
        if not sale.is_credit:
            return JsonResponse({
                'success': False,
                'error': 'This is not a credit sale'
            })
        
        # Default commission values (can be customized later)
        commission_type = 'percentage'
        commission_value = Decimal('5')  # Default 5%
        commission_amount = (sale.total_amount * commission_value) / Decimal('100.00')
        
        # Create credit transaction
        credit_transaction = CreditTransaction.objects.create(
            credit_company=None,  # To be assigned later
            customer=CreditCustomer.objects.get_or_create(
                phone_number=sale.buyer_phone or '0000000000',
                defaults={
                    'full_name': sale.buyer_name or 'Unknown Customer',
                    'id_number': sale.buyer_id_number or '00000000',
                }
            )[0],
            dealer=sale.seller,
            product=sale.items.first().product,
            ceiling_price=sale.total_amount,
            notes=f"From sale #{sale.sale_id}",
            # Commission fields
            commission_type=commission_type,
            commission_value=commission_value,
            commission_amount=round(commission_amount, 2),
        )
        
        # Create commission record
        SellerCommission.objects.create(
            seller=sale.seller,
            transaction=credit_transaction,
            amount=round(commission_amount, 2)
        )
        
        # Link back to sale
        sale.credit_sale = credit_transaction
        sale.save()
        
        return JsonResponse({
            'success': True,
            'credit_transaction_id': credit_transaction.transaction_id,
            'commission_amount': float(commission_amount)
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })
    




# ====================================
# COMMISSION VIEWS - 5 BUTTONS
# ====================================
@login_required
def commission_dashboard(request):
    """Commission Dashboard - Using actual model statuses"""
    
    # Get all transactions with commission info
    transactions = CreditTransaction.objects.select_related(
        'dealer', 'product'
    ).order_by('-transaction_date')
    
    # Apply filters
    seller_id = request.GET.get('seller')
    status = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    if seller_id:
        transactions = transactions.filter(dealer_id=seller_id)
    
    if status:
        transactions = transactions.filter(commission_status=status)
    
    if date_from:
        date_from_aware = timezone.make_aware(datetime.strptime(date_from, '%Y-%m-%d'))
        transactions = transactions.filter(transaction_date__date__gte=date_from_aware)
    
    if date_to:
        date_to_aware = timezone.make_aware(datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
        transactions = transactions.filter(transaction_date__lt=date_to_aware)
    
    # Get unique sellers
    sellers = User.objects.filter(credit_transactions__isnull=False).distinct()
    total_sellers = sellers.count()
    
    # Calculate totals for each transaction
    transaction_list = []
    total_selling = 0
    total_buying = 0
    total_profit_sum = 0
    total_commission_sum = 0
    total_owner_balance = 0
    
    for trans in transactions:
        selling_price = trans.ceiling_price
        buying_price = getattr(trans.product, 'buying_price', 0) or 0
        total_profit = selling_price - buying_price
        seller_commission = trans.commission_amount or 0
        owner_commission = total_profit - seller_commission
        
        # Add to transaction list with calculated fields
        transaction_list.append({
            'id': trans.id,
            'transaction_id': trans.transaction_id,
            'transaction_date': trans.transaction_date,
            'dealer': trans.dealer,
            'product': trans.product,
            'imei': trans.imei,
            'selling_price': selling_price,
            'buying_price': buying_price,
            'total_profit': total_profit,
            'seller_commission': seller_commission,
            'owner_commission': owner_commission,
            'commission_status': trans.commission_status,
            'commission_status_display': trans.get_commission_status_display(),
        })
        
        # Update totals
        total_selling += selling_price
        total_buying += buying_price
        total_profit_sum += total_profit
        total_commission_sum += seller_commission
        total_owner_balance += owner_commission
    
    # Status counts and totals
    status_counts = {
        'not_set': transactions.filter(commission_status='not_set').count(),
        'requested': transactions.filter(commission_status='requested').count(),
        'approved': transactions.filter(commission_status='approved').count(),
        'paid': transactions.filter(commission_status='paid').count(),
        'cancelled': transactions.filter(commission_status='cancelled').count(),
    }
    
    status_totals = {
        'pending': transactions.filter(commission_status__in=['requested', 'approved']).aggregate(
            total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
        )['total'],
        'requested': transactions.filter(commission_status='requested').aggregate(
            total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
        )['total'],
        'approved': transactions.filter(commission_status='approved').aggregate(
            total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
        )['total'],
        'paid': transactions.filter(commission_status='paid').aggregate(
            total=Coalesce(Sum('commission_amount'), Value(0, output_field=DecimalField()))
        )['total'],
    }
    
    context = {
        'transactions': transaction_list,  # Use the processed list
        'sellers': sellers,
        'total_sellers': total_sellers,
        
        # Totals for footer
        'total_selling': total_selling,
        'total_buying': total_buying,
        'total_profit_sum': total_profit_sum,
        'total_commission_sum': total_commission_sum,
        'total_owner_balance': total_owner_balance,
        
        # Counts
        'pending_count': status_counts['requested'] + status_counts['approved'],
        'requested_count': status_counts['requested'],
        'approved_count': status_counts['approved'],
        'paid_count': status_counts['paid'],
        'cancelled_count': status_counts['cancelled'],
        'not_set_count': status_counts['not_set'],
        
        # Totals
        'pending_total': status_totals['pending'],
        'requested_total': status_totals['requested'],
        'approved_total': status_totals['approved'],
        'paid_total': status_totals['paid'],
    }
    
    return render(request, 'credit/commission/dashboard.html', context)







@login_required
def request_commission_list(request):
    """
    Request Commissions page - Show transactions where seller commission is not yet set.
    This completely ignores company payment status.
    """
    
    # Only show transactions where commission status is 'not_set'
    # No filtering on payment_status at all
    transactions_needing_commission = CreditTransaction.objects.filter(
        commission_status='not_set'  # Only where commission hasn't been set
    ).select_related(
        'dealer', 'product', 'customer'
    ).order_by('-transaction_date')[:20]
    
    context = {
        'transactions_needing_commission': transactions_needing_commission,
        'total_pending': transactions_needing_commission.count(),
    }
    
    return render(request, 'credit/commission/request.html', context)




@login_required
def commission_detail(request, pk):
    """Display detailed commission information including requester/approver/payer"""
    transaction = get_object_or_404(
        CreditTransaction.objects.select_related(
            'dealer', 'customer', 'product', 'credit_company',
            'commission_paid_by'
        ),
        pk=pk
    )
    
    # Get commission record
    try:
        commission_record = transaction.seller_commission_record
    except SellerCommission.DoesNotExist:
        commission_record = None
    
    context = {
        'transaction': transaction,
        'commission_record': commission_record,
    }
    
    return render(request, 'credit/commission/detail.html', context)





@login_required
def search_transaction(request):
    """Search for transaction by SKU or Transaction ID"""
    query = request.GET.get('q', '').strip()
    
    if not query or len(query) < 3:
        return JsonResponse({'success': False, 'error': 'Search query too short'})
    
    try:
        # Search by transaction ID or product SKU
        transaction = CreditTransaction.objects.select_related(
            'dealer', 'customer', 'product'
        ).filter(
            Q(transaction_id__icontains=query) |
            Q(product__product_code__icontains=query) |
            Q(imei__icontains=query)
        ).first()
        
        if not transaction:
            return JsonResponse({'success': False, 'error': 'No transaction found'})
        
        # Calculate profit (you can adjust this based on your business logic)
        # For now, using ceiling_price as profit or you can calculate actual profit
        profit = transaction.ceiling_price  # Replace with actual profit calculation if available
        
        data = {
            'success': True,
            'transaction': {
                'id': transaction.id,
                'transaction_id': transaction.transaction_id,
                'date': transaction.transaction_date.strftime('%d %b %Y'),
                'seller': transaction.dealer.get_full_name() or transaction.dealer.username,
                'customer': transaction.customer.full_name,
                'product': transaction.product.name,
                'sku': transaction.product.product_code,
                'price': float(transaction.ceiling_price),
                'profit': float(profit),
                'payment_status': transaction.payment_status,
                'commission_status': transaction.commission_status,
                'commission_status_display': transaction.get_commission_status_display(),
            }
        }
        
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})




@login_required
def search_seller_commission_status(request):
    """
    Search for a transaction and return the SELLER'S COMMISSION status only.
    This completely ignores the company payment status.
    """
    query = request.GET.get('q', '').strip()
    
    if not query or len(query) < 3:
        return JsonResponse({'success': False, 'error': 'Please enter at least 3 characters'})
    
    try:
        transaction = CreditTransaction.objects.select_related(
            'dealer', 'customer', 'product'
        ).filter(
            Q(transaction_id__icontains=query) |
            Q(product__product_code__icontains=query)
        ).first()
        
        if not transaction:
            return JsonResponse({'success': False, 'error': 'Transaction not found'})
        
        # Return ONLY commission-related information - NO payment status
        data = {
            'success': True,
            'transaction': {
                'id': transaction.id,
                'transaction_id': transaction.transaction_id,
                'date': transaction.transaction_date.strftime('%d %b %Y'),
                'seller': {
                    'id': transaction.dealer.id,
                    'name': transaction.dealer.get_full_name() or transaction.dealer.username,
                },
                'customer': {
                    'name': transaction.customer.full_name,
                },
                'product': {
                    'name': transaction.product.name,
                    'sku': transaction.product.product_code,
                },
                'sale': {
                    'price': float(transaction.ceiling_price),
                },
                'commission': {
                    'status': transaction.commission_status,
                    'status_display': transaction.get_commission_status_display(),
                    'amount': float(transaction.commission_amount) if transaction.commission_amount else 0,
                    # ONLY 'not_set' can be requested - no more 'pending'
                    'can_request': transaction.commission_status == 'not_set',
                    'paid_date': transaction.commission_paid_date.strftime('%d %b %Y') if transaction.commission_paid_date else None,
                }
            }
        }
        
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



@login_required
def request_commission_submit(request, pk):
    """Submit commission request for a transaction - ONLY checks commission status"""
    if request.method == 'POST':
        try:
            transaction = get_object_or_404(CreditTransaction, pk=pk)
            
            # ONLY allow 'not_set' - no more 'pending'
            if transaction.commission_status != 'not_set':
                return JsonResponse({
                    'success': False, 
                    'error': f'Commission already {transaction.get_commission_status_display()}'
                })
            
            commission_amount = Decimal(request.POST.get('commission_amount', '0'))
            notes = request.POST.get('notes', '')
            
            # Validate amount
            if commission_amount <= 0:
                return JsonResponse({'success': False, 'error': 'Amount must be greater than 0'})
            
            if commission_amount > transaction.ceiling_price:
                return JsonResponse({'success': False, 'error': 'Amount cannot exceed total price'})
            
            # Update transaction
            transaction.commission_amount = commission_amount
            transaction.commission_status = 'requested'  # Changes from not_set to requested
            transaction.commission_notes = notes
            transaction.save()
            
            # Create or update commission record
            SellerCommission.objects.update_or_create(
                transaction=transaction,
                defaults={
                    'seller': transaction.dealer,
                    'amount': commission_amount,
                    'status': 'pending',  # SellerCommission uses 'pending' for requested
                    'notes': notes
                }
            )
            
            # Create log
            CreditTransactionLog.objects.create(
                transaction=transaction,
                action='commission_requested',
                performed_by=request.user,
                notes=f"Commission requested: KES {commission_amount}"
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Commission of KES {commission_amount} set for {transaction.transaction_id}',
                'transaction_id': transaction.transaction_id,
                'amount': float(commission_amount)
            })
            
        except CreditTransaction.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Transaction not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})




@login_required
def approve_commission_list(request):
    """3. Approve Commissions - Show requested commissions pending approval"""
    
    # Get requested commissions
    requested_transactions = CreditTransaction.objects.filter(
        commission_status='requested'
    ).select_related(
        'dealer', 'customer', 'credit_company', 'product'
    ).order_by('-commission_paid_date')
    
    # Filter by seller if provided
    seller_id = request.GET.get('seller')
    if seller_id:
        requested_transactions = requested_transactions.filter(dealer_id=seller_id)
    
    # Get sellers for filter dropdown
    sellers = User.objects.filter(
        credit_transactions__commission_status='requested'
    ).distinct().order_by('first_name', 'last_name')
    
    context = {
        'transactions': requested_transactions,
        'sellers': sellers,
        'count': requested_transactions.count(),
    }
    
    return render(request, 'credit/commission/approve.html', context)


@login_required
def approve_commission_submit(request, pk):
    """Approve a commission request"""
    if request.method == 'POST':
        transaction = get_object_or_404(CreditTransaction, pk=pk, commission_status='requested')
        
        try:
            notes = request.POST.get('notes', '')
            
            # Update transaction
            transaction.commission_status = 'approved'
            transaction.commission_notes = f"Approved: {notes}" if notes else "Approved"
            transaction.save()
            
            # Update commission record
            SellerCommission.objects.filter(transaction=transaction).update(
                status='approved',
                notes=f"Approved: {notes}" if notes else "Approved"
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Commission approved for {transaction.transaction_id}'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


@login_required
def pay_commission_list(request):
    """4. Pay Commissions - Show approved commissions ready for payment"""
    
    # Get approved commissions
    approved_transactions = CreditTransaction.objects.filter(
        commission_status='approved'
    ).select_related(
        'dealer', 'customer', 'credit_company', 'product'
    ).order_by('-commission_paid_date')
    
    # Filter by seller if provided
    seller_id = request.GET.get('seller')
    if seller_id:
        approved_transactions = approved_transactions.filter(dealer_id=seller_id)
    
    # Get sellers for filter dropdown
    sellers = User.objects.filter(
        credit_transactions__commission_status='approved'
    ).distinct().order_by('first_name', 'last_name')
    
    context = {
        'transactions': approved_transactions,
        'sellers': sellers,
        'count': approved_transactions.count(),
    }
    
    return render(request, 'credit/commission/pay.html', context)


@login_required
def pay_commission_submit(request, pk):
    """Pay a commission"""
    if request.method == 'POST':
        transaction = get_object_or_404(CreditTransaction, pk=pk, commission_status='approved')
        
        try:
            notes = request.POST.get('notes', '')
            
            # Update transaction
            transaction.commission_status = 'paid'
            transaction.commission_paid_date = timezone.now()
            transaction.commission_paid_by = request.user
            transaction.commission_notes = f"Paid: {notes}" if notes else "Paid"
            transaction.save()
            
            # Update commission record
            SellerCommission.objects.filter(transaction=transaction).update(
                status='paid',
                paid_date=timezone.now(),
                paid_by=request.user,
                notes=f"Paid: {notes}" if notes else "Paid"
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Commission paid for {transaction.transaction_id}'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})





@login_required
def bulk_pay_commission(request):
    """Bulk pay multiple commissions at once"""
    if request.method == 'POST':
        try:
            transaction_ids = request.POST.getlist('transaction_ids')
            notes = request.POST.get('notes', '')
            
            if not transaction_ids:
                return JsonResponse({'success': False, 'error': 'No transactions selected'})
            
            transactions = CreditTransaction.objects.filter(
                id__in=transaction_ids,
                commission_status='approved'
            )
            
            count = 0
            total_amount = 0
            
            for transaction in transactions:
                transaction.commission_status = 'paid'
                transaction.commission_paid_date = timezone.now()
                transaction.commission_paid_by = request.user
                transaction.commission_notes = f"Bulk paid: {notes}" if notes else "Bulk paid"
                transaction.save()
                
                SellerCommission.objects.filter(transaction=transaction).update(
                    status='paid',
                    paid_date=timezone.now(),
                    paid_by=request.user,
                    notes=f"Bulk paid: {notes}" if notes else "Bulk paid"
                )
                
                count += 1
                total_amount += transaction.commission_amount
            
            return JsonResponse({
                'success': True,
                'message': f'Paid {count} commissions totaling KES {total_amount}',
                'count': count,
                'total_amount': float(total_amount)
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})




@login_required
def commission_report(request):
    """Commission Report page"""
    
    # Get all commission records
    commissions = SellerCommission.objects.select_related(
        'seller', 'transaction', 'paid_by',
        'transaction__customer', 'transaction__product',
        'transaction__credit_company', 'transaction__dealer'
    ).order_by('-created_at')
    
    # Apply filters
    seller_id = request.GET.get('seller')
    status = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    if seller_id:
        commissions = commissions.filter(seller_id=seller_id)
    
    if status:
        commissions = commissions.filter(status=status)
    
    if date_from:
        date_from_aware = timezone.make_aware(datetime.strptime(date_from, '%Y-%m-%d'))
        commissions = commissions.filter(created_at__date__gte=date_from_aware)
    
    if date_to:
        date_to_aware = timezone.make_aware(datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
        commissions = commissions.filter(created_at__lt=date_to_aware)
    
    # Calculate totals
    total_commission = commissions.aggregate(
        total=Coalesce(Sum('amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    paid_total = commissions.filter(status='paid').aggregate(
        total=Coalesce(Sum('amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    pending_total = commissions.filter(status='pending').aggregate(
        total=Coalesce(Sum('amount'), Value(0, output_field=DecimalField()))
    )['total']
    
    total_sale_amount = commissions.aggregate(
        total=Coalesce(Sum('transaction__ceiling_price'), Value(0, output_field=DecimalField()))
    )['total']
    
    # Get filter options
    sellers = User.objects.filter(commissions_earned__isnull=False).distinct()
    
    context = {
        'commissions': commissions,
        'total_commission': total_commission,
        'paid_total': paid_total,
        'pending_total': pending_total,
        'pending_count': commissions.filter(status='pending').count(),
        'total_transactions': commissions.count(),
        'total_sale_amount': total_sale_amount,
        'sellers': sellers,
        'status_choices': SellerCommission._meta.get_field('status').choices,
        'filters': {
            'seller_id': int(seller_id) if seller_id else None,
            'status': status,
            'date_from': date_from,
            'date_to': date_to,
        }
    }
    
    return render(request, 'credit/commission/report.html', context)





@login_required
def export_commission_report(request):
    """Export commission report as CSV"""
    # Check permission
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    
    import csv
    from django.http import HttpResponse
    
    # Create HttpResponse with CSV header
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="commission_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    # Get filter parameters from request
    seller_id = request.GET.get('seller')
    status = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    # Base queryset
    commissions = SellerCommission.objects.select_related(
        'seller', 'transaction', 'paid_by', 
        'transaction__credit_company', 'transaction__customer',
        'transaction__product', 'transaction__dealer'
    )
    
    # Apply filters
    if seller_id:
        commissions = commissions.filter(seller_id=seller_id)
    
    if status:
        commissions = commissions.filter(status=status)
    
    if date_from:
        date_from_aware = timezone.make_aware(datetime.strptime(date_from, '%Y-%m-%d'))
        commissions = commissions.filter(created_at__date__gte=date_from_aware)
    
    if date_to:
        date_to_aware = timezone.make_aware(datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
        commissions = commissions.filter(created_at__lt=date_to_aware)
    
    commissions = commissions.order_by('-created_at')
    
    # Create CSV writer
    writer = csv.writer(response)
    
    # Write headers
    writer.writerow([
        'Date', 
        'Transaction ID', 
        'Seller Name', 
        'Seller Username',
        'Customer Name', 
        'Customer Phone',
        'Product Name',
        'Product SKU',
        'Sale Amount',
        'Commission Amount',
        'Status',
        'Requested By',
        'Approved By',
        'Paid By',
        'Paid Date',
        'Payment Reference',
        'Notes'
    ])
    
    # Write data rows
    for commission in commissions:
        writer.writerow([
            commission.created_at.strftime('%Y-%m-%d %H:%M'),
            commission.transaction.transaction_id,
            commission.seller.get_full_name() or commission.seller.username,
            commission.seller.username,
            commission.transaction.customer.full_name,
            commission.transaction.customer.phone_number,
            commission.transaction.product.name,
            commission.transaction.product.product_code,
            f'{commission.transaction.ceiling_price:.2f}',
            f'{commission.amount:.2f}',
            commission.get_status_display(),
            commission.transaction.commission_paid_by.get_full_name() if commission.transaction.commission_paid_by else '',
            commission.paid_by.get_full_name() if commission.paid_by and commission.status == 'paid' else '',
            commission.paid_by.get_full_name() if commission.paid_by and commission.status == 'paid' else '',
            commission.paid_date.strftime('%Y-%m-%d %H:%M') if commission.paid_date else '',
            commission.transaction.payment_reference or '',
            commission.notes or commission.transaction.commission_notes or ''
        ])
    
    return response