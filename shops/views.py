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
    CashAccount, CashDailyBalance, ShopExpense, DailyShopReport, 
    DailyMpesaAccountReport, ShopConfiguration, BankClosingBalance, DynamicChoice
)
from .forms import (
    ShopBranchForm, BankAccountForm, DailyShopReportForm, CashAccountForm,
    MpesaAccountForm, MpesaDailyBalanceForm, BankDailyBalanceForm, 
    CashDailyBalanceForm, ShopExpenseForm, DynamicChoiceForm, ShopConfigurationForm
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
                    report.total_expenses = 0
                    report.total_closing_balance = 0
                    
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
                    # PROCESS EXPENSES
                    # ============================================
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
                    # UPDATE REPORT TOTALS
                    # ============================================
                    report.total_expenses = expense_total
                    report.save(update_fields=['total_expenses'])
                    
                    # Calculate M-Pesa total
                    mpesa_total = DailyMpesaAccountReport.objects.filter(daily_report=report).aggregate(
                        total=Sum('closing_mpesa_float')
                    )['total'] or 0
                    
                    # Calculate Bank total
                    bank_total = BankClosingBalance.objects.filter(daily_report=report).aggregate(
                        total=Sum('closing_balance')
                    )['total'] or 0
                    
                    # Calculate total closing balance (M-Pesa + Cash + Bank)
                    report.total_closing_balance = float(mpesa_total) + float(report.cash_balance) + float(bank_total)
                    report.save(update_fields=['total_closing_balance'])
                    
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
        'total_cash': 0,  # Default cash value for new report
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
    # FIXED: Calculate bank total for each report using BankClosingBalance
    # Use 'daily_report' as the foreign key field name
    # ============================================
    reports_list = []
    for report in reports:
        # Calculate bank total from related bank closing balances
        bank_total = BankClosingBalance.objects.filter(
            daily_report=report,  # Changed from 'report' to 'daily_report'
            is_active=True
        ).aggregate(total=Sum('closing_balance'))['total'] or 0
        report.bank_total = bank_total
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



    """Revert a finalized report back to draft"""
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
    
    return redirect('shops:report_detail', report_id=report.id)



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
    """List all M-Pesa accounts"""
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
    
    # Calculate statistics
    total_accounts = accounts.count()
    active_accounts = accounts.filter(status='active', is_active=True).count()
    total_balance = accounts.aggregate(total=Sum('current_balance'))['total'] or 0
    till_count = accounts.filter(account_type='till', status='active').count()
    paybill_count = accounts.filter(account_type='paybill', status='active').count()
    
    # Pagination
    paginator = Paginator(accounts, 20)
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
        'total_balance': total_balance,
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