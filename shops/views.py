# shops/views.py - Complete refactored version

import logging

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.db import models
from decimal import Decimal
from django.db.models import Sum, Count, Q, Avg, F, DecimalField
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek
from datetime import datetime, timedelta

from .models import (
    ShopBranch, MpesaAccount, MpesaDailyBalance, BankAccount, BankDailyBalance,
    CashAccount, CashDailyBalance, ShopExpense, DailyShopReport, AccountTransaction,
    DailyMpesaAccountReport, ShopConfiguration, BankClosingBalance, DynamicChoice
)
from .forms import (
    ShopBranchForm, BankAccountForm, DailyShopReportForm, CashAccountForm,
    MpesaAccountForm, MpesaDailyBalanceForm, BankDailyBalanceForm, 
    CashDailyBalanceForm, ShopExpenseForm, DynamicChoiceForm, ShopConfigurationForm,
    MpesaAdjustment, MpesaAdjustmentForm, AccountInjectionForm
)
import logging
import json





logger = logging.getLogger(__name__)
User = get_user_model()




# ==================== PERMISSION HELPERS ====================

def is_staff_or_admin(user):
    """Check if user is staff, admin, or M-Pesa Agent"""
    if user.is_superuser:
        return True
    if user.is_staff:
        return True
    if user.groups.filter(name='M-Pesa Agent').exists():
        return True
    if hasattr(user, 'staff_profile') and user.staff_profile.assigned_shop:
        return True
    return False


def is_superuser(user):
    return user.is_superuser


def filter_by_user_queryset(request, queryset, user_field='submitted_by'):
    if request.user.is_superuser:
        return queryset
    return queryset.filter(**{user_field: request.user})


def get_user_assigned_shop(request):
    """Get the shop assigned to the current user"""
    if request.user.is_superuser:
        return None
    if hasattr(request.user, 'staff_profile') and request.user.staff_profile:
        return request.user.staff_profile.assigned_shop
    return None


@login_required
def get_shop_users(request, shop_id):
    """AJAX endpoint to get users assigned to a specific shop"""
    try:
        shop = get_object_or_404(ShopBranch, id=shop_id)
        
        # Get users assigned to this shop via staff_profile
        users = User.objects.filter(
            is_active=True,
            staff_profile__assigned_shop=shop
        ).distinct()
        
        users_data = [{
            'id': user.id,
            'name': user.get_full_name() or user.username,
            'username': user.username,
        } for user in users]
        
        return JsonResponse({'success': True, 'users': users_data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_shop_accounts(request, shop_id):
    """AJAX endpoint to get M-Pesa and Bank accounts for a shop"""
    try:
        shop = get_object_or_404(ShopBranch, id=shop_id)
        
        # Get M-Pesa accounts
        mpesa_accounts = MpesaAccount.objects.filter(
            shop=shop, is_active=True, status='active'
        ).values('id', 'account_name', 'account_number', 'account_type')
        
        # Get Bank accounts
        bank_accounts = BankAccount.objects.filter(
            shop=shop, is_active=True
        ).values('id', 'bank_name', 'account_name', 'account_number')
        
        return JsonResponse({
            'success': True,
            'mpesa_accounts': list(mpesa_accounts),
            'bank_accounts': list(bank_accounts),
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
    



# ==================== DASHBOARD & STATISTICS ====================

@login_required
@user_passes_test(is_staff_or_admin)
def shop_dashboard(request):
    """Main shop dashboard"""
    shops = ShopBranch.objects.filter(is_active=True)
    today = timezone.now().date()
    month_ago = today - timedelta(days=30)
    
    assigned_shop = get_user_assigned_shop(request)
    
    if request.user.is_superuser:
        today_reports = DailyShopReport.objects.filter(report_date=today)
        recent_reports = DailyShopReport.objects.all().order_by('-submission_time')[:10]
        total_transactions_today = today_reports.aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
        reports_today = today_reports.count()
    else:
        today_reports = DailyShopReport.objects.filter(
            report_date=today,
            submitted_by=request.user
        )
        recent_reports = DailyShopReport.objects.filter(
            submitted_by=request.user
        ).order_by('-submission_time')[:10]
        total_transactions_today = today_reports.aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
        reports_today = today_reports.count()
    
    # Get M-Pesa accounts summary
    mpesa_accounts = MpesaAccount.objects.filter(is_active=True)
    if assigned_shop:
        mpesa_accounts = mpesa_accounts.filter(shop=assigned_shop)
    
    total_mpesa_balance = mpesa_accounts.aggregate(total=Sum('current_balance'))['total'] or 0
    
    # Get bank accounts summary
    bank_accounts = BankAccount.objects.filter(is_active=True)
    if assigned_shop:
        bank_accounts = bank_accounts.filter(shop=assigned_shop)
    total_bank_balance = bank_accounts.aggregate(total=Sum('current_balance'))['total'] or 0
    
    # Get cash accounts summary
    cash_accounts = CashAccount.objects.filter(is_active=True)
    if assigned_shop:
        cash_accounts = cash_accounts.filter(shop=assigned_shop)
    total_cash_balance = cash_accounts.aggregate(total=Sum('current_balance'))['total'] or 0
    
    # ============================================
    # Calculate Unverified Reports for Warning Card
    # ============================================
    unverified_reports = []
    verified_count = 0
    unverified_count = 0
    
    for report in recent_reports:
        # Get previous report for this shop
        previous_report = DailyShopReport.objects.filter(
            shop=report.shop,
            report_date__lt=report.report_date
        ).order_by('-report_date').first()
        
        # Calculate verification status
        if previous_report:
            # Expected closing = Previous closing - Today's expenses
            expected_closing = previous_report.total_closing_balance - report.total_expenses
            difference = report.total_closing_balance - expected_closing
            
            # Use small tolerance for floating point comparison
            if abs(difference) < 0.01:
                report.verification_status = 'verified'
                report.verification_icon = 'fas fa-check-circle'
                report.verification_text = 'Verified'
                report.verification_color = 'success'
                verified_count += 1
            elif difference > 0:
                report.verification_status = 'surplus'
                report.verification_icon = 'fas fa-exclamation-triangle'
                report.verification_text = f'Surplus (+{difference:,.2f})'
                report.verification_color = 'warning'
                unverified_reports.append(report)
                unverified_count += 1
            else:
                report.verification_status = 'deficit'
                report.verification_icon = 'fas fa-times-circle'
                report.verification_text = f'Deficit ({difference:,.2f})'
                report.verification_color = 'danger'
                unverified_reports.append(report)
                unverified_count += 1
        else:
            # First report for this shop
            report.verification_status = 'first'
            report.verification_icon = 'fas fa-info-circle'
            report.verification_text = 'First Report'
            report.verification_color = 'info'
    
    # Get unverified reports for the warning card (only show if there are any)
    recent_unverified = [r for r in unverified_reports if r.verification_status in ['surplus', 'deficit']][:5]
    
    context = {
        'shops': shops,
        'today_reports': today_reports,
        'recent_reports': recent_reports,
        'today': today,
        'total_shops': shops.count(),
        'reports_today': reports_today,
        'total_transactions_today': int(total_transactions_today),
        'assigned_shop': assigned_shop,
        'total_mpesa_balance': total_mpesa_balance,
        'total_bank_balance': total_bank_balance,
        'total_cash_balance': total_cash_balance,
        # Unverified reports for warning card
        'unverified_reports_count': unverified_count,
        'unverified_reports': recent_unverified,
        'verified_count': verified_count,
    }
    return render(request, 'shops/dashboard.html', context)




@login_required
@user_passes_test(lambda u: u.is_superuser or u.groups.filter(name__in=['admin', 'manager', 'accountant']).exists())
def shop_statistics(request):
    """Comprehensive Shop Statistics Dashboard"""
    
    from django.db.models import Sum, Count, Q, Avg
    from decimal import Decimal
    from datetime import timedelta
    
    # ============================================
    # FILTER PARAMETERS
    # ============================================
    shop_id = request.GET.get('shop', 'all')
    date_range = request.GET.get('date_range', 'month')
    
    # Date range logic
    today = timezone.now().date()
    if date_range == 'today':
        start_date = today
        end_date = today
    elif date_range == 'week':
        start_date = today - timedelta(days=7)
        end_date = today
    elif date_range == 'month':
        start_date = today - timedelta(days=30)
        end_date = today
    elif date_range == 'quarter':
        start_date = today - timedelta(days=90)
        end_date = today
    elif date_range == 'year':
        start_date = today - timedelta(days=365)
        end_date = today
    else:
        start_date = today - timedelta(days=30)
        end_date = today
    
    # Base queryset for daily reports
    reports = DailyShopReport.objects.filter(
        report_date__gte=start_date,
        report_date__lte=end_date
    )
    
    if shop_id != 'all':
        reports = reports.filter(shop_id=shop_id)
    
    # ============================================
    # LATEST REPORT (Most Recent)
    # ============================================
    if shop_id != 'all':
        latest_report = DailyShopReport.objects.filter(
            shop_id=shop_id
        ).order_by('-report_date').first()
    else:
        latest_report = DailyShopReport.objects.all().order_by('-report_date').first()
    
    if latest_report:
        # Get latest M-Pesa balances from the latest report
        latest_mpesa_reports = DailyMpesaAccountReport.objects.filter(
            daily_report=latest_report
        )
        
        latest_mpesa_float = latest_mpesa_reports.aggregate(
            total=Sum('closing_mpesa_float')
        )['total'] or 0
        
        latest_mpesa_cash = latest_mpesa_reports.aggregate(
            total=Sum('closing_cash')
        )['total'] or 0
        
        # Get latest bank balances from the latest report
        latest_bank_closings = BankClosingBalance.objects.filter(
            daily_report=latest_report,
            is_active=True
        )
        latest_bank_total = latest_bank_closings.aggregate(
            total=Sum('closing_balance')
        )['total'] or 0
        
        # Get detailed bank breakdown for the latest report
        latest_bank_breakdown = latest_bank_closings.values(
            'bank_account__bank_name',
            'bank_account__account_name',
            'bank_account__account_number'
        ).annotate(
            balance=Sum('closing_balance')
        ).order_by('-balance')
        
        # Get latest cash balance
        latest_cash_balance = latest_report.cash_balance or 0
        
        # Get latest closing balance
        latest_closing_balance = latest_report.total_closing_balance or 0
        
        # Get latest expenses
        latest_expenses = latest_report.total_expenses or 0
        
        # Get latest revenue
        latest_revenue = latest_report.total_mpesa_amount or 0
        
        latest_transactions = latest_report.total_mpesa_transactions or 0
        latest_report_date = latest_report.report_date
    else:
        latest_mpesa_float = 0
        latest_mpesa_cash = 0
        latest_bank_total = 0
        latest_bank_breakdown = []
        latest_cash_balance = 0
        latest_closing_balance = 0
        latest_expenses = 0
        latest_revenue = 0
        latest_transactions = 0
        latest_report_date = None
    
    # ============================================
    # CURRENT BANK BALANCE (from BankAccount model)
    # ============================================
    bank_accounts = BankAccount.objects.filter(is_active=True)
    if shop_id != 'all':
        bank_accounts = bank_accounts.filter(shop_id=shop_id)
    current_bank_balance = bank_accounts.aggregate(total=Sum('current_balance'))['total'] or 0
    
    # ============================================
    # SHOP BRANCHES
    # ============================================
    shops = ShopBranch.objects.filter(is_active=True)
    total_shops = shops.count()
    
    # ============================================
    # PERIOD AGGREGATES
    # ============================================
    
    # Total Revenue for period
    total_revenue = reports.aggregate(
        total=Sum('total_mpesa_amount')
    )['total'] or Decimal('0.00')
    
    # Total Expenses for period
    total_expenses = reports.aggregate(
        total=Sum('total_expenses')
    )['total'] or Decimal('0.00')
    
    # Total Transactions Count for period
    total_transactions_count = reports.aggregate(
        total=Sum('total_mpesa_transactions')
    )['total'] or 0
    
    # ============================================
    # MPESA ACCOUNT METRICS
    # ============================================
    active_mpesa_accounts = MpesaAccount.objects.filter(
        is_active=True,
        status='active'
    )
    if shop_id != 'all':
        active_mpesa_accounts = active_mpesa_accounts.filter(shop_id=shop_id)
    total_mpesa_accounts = active_mpesa_accounts.count()
    
    # ============================================
    # EXPENSE METRICS (Monthly total)
    # ============================================
    first_day_of_month = today.replace(day=1)
    
    monthly_expenses = ShopExpense.objects.filter(
        daily_report__report_date__gte=first_day_of_month,
        daily_report__report_date__lte=today
    )
    
    if shop_id != 'all':
        monthly_expenses = monthly_expenses.filter(daily_report__shop_id=shop_id)
    
    total_monthly_expenses = monthly_expenses.aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0.00')
    
    expense_by_category = monthly_expenses.values('expense_category').annotate(
        total=Sum('amount')
    ).order_by('-total')[:10]
    
    total_expense_count = monthly_expenses.count()
    
    # ============================================
    # DAILY TREND (Last 30 days) - FIXED with net position
    # ============================================
    daily_trend = []
    for i in range(30):
        date = today - timedelta(days=i)
        day_reports = reports.filter(report_date=date)
        day_revenue = day_reports.aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
        day_expenses = day_reports.aggregate(total=Sum('total_expenses'))['total'] or 0
        daily_trend.append({
            'report_date': date,
            'transactions': day_revenue,  # Changed from 'revenue' to 'transactions'
            'expenses': day_expenses,
            'net': day_revenue - day_expenses,  # Added net position
        })
    daily_trend.reverse()
    
    # ============================================
    # SHOP PERFORMANCE (Latest report per shop)
    # ============================================
    shop_performance = []
    for shop in shops:
        latest_shop_report = DailyShopReport.objects.filter(
            shop=shop
        ).order_by('-report_date').first()
        
        if latest_shop_report:
            shop_revenue = latest_shop_report.total_mpesa_amount or 0
            shop_expenses = latest_shop_report.total_expenses or 0
            shop_closing = latest_shop_report.total_closing_balance or 0
            shop_transactions = latest_shop_report.total_mpesa_transactions or 0
        else:
            shop_revenue = 0
            shop_expenses = 0
            shop_closing = 0
            shop_transactions = 0
        
        shop_performance.append({
            'id': shop.id,
            'name': shop.name,
            'code': shop.code,
            'location': shop.location,
            'manager': shop.manager,
            'total_revenue': shop_revenue,
            'total_expenses': shop_expenses,
            'total_closing': shop_closing,
            'total_transactions': shop_transactions,  # Added transactions
        })
    
    shop_performance.sort(key=lambda x: x['total_revenue'], reverse=True)
    
    # ============================================
    # REPORT STATUS
    # ============================================
    total_reports = reports.count()
    finalized_reports = reports.filter(is_finalized=True).count()
    pending_reports = total_reports - finalized_reports
    finalization_rate = (finalized_reports / total_reports * 100) if total_reports > 0 else 0
    
    # ============================================
    # CONTEXT - FIXED with all required variables
    # ============================================
    context = {
        # Shop info
        'shops': shops,
        'selected_shop': shop_id,
        'total_shops': total_shops,
        'date_range': date_range,
        'start_date': start_date,
        'end_date': end_date,
        
        # Latest balances
        'latest_report_date': latest_report_date,
        'latest_mpesa_float': latest_mpesa_float,
        'latest_mpesa_cash': latest_mpesa_cash,
        'latest_bank_total': latest_bank_total,
        'latest_bank_breakdown': latest_bank_breakdown,
        'latest_cash_balance': latest_cash_balance,
        'latest_closing_balance': latest_closing_balance,
        'latest_revenue': latest_revenue,
        'latest_expenses': latest_expenses,
        'latest_transactions': latest_transactions,
        'current_bank_balance': current_bank_balance,  # Added
         # Use correct field names from DailyShopReport
        'latest_mpesa_amount': latest_report.total_mpesa_amount if latest_report else 0,
        'latest_mpesa_transactions': latest_report.total_mpesa_transactions if latest_report else 0,
        'total_mpesa_amount': total_revenue,  # total_mpesa_amount from period reports
        'total_mpesa_transactions': total_transactions_count,  # total transactions from period

        # M-Pesa account stats
        'total_mpesa_accounts': total_mpesa_accounts,
        
        # Period aggregates - FIXED variable names
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'total_transactions': total_transactions_count,  # Changed from total_transactions
        'total_transaction': total_revenue,  # Added for template compatibility
        
        # Monthly expenses
        'total_monthly_expenses': total_monthly_expenses,
        'expense_by_category': expense_by_category,
        'total_expense_count': total_expense_count,
        
        # Trends
        'daily_trend': daily_trend,


        # Shop performance
        'shop_performance': shop_performance,
        
        # Report status
        'total_reports': total_reports,
        'finalized_reports': finalized_reports,
        'pending_reports': pending_reports,
        'finalization_rate': finalization_rate,
    }
    
    return render(request, 'shops/statistics.html', context)

    

@login_required
def shop_detail_statistics(request, shop_id):
    """Detailed statistics for a specific shop"""
    from django.db.models import Sum, Count, Q, Avg
    from datetime import timedelta
    
    shop = get_object_or_404(ShopBranch, id=shop_id)
    
    # Get date range
    date_range = request.GET.get('date_range', 'month')
    today = timezone.now().date()
    
    if date_range == 'today':
        start_date = today
        end_date = today
    elif date_range == 'week':
        start_date = today - timedelta(days=7)
        end_date = today
    elif date_range == 'month':
        start_date = today - timedelta(days=30)
        end_date = today
    elif date_range == 'quarter':
        start_date = today - timedelta(days=90)
        end_date = today
    elif date_range == 'year':
        start_date = today - timedelta(days=365)
        end_date = today
    else:
        start_date = today - timedelta(days=30)
        end_date = today
    
    # Get reports for this shop
    reports = DailyShopReport.objects.filter(
        shop=shop,
        report_date__gte=start_date,
        report_date__lte=end_date
    )
    
    # Calculate metrics
    total_sales = reports.aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
    total_expenses = reports.aggregate(total=Sum('total_expenses'))['total'] or 0
    total_transactions = reports.aggregate(total=Sum('total_mpesa_transactions'))['total'] or 0
    avg_daily_sales = reports.aggregate(avg=Avg('total_mpesa_amount'))['avg'] or 0
    
    # Get M-Pesa account balances for this shop
    mpesa_accounts = MpesaAccount.objects.filter(shop=shop, is_active=True)
    total_mpesa_balance = mpesa_accounts.aggregate(total=Sum('current_balance'))['total'] or 0
    
    # Get M-Pesa daily reports
    mpesa_daily_reports = DailyMpesaAccountReport.objects.filter(
        daily_report__in=reports
    )
    
    mpesa_float_total = mpesa_daily_reports.aggregate(total=Sum('closing_mpesa_float'))['total'] or 0
    mpesa_airtel_total = mpesa_daily_reports.aggregate(total=Sum('closing_airtel_float'))['total'] or 0
    mpesa_cash_total = mpesa_daily_reports.aggregate(total=Sum('closing_cash'))['total'] or 0
    
    # Get bank accounts for this shop
    bank_accounts = BankAccount.objects.filter(shop=shop, is_active=True)
    total_bank_balance = bank_accounts.aggregate(total=Sum('current_balance'))['total'] or 0
    
    # Get bank closing balances from reports
    bank_closings = BankClosingBalance.objects.filter(
        daily_report__in=reports
    )
    bank_total = bank_closings.aggregate(total=Sum('closing_balance'))['total'] or 0
    
    # Get cash accounts for this shop
    cash_accounts = CashAccount.objects.filter(shop=shop, is_active=True)
    total_cash_balance = cash_accounts.aggregate(total=Sum('current_balance'))['total'] or 0
    
    # Get expenses breakdown
    expenses = ShopExpense.objects.filter(
        daily_report__in=reports
    )
    expense_by_category = expenses.values('expense_category').annotate(
        total=Sum('amount')
    ).order_by('-total')[:10]
    
    # Daily trend for this shop
    daily_trend = []
    for i in range(30):
        date = today - timedelta(days=i)
        day_reports = reports.filter(report_date=date)
        daily_trend.append({
            'report_date': date,
            'sales': day_reports.aggregate(total=Sum('total_mpesa_amount'))['total'] or 0,
            'expenses': day_reports.aggregate(total=Sum('total_expenses'))['total'] or 0,
            'profit': (day_reports.aggregate(total=Sum('total_mpesa_amount'))['total'] or 0) - 
                     (day_reports.aggregate(total=Sum('total_expenses'))['total'] or 0)
        })
    daily_trend.reverse()
    
    # Recent reports
    recent_reports = reports.select_related('submitted_by').order_by('-report_date')[:10]
    
    # Calculate daily averages
    days_count = max(reports.count(), 1)
    avg_daily_expenses = total_expenses / days_count if days_count > 0 else 0
    
    # Calculate profit margin
    profit_margin = (total_sales - total_expenses) / total_sales * 100 if total_sales > 0 else 0
    
    # Get report status
    total_reports_count = reports.count()
    finalized_count = reports.filter(is_finalized=True).count()
    pending_count = total_reports_count - finalized_count
    finalization_rate = (finalized_count / total_reports_count * 100) if total_reports_count > 0 else 0
    
    context = {
        'shop': shop,
        'date_range': date_range,
        'start_date': start_date,
        'end_date': end_date,
        
        # Financial metrics
        'total_sales': total_sales,
        'total_expenses': total_expenses,
        'net_profit': total_sales - total_expenses,
        'total_transactions': total_transactions,
        'avg_daily_sales': avg_daily_sales,
        'avg_daily_expenses': avg_daily_expenses,
        'profit_margin': profit_margin,
        
        # M-Pesa metrics
        'mpesa_accounts': mpesa_accounts,
        'total_mpesa_balance': total_mpesa_balance,
        'mpesa_float_total': mpesa_float_total,
        'mpesa_airtel_total': mpesa_airtel_total,
        'mpesa_cash_total': mpesa_cash_total,
        
        # Bank metrics
        'bank_accounts': bank_accounts,
        'total_bank_balance': total_bank_balance,
        'bank_total': bank_total,
        
        # Cash metrics
        'cash_accounts': cash_accounts,
        'total_cash_balance': total_cash_balance,
        
        # Expenses
        'expense_by_category': expense_by_category,
        'total_expense_count': expenses.count(),
        
        # Trends
        'daily_trend': daily_trend,
        
        # Reports
        'recent_reports': recent_reports,
        'total_reports': total_reports_count,
        'finalized_count': finalized_count,
        'pending_count': pending_count,
        'finalization_rate': finalization_rate,
    }
    
    return render(request, 'shops/shop_detail_stats.html', context)





# ==================== DAILY SHOP REPORT VIEWS ====================

@login_required
@user_passes_test(is_staff_or_admin)
def create_daily_report(request):
    """Create a new daily report for a shop"""
    
    # Get user's assigned shop (for non-superusers)
    assigned_shop = None
    user_can_select_shop = request.user.is_superuser
    
    # Get all shops for superuser dropdown
    all_shops = []
    if user_can_select_shop:
        all_shops = ShopBranch.objects.filter(is_active=True)
    
    # Handle shop selection from GET parameter (for superusers)
    selected_shop_id = request.GET.get('shop')
    if user_can_select_shop and selected_shop_id:
        assigned_shop = get_object_or_404(ShopBranch, id=selected_shop_id)
    elif not user_can_select_shop:
        # Non-superuser: get assigned shop from staff profile
        if hasattr(request.user, 'staff_profile') and request.user.staff_profile:
            assigned_shop = request.user.staff_profile.assigned_shop
        
        # If no assigned shop, try to get from recent reports
        if not assigned_shop:
            recent_report = DailyShopReport.objects.filter(
                submitted_by=request.user
            ).order_by('-report_date').first()
            if recent_report:
                assigned_shop = recent_report.shop
    
    # Get available M-Pesa accounts for the assigned shop
    available_mpesa_accounts = []
    if assigned_shop:
        available_mpesa_accounts = MpesaAccount.objects.filter(
            shop=assigned_shop,
            is_active=True,
            status='active'
        )
    
    # Get available banks for the assigned shop
    available_banks = []
    if assigned_shop:
        available_banks = BankAccount.objects.filter(
            shop=assigned_shop,
            is_active=True
        )
    
    # Get previous closing balance
    previous_closing_balance = 0
    previous_report_date = None
    
    if assigned_shop:
        last_shop_report = DailyShopReport.objects.filter(
            shop=assigned_shop
        ).order_by('-report_date').first()
        
        if last_shop_report:
            previous_closing_balance = float(last_shop_report.total_closing_balance)
            previous_report_date = last_shop_report.report_date
    
    if request.method == 'POST':
        form = DailyShopReportForm(request.POST)
        
        # For non-superusers, force the shop to their assigned shop
        if not user_can_select_shop and assigned_shop:
            form.data = form.data.copy()
            form.data['shop'] = assigned_shop.id
        
        if form.is_valid():
            shop = form.cleaned_data.get('shop')
            report_date = form.cleaned_data.get('report_date')
            
            # Check if report already exists
            existing_report = DailyShopReport.objects.filter(
                shop=shop,
                report_date=report_date
            ).first()
            
            if existing_report:
                messages.error(
                    request, 
                    f'A report already exists for {shop.name} on {report_date}. '
                    f'Please edit the existing report instead.'
                )
                return redirect('shops:edit_report', report_id=existing_report.id)
            
            try:
                with transaction.atomic():
                    # Save the main report
                    report = form.save(commit=False)
                    report.submitted_by = request.user
                    report.total_expenses = Decimal('0')
                    report.total_closing_balance = Decimal('0')
                    
                    # Get cash value from POST data and save it
                    cash_balance = request.POST.get('total_cash', 0)
                    report.cash_balance = Decimal(str(cash_balance)) if cash_balance else Decimal('0')
                    
                    report.save()
                    
                    # ============================================
                    # PROCESS MPESA ACCOUNTS
                    # ============================================
                    mpesa_keys = [k for k in request.POST.keys() if k.startswith('mpesa_account_')]
                    selected_mpesa_ids = set()
                    
                    for key in mpesa_keys:
                        index = key.split('_')[-1]
                        account_id = request.POST.get(key)
                        
                        if account_id and account_id not in selected_mpesa_ids:
                            closing_balance = request.POST.get(f'closing_balance_{index}', 0)
                            
                            if closing_balance and float(closing_balance) > 0:
                                DailyMpesaAccountReport.objects.create(
                                    daily_report=report,
                                    mpesa_account_id=int(account_id),
                                    closing_mpesa_float=Decimal(str(closing_balance)),
                                    closing_airtel_float=Decimal('0'),
                                    closing_cash=Decimal('0')
                                )
                                selected_mpesa_ids.add(account_id)
                    
                    # ============================================
                    # PROCESS BANK ACCOUNTS
                    # ============================================
                    bank_keys = [k for k in request.POST.keys() if k.startswith('bank_account_')]
                    selected_bank_ids = set()
                    
                    for key in bank_keys:
                        index = key.split('_')[-1]
                        bank_id = request.POST.get(key)
                        
                        if bank_id and bank_id not in selected_bank_ids:
                            closing_balance = request.POST.get(f'bank_closing_balance_{index}', 0)
                            
                            if closing_balance and float(closing_balance) > 0:
                                BankClosingBalance.objects.create(
                                    daily_report=report,
                                    bank_account_id=int(bank_id),
                                    closing_balance=Decimal(str(closing_balance))
                                )
                                selected_bank_ids.add(bank_id)
                    
                    # ============================================
                    # PROCESS EXPENSES - FIXED
                    # ============================================
                    expense_keys = [k for k in request.POST.keys() if k.startswith('expense_type_')]
                    expense_total = Decimal('0')
                    
                    for key in expense_keys:
                        index = key.split('_')[-1]
                        expense_type = request.POST.get(key)
                        description = request.POST.get(f'expense_description_{index}', '')
                        amount_str = request.POST.get(f'expense_amount_{index}', '0')
                        
                        # Convert to Decimal safely
                        try:
                            amount = Decimal(str(amount_str))
                        except:
                            amount = Decimal('0')
                        
                        if expense_type and amount > 0:
                            ShopExpense.objects.create(
                                daily_report=report,
                                expense_category=expense_type,
                                description=description,
                                amount=amount,
                                payment_method='cash'
                            )
                            expense_total += amount
                            print(f"Created expense: {expense_type} - KES {amount}")  # Debug print
                    
                    # ============================================
                    # UPDATE REPORT TOTALS
                    # ============================================
                    report.total_expenses = expense_total
                    report.save(update_fields=['total_expenses'])
                    
                    # Calculate M-Pesa total
                    mpesa_total = DailyMpesaAccountReport.objects.filter(daily_report=report).aggregate(
                        total=Sum('closing_mpesa_float')
                    )['total'] or Decimal('0')
                    
                    # Calculate Bank total
                    bank_total = BankClosingBalance.objects.filter(daily_report=report).aggregate(
                        total=Sum('closing_balance')
                    )['total'] or Decimal('0')
                    
                    # Calculate total closing balance (M-Pesa + Cash + Bank)
                    report.total_closing_balance = mpesa_total + report.cash_balance + bank_total
                    report.save(update_fields=['total_closing_balance'])
                    
                    print(f"Expenses saved: {expense_total}")  # Debug print
                    print(f"Total closing balance: {report.total_closing_balance}")  # Debug print
                    
                    messages.success(
                        request, 
                        f'Daily report for {report.shop.name} on {report.report_date} submitted successfully!'
                    )
                    return redirect('shops:report_detail', report_id=report.id)
                    
            except Exception as e:
                messages.error(request, f'Error saving report: {str(e)}')
                import traceback
                print(traceback.format_exc())
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = DailyShopReportForm()
        # Pre-select shop for non-superusers
        if not user_can_select_shop and assigned_shop:
            form.fields['shop'].initial = assigned_shop.id
            form.fields['shop'].widget.attrs['readonly'] = True
        elif user_can_select_shop and assigned_shop:
            form.fields['shop'].initial = assigned_shop.id
    
    # Get previous net balance for display
    previous_net_balance = 0
    if assigned_shop:
        last_report = DailyShopReport.objects.filter(
            shop=assigned_shop
        ).order_by('-report_date').first()
        if last_report:
            previous_net_balance = float(last_report.total_closing_balance)
    
    context = {
        'form': form,
        'title': 'Create Daily Report',
        'assigned_shop': assigned_shop,
        'user_can_select_shop': user_can_select_shop,
        'all_shops': all_shops,
        'selected_shop_id': selected_shop_id,
        'previous_closing_balance': previous_closing_balance,
        'previous_net_balance': previous_net_balance,
        'previous_report_date': previous_report_date,
        'available_mpesa_accounts': available_mpesa_accounts,
        'available_banks': available_banks,
        'mpesa_account_reports': [],
        'bank_closings': [],
        'expenses': [],
        'total_cash': 0,
    }
    
    return render(request, 'shops/report_form.html', context)


@login_required
@user_passes_test(is_staff_or_admin)
def edit_daily_report(request, report_id):
    """Edit an existing daily report"""
    report = get_object_or_404(DailyShopReport, id=report_id)
    
    # Check permission
    if not request.user.is_superuser and report.submitted_by != request.user:
        messages.error(request, 'You can only edit your own reports.')
        return redirect('shops:reports_list')
    
    if report.is_finalized:
        messages.warning(request, 'This report is finalized and cannot be edited.')
        return redirect('shops:report_detail', report_id=report.id)
    
    assigned_shop = None
    user_can_select_shop = request.user.is_superuser
    
    if not user_can_select_shop:
        if hasattr(request.user, 'staff_profile') and request.user.staff_profile:
            assigned_shop = request.user.staff_profile.assigned_shop
        if not assigned_shop:
            assigned_shop = report.shop
    else:
        assigned_shop = report.shop
    
    # Get available accounts
    available_mpesa_accounts = MpesaAccount.objects.filter(
        shop=report.shop, is_active=True, status='active'
    )
    available_banks = BankAccount.objects.filter(shop=report.shop, is_active=True)
    
    # Get existing data
    existing_mpesa_reports = DailyMpesaAccountReport.objects.filter(daily_report=report)
    existing_mpesa_ids = set([str(r.mpesa_account_id) for r in existing_mpesa_reports])
    
    existing_bank_closings = report.bank_closings.filter(is_active=True)
    existing_bank_ids = set([str(b.bank_account_id) for b in existing_bank_closings])
    
    # Mark which accounts are already used
    for account in available_mpesa_accounts:
        account.is_selected = str(account.id) in existing_mpesa_ids
    
    for bank in available_banks:
        bank.is_selected = str(bank.id) in existing_bank_ids
    
    # Get existing data for template
    mpesa_account_reports = existing_mpesa_reports
    bank_closings = existing_bank_closings
    expenses = report.expenses.all()
    
    # Get previous day's closing balance
    previous_report = DailyShopReport.objects.filter(
        shop=report.shop,
        report_date__lt=report.report_date
    ).order_by('-report_date').first()
    
    previous_net_balance = float(previous_report.total_closing_balance) if previous_report else 0
    
    if request.method == 'POST':
        form = DailyShopReportForm(request.POST, instance=report)
        
        if not user_can_select_shop and assigned_shop:
            form.data = form.data.copy()
            form.data['shop'] = assigned_shop.id
        
        if form.is_valid():
            try:
                with transaction.atomic():
                    report = form.save(commit=False)
                    
                    # Get cash value from POST data and save it
                    cash_balance = request.POST.get('total_cash', 0)
                    report.cash_balance = Decimal(str(cash_balance)) if cash_balance else Decimal('0')
                    
                    report.save()
                    
                    # ============================================
                    # UPDATE MPESA ACCOUNTS
                    # ============================================
                    DailyMpesaAccountReport.objects.filter(daily_report=report).delete()
                    
                    mpesa_keys = [k for k in request.POST.keys() if k.startswith('mpesa_account_')]
                    selected_mpesa_ids = set()
                    
                    for key in mpesa_keys:
                        index = key.split('_')[-1]
                        account_id = request.POST.get(key)
                        
                        if account_id and account_id not in selected_mpesa_ids:
                            closing_balance = request.POST.get(f'closing_balance_{index}', 0)
                            
                            if closing_balance and float(closing_balance) > 0:
                                DailyMpesaAccountReport.objects.create(
                                    daily_report=report,
                                    mpesa_account_id=int(account_id),
                                    closing_mpesa_float=Decimal(str(closing_balance)),
                                    closing_airtel_float=Decimal('0'),
                                    closing_cash=Decimal('0')
                                )
                                selected_mpesa_ids.add(account_id)
                    
                    # ============================================
                    # UPDATE BANK ACCOUNTS
                    # ============================================
                    BankClosingBalance.objects.filter(daily_report=report).delete()
                    
                    bank_keys = [k for k in request.POST.keys() if k.startswith('bank_account_')]
                    selected_bank_ids = set()
                    
                    for key in bank_keys:
                        index = key.split('_')[-1]
                        bank_id = request.POST.get(key)
                        
                        if bank_id and bank_id not in selected_bank_ids:
                            closing_balance = request.POST.get(f'bank_closing_balance_{index}', 0)
                            
                            if closing_balance and float(closing_balance) > 0:
                                BankClosingBalance.objects.create(
                                    daily_report=report,
                                    bank_account_id=int(bank_id),
                                    closing_balance=Decimal(str(closing_balance))
                                )
                                selected_bank_ids.add(bank_id)
                    
                    # ============================================
                    # UPDATE EXPENSES
                    # ============================================
                    ShopExpense.objects.filter(daily_report=report).delete()
                    
                    expense_keys = [k for k in request.POST.keys() if k.startswith('expense_type_')]
                    expense_total = 0
                    
                    for key in expense_keys:
                        index = key.split('_')[-1]
                        expense_type = request.POST.get(key)
                        description = request.POST.get(f'expense_description_{index}', '')
                        amount = request.POST.get(f'expense_amount_{index}', 0)
                        
                        if expense_type and float(amount) > 0:
                            ShopExpense.objects.create(
                                daily_report=report,
                                expense_category=expense_type,
                                description=description,
                                amount=Decimal(str(amount)),
                                payment_method='cash'
                            )
                            expense_total += float(amount)
                    
                    # ============================================
                    # UPDATE TOTALS
                    # ============================================
                    report.total_expenses = expense_total
                    report.save(update_fields=['total_expenses'])
                    
                    mpesa_total = DailyMpesaAccountReport.objects.filter(daily_report=report).aggregate(
                        total=Sum('closing_mpesa_float')
                    )['total'] or 0
                    
                    bank_total = BankClosingBalance.objects.filter(daily_report=report).aggregate(
                        total=Sum('closing_balance')
                    )['total'] or 0
                    
                    # Include cash_balance in total closing balance
                    report.total_closing_balance = float(mpesa_total) + float(report.cash_balance) + float(bank_total)
                    report.save(update_fields=['total_closing_balance'])
                    
                    messages.success(request, f'Report for {report.shop.name} updated successfully!')
                    return redirect('shops:report_detail', report_id=report.id)
                    
            except Exception as e:
                messages.error(request, f'Error updating report: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = DailyShopReportForm(instance=report)
        if not user_can_select_shop and assigned_shop:
            form.fields['shop'].initial = assigned_shop.id
            form.fields['shop'].widget.attrs['readonly'] = True
    
    context = {
        'form': form,
        'report': report,
        'title': 'Edit Daily Report',
        'assigned_shop': assigned_shop,
        'user_can_select_shop': user_can_select_shop,
        'previous_net_balance': previous_net_balance,
        'previous_closing_balance': previous_net_balance,
        'previous_report_date': previous_report.report_date if previous_report else None,
        'available_mpesa_accounts': available_mpesa_accounts,
        'available_banks': available_banks,
        'mpesa_account_reports': mpesa_account_reports,
        'bank_closings': bank_closings,
        'expenses': expenses,
        'existing_mpesa_ids': list(existing_mpesa_ids),
        'existing_bank_ids': list(existing_bank_ids),
        'total_cash': float(report.cash_balance) if hasattr(report, 'cash_balance') else 0,
    }
    return render(request, 'shops/report_form.html', context)


@login_required
def report_detail(request, report_id):
    """View detailed report"""
    from django.db.models import Sum
    
    report = get_object_or_404(DailyShopReport, id=report_id)
    
    if not request.user.is_superuser and report.submitted_by != request.user:
        messages.error(request, 'You can only view your own reports.')
        return redirect('shops:reports_list')
    
    # Get previous day's closing balance
    previous_report = DailyShopReport.objects.filter(
        shop=report.shop,
        report_date__lt=report.report_date
    ).order_by('-report_date').first()
    
    opening_balance = previous_report.total_closing_balance if previous_report else Decimal('0.00')
    
    # Get M-Pesa reports (only M-Pesa float, not cash)
    mpesa_reports = report.mpesa_balances.all()
    total_mpesa = mpesa_reports.aggregate(
        total=Sum('closing_mpesa_float')
    )['total'] or 0
    
    # Get bank closings
    bank_closings = report.bank_closings.filter(is_active=True)
    bank_total = bank_closings.aggregate(
        total=Sum('closing_balance')
    )['total'] or 0
    
    # Get expenses
    expenses = report.expenses.all()
    expense_total = expenses.aggregate(total=Sum('amount'))['total'] or 0
    
    # IMPORTANT: Get cash balance directly from the report's cash_balance field
    # This is the cash entered in the form, not calculated
    total_cash = float(report.cash_balance) if report.cash_balance else 0
    
    # Calculate today's closing = M-Pesa Float + Cash + Bank
    today_closing = float(total_mpesa) + float(total_cash) + float(bank_total)
    
    # Calculate net position (for display)
    net_position = today_closing
    
    context = {
        'report': report,
        'mpesa_reports': mpesa_reports,
        'bank_closings': bank_closings,
        'bank_total': bank_total,
        'total_mpesa': total_mpesa,
        'total_cash': total_cash,  # This is the cash from cash_balance field
        'today_closing': today_closing,
        'net_position': net_position,
        'opening_balance': opening_balance,
        'previous_report': previous_report,
        'expenses': expenses,
        'expense_total': expense_total,
    }
    return render(request, 'shops/report_detail.html', context)

@login_required
def reports_list(request):
    """List all reports - filtered by user"""
    from django.db.models import Sum, Q
    from django.core.paginator import Paginator
    from decimal import Decimal
    from django.utils import timezone
    from shops.models import DailyShopReport, ShopBranch, BankClosingBalance
    
    # Get current date range for monthly calculations
    today = timezone.now().date()
    first_day_of_month = today.replace(day=1)
    
    # Filter reports based on user permissions
    if request.user.is_superuser:
        reports = DailyShopReport.objects.all().order_by('-report_date')
        monthly_expenses = DailyShopReport.objects.filter(
            report_date__gte=first_day_of_month,
            report_date__lte=today
        ).aggregate(total=Sum('total_expenses'))['total'] or Decimal('0.00')
    else:
        reports = DailyShopReport.objects.filter(
            submitted_by=request.user
        ).order_by('-report_date')
        monthly_expenses = DailyShopReport.objects.filter(
            submitted_by=request.user,
            report_date__gte=first_day_of_month,
            report_date__lte=today
        ).aggregate(total=Sum('total_expenses'))['total'] or Decimal('0.00')
    
    # Store original queryset for stats (before pagination)
    all_reports = reports
    
    # Filter by shop
    shop_id = request.GET.get('shop')
    if shop_id:
        if request.user.is_superuser:
            reports = reports.filter(shop_id=shop_id)
            all_reports = all_reports.filter(shop_id=shop_id)
        else:
            user_shops = reports.values_list('shop_id', flat=True).distinct()
            if int(shop_id) in user_shops:
                reports = reports.filter(shop_id=shop_id)
                all_reports = all_reports.filter(shop_id=shop_id)
    
    # Filter by date range
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    if from_date:
        reports = reports.filter(report_date__gte=from_date)
        all_reports = all_reports.filter(report_date__gte=from_date)
    if to_date:
        reports = reports.filter(report_date__lte=to_date)
        all_reports = all_reports.filter(report_date__lte=to_date)
    
    # Filter by finalized status
    finalized = request.GET.get('finalized')
    if finalized == 'true':
        reports = reports.filter(is_finalized=True)
        all_reports = all_reports.filter(is_finalized=True)
    elif finalized == 'false':
        reports = reports.filter(is_finalized=False)
        all_reports = all_reports.filter(is_finalized=False)
    
    # Calculate statistics
    finalized_count = all_reports.filter(is_finalized=True).count()
    draft_count = all_reports.filter(is_finalized=False).count()
    total_sales_value = all_reports.aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
    total_expenses_value = all_reports.aggregate(total=Sum('total_expenses'))['total'] or 0
    
    # ============================================
    # Process each report with verification status
    # CORRECTED FORMULA: Today's Closing = Yesterday's Closing - Today's Expenses
    # ============================================
    reports_list = []
    for report in reports:
        # Calculate bank total from related bank closing balances
        bank_total = BankClosingBalance.objects.filter(
            daily_report=report,
            is_active=True
        ).aggregate(total=Sum('closing_balance'))['total'] or 0
        report.bank_total = bank_total
        
        # Get previous report for this shop
        previous_report = DailyShopReport.objects.filter(
            shop=report.shop,
            report_date__lt=report.report_date
        ).order_by('-report_date').first()
        
        # Calculate verification status using CORRECT formula
        if previous_report:
            # Expected closing = Previous closing - Today's expenses
            expected_closing = previous_report.total_closing_balance - report.total_expenses
            difference = report.total_closing_balance - expected_closing
            
            # Use small tolerance for floating point comparison
            if abs(difference) < 0.01:  # Within 0.01 KES tolerance
                report.verification_status = 'verified'
                report.verification_icon = 'fas fa-check-circle'
                report.verification_text = 'Report Matches'
                report.verification_color = 'success'
                report.verification_title = f'✓ Verified: Closing KES {report.total_closing_balance:,.2f} = Previous KES {previous_report.total_closing_balance:,.2f} - Expenses KES {report.total_expenses:,.2f}'
            elif difference > 0:
                # Actual closing is HIGHER than expected (Surplus)
                report.verification_status = 'surplus'
                report.verification_icon = 'fas fa-exclamation-triangle'
                report.verification_text = f'Extra By (+{difference:,.2f})'
                report.verification_color = 'warning'
                report.verification_title = f'⚠️ Surplus: Closing is KES {difference:,.2f} higher than expected\nExpected: KES {expected_closing:,.2f}\nActual: KES {report.total_closing_balance:,.2f}'
            else:
                # Actual closing is LOWER than expected (Deficit)
                report.verification_status = 'deficit'
                report.verification_icon = 'fas fa-times-circle'
                report.verification_text = f'Less By ({difference:,.2f})'
                report.verification_color = 'danger'
                report.verification_title = f'❌ Deficit: Closing is KES {abs(difference):,.2f} lower than expected\nExpected: KES {expected_closing:,.2f}\nActual: KES {report.total_closing_balance:,.2f}'
        else:
            # First report for this shop
            report.verification_status = 'first'
            report.verification_icon = 'fas fa-info-circle'
            report.verification_text = 'First Report'
            report.verification_color = 'info'
            report.verification_title = 'First report - no previous data to compare'
        
        reports_list.append(report)
    
    # Pagination on the list
    paginator = Paginator(reports_list, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # For shop filter dropdown
    if request.user.is_superuser:
        shops = ShopBranch.objects.filter(is_active=True)
    else:
        user_shop_ids = DailyShopReport.objects.filter(
            submitted_by=request.user
        ).values_list('shop_id', flat=True).distinct()
        shops = ShopBranch.objects.filter(id__in=user_shop_ids, is_active=True)
    
    context = {
        'reports': page_obj,
        'shops': shops,
        'selected_shop': shop_id,
        'from_date': from_date,
        'to_date': to_date,
        'finalized_filter': finalized,
        'finalized_count': finalized_count,
        'draft_count': draft_count,
        'total_sales_value': total_sales_value,
        'total_expenses_value': total_expenses_value,
        'monthly_expenses': monthly_expenses,
        'is_superuser': request.user.is_superuser,
    }
    return render(request, 'shops/reports_list.html', context)


@login_required
@user_passes_test(is_staff_or_admin)
def finalize_report(request, report_id):
    """Finalize a report and redirect back to the referring page"""
    report = get_object_or_404(DailyShopReport, id=report_id)
    
    if not request.user.is_superuser and report.submitted_by != request.user:
        messages.error(request, 'You can only finalize your own reports.')
        return redirect('shops:reports_list')
    
    if request.method == 'POST':
        report.is_finalized = True
        report.finalized_by = request.user
        report.finalized_at = timezone.now()
        report.save()
        messages.success(request, f'Report for {report.report_date} has been finalized!')
    
    # Try to go back to the referring page
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    
    # Default to detail page
    return redirect('shops:report_detail', report_id=report.id)


@login_required
@user_passes_test(is_superuser)
def unfinalize_report(request, report_id):
    """Revert a finalized report back to draft and redirect back to the referring page"""
    report = get_object_or_404(DailyShopReport, id=report_id)
    
    if not report.is_finalized:
        messages.warning(request, 'This report is already in draft status.')
        return redirect('shops:report_detail', report_id=report.id)
    
    if request.method == 'POST':
        report.is_finalized = False
        report.finalized_by = None
        report.finalized_at = None
        report.save()
        messages.success(request, f'Report for {report.report_date} has been reverted to draft.')
    
    # Try to go back to the referring page
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    
    # Default to detail page
    return redirect('shops:report_detail', report_id=report.id)


@login_required
def weekly_sales_data(request):
    """AJAX endpoint for weekly sales chart data - filtered by user"""
    try:
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=6)
        
        sales_data = []
        days = []
        
        for i in range(7):
            current_date = start_date + timedelta(days=i)
            days.append(current_date.strftime('%a, %b %d'))
            
            if request.user.is_superuser:
                daily_total = DailyShopReport.objects.filter(
                    report_date=current_date,
                    is_finalized=True
                ).aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
            else:
                daily_total = DailyShopReport.objects.filter(
                    report_date=current_date,
                    is_finalized=True,
                    submitted_by=request.user
                ).aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
            
            sales_data.append(float(daily_total))
        
        return JsonResponse({
            'success': True,
            'days': days,
            'sales': sales_data
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def weekly_transactions_data(request):
    """AJAX endpoint for weekly transactions chart data"""
    try:
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=6)
        
        transactions_data = []
        days = []
        
        if request.user.is_superuser:
            reports = DailyShopReport.objects.all()
        else:
            reports = DailyShopReport.objects.filter(submitted_by=request.user)
        
        for i in range(7):
            current_date = start_date + timedelta(days=i)
            days.append(current_date.strftime('%a, %b %d'))
            
            daily_total = reports.filter(
                report_date=current_date,
                is_finalized=True
            ).aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
            
            transactions_data.append(float(daily_total))
        
        return JsonResponse({
            'success': True,
            'days': days,
            'transactions': transactions_data
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def expense_distribution(request):
    """AJAX endpoint for expense distribution chart data - filtered by user"""
    try:
        from django.db.models import Sum
        
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        
        if request.user.is_superuser:
            expenses = ShopExpense.objects.all()
        else:
            expenses = ShopExpense.objects.filter(
                daily_report__submitted_by=request.user
            )
        
        if start_date:
            expenses = expenses.filter(daily_report__report_date__gte=start_date)
        if end_date:
            expenses = expenses.filter(daily_report__report_date__lte=end_date)
        
        expense_data = expenses.values('expense_category').annotate(
            total=Sum('amount')
        ).order_by('-total')
        
        categories = [item['expense_category'] or 'Uncategorized' for item in expense_data]
        amounts = [float(item['total']) for item in expense_data]
        
        return JsonResponse({
            'success': True,
            'categories': categories,
            'amounts': amounts
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })





# ==================== SHOP BRANCH MANAGEMENT ====================

@login_required
@user_passes_test(is_superuser)
def add_branch(request):
    """Add a new shop branch - Superuser only"""
    if not request.user.is_superuser:
        messages.error(request, 'Only superusers can add shop branches.')
        return redirect('shops:branches')
    
    if request.method == 'POST':
        form = ShopBranchForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Shop branch added successfully!')
            return redirect('shops:branches')
    else:
        form = ShopBranchForm()
    
    context = {
        'form': form,
        'title': 'Add Shop Branch',
    }
    return render(request, 'shops/add_branch.html', context)


@login_required
@user_passes_test(is_superuser)
def edit_shop_branch(request, shop_id):
    """Edit shop branch - Superuser only"""
    branch = get_object_or_404(ShopBranch, id=shop_id)
    
    if request.method == 'POST':
        form = ShopBranchForm(request.POST, instance=branch)
        if form.is_valid():
            form.save()
            messages.success(request, 'Shop branch updated successfully!')
            return redirect('shops:branches')
    else:
        form = ShopBranchForm(instance=branch)
    
    context = {
        'form': form,
        'branch': branch,
    }
    return render(request, 'shops/edit_branch.html', context)


@login_required
@user_passes_test(is_superuser)
def shop_branches(request):
    """Manage shop branches"""
    branches = ShopBranch.objects.all()
    
    if request.method == 'POST':
        form = ShopBranchForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Shop branch added successfully!')
            return redirect('shops:branches')
    else:
        form = ShopBranchForm()
    
    context = {
        'branches': branches,
        'form': form,
    }
    return render(request, 'shops/branches.html', context)




# ==================== MPESA ACCOUNT MANAGEMENT ====================

@login_required
@user_passes_test(is_superuser)
def mpesa_accounts(request):
    """List all M-Pesa accounts with effective balances (closing + post-report injections)"""
    
    accounts = MpesaAccount.objects.all().select_related('shop', 'assigned_user')
    
    # Filter by shop
    shop_id = request.GET.get('shop')
    if shop_id:
        accounts = accounts.filter(shop_id=shop_id)
    
    # Filter by account type
    account_type = request.GET.get('account_type')
    if account_type:
        accounts = accounts.filter(account_type=account_type)
    
    # Filter by status
    status = request.GET.get('status')
    if status:
        accounts = accounts.filter(status=status)
    
    # Search
    search = request.GET.get('search')
    if search:
        accounts = accounts.filter(
            Q(account_name__icontains=search) |
            Q(account_number__icontains=search) |
            Q(store_number__icontains=search)
        )
    
    # Enhance each account with effective balance (last closing + post-report injections)
    accounts_with_balance = []
    total_effective_balance = Decimal('0')
    total_closing_balance = Decimal('0')
    total_post_injections = Decimal('0')
    
    for account in accounts:
        # Get the latest report for this specific M-Pesa account
        latest_account_report = DailyMpesaAccountReport.objects.filter(
            mpesa_account=account
        ).order_by('-daily_report__report_date').first()
        
        if latest_account_report:
            closing_balance = latest_account_report.closing_mpesa_float
            report_date = latest_account_report.daily_report.report_date
            
            # Get injections AFTER this report
            post_report_injections = AccountTransaction.objects.filter(
                transaction_type='injection',
                is_approved=True,
                account_type='mpesa',
                mpesa_account=account,
                created_at__date__gt=report_date
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            
            effective_balance = closing_balance + post_report_injections
        else:
            closing_balance = Decimal('0')
            effective_balance = account.current_balance  # Fallback to current balance
            post_report_injections = Decimal('0')
            report_date = None
        
        # Store the calculated values on the account object
        account.effective_balance = effective_balance
        account.closing_balance = closing_balance
        account.post_report_injections = post_report_injections
        account.last_report_date = report_date
        
        accounts_with_balance.append(account)
        total_effective_balance += effective_balance
        total_closing_balance += closing_balance
        total_post_injections += post_report_injections
    
    # Calculate statistics
    total_accounts = accounts.count()
    active_accounts = accounts.filter(status='active', is_active=True).count()
    till_count = accounts.filter(account_type='till', status='active').count()
    paybill_count = accounts.filter(account_type='paybill', status='active').count()
    
    # Pagination on the list
    paginator = Paginator(accounts_with_balance, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'accounts': page_obj,
        'shops': ShopBranch.objects.filter(is_active=True),
        'selected_shop': shop_id,
        'selected_account_type': account_type,
        'selected_status': status,
        'search': search,
        'total_accounts': total_accounts,
        'active_accounts': active_accounts,
        'total_closing_balance': total_closing_balance,
        'total_post_injections': total_post_injections,
        'total_effective_balance': total_effective_balance,
        'till_count': till_count,
        'paybill_count': paybill_count,
    }
    return render(request, 'shops/mpesa_accounts.html', context)


@login_required
def mpesa_accounts_detail(request, account_id):
    """View M-Pesa account details"""
    account = get_object_or_404(MpesaAccount, id=account_id)
    
    context = {
        'account': account,
    }
    return render(request, 'shops/mpesa_account_detail.html', context)


@login_required
@user_passes_test(is_superuser)
def add_mpesa_account(request):
    """Add a new M-Pesa account"""
    if request.method == 'POST':
        form = MpesaAccountForm(request.POST)
        if form.is_valid():
            account = form.save(commit=False)
            account.created_by = request.user
            account.current_balance = account.opening_balance
            account.save()
            messages.success(request, f'M-Pesa account "{account.account_name}" added successfully!')
            return redirect('shops:mpesa_accounts')
    else:
        form = MpesaAccountForm()
    
    context = {
        'form': form,
        'title': 'Add M-Pesa Account',
    }
    return render(request, 'shops/mpesa_account_form.html', context)


@login_required
@user_passes_test(is_superuser)
def edit_mpesa_account(request, account_id):
    """Edit an M-Pesa account"""
    account = get_object_or_404(MpesaAccount, id=account_id)
    
    if request.method == 'POST':
        form = MpesaAccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, f'M-Pesa account "{account.account_name}" updated successfully!')
            return redirect('shops:mpesa_accounts')
    else:
        form = MpesaAccountForm(instance=account)
    
    context = {
        'form': form,
        'account': account,
        'title': 'Edit M-Pesa Account',
    }
    return render(request, 'shops/mpesa_account_form.html', context)


@login_required
@user_passes_test(is_superuser)
def delete_mpesa_account(request, account_id):
    """Soft delete an M-Pesa account"""
    account = get_object_or_404(MpesaAccount, id=account_id)
    
    if request.method == 'POST':
        account.is_active = False
        account.status = 'inactive'
        account.save()
        messages.success(request, f'M-Pesa account "{account.account_name}" deactivated successfully!')
        return redirect('shops:mpesa_accounts')
    
    return redirect('shops:mpesa_accounts')





# ==================== BANK ACCOUNT MANAGEMENT ====================

@login_required
@user_passes_test(is_superuser)
def bank_accounts(request):
    """View all bank accounts"""
    accounts = BankAccount.objects.all().select_related('shop')
    
    shop_id = request.GET.get('shop')
    if shop_id:
        accounts = accounts.filter(shop_id=shop_id)
    
    context = {
        'accounts': accounts,
        'shops': ShopBranch.objects.filter(is_active=True),
        'selected_shop': shop_id,
    }
    return render(request, 'shops/bank_accounts.html', context)


@login_required
@user_passes_test(is_superuser)
def add_bank_account(request):
    """Add a new bank account"""
    if request.method == 'POST':
        form = BankAccountForm(request.POST)
        if form.is_valid():
            account = form.save()
            messages.success(request, 'Bank account added successfully!')
            return redirect('shops:bank_accounts')
    else:
        form = BankAccountForm()
    
    context = {
        'form': form,
        'title': 'Add Bank Account',
    }
    return render(request, 'shops/bank_account_form.html', context)


@login_required
@user_passes_test(is_superuser)
def edit_bank_account(request, account_id):
    """Edit a bank account"""
    account = get_object_or_404(BankAccount, id=account_id)
    
    if request.method == 'POST':
        form = BankAccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, 'Bank account updated successfully!')
            return redirect('shops:bank_accounts')
    else:
        form = BankAccountForm(instance=account)
    
    context = {
        'form': form,
        'account': account,
        'title': 'Edit Bank Account',
    }
    return render(request, 'shops/bank_account_form.html', context)







# ==================== CASH ACCOUNT MANAGEMENT ====================

@login_required
@user_passes_test(is_superuser)
def cash_accounts(request):
    """View all cash accounts"""
    accounts = CashAccount.objects.all().select_related('shop')
    
    shop_id = request.GET.get('shop')
    if shop_id:
        accounts = accounts.filter(shop_id=shop_id)
    
    context = {
        'accounts': accounts,
        'shops': ShopBranch.objects.filter(is_active=True),
        'selected_shop': shop_id,
    }
    return render(request, 'shops/cash_accounts.html', context)


@login_required
@user_passes_test(is_superuser)
def add_cash_account(request):
    """Add a new cash account"""
    if request.method == 'POST':
        form = CashAccountForm(request.POST)
        if form.is_valid():
            account = form.save()
            messages.success(request, 'Cash account added successfully!')
            return redirect('shops:cash_accounts')
    else:
        form = CashAccountForm()
    
    context = {
        'form': form,
        'title': 'Add Cash Account',
    }
    return render(request, 'shops/cash_account_form.html', context)


@login_required
@user_passes_test(is_superuser)
def edit_cash_account(request, account_id):
    """Edit a cash account"""
    account = get_object_or_404(CashAccount, id=account_id)
    
    if request.method == 'POST':
        form = CashAccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cash account updated successfully!')
            return redirect('shops:cash_accounts')
    else:
        form = CashAccountForm(instance=account)
    
    context = {
        'form': form,
        'account': account,
        'title': 'Edit Cash Account',
    }
    return render(request, 'shops/cash_account_form.html', context)






# ==================== AJAX ENDPOINTS ====================

@login_required
def get_shop_banks(request, shop_id):
    """AJAX endpoint to get bank accounts for a shop"""
    try:
        shop = get_object_or_404(ShopBranch, id=shop_id)
        banks = shop.bank_accounts.filter(is_active=True)
        
        banks_data = [{
            'id': bank.id,
            'name': bank.bank_name,
            'account_name': bank.account_name,
            'account_number': bank.account_number,
        } for bank in banks]
        
        return JsonResponse({'success': True, 'banks': banks_data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_shop_mpesa_accounts(request, shop_id):
    """AJAX endpoint to get M-Pesa accounts for a shop"""
    try:
        shop = get_object_or_404(ShopBranch, id=shop_id)
        accounts = MpesaAccount.objects.filter(shop=shop, is_active=True, status='active')
        
        accounts_data = [{
            'id': account.id,
            'name': account.account_name,
            'number': account.account_number,
            'type': account.account_type,
            'phone': account.phone_number,
        } for account in accounts]
        
        return JsonResponse({'success': True, 'mpesa_accounts': accounts_data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_shop_cash_accounts(request, shop_id):
    """AJAX endpoint to get cash accounts for a shop"""
    try:
        shop = get_object_or_404(ShopBranch, id=shop_id)
        accounts = CashAccount.objects.filter(shop=shop, is_active=True)
        
        accounts_data = [{
            'id': account.id,
            'name': account.account_name,
            'balance': float(account.current_balance),
        } for account in accounts]
        
        return JsonResponse({'success': True, 'cash_accounts': accounts_data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_previous_closing_balance(request):
    """AJAX endpoint to get previous day's SHOP closing balance"""
    try:
        shop_id = request.GET.get('shop_id')
        report_date = request.GET.get('report_date')
        
        if shop_id and report_date:
            report_date = datetime.strptime(report_date, '%Y-%m-%d').date()
            previous_date = report_date - timedelta(days=1)
            
            previous_report = DailyShopReport.objects.filter(
                shop_id=shop_id,
                report_date=previous_date
            ).first()
            
            if not previous_report:
                previous_report = DailyShopReport.objects.filter(
                    shop_id=shop_id,
                    report_date__lt=report_date
                ).order_by('-report_date').first()
            
            closing_balance = float(previous_report.total_closing_balance) if previous_report else 0
            
            return JsonResponse({
                'success': True,
                'closing_balance': closing_balance,
                'has_previous': previous_report is not None,
                'previous_date': str(previous_report.report_date) if previous_report else None,
            })
        return JsonResponse({'success': False, 'error': 'Missing parameters'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})






# ==================== EXPORT VIEWS ====================

@login_required
@user_passes_test(is_superuser)
def export_reports_csv(request):
    """Export filtered reports to CSV"""
    import csv
    from django.http import HttpResponse
    
    reports = DailyShopReport.objects.all()
    
    shop_id = request.GET.get('shop')
    if shop_id:
        reports = reports.filter(shop_id=shop_id)
    
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    if from_date:
        reports = reports.filter(report_date__gte=from_date)
    if to_date:
        reports = reports.filter(report_date__lte=to_date)
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="shop_reports.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Date', 'Shop', 'Submitted By', 'Total M-Pesa Amount', 'Total Expenses', 
        'Total Closing Balance', 'Finalized'
    ])
    
    for report in reports:
        writer.writerow([
            report.report_date,
            report.shop.name,
            report.submitted_by.username,
            report.total_mpesa_amount,
            report.total_expenses,
            report.total_closing_balance,
            'Yes' if report.is_finalized else 'No'
        ])
    
    return response







# ==================== DYNAMIC CHOICES MANAGEMENT ====================

@login_required
@user_passes_test(is_superuser)
def manage_choices(request):
    """Manage dynamic choices"""
    if request.method == 'POST':
        form = DynamicChoiceForm(request.POST)
        if form.is_valid():
            choice = form.save(commit=False)
            choice.created_by = request.user
            choice.save()
            messages.success(request, f'Choice "{choice.value}" added successfully!')
            return redirect('shops:manage_choices')
    else:
        form = DynamicChoiceForm()
    
    bank_choices = DynamicChoice.objects.filter(choice_type='bank_name', is_active=True)
    mpesa_types = DynamicChoice.objects.filter(choice_type='mpesa_account_type', is_active=True)
    expense_cats = DynamicChoice.objects.filter(choice_type='expense_category', is_active=True)
    payment_methods = DynamicChoice.objects.filter(choice_type='payment_method', is_active=True)
    
    context = {
        'form': form,
        'bank_choices': bank_choices,
        'mpesa_types': mpesa_types,
        'expense_cats': expense_cats,
        'payment_methods': payment_methods,
    }
    return render(request, 'shops/manage_choices.html', context)

@login_required
@user_passes_test(is_superuser)
def delete_choice(request, choice_id):
    """Soft delete a dynamic choice"""
    choice = get_object_or_404(DynamicChoice, id=choice_id)
    choice.is_active = False
    choice.save()
    messages.success(request, f'Choice "{choice.value}" deactivated successfully!')
    return redirect('shops:manage_choices')






# ==================== MPESA ADJUSTMENTS (INJECTION/WITHDRAWAL) ====================

@login_required
@user_passes_test(is_staff_or_admin)
def mpesa_adjustments_list(request):
    """List all M-Pesa adjustments"""
    adjustments = MpesaAdjustment.objects.all().select_related('mpesa_account__shop', 'created_by', 'approved_by')
    
    # Filter by shop
    shop_id = request.GET.get('shop')
    if shop_id:
        adjustments = adjustments.filter(mpesa_account__shop_id=shop_id)
    
    # Filter by type
    adj_type = request.GET.get('type')
    if adj_type:
        adjustments = adjustments.filter(adjustment_type=adj_type)
    
    # Filter by approval status
    approved = request.GET.get('approved')
    if approved == 'true':
        adjustments = adjustments.filter(is_approved=True)
    elif approved == 'false':
        adjustments = adjustments.filter(is_approved=False)
    
    # Filter by date range
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    if from_date:
        adjustments = adjustments.filter(created_at__date__gte=from_date)
    if to_date:
        adjustments = adjustments.filter(created_at__date__lte=to_date)
    
    # Calculate totals
    total_injections = adjustments.filter(adjustment_type='injection', is_approved=True).aggregate(
        total=Sum('amount')
    )['total'] or 0
    
    total_withdrawals = adjustments.filter(adjustment_type='withdrawal', is_approved=True).aggregate(
        total=Sum('amount')
    )['total'] or 0
    
    pending_approvals = adjustments.filter(is_approved=False).count()
    
    # Pagination
    paginator = Paginator(adjustments, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'adjustments': page_obj,
        'shops': ShopBranch.objects.filter(is_active=True),
        'selected_shop': shop_id,
        'selected_type': adj_type,
        'selected_approved': approved,
        'from_date': from_date,
        'to_date': to_date,
        'total_injections': total_injections,
        'total_withdrawals': total_withdrawals,
        'net_change': total_injections - total_withdrawals,
        'pending_approvals': pending_approvals,
    }
    return render(request, 'shops/mpesa_adjustments_list.html', context)


@login_required
@user_passes_test(is_staff_or_admin)
def mpesa_adjustment_create(request):
    """Create a new M-Pesa adjustment (injection or withdrawal)"""
    
    # Handle pre-selected account from GET parameter
    initial_data = {}
    account_id = request.GET.get('account')
    adjustment_type = request.GET.get('type')
    
    if account_id:
        try:
            account = MpesaAccount.objects.get(id=account_id)
            initial_data['mpesa_account'] = account
        except MpesaAccount.DoesNotExist:
            pass
    
    if adjustment_type in ['injection', 'withdrawal']:
        initial_data['adjustment_type'] = adjustment_type
    
    if request.method == 'POST':
        form = MpesaAdjustmentForm(request.POST, user=request.user)
        if form.is_valid():
            adjustment = form.save(commit=False)
            adjustment.created_by = request.user
            
            # Auto-approve for superusers and managers
            if request.user.is_superuser or request.user.groups.filter(name='manager').exists():
                adjustment.is_approved = True
                adjustment.approved_by = request.user
                adjustment.approved_at = timezone.now()
                messages.success(request, f'Adjustment completed and approved! New balance: KES {adjustment.mpesa_account.current_balance:,.2f}')
            else:
                messages.info(request, 'Adjustment created and pending approval.')
            
            adjustment.save()
            
            # Redirect based on user role
            if adjustment.is_approved:
                return redirect('shops:mpesa_accounts_detail', account_id=adjustment.mpesa_account.id)
            else:
                return redirect('shops:mpesa_adjustments_pending')
    else:
        form = MpesaAdjustmentForm(user=request.user, initial=initial_data)
    
    context = {
        'form': form,
        'title': 'Create M-Pesa Adjustment',
        'preselected_account': account_id,
        'preselected_type': adjustment_type,
    }
    return render(request, 'shops/mpesa_adjustment_form.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser or u.groups.filter(name='manager').exists())
def mpesa_adjustment_approve(request, adjustment_id):
    """Approve a pending adjustment"""
    adjustment = get_object_or_404(MpesaAdjustment, id=adjustment_id)
    
    if adjustment.is_approved:
        messages.warning(request, 'This adjustment has already been approved.')
        return redirect('shops:mpesa_adjustments_list')
    
    if request.method == 'POST':
        adjustment.is_approved = True
        adjustment.approved_by = request.user
        adjustment.approved_at = timezone.now()
        adjustment.save()
        
        # The balance was already updated when the adjustment was created
        # But we need to ensure it's correct
        adjustment.mpesa_account.refresh_from_db()
        
        messages.success(
            request, 
            f'Approved {adjustment.get_adjustment_type_display()} of KES {adjustment.amount:,.2f} '
            f'for {adjustment.mpesa_account.account_name}. New balance: KES {adjustment.mpesa_account.current_balance:,.2f}'
        )
        return redirect('shops:mpesa_adjustments_list')
    
    context = {
        'adjustment': adjustment,
    }
    return render(request, 'shops/mpesa_adjustment_approve.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def mpesa_adjustment_reject(request, adjustment_id):
    """Reject and delete a pending adjustment"""
    adjustment = get_object_or_404(MpesaAdjustment, id=adjustment_id)
    
    if adjustment.is_approved:
        messages.warning(request, 'Approved adjustments cannot be rejected.')
        return redirect('shops:mpesa_adjustments_list')
    
    if request.method == 'POST':
        # Revert the balance change
        if adjustment.adjustment_type == 'injection':
            adjustment.mpesa_account.current_balance -= adjustment.amount
        else:
            adjustment.mpesa_account.current_balance += adjustment.amount
        
        adjustment.mpesa_account.save()
        adjustment.delete()
        
        messages.success(request, 'Adjustment rejected and removed.')
        return redirect('shops:mpesa_adjustments_list')
    
    context = {
        'adjustment': adjustment,
    }
    return render(request, 'shops/mpesa_adjustment_reject.html', context)


@login_required
@user_passes_test(is_staff_or_admin)
def mpesa_adjustments_pending(request):
    """View pending adjustments requiring approval"""
    adjustments = MpesaAdjustment.objects.filter(
        is_approved=False
    ).select_related('mpesa_account__shop', 'created_by')
    
    context = {
        'adjustments': adjustments,
    }
    return render(request, 'shops/mpesa_adjustments_pending.html', context)


from django.utils import timezone
from datetime import datetime, date, timedelta
from django.db.models import Sum, F

@login_required
def mpesa_account_balance_history(request, account_id):
    """View balance history for a specific M-Pesa account"""
    account = get_object_or_404(MpesaAccount, id=account_id)
    
    history = []
    
    # ============================================
    # 1. Get manual adjustments (injections/withdrawals)
    # ============================================
    adjustments = account.adjustments.filter(is_approved=True).order_by('-created_at')
    
    for adj in adjustments:
        # Format the date
        adj_date = adj.created_at
        if timezone.is_naive(adj_date):
            adj_date = timezone.make_aware(adj_date)
        
        # Calculate the amount change (for display)
        if adj.adjustment_type == 'injection':
            amount_change = adj.amount
            change_type = 'positive'
            display_type = 'Manual Injection'
        else:
            amount_change = -adj.amount
            change_type = 'negative'
            display_type = 'Manual Withdrawal'
        
        history.append({
            'date': adj_date,
            'date_display': adj_date.strftime('%Y-%m-%d %H:%M:%S'),
            'type': display_type,
            'amount': adj.amount,
            'amount_change': amount_change,
            'change_type': change_type,
            'balance_after': adj.balance_after,
            'reference': adj.reference_number or '-',
            'reason': adj.reason,
            'approved': adj.is_approved,
            'source': 'adjustment',
        })
    
    # ============================================
    # 2. Get daily report closings with actual changes
    # ============================================
    daily_reports = DailyMpesaAccountReport.objects.filter(
        mpesa_account=account
    ).select_related('daily_report').order_by('-daily_report__report_date')
    
    # Get previous day's balance to calculate actual change
    previous_balance = None
    daily_reports_list = list(daily_reports)
    
    for i, dr in enumerate(daily_reports_list):
        report_date = dr.daily_report.report_date
        
        # Get the closing balance from this report
        current_balance = dr.closing_mpesa_float
        
        # Calculate the change from previous day
        if i < len(daily_reports_list) - 1:
            # Get next report (previous day) to calculate change
            next_report = daily_reports_list[i + 1]
            previous_balance = next_report.closing_mpesa_float
            amount_change = current_balance - previous_balance
        else:
            # This is the oldest report, can't calculate change
            # Get the balance from before this report (from opening balance or adjustments)
            amount_change = None
        
        # Convert date to timezone-aware datetime
        naive_datetime = datetime.combine(report_date, datetime.min.time())
        aware_datetime = timezone.make_aware(naive_datetime)
        
        history.append({
            'date': aware_datetime,
            'date_display': report_date.strftime('%Y-%m-%d'),
            'type': 'Daily Report',
            'amount': current_balance,
            'amount_change': amount_change,
            'change_type': 'neutral',
            'balance_after': current_balance,
            'reference': f"Report #{dr.daily_report.id}",
            'reason': f"Daily closing balance from {report_date}",
            'approved': True,
            'source': 'daily_report',
        })
    
    # ============================================
    # 3. Sort by date descending
    # ============================================
    history.sort(key=lambda x: x['date'], reverse=True)
    
    # ============================================
    # 4. Calculate running balance (if needed)
    # ============================================
    running_balance = account.current_balance
    for item in history:
        if item['source'] == 'adjustment' and item['approved']:
            # For adjustments, we already have balance_after
            pass
        elif item['source'] == 'daily_report':
            # For daily reports, balance_after is the closing balance
            pass
    
    # ============================================
    # 5. Calculate summary statistics
    # ============================================
    total_injections = adjustments.filter(
        adjustment_type='injection'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    total_withdrawals = adjustments.filter(
        adjustment_type='withdrawal'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # Calculate total sales from M-Pesa account
    total_sales = account.total_sale_amount
    
    context = {
        'account': account,
        'history': history[:50],  # Last 50 entries
        'total_injections': total_injections,
        'total_withdrawals': total_withdrawals,
        'total_sales': total_sales,
    }
    return render(request, 'shops/mpesa_balance_history.html', context)








# ==================== FINANCIAL DASHBOARD VIEWS ====================

from django.db.models import Sum, Count, Q, F, DecimalField, Avg
from django.db.models.functions import Coalesce, TruncMonth, TruncDate
from datetime import datetime, timedelta
from decimal import Decimal


@login_required
@user_passes_test(is_staff_or_admin)
def financial_dashboard(request):
    """Comprehensive financial dashboard - Shows effective balances (last report closing + injections)"""
    
    # Get filter parameters
    shop_id = request.GET.get('shop', 'all')
    date_range = request.GET.get('date_range', 'month')
    
    # Date range logic
    today = timezone.now().date()
    if date_range == 'today':
        start_date = today
        end_date = today
    elif date_range == 'week':
        start_date = today - timedelta(days=7)
        end_date = today
    elif date_range == 'month':
        start_date = today.replace(day=1)
        end_date = today
    elif date_range == 'quarter':
        start_date = today - timedelta(days=90)
        end_date = today
    elif date_range == 'year':
        start_date = today.replace(month=1, day=1)
        end_date = today
    else:
        start_date = today.replace(day=1)
        end_date = today
    
    # Base queryset for shops
    shops = ShopBranch.objects.filter(is_active=True)
    if shop_id != 'all':
        shops = shops.filter(id=shop_id)
    
    # ============================================
    # GET LAST REPORT CLOSING BALANCES
    # ============================================
    
    last_report_mpesa = Decimal('0')
    last_report_bank = Decimal('0')
    last_report_cash = Decimal('0')
    last_report_total = Decimal('0')
    
    for shop in shops:
        # Get the most recent report
        latest_report = DailyShopReport.objects.filter(shop=shop).order_by('-report_date').first()
        
        if latest_report:
            # Get M-Pesa closing balances from the latest report
            mpesa_reports = DailyMpesaAccountReport.objects.filter(daily_report=latest_report)
            for mr in mpesa_reports:
                last_report_mpesa += mr.closing_mpesa_float
            
            # Get Bank closing balances
            bank_closings = BankClosingBalance.objects.filter(daily_report=latest_report, is_active=True)
            for bc in bank_closings:
                last_report_bank += bc.closing_balance
            
            # Get Cash balance
            last_report_cash += latest_report.cash_balance or Decimal('0')
    
    last_report_total = last_report_mpesa + last_report_bank + last_report_cash
    
    # ============================================
    # GET ALL INJECTIONS (for all time - these should be added to balances)
    # ============================================
    
    # Get ALL injections (approved) - these represent money added to accounts
    all_injections = AccountTransaction.objects.filter(
        transaction_type='injection',
        is_approved=True
    )
    if shop_id != 'all':
        all_injections = all_injections.filter(
            Q(mpesa_account__shop_id=shop_id) |
            Q(bank_account__shop_id=shop_id) |
            Q(cash_account__shop_id=shop_id)
        )
    
    # Calculate injection totals BY ACCOUNT TYPE (ALL TIME)
    mpesa_injections_all = all_injections.filter(account_type='mpesa').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    bank_injections_all = all_injections.filter(account_type='bank').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    cash_injections_all = all_injections.filter(account_type='cash').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    total_injections_all = mpesa_injections_all + bank_injections_all + cash_injections_all
    
    # ============================================
    # EFFECTIVE BALANCES = Last report closing + ALL injections
    # ============================================
    
    effective_mpesa = last_report_mpesa + mpesa_injections_all
    effective_bank = last_report_bank + bank_injections_all
    effective_cash = last_report_cash + cash_injections_all
    effective_total = last_report_total + total_injections_all
    
    # ============================================
    # PERIOD INJECTIONS (for display only - within date range)
    # ============================================
    
    period_injections = AccountTransaction.objects.filter(
        transaction_type='injection',
        is_approved=True,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )
    if shop_id != 'all':
        period_injections = period_injections.filter(
            Q(mpesa_account__shop_id=shop_id) |
            Q(bank_account__shop_id=shop_id) |
            Q(cash_account__shop_id=shop_id)
        )
    
    period_injections_total = period_injections.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    period_injections_count = period_injections.count()
    
    # Period injection breakdown
    period_mpesa_inj = period_injections.filter(account_type='mpesa').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    period_bank_inj = period_injections.filter(account_type='bank').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    period_cash_inj = period_injections.filter(account_type='cash').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    # Injections by account for display (period only)
    injections_by_account = []
    
    mpesa_inj_group = period_injections.filter(account_type='mpesa').values(
        'mpesa_account__account_name',
        'mpesa_account__account_number'
    ).annotate(total=Sum('amount'), count=Count('id')).order_by('-total')
    
    for inj in mpesa_inj_group:
        injections_by_account.append({
            'type': 'M-Pesa',
            'name': inj['mpesa_account__account_name'],
            'number': inj['mpesa_account__account_number'],
            'total': inj['total'],
            'count': inj['count']
        })
    
    cash_inj_group = period_injections.filter(account_type='cash').values(
        'cash_account__account_name'
    ).annotate(total=Sum('amount'), count=Count('id')).order_by('-total')
    
    for inj in cash_inj_group:
        injections_by_account.append({
            'type': 'Cash',
            'name': inj['cash_account__account_name'] or 'Main Cash',
            'number': 'N/A',
            'total': inj['total'],
            'count': inj['count']
        })
    
    bank_inj_group = period_injections.filter(account_type='bank').values(
        'bank_account__bank_name',
        'bank_account__account_name'
    ).annotate(total=Sum('amount'), count=Count('id')).order_by('-total')
    
    for inj in bank_inj_group:
        injections_by_account.append({
            'type': 'Bank',
            'name': f"{inj['bank_account__bank_name']} - {inj['bank_account__account_name']}",
            'number': 'N/A',
            'total': inj['total'],
            'count': inj['count']
        })
    
    # ============================================
    # GET M-PESA ACCOUNTS WITH EFFECTIVE BALANCES
    # ============================================
    
    mpesa_accounts_with_balances = []
    mpesa_accounts = MpesaAccount.objects.filter(is_active=True, status='active')
    if shop_id != 'all':
        mpesa_accounts = mpesa_accounts.filter(shop_id=shop_id)
    
    for account in mpesa_accounts:
        latest_account_report = DailyMpesaAccountReport.objects.filter(
            mpesa_account=account
        ).order_by('-daily_report__report_date').first()
        
        if latest_account_report:
            closing_balance = latest_account_report.closing_mpesa_float
            report_date = latest_account_report.daily_report.report_date
        else:
            closing_balance = Decimal('0')
            report_date = None
        
        # Get ALL injections for this account
        account_injections = AccountTransaction.objects.filter(
            transaction_type='injection',
            is_approved=True,
            account_type='mpesa',
            mpesa_account=account
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        effective_balance = closing_balance + account_injections
        
        mpesa_accounts_with_balances.append({
            'id': account.id,
            'account_name': account.account_name,
            'account_number': account.account_number,
            'account_type': account.get_account_type_display(),
            'shop_name': account.shop.name,
            'closing_balance': closing_balance,
            'total_injections': account_injections,
            'effective_balance': effective_balance,
            'report_date': report_date,
        })
    
    # ============================================
    # GET BANK ACCOUNTS WITH EFFECTIVE BALANCES
    # ============================================
    
    bank_accounts_with_balances = []
    bank_accounts = BankAccount.objects.filter(is_active=True)
    if shop_id != 'all':
        bank_accounts = bank_accounts.filter(shop_id=shop_id)
    
    for account in bank_accounts:
        latest_bank_closing = BankClosingBalance.objects.filter(
            bank_account=account, is_active=True
        ).order_by('-daily_report__report_date').first()
        
        if latest_bank_closing:
            closing_balance = latest_bank_closing.closing_balance
            report_date = latest_bank_closing.daily_report.report_date
        else:
            closing_balance = Decimal('0')
            report_date = None
        
        # Get ALL injections for this account
        account_injections = AccountTransaction.objects.filter(
            transaction_type='injection',
            is_approved=True,
            account_type='bank',
            bank_account=account
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        effective_balance = closing_balance + account_injections
        
        bank_accounts_with_balances.append({
            'id': account.id,
            'bank_name': account.bank_name,
            'account_name': account.account_name,
            'account_number': account.account_number,
            'shop_name': account.shop.name,
            'closing_balance': closing_balance,
            'total_injections': account_injections,
            'effective_balance': effective_balance,
            'report_date': report_date,
        })
    
    # ============================================
    # EXPENSES SUMMARY (For information only)
    # ============================================
    
    expenses = ShopExpense.objects.filter(
        daily_report__report_date__gte=start_date,
        daily_report__report_date__lte=end_date
    )
    if shop_id != 'all':
        expenses = expenses.filter(daily_report__shop_id=shop_id)
    
    total_expenses_amount = expenses.aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']
    total_expenses_count = expenses.count()
    
    expense_by_category = []
    category_totals = expenses.values('expense_category').annotate(
        total=Coalesce(Sum('amount'), Decimal('0')),
        count=Count('id')
    ).order_by('-total')[:10]
    
    for cat in category_totals:
        if total_expenses_amount > 0:
            percentage = float(cat['total']) / float(total_expenses_amount) * 100
        else:
            percentage = 0
        expense_by_category.append({
            'expense_category': cat['expense_category'] or 'Uncategorized',
            'total': cat['total'],
            'count': cat['count'],
            'percentage': percentage
        })
    
    # ============================================
    # REVENUE SUMMARY (For information only)
    # ============================================
    
    reports_in_period = DailyShopReport.objects.filter(
        report_date__gte=start_date,
        report_date__lte=end_date
    )
    if shop_id != 'all':
        reports_in_period = reports_in_period.filter(shop_id=shop_id)
    
    total_revenue = reports_in_period.aggregate(total=Coalesce(Sum('total_mpesa_amount'), Decimal('0')))['total']
    total_transactions = reports_in_period.aggregate(total=Coalesce(Sum('total_mpesa_transactions'), 0))['total']
    
    net_profit = total_revenue - total_expenses_amount
    profit_margin = float(net_profit) / float(total_revenue) * 100 if total_revenue > 0 else 0
    total_inflow = total_revenue + period_injections_total
    
    # ============================================
    # CHART DATA
    # ============================================
    
    weekly_data_raw = []
    for i in range(7):
        date = today - timedelta(days=6-i)
        day_reports = DailyShopReport.objects.filter(report_date=date)
        day_expenses = ShopExpense.objects.filter(daily_report__report_date=date)
        day_injections = AccountTransaction.objects.filter(
            transaction_type='injection', is_approved=True, created_at__date=date
        )
        
        if shop_id != 'all':
            day_reports = day_reports.filter(shop_id=shop_id)
            day_expenses = day_expenses.filter(daily_report__shop_id=shop_id)
            day_injections = day_injections.filter(
                Q(mpesa_account__shop_id=shop_id) |
                Q(bank_account__shop_id=shop_id) |
                Q(cash_account__shop_id=shop_id)
            )
        
        weekly_data_raw.append({
            'date': date.strftime('%a'),
            'expenses': float(day_expenses.aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']),
            'sales': float(day_reports.aggregate(total=Coalesce(Sum('total_mpesa_amount'), Decimal('0')))['total']),
            'injections': float(day_injections.aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total'])
        })
    
    chart_labels = [item['date'] for item in weekly_data_raw]
    chart_sales = [item['sales'] for item in weekly_data_raw]
    chart_expenses = [item['expenses'] for item in weekly_data_raw]
    chart_injections = [item['injections'] for item in weekly_data_raw]
    
    expense_labels = [item['expense_category'] for item in expense_by_category[:5]]
    expense_values = [float(item['total']) for item in expense_by_category[:5]]
    
    account_breakdown = {
        'labels': ['M-Pesa', 'Bank', 'Cash'],
        'values': [float(effective_mpesa), float(effective_bank), float(effective_cash)],
        'colors': ['#11998e', '#667eea', '#f39c12']
    }
    
    # ============================================
    # MONTHLY TRENDS
    # ============================================
    
    monthly_trends = []
    for i in range(6):
        month_date = today.replace(day=1) - timedelta(days=30 * i)
        month_start = month_date.replace(day=1)
        if i == 0:
            month_end = today
        else:
            next_month = month_start + timedelta(days=32)
            month_end = next_month.replace(day=1) - timedelta(days=1)
        
        month_reports = DailyShopReport.objects.filter(
            report_date__gte=month_start,
            report_date__lte=month_end
        )
        month_expenses = ShopExpense.objects.filter(
            daily_report__report_date__gte=month_start,
            daily_report__report_date__lte=month_end
        )
        month_injections = AccountTransaction.objects.filter(
            transaction_type='injection', is_approved=True,
            created_at__date__gte=month_start, created_at__date__lte=month_end
        )
        
        if shop_id != 'all':
            month_reports = month_reports.filter(shop_id=shop_id)
            month_expenses = month_expenses.filter(daily_report__shop_id=shop_id)
            month_injections = month_injections.filter(
                Q(mpesa_account__shop_id=shop_id) |
                Q(bank_account__shop_id=shop_id) |
                Q(cash_account__shop_id=shop_id)
            )
        
        month_sales = month_reports.aggregate(total=Coalesce(Sum('total_mpesa_amount'), Decimal('0')))['total']
        month_expenses_total = month_expenses.aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']
        month_injections_total = month_injections.aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']
        month_net = month_sales - month_expenses_total
        month_margin = float(month_net) / float(month_sales) * 100 if month_sales > 0 else 0
        
        monthly_trends.insert(0, {
            'month': month_start.strftime('%B %Y'),
            'expenses': month_expenses_total,
            'sales': month_sales,
            'injections': month_injections_total,
            'net': month_net,
            'margin': month_margin
        })
    
    context = {
        # Effective Balances (Last Report Closing + ALL Injections)
        'total_liquidity': effective_total,
        'total_mpesa_balance': effective_mpesa,
        'total_bank_balance': effective_bank,
        'total_cash_balance': effective_cash,
        
        # Financial Metrics (For information only)
        'total_expenses': total_expenses_amount,
        'total_revenue': total_revenue,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        'period_injections_total': period_injections_total,
        'period_injections_count': period_injections_count,
        'total_inflow': total_inflow,
        
        # Period Injection Breakdown
        'mpesa_injections_total': period_mpesa_inj,
        'mpesa_injections_count': period_injections.filter(account_type='mpesa').count(),
        'bank_injections_total': period_bank_inj,
        'bank_injections_count': period_injections.filter(account_type='bank').count(),
        'cash_injections_total': period_cash_inj,
        'cash_injections_count': period_injections.filter(account_type='cash').count(),
        'injections_by_account': injections_by_account,
        
        # Account Lists with Effective Balances
        'mpesa_accounts': mpesa_accounts_with_balances,
        'bank_accounts': bank_accounts_with_balances,
        
        # Expense Data
        'expense_summary': {
            'total_expenses': total_expenses_amount,
            'total_transactions': total_expenses_count,
            'by_category': expense_by_category,
        },
        'top_expense_categories': expense_by_category[:5],
        
        # Revenue Data
        'total_transactions_count': total_transactions,
        
        # Chart Data
        'chart_labels': chart_labels,
        'chart_sales': chart_sales,
        'chart_expenses': chart_expenses,
        'chart_injections': chart_injections,
        'expense_labels': expense_labels,
        'expense_values': expense_values,
        'account_breakdown': account_breakdown,
        
        # Monthly Trends
        'monthly_trends': monthly_trends,
        
        # Filters
        'shops': ShopBranch.objects.filter(is_active=True),
        'selected_shop': shop_id,
        'date_range': date_range,
        'start_date': start_date,
        'end_date': end_date,
    }
    
    return render(request, 'shops/financial_dashboard.html', context)



@login_required
@user_passes_test(is_staff_or_admin)
def financial_summary_api(request):
    """API endpoint for financial summary data (for charts)"""
    shop_id = request.GET.get('shop', 'all')
    period = request.GET.get('period', 'month')
    
    today = timezone.now().date()
    if period == 'week':
        start_date = today - timedelta(days=7)
    elif period == 'month':
        start_date = today - timedelta(days=30)
    elif period == 'quarter':
        start_date = today - timedelta(days=90)
    elif period == 'year':
        start_date = today - timedelta(days=365)
    else:
        start_date = today - timedelta(days=30)
    
    # Get expenses
    expenses = ShopExpense.objects.filter(
        daily_report__report_date__gte=start_date,
        daily_report__report_date__lte=today
    )
    
    # Get sales
    sales = MpesaAccount.objects.filter(is_active=True)
    
    if shop_id != 'all':
        expenses = expenses.filter(daily_report__shop_id=shop_id)
        sales = sales.filter(shop_id=shop_id)
    
    # Daily breakdown
    daily_data = []
    for i in range(30):
        date = today - timedelta(days=29-i)
        daily_expenses = expenses.filter(daily_report__report_date=date).aggregate(
            total=Coalesce(Sum('amount'), Decimal('0'))
        )['total']
        
        daily_sales = sales.filter(
            daily_reports__daily_report__report_date=date
        ).aggregate(
            total=Coalesce(Sum('total_sale_amount'), Decimal('0'))
        )['total']
        
        daily_data.append({
            'date': date.strftime('%Y-%m-%d'),
            'expenses': float(daily_expenses),
            'sales': float(daily_sales),
            'net': float(daily_sales - daily_expenses)
        })
    
    return JsonResponse({
        'success': True,
        'data': daily_data,
        'summary': {
            'total_expenses': float(expenses.aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total']),
            'total_sales': float(sales.aggregate(total=Coalesce(Sum('total_sale_amount'), Decimal('0')))['total']),
        }
    })


@login_required
@user_passes_test(is_staff_or_admin)
def account_injections_report(request):
    """Show injections for all accounts (M-Pesa, Bank, Cash)"""
    
    # Get filter parameters
    shop_id = request.GET.get('shop', 'all')
    date_range = request.GET.get('date_range', 'month')
    
    today = timezone.now().date()
    if date_range == 'today':
        start_date = today
        end_date = today
    elif date_range == 'week':
        start_date = today - timedelta(days=7)
        end_date = today
    elif date_range == 'month':
        start_date = today.replace(day=1)
        end_date = today
    elif date_range == 'quarter':
        start_date = today - timedelta(days=90)
        end_date = today
    elif date_range == 'year':
        start_date = today.replace(month=1, day=1)
        end_date = today
    else:
        start_date = today.replace(day=1)
        end_date = today
    
    # Get all injections from AccountTransaction model
    injections = AccountTransaction.objects.filter(
        transaction_type='injection',
        is_approved=True,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )
    
    if shop_id != 'all':
        # Filter by shop for each account type
        mpesa_ids = MpesaAccount.objects.filter(shop_id=shop_id).values_list('id', flat=True)
        bank_ids = BankAccount.objects.filter(shop_id=shop_id).values_list('id', flat=True)
        cash_ids = CashAccount.objects.filter(shop_id=shop_id).values_list('id', flat=True)
        
        injections = injections.filter(
            Q(mpesa_account_id__in=mpesa_ids) |
            Q(bank_account_id__in=bank_ids) |
            Q(cash_account_id__in=cash_ids)
        )
    
    # Calculate totals
    total_injected = injections.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    total_injection_count = injections.count()
    
    # Calculate average (in Python, not template)
    average_injection = total_injected / total_injection_count if total_injection_count > 0 else Decimal('0')
    
    # Group injections by account
    injections_by_account = []
    
    # M-Pesa injections
    mpesa_injections = injections.filter(account_type='mpesa').values(
        'mpesa_account__shop__name',
        'mpesa_account__account_name',
        'mpesa_account__account_number',
        'mpesa_account__account_type'
    ).annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')
    
    for inj in mpesa_injections:
        # Get the current balance of this account
        account = MpesaAccount.objects.filter(
            account_name=inj['mpesa_account__account_name'],
            account_number=inj['mpesa_account__account_number']
        ).first()
        
        injections_by_account.append({
            'shop': inj['mpesa_account__shop__name'],
            'account_type': 'M-Pesa',
            'account_name': inj['mpesa_account__account_name'],
            'account_number': inj['mpesa_account__account_number'],
            'sub_type': inj['mpesa_account__account_type'],
            'total': inj['total'],
            'count': inj['count'],
            'current_balance': account.current_balance if account else Decimal('0')
        })
    
    # Bank injections
    bank_injections = injections.filter(account_type='bank').values(
        'bank_account__shop__name',
        'bank_account__bank_name',
        'bank_account__account_name',
        'bank_account__account_number'
    ).annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')
    
    for inj in bank_injections:
        account = BankAccount.objects.filter(
            bank_name=inj['bank_account__bank_name'],
            account_name=inj['bank_account__account_name'],
            account_number=inj['bank_account__account_number']
        ).first()
        
        injections_by_account.append({
            'shop': inj['bank_account__shop__name'],
            'account_type': 'Bank',
            'account_name': f"{inj['bank_account__bank_name']} - {inj['bank_account__account_name']}",
            'account_number': inj['bank_account__account_number'],
            'sub_type': inj['bank_account__bank_name'],
            'total': inj['total'],
            'count': inj['count'],
            'current_balance': account.current_balance if account else Decimal('0')
        })
    
    # Cash injections
    cash_injections = injections.filter(account_type='cash').values(
        'cash_account__shop__name',
        'cash_account__account_name'
    ).annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')
    
    for inj in cash_injections:
        account = CashAccount.objects.filter(
            account_name=inj['cash_account__account_name']
        ).first()
        
        injections_by_account.append({
            'shop': inj['cash_account__shop__name'],
            'account_type': 'Cash',
            'account_name': inj['cash_account__account_name'],
            'account_number': 'N/A',
            'sub_type': 'Physical Cash',
            'total': inj['total'],
            'count': inj['count'],
            'current_balance': account.current_balance if account else Decimal('0')
        })
    
    # Sort by total amount
    injections_by_account.sort(key=lambda x: x['total'], reverse=True)
    
    # Get individual transactions for detailed view
    individual_transactions = injections.select_related(
        'mpesa_account', 'bank_account', 'cash_account', 'created_by'
    ).order_by('-created_at')[:50]
    
    context = {
        'injections_by_account': injections_by_account,
        'individual_transactions': individual_transactions,
        'total_injected': total_injected,
        'total_injection_count': total_injection_count,
        'average_injection': average_injection,  # Added this
        'start_date': start_date,
        'end_date': end_date,
        'date_range': date_range,
        'shops': ShopBranch.objects.filter(is_active=True),
        'selected_shop': shop_id,
        'period_display': f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}",
    }
    
    return render(request, 'shops/account_injections_report.html', context)

# shops/views.py - Add this function

@login_required
@user_passes_test(is_staff_or_admin)
def create_account_injection(request):
    """Create a new account injection (add money to any account)"""
    
    if request.method == 'POST':
        form = AccountInjectionForm(request.POST, user=request.user)
        if form.is_valid():
            transaction = form.save(commit=False)
            transaction.transaction_type = 'injection'
            transaction.created_by = request.user
            
            # Auto-approve for superusers and managers
            if request.user.is_superuser or request.user.groups.filter(name='manager').exists():
                transaction.is_approved = True
                transaction.approved_by = request.user
                transaction.approved_at = timezone.now()
                messages.success(request, f'Injection of KES {transaction.amount:,.2f} completed and approved!')
            else:
                messages.info(request, 'Injection created and pending approval.')
            
            transaction.save()
            
            # Get account name for success message
            account_name = ""
            if transaction.mpesa_account:
                account_name = transaction.mpesa_account.account_name
            elif transaction.bank_account:
                account_name = f"{transaction.bank_account.bank_name} - {transaction.bank_account.account_name}"
            elif transaction.cash_account:
                account_name = transaction.cash_account.account_name
            
            messages.success(
                request, 
                f'Successfully injected KES {transaction.amount:,.2f} into {account_name}'
            )
            
            return redirect('shops:account_injections_report')
    else:
        form = AccountInjectionForm(user=request.user)
        
        # Pre-select account if passed in URL
        account_type = request.GET.get('account_type')
        account_id = request.GET.get('account_id')
        
        if account_type and account_id:
            if account_type == 'mpesa':
                form.fields['account_type'].initial = 'mpesa'
                form.fields['mpesa_account'].initial = account_id
            elif account_type == 'bank':
                form.fields['account_type'].initial = 'bank'
                form.fields['bank_account'].initial = account_id
            elif account_type == 'cash':
                form.fields['account_type'].initial = 'cash'
                form.fields['cash_account'].initial = account_id
    
    context = {
        'form': form,
        'title': 'Create Account Injection',
    }
    return render(request, 'shops/account_injection_form.html', context)


from django.db.models import Sum, Q, Count
from datetime import datetime, timedelta
from calendar import monthrange

@login_required
@user_passes_test(is_staff_or_admin)
def monthly_financial_report(request):
    """
    Monthly Financial Report showing:
    - Opening balance = Last report closing + All injections
    - Closing balance = Opening balance (if no new report) OR Opening - Today's expenses (if report exists)
    """
    
    # Get filter parameters
    period_type = request.GET.get('period', 'month')
    shop_id = request.GET.get('shop', 'all')
    custom_date = request.GET.get('date', '')
    
    today = timezone.now().date()
    
    # Set date range based on period type
    if custom_date:
        try:
            if period_type == 'day':
                start_date = datetime.strptime(custom_date, '%Y-%m-%d').date()
                end_date = start_date
            elif period_type == 'week':
                start_date = datetime.strptime(custom_date, '%Y-%m-%d').date()
                end_date = start_date + timedelta(days=6)
            elif period_type == 'month':
                start_date = datetime.strptime(custom_date, '%Y-%m').date().replace(day=1)
                last_day = monthrange(start_date.year, start_date.month)[1]
                end_date = start_date.replace(day=last_day)
            elif period_type == 'year':
                start_date = datetime.strptime(custom_date, '%Y').date().replace(month=1, day=1)
                end_date = start_date.replace(month=12, day=31)
            else:
                start_date = today.replace(day=1)
                end_date = today
        except ValueError:
            start_date = today.replace(day=1)
            end_date = today
    else:
        if period_type == 'day':
            start_date = today
            end_date = today
        elif period_type == 'week':
            start_date = today - timedelta(days=today.weekday())
            end_date = start_date + timedelta(days=6)
        elif period_type == 'month':
            start_date = today.replace(day=1)
            end_date = today
        elif period_type == 'year':
            start_date = today.replace(month=1, day=1)
            end_date = today
        else:
            start_date = today.replace(day=1)
            end_date = today
    
    # Get shops
    shops = ShopBranch.objects.filter(is_active=True)
    if shop_id != 'all':
        shops = shops.filter(id=shop_id)
    
    # ============================================
    # GET THE LAST REPORT CLOSING BALANCE
    # ============================================
    
    last_report_mpesa = Decimal('0')
    last_report_bank = Decimal('0')
    last_report_cash = Decimal('0')
    last_report_total = Decimal('0')
    last_report_date = None
    
    for shop in shops:
        # Get the most recent report
        last_report = DailyShopReport.objects.filter(
            shop=shop
        ).order_by('-report_date').first()
        
        if last_report:
            last_report_date = last_report.report_date
            
            # Get M-Pesa closing balances
            mpesa_reports = DailyMpesaAccountReport.objects.filter(daily_report=last_report)
            for mr in mpesa_reports:
                last_report_mpesa += mr.closing_mpesa_float
            
            # Get Bank closing balances
            bank_closings = BankClosingBalance.objects.filter(daily_report=last_report, is_active=True)
            for bc in bank_closings:
                last_report_bank += bc.closing_balance
            
            # Get Cash balance
            last_report_cash += last_report.cash_balance or Decimal('0')
    
    last_report_total = last_report_mpesa + last_report_bank + last_report_cash
    
    # ============================================
    # GET ALL INJECTIONS
    # ============================================
    
    all_injections = AccountTransaction.objects.filter(
        transaction_type='injection',
        is_approved=True
    )
    if shop_id != 'all':
        all_injections = all_injections.filter(
            Q(mpesa_account__shop_id=shop_id) |
            Q(bank_account__shop_id=shop_id) |
            Q(cash_account__shop_id=shop_id)
        )
    
    mpesa_injections = all_injections.filter(account_type='mpesa').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    bank_injections = all_injections.filter(account_type='bank').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    cash_injections = all_injections.filter(account_type='cash').aggregate(total=Sum('amount'))['total'] or Decimal('0')
    total_injections = mpesa_injections + bank_injections + cash_injections
    injection_count = all_injections.count()
    
    # ============================================
    # OPENING BALANCE = Last report closing + Injections
    # ============================================
    
    opening_balance_mpesa = last_report_mpesa + mpesa_injections
    opening_balance_bank = last_report_bank + bank_injections
    opening_balance_cash = last_report_cash + cash_injections
    opening_balance_total = last_report_total + total_injections
    
    # ============================================
    # CHECK IF THERE IS A REPORT FOR TODAY
    # ============================================
    
    today_report_exists = False
    for shop in shops:
        report_today = DailyShopReport.objects.filter(
            shop=shop,
            report_date=today
        ).exists()
        if report_today:
            today_report_exists = True
            break
    
    # ============================================
    # GET EXPENSES - ONLY FOR DATES THAT HAVE REPORTS
    # ============================================
    
    # Get all report dates in the period
    report_dates = DailyShopReport.objects.filter(
        report_date__gte=start_date,
        report_date__lte=end_date
    ).values_list('report_date', flat=True).distinct()
    
    # Only get expenses for dates that actually have reports
    expenses = ShopExpense.objects.filter(
        daily_report__report_date__in=report_dates
    )
    if shop_id != 'all':
        expenses = expenses.filter(daily_report__shop_id=shop_id)
    
    total_expenses = expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    expense_count = expenses.count()
    
    # ============================================
    # CLOSING BALANCE = Opening - Expenses (only if report exists for that date)
    # If no report for today, closing = opening
    # ============================================
    
    if today_report_exists:
        # There is a report for today, so deduct expenses
        closing_balance_mpesa = opening_balance_mpesa
        closing_balance_bank = opening_balance_bank
        closing_balance_cash = opening_balance_cash
        closing_balance_total = opening_balance_total - total_expenses
    else:
        # No report for today, closing equals opening
        closing_balance_mpesa = opening_balance_mpesa
        closing_balance_bank = opening_balance_bank
        closing_balance_cash = opening_balance_cash
        closing_balance_total = opening_balance_total
    
    # ============================================
    # COMMISSION (Revenue)
    # ============================================
    
    reports_in_period = DailyShopReport.objects.filter(
        report_date__gte=start_date,
        report_date__lte=end_date
    )
    if shop_id != 'all':
        reports_in_period = reports_in_period.filter(shop_id=shop_id)
    
    commission_received = reports_in_period.aggregate(
        total=Sum('total_mpesa_amount')
    )['total'] or Decimal('0')
    
    commission_transactions = reports_in_period.aggregate(
        total=Sum('total_mpesa_transactions')
    )['total'] or 0
    
    # ============================================
    # INJECTIONS DETAILS
    # ============================================
    
    injections_by_account = []
    
    mpesa_inj_group = all_injections.filter(account_type='mpesa').values(
        'mpesa_account__account_name',
        'mpesa_account__account_number'
    ).annotate(total=Sum('amount'), count=Count('id')).order_by('-total')
    
    for inj in mpesa_inj_group:
        injections_by_account.append({
            'type': 'M-Pesa',
            'name': inj['mpesa_account__account_name'],
            'number': inj['mpesa_account__account_number'],
            'total': inj['total'],
            'count': inj['count']
        })
    
    cash_inj_group = all_injections.filter(account_type='cash').values(
        'cash_account__account_name'
    ).annotate(total=Sum('amount'), count=Count('id')).order_by('-total')
    
    for inj in cash_inj_group:
        injections_by_account.append({
            'type': 'Cash',
            'name': inj['cash_account__account_name'] or 'Main Cash',
            'number': 'N/A',
            'total': inj['total'],
            'count': inj['count']
        })
    
    bank_inj_group = all_injections.filter(account_type='bank').values(
        'bank_account__bank_name',
        'bank_account__account_name'
    ).annotate(total=Sum('amount'), count=Count('id')).order_by('-total')
    
    for inj in bank_inj_group:
        injections_by_account.append({
            'type': 'Bank',
            'name': f"{inj['bank_account__bank_name']} - {inj['bank_account__account_name']}",
            'number': 'N/A',
            'total': inj['total'],
            'count': inj['count']
        })
    
    # ============================================
    # EXPENSES DETAILS (only for dates with reports)
    # ============================================
    
    expenses_by_category = expenses.values('expense_category').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')
    
    expenses_by_payment = expenses.values('payment_method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')
    
    recent_expenses = expenses.order_by('-created_at')[:10]
    
    # ============================================
    # CALCULATIONS
    # ============================================
    
    expected_closing = opening_balance_total - total_expenses if today_report_exists else opening_balance_total
    actual_closing = closing_balance_total
    variance = actual_closing - expected_closing
    net_change = closing_balance_total - opening_balance_total
    
    # ============================================
    # PERIOD SUMMARY
    # ============================================
    
    period_summary = {
        'start_date': start_date,
        'end_date': end_date,
        'period_type': period_type,
        'total_days': (end_date - start_date).days + 1,
        'total_reports': reports_in_period.count(),
        'finalized_reports': reports_in_period.filter(is_finalized=True).count(),
        'today_report_exists': today_report_exists,
    }
    
    if period_type == 'day':
        period_display = start_date.strftime('%B %d, %Y')
    elif period_type == 'week':
        period_display = f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"
    elif period_type == 'month':
        period_display = start_date.strftime('%B %Y')
    else:
        period_display = start_date.strftime('%Y')
    
    context = {
        'period_type': period_type,
        'period_display': period_display,
        'start_date': start_date,
        'end_date': end_date,
        'period_summary': period_summary,
        
        # Opening Balance
        'opening_balance_mpesa': opening_balance_mpesa,
        'opening_balance_bank': opening_balance_bank,
        'opening_balance_cash': opening_balance_cash,
        'opening_balance_total': opening_balance_total,
        
        # Closing Balance
        'closing_balance_mpesa': closing_balance_mpesa,
        'closing_balance_bank': closing_balance_bank,
        'closing_balance_cash': closing_balance_cash,
        'closing_balance_total': closing_balance_total,
        
        # Last Report Info
        'last_report_total': last_report_total,
        'last_report_date': last_report_date,
        
        # Commission
        'commission_received': commission_received,
        'commission_transactions': commission_transactions,
        
        # Injections
        'money_injected': total_injections,
        'injection_count': injection_count,
        'injections_by_account': injections_by_account,
        
        # Expenses
        'total_expenses': total_expenses,
        'expense_count': expense_count,
        'expenses_by_category': expenses_by_category,
        'expenses_by_payment': expenses_by_payment,
        'recent_expenses': recent_expenses,
        
        # Calculations
        'expected_closing': expected_closing,
        'actual_closing': actual_closing,
        'variance': variance,
        'net_change': net_change,
        'today_report_exists': today_report_exists,
        
        # Charts
        'chart_dates': ['Current'],
        'chart_commission': [float(commission_received)],
        'chart_expenses': [float(total_expenses) if today_report_exists else 0],
        'chart_injections': [float(total_injections)],
        'chart_closing': [float(closing_balance_total)],
        
        # Filters
        'shops': ShopBranch.objects.filter(is_active=True),
        'selected_shop': shop_id,
        'selected_date': custom_date,
    }
    
    return render(request, 'shops/monthly_financial_report.html', context)