# finance/views.py
from django.core.cache import cache
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, Value, DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone
from decimal import Decimal
from django.core.paginator import Paginator
from django.http import JsonResponse
from .models import (
    Salary, 
    FinancialTransaction, 
    FinancialSummary,
    AccountTransaction,  
    CashAccount,   
    BankAccount,       
    CreditAccount        
)
from credit.models import SellerCommission, CreditTransaction, CreditTransactionLog
from sales.models import Sale, SaleItem
from django.contrib.auth.models import User
import calendar
from datetime import datetime, date, timedelta
from django.db import transaction
from django.db import models
import logging
import time
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
import json
from .models import MpesaTransaction, MpesaCallbackLog
from sales.models import Sale 
from django.views.decorators.http import require_http_methods
from .kopokopo_service import stk_push_request, clean_phone_number, check_pending_transaction



logger = logging.getLogger(__name__)


# ============================================
# FINANCE DASHBOARD
# ============================================

@login_required
def finance_dashboard(request):
    """Finance dashboard overview - ALL cards respect date filters"""
    from decimal import Decimal
    from django.db.models import Sum, Q
    from datetime import datetime, timedelta
    from .models import AccountTransaction
    from credit.models import CreditTransaction, SellerCommission, CompanyPayment
    
    # ============================================
    # GET DATE RANGE FROM REQUEST
    # ============================================
    date_range = request.GET.get('range', 'month')  # day, week, month, year, custom
    date_from_str = request.GET.get('date_from')
    date_to_str = request.GET.get('date_to')
    
    today = timezone.now().date()
    
    if date_range == 'today':
        date_from = today
        date_to = today
    elif date_range == 'week':
        date_from = today - timedelta(days=7)
        date_to = today
    elif date_range == 'month':
        date_from = today - timedelta(days=30)
        date_to = today
    elif date_range == 'year':
        date_from = today - timedelta(days=365)
        date_to = today
    elif date_from_str and date_to_str:
        date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
        date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
        date_range = 'custom'
    else:
        # Default to current month
        date_from = today.replace(day=1)
        date_to = today
        date_range = 'month'
    
    date_from_aware = timezone.make_aware(datetime.combine(date_from, datetime.min.time()))
    date_to_aware = timezone.make_aware(datetime.combine(date_to, datetime.max.time()))
    
    # ============================================
    # FILTERED INCOME (based on date range)
    # ============================================
    
    # Sales Income
    filtered_sales_income = Sale.objects.filter(
        sale_date__range=[date_from_aware, date_to_aware],
        is_reversed=False
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    # Credit Income (paid_date)
    filtered_credit_income = CreditTransaction.objects.filter(
        paid_date__range=[date_from_aware, date_to_aware],
        payment_status='paid'
    ).aggregate(total=Sum('ceiling_price'))['total'] or Decimal('0.00')
    
    # Account Income
    filtered_account_income = AccountTransaction.objects.filter(
        transaction_date__range=[date_from_aware, date_to_aware],
        transaction_type='income'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    filtered_total_income = filtered_sales_income + filtered_credit_income + filtered_account_income
    
    # ============================================
    # FILTERED EXPENSES (based on date range)
    # ============================================
    
    # Salary Expenses (paid_date)
    filtered_salary_expenses = Salary.objects.filter(
        paid_date__range=[date_from_aware, date_to_aware],
        status='paid'
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    # Commission Expenses (paid_date)
    filtered_commission_expenses = SellerCommission.objects.filter(
        status='paid',
        paid_date__range=[date_from_aware, date_to_aware]
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    # Account Expenses
    filtered_account_expenses = AccountTransaction.objects.filter(
        transaction_date__range=[date_from_aware, date_to_aware],
        transaction_type='expense'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    filtered_total_expenses = filtered_salary_expenses + filtered_commission_expenses + filtered_account_expenses
    
    # ============================================
    # FILTERED PROFIT
    # ============================================
    
    # Sales Profit from filtered sales
    filtered_sales = Sale.objects.filter(
        sale_date__range=[date_from_aware, date_to_aware],
        is_reversed=False
    )
    
    filtered_sales_profit = Decimal('0.00')
    for sale in filtered_sales:
        for item in sale.items.all():
            if item.product and item.product.buying_price:
                profit = (item.unit_price - item.product.buying_price) * item.quantity
                filtered_sales_profit += profit
    
    # Credit payments within date range
    filtered_credit_payments = CompanyPayment.objects.filter(
        payment_date__range=[date_from, date_to]
    )
    filtered_credit_profit = filtered_credit_payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    filtered_total_profit = filtered_sales_profit + filtered_credit_profit
    
    # ============================================
    # FILTERED NET PROFIT & MARGIN
    # ============================================
    filtered_net_profit = filtered_total_income - filtered_total_expenses
    filtered_profit_margin = (filtered_net_profit / filtered_total_income * 100) if filtered_total_income > 0 else 0
    
    # ============================================
    # STATIC PERIOD CALCULATIONS (for comparison charts)
    # ============================================
    
    current_month = today.month
    current_year = today.year
    
    # Calculate previous month
    if current_month == 1:
        previous_month = 12
        previous_year = current_year - 1
    else:
        previous_month = current_month - 1
        previous_year = current_year
    
    # Month start and end dates
    month_start = datetime(current_year, current_month, 1)
    if current_month == 12:
        month_end = datetime(current_year + 1, 1, 1) - timedelta(seconds=1)
    else:
        month_end = datetime(current_year, current_month + 1, 1) - timedelta(seconds=1)
    
    month_start_aware = timezone.make_aware(month_start)
    month_end_aware = timezone.make_aware(month_end)
    
    # Year start and end dates
    year_start = datetime(current_year, 1, 1)
    year_end = datetime(current_year + 1, 1, 1) - timedelta(seconds=1)
    year_start_aware = timezone.make_aware(year_start)
    year_end_aware = timezone.make_aware(year_end)
    
    # Week start
    week_start = today - timedelta(days=7)
    week_start_aware = timezone.make_aware(datetime.combine(week_start, datetime.min.time()))
    
    # Today's range
    today_start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    today_end = timezone.make_aware(datetime.combine(today, datetime.max.time()))
    
    # ============================================
    # MONTHLY INCOME (Static - for charts)
    # ============================================
    monthly_sales_income = Sale.objects.filter(
        sale_date__range=[month_start_aware, month_end_aware],
        is_reversed=False
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    monthly_credit_income = CreditTransaction.objects.filter(
        paid_date__range=[month_start_aware, month_end_aware],
        payment_status='paid'
    ).aggregate(total=Sum('ceiling_price'))['total'] or Decimal('0.00')
    
    monthly_account_income = AccountTransaction.objects.filter(
        transaction_date__range=[month_start_aware, month_end_aware],
        transaction_type='income'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    monthly_total_income = monthly_sales_income + monthly_credit_income + monthly_account_income
    
    # ============================================
    # MONTHLY EXPENSES (Static)
    # ============================================
    monthly_salary_expenses = Salary.objects.filter(
        month=previous_month,
        year=previous_year,
        status='paid'
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    monthly_commission_expenses = SellerCommission.objects.filter(
        status='paid',
        paid_date__range=[month_start_aware, month_end_aware]
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    monthly_account_expenses = AccountTransaction.objects.filter(
        transaction_date__range=[month_start_aware, month_end_aware],
        transaction_type='expense'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    monthly_total_expenses = monthly_salary_expenses + monthly_commission_expenses + monthly_account_expenses
    
    # ============================================
    # NET PROFIT (Static)
    # ============================================
    monthly_net_profit = monthly_total_income - monthly_total_expenses
    monthly_profit_margin = (monthly_net_profit / monthly_total_income * 100) if monthly_total_income > 0 else 0
    
    # ============================================
    # CHART DATA (Last 30 days)
    # ============================================
    thirty_days_ago = today - timedelta(days=30)
    thirty_days_ago_aware = timezone.make_aware(datetime.combine(thirty_days_ago, datetime.min.time()))
    
    chart_labels = []
    income_data = []
    expense_data = []
    profit_data = []
    
    for i in range(30):
        day = thirty_days_ago + timedelta(days=i)
        day_start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
        day_end = timezone.make_aware(datetime.combine(day, datetime.max.time()))
        
        day_sales = Sale.objects.filter(
            sale_date__range=[day_start, day_end],
            is_reversed=False
        ).aggregate(total=Sum('total_amount'))['total'] or 0
        
        day_credit = CreditTransaction.objects.filter(
            paid_date__range=[day_start, day_end],
            payment_status='paid'
        ).aggregate(total=Sum('ceiling_price'))['total'] or 0
        
        day_account_income = AccountTransaction.objects.filter(
            transaction_date__range=[day_start, day_end],
            transaction_type='income'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        daily_income = day_sales + day_credit + day_account_income
        
        day_commissions = SellerCommission.objects.filter(
            paid_date__range=[day_start, day_end],
            status='paid'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        day_account_expenses = AccountTransaction.objects.filter(
            transaction_date__range=[day_start, day_end],
            transaction_type='expense'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        day_salaries = Salary.objects.filter(
            paid_date__range=[day_start, day_end],
            status='paid'
        ).aggregate(total=Sum('total_amount'))['total'] or 0
        
        daily_expense = day_salaries + day_commissions + day_account_expenses
        
        chart_labels.append(day.strftime('%d %b'))
        income_data.append(float(daily_income))
        expense_data.append(float(daily_expense))
        profit_data.append(float(daily_income - daily_expense))
    
    # ============================================
    # SALARY SUMMARY
    # ============================================
    previous_month_salaries = Salary.objects.filter(
        month=previous_month,
        year=previous_year
    ).select_related('staff')
    
    total_base_salary = previous_month_salaries.aggregate(total=Sum('base_salary'))['total'] or 0
    total_bonus = previous_month_salaries.aggregate(total=Sum('bonus'))['total'] or 0
    total_deductions = previous_month_salaries.aggregate(total=Sum('deductions'))['total'] or 0
    total_salary_amount = previous_month_salaries.aggregate(total=Sum('total_amount'))['total'] or 0
    
    salaries_pending = previous_month_salaries.filter(status='pending').aggregate(total=Sum('total_amount'))['total'] or 0
    salaries_approved = previous_month_salaries.filter(status='approved').aggregate(total=Sum('total_amount'))['total'] or 0
    salaries_paid = previous_month_salaries.filter(status='paid').aggregate(total=Sum('total_amount'))['total'] or 0
    salaries_paid_count = previous_month_salaries.filter(status='paid').count()
    previous_month_salaries_paid = previous_month_salaries.filter(status='paid')
    previous_month_salaries_count = previous_month_salaries.count()
    
    current_month_salaries = Salary.objects.filter(
        month=current_month,
        year=current_year
    ).select_related('staff')
    
    # ============================================
    # COMMISSION SUMMARY
    # ============================================
    commissions_pending = SellerCommission.objects.filter(
        status='pending'
    ).aggregate(total=Sum('amount'))['total'] or 0
    commissions_pending_count = SellerCommission.objects.filter(status='pending').count()
    
    commissions_approved = SellerCommission.objects.filter(
        status='approved'
    ).aggregate(total=Sum('amount'))['total'] or 0
    commissions_approved_count = SellerCommission.objects.filter(status='approved').count()
    
    commissions_paid = SellerCommission.objects.filter(
        status='paid',
        paid_date__range=[month_start_aware, month_end_aware]
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    sellers_with_pending = SellerCommission.objects.filter(
        status='pending'
    ).values('seller').distinct().count()
    
    pending_commissions = SellerCommission.objects.filter(
        status='pending'
    ).select_related('seller', 'transaction')[:10]
    
    total_pending_commissions = commissions_pending
    
    # ============================================
    # EXPENSE DISTRIBUTION
    # ============================================
    salary_expenses_total = monthly_salary_expenses
    commission_expenses_total = monthly_commission_expenses
    operational_expenses = monthly_account_expenses
    
    # ============================================
    # RECENT TRANSACTIONS
    # ============================================
    recent_transactions = FinancialTransaction.objects.select_related('created_by').order_by('-transaction_date')[:10]
    
    # ============================================
    # CONTEXT
    # ============================================
    context = {
        # FILTERED SUMMARY (for main cards)
        'filtered_total_income': filtered_total_income,
        'filtered_total_expenses': filtered_total_expenses,
        'filtered_net_profit': filtered_net_profit,
        'filtered_profit_margin': filtered_profit_margin,
        'filtered_total_profit': filtered_total_profit,
        'filtered_date_from': date_from,
        'filtered_date_to': date_to,
        'selected_range': date_range,
        
        # Static Monthly Summary (for reference/charts)
        'total_income': monthly_total_income,
        'total_expenses': monthly_total_expenses,
        'net_profit': monthly_net_profit,
        'profit_margin': monthly_profit_margin,
        
        # Chart data
        'chart_labels': chart_labels,
        'income_data': income_data,
        'expense_data': expense_data,
        'profit_data': profit_data,
        
        # Salaries
        'salaries_pending': salaries_pending,
        'salaries_approved': salaries_approved,
        'salaries_paid': salaries_paid,
        'salaries_paid_count': salaries_paid_count,
        'previous_month_salaries': previous_month_salaries,
        'previous_month_salaries_paid': previous_month_salaries_paid,
        'previous_month_salaries_count': previous_month_salaries_count,
        'current_month_salaries': current_month_salaries,
        'total_base_salary': total_base_salary,
        'total_bonus': total_bonus,
        'total_deductions': total_deductions,
        'total_salary_amount': total_salary_amount,
        
        # Commissions
        'commissions_pending': commissions_pending,
        'commissions_pending_count': commissions_pending_count,
        'commissions_approved': commissions_approved,
        'commissions_approved_count': commissions_approved_count,
        'commissions_paid': commissions_paid,
        'sellers_with_pending': sellers_with_pending,
        'pending_commissions': pending_commissions,
        'total_pending_commissions': total_pending_commissions,
        
        # Expense distribution
        'salary_expenses': salary_expenses_total,
        'commission_expenses': commission_expenses_total,
        'operational_expenses': operational_expenses,
        
        # Recent transactions
        'recent_transactions': recent_transactions,
        
        # Date info
        'current_month': calendar.month_name[current_month],
        'current_year': current_year,
        'previous_month': calendar.month_name[previous_month],
        'previous_year': previous_year,
        'today': today,
    }
    
    return render(request, 'finance/dashboard.html', context)












    

# ============================================
# SALARY MANAGEMENT VIEWS
# ============================================

@login_required
def salary_list(request):
    """List all staff salaries with filtering"""
    salaries = Salary.objects.select_related('staff', 'created_by', 'paid_by').all()
    
    # Filters
    status = request.GET.get('status')
    if status:
        salaries = salaries.filter(status=status)
    
    staff_id = request.GET.get('staff')
    if staff_id:
        salaries = salaries.filter(staff_id=staff_id)
    
    month = request.GET.get('month')
    if month:
        salaries = salaries.filter(month=month)
    
    year = request.GET.get('year')
    if year:
        salaries = salaries.filter(year=year)
    
    # Calculate totals for summary cards
    total_pending = salaries.filter(status='pending').aggregate(total=Sum('total_amount'))['total'] or 0
    total_approved = salaries.filter(status='approved').aggregate(total=Sum('total_amount'))['total'] or 0
    total_paid = salaries.filter(status='paid').aggregate(total=Sum('total_amount'))['total'] or 0
    total_records = salaries.count()
    
    # Calculate totals for table footer
    total_base_salary = salaries.aggregate(total=Sum('base_salary'))['total'] or 0
    total_bonus = salaries.aggregate(total=Sum('bonus'))['total'] or 0
    total_deductions = salaries.aggregate(total=Sum('deductions'))['total'] or 0
    total_amount = salaries.aggregate(total=Sum('total_amount'))['total'] or 0
    
    # Pagination
    paginator = Paginator(salaries, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get staff list for filter
    staff_list = User.objects.filter(is_active=True)
    
    # Get unique years for filter
    years = Salary.objects.dates('created_at', 'year').values_list('year', flat=True).distinct()
    if not years:
        years = range(2020, timezone.now().year + 1)
    
    context = {
        'salaries': page_obj,
        'staff_list': staff_list,
        'current_filters': {
            'status': status,
            'staff': staff_id,
            'month': month,
            'year': year,
        },
        'months': Salary.MONTH_CHOICES,
        'years': range(2020, timezone.now().year + 1),
        
        # Summary card totals
        'total_pending': total_pending,
        'total_approved': total_approved,
        'total_paid': total_paid,
        'total_records': total_records,
        
        # Table footer totals
        'total_base_salary': total_base_salary,
        'total_bonus': total_bonus,
        'total_deductions': total_deductions,
        'total_amount': total_amount,
    }
    
    return render(request, 'finance/salary_list.html', context)






@login_required
def salary_create(request):
    """Create staff salary - Prevents multiple requests per month"""
    
    if request.method == 'POST':
        try:
            staff_id = request.POST.get('staff')
            month = int(request.POST.get('month'))
            year = int(request.POST.get('year'))
            base_salary = Decimal(request.POST.get('base_salary', '0'))
            
            # Handle bonus - check if bonus checkbox was checked
            has_bonus = request.POST.get('has_bonus') == 'on'
            bonus = Decimal(request.POST.get('bonus_amount', '0')) if has_bonus else Decimal('0')
            bonus_reason = request.POST.get('bonus_reason', '') if has_bonus else ''
            
            # Handle deductions - check if deductions checkbox was checked
            has_deductions = request.POST.get('has_deductions') == 'on'
            deductions = Decimal(request.POST.get('deduction_amount', '0')) if has_deductions else Decimal('0')
            deduction_type = request.POST.get('deduction_type', '') if has_deductions else ''
            deduction_reason = request.POST.get('deduction_reason', '') if has_deductions else ''
            
            notes = request.POST.get('notes', '')
            
            # Combine notes with bonus and deduction info
            full_notes = notes
            if bonus_reason:
                full_notes += f"\nBonus: {bonus_reason}"
            if deduction_reason:
                full_notes += f"\nDeduction ({deduction_type}): {deduction_reason}"
            
            staff = User.objects.get(id=staff_id)
            
            # VALIDATION 1: Check if salary already exists for this month
            existing_salary = Salary.objects.filter(
                staff=staff, 
                month=month, 
                year=year
            ).first()
            
            if existing_salary:
                messages.error(
                    request, 
                    f'❌ Salary for {staff.get_full_name() or staff.username} in '
                    f'{calendar.month_name[month]} {year} already exists!\n'
                    f'Status: {existing_salary.get_status_display()} | '
                    f'Amount: KSH {existing_salary.total_amount}'
                )
                return redirect('finance:salary_create')
            
            # VALIDATION 2: Check if previous month's salary is paid
            if month == 1:
                prev_month = 12
                prev_year = year - 1
            else:
                prev_month = month - 1
                prev_year = year
            
            previous_salary = Salary.objects.filter(
                staff=staff,
                month=prev_month,
                year=prev_year
            ).first()
            
            if previous_salary and previous_salary.status != 'paid':
                messages.error(
                    request, 
                    f'❌ Cannot create salary for {calendar.month_name[month]} {year}!\n'
                    f'Previous month\'s salary ({calendar.month_name[prev_month]} {prev_year}) '
                    f'is still {previous_salary.get_status_display()}.\n'
                    f'Please complete the previous month\'s salary first.'
                )
                return redirect('finance:salary_create')
            
            # VALIDATION 3: Check if next month's salary already exists
            if month == 12:
                next_month = 1
                next_year = year + 1
            else:
                next_month = month + 1
                next_year = year
            
            next_salary = Salary.objects.filter(
                staff=staff,
                month=next_month,
                year=next_year
            ).first()
            
            if next_salary:
                messages.error(
                    request,
                    f'❌ Cannot create salary for {calendar.month_name[month]} {year}!\n'
                    f'{calendar.month_name[next_month]} {next_year} salary already exists.\n'
                    f'Please create salaries in order.'
                )
                return redirect('finance:salary_create')
            
            # VALIDATION 4: Check if salary is within current date range
            current_date = timezone.now().date()
            salary_date = date(year, month, 1)
            months_ahead = (salary_date.year - current_date.year) * 12 + (salary_date.month - current_date.month)
            
            # Allow previous month within first 5 days
            is_start_of_month = current_date.day <= 5
            is_previous_month = months_ahead == -1
            
            if months_ahead > 1:
                messages.error(
                    request,
                    f'❌ Cannot create salary for {calendar.month_name[month]} {year}!\n'
                    f'You can only create salary for current month or next month.\n'
                    f'Please wait until closer to the payment date.'
                )
                return redirect('finance:salary_create')
            
            if is_previous_month and not is_start_of_month:
                messages.error(
                    request,
                    f'❌ Cannot create salary for {calendar.month_name[month]} {year}!\n'
                    f'Previous month salary can only be created within the first 5 days of the current month.'
                )
                return redirect('finance:salary_create')
            
            # Create salary with all fields
            salary = Salary.objects.create(
                staff=staff,
                month=month,
                year=year,
                base_salary=base_salary,
                bonus=bonus,
                deductions=deductions,
                notes=full_notes.strip(),
                created_by=request.user,
                status='pending'
            )
            
            # Create success message with details
            message_parts = [f'✅ Salary created for {staff.get_full_name() or staff.username} - {calendar.month_name[month]} {year}']
            message_parts.append(f'Amount: KSH {salary.total_amount} | Status: Pending Approval')
            
            if bonus > 0:
                message_parts.append(f'Bonus: KSH {bonus} - {bonus_reason}')
            if deductions > 0:
                message_parts.append(f'Deduction: KSH {deductions} - {deduction_reason}')
            
            messages.success(request, '\n'.join(message_parts))
            return redirect('finance:salary_list')
            
        except User.DoesNotExist:
            messages.error(request, 'Staff member not found')
            return redirect('finance:salary_create')
        except Exception as e:
            messages.error(request, f'Error creating salary: {str(e)}')
            return redirect('finance:salary_create')
    
    # GET request - show form
    staff_list = User.objects.filter(is_active=True)
    current_date = timezone.now().date()
    current_year = current_date.year
    current_month = current_date.month
    years = range(current_year - 2, current_year + 2)
    
    # Calculate previous month info
    previous_month = current_month - 1 if current_month > 1 else 12
    previous_year = current_year if current_month > 1 else current_year - 1
    previous_month_name = calendar.month_name[previous_month]
    
    staff_status = {}
    for staff in staff_list:
        # Check current month salary
        existing_this_month = Salary.objects.filter(
            staff=staff,
            month=current_month,
            year=current_year
        ).first()
        
        # Check previous month salary
        previous_salary = Salary.objects.filter(
            staff=staff,
            month=previous_month,
            year=previous_year
        ).first()
        
        # Check if previous month's salary is paid
        previous_paid = previous_salary.status == 'paid' if previous_salary else True
        
        # Determine if previous month can be created (only in first 5 days)
        can_create_previous = current_date.day <= 5
        
        staff_status[staff.id] = {
            'has_this_month': existing_this_month is not None,
            'this_month_status': existing_this_month.status if existing_this_month else None,
            'previous_paid': previous_paid,
            'can_create_current': (not existing_this_month) and previous_paid,
            'can_create_previous': can_create_previous,
            'can_create_next': existing_this_month and existing_this_month.status in ['approved', 'paid']
        }
    
    context = {
        'staff_list': staff_list,
        'staff_status': staff_status,
        'months': Salary.MONTH_CHOICES,
        'current_month': current_month,
        'current_year': current_year,
        'years': years,
        'next_month': current_month + 1 if current_month < 12 else 1,
        'next_year': current_year if current_month < 12 else current_year + 1,
        'previous_month': previous_month,
        'previous_year': previous_year,
        'previous_month_name': previous_month_name,
        'is_start_of_month': current_date.day <= 5,
        'current_day': current_date.day,
    }
    
    return render(request, 'finance/salary_create.html', context)



    


@login_required
def salary_detail(request, pk):
    """View salary details"""
    salary = get_object_or_404(Salary.objects.select_related('staff', 'created_by', 'paid_by'), pk=pk)
    
    context = {
        'salary': salary,
    }
    return render(request, 'finance/salary_detail.html', context)


@login_required
def salary_receipt(request, pk):
    """View/print salary receipt"""
    salary = get_object_or_404(Salary.objects.select_related('staff', 'created_by', 'paid_by'), pk=pk)
    
    if salary.status != 'paid':
        messages.warning(request, 'This salary has not been paid yet.')
        return redirect('finance:salary_detail', pk=pk)
    
    context = {
        'salary': salary,
        'receipt_number': f"SLR-{salary.id}-{salary.year}{salary.month:02d}",
        'company_name': 'FieldMax Suppliers Limited',
        'company_address': 'Nairobi, Kenya',
        'company_phone': '+254 722 558 544',
        'company_email': 'fieldmaxsuppliers@gmail.com',
    }
    return render(request, 'finance/salary_receipt.html', context)


@login_required
def salary_approve(request, pk):
    """Approve salary"""
    salary = get_object_or_404(Salary, pk=pk)
    
    if salary.status != 'pending':
        messages.error(request, f'This salary cannot be approved. Current status: {salary.get_status_display()}')
        return redirect('finance:salary_list')
    
    if request.method == 'POST':
        try:
            notes = request.POST.get('notes', '')
            
            salary.status = 'approved'
            salary.approved_by = request.user
            salary.approved_at = timezone.now()
            if notes:
                salary.notes = notes
            salary.save()
            
            messages.success(request, f'Salary approved for {salary.staff.get_full_name() or salary.staff.username}')
            return redirect('finance:salary_approve_list')
            
        except Exception as e:
            messages.error(request, f'Error approving salary: {str(e)}')
            return redirect('finance:salary_approve', pk=pk)
    
    context = {
        'salary': salary,
        'staff_name': salary.staff.get_full_name() or salary.staff.username,
        'period': f"{salary.get_month_display()} {salary.year}",
        'total_amount': salary.total_amount,
    }
    
    return render(request, 'finance/salary_approve.html', context)


@login_required
def salary_approve_list(request):
    """List all salaries pending approval"""
    salaries = Salary.objects.filter(
        status='pending'
    ).select_related('staff').order_by('-year', '-month')
    
    staff_id = request.GET.get('staff')
    if staff_id:
        salaries = salaries.filter(staff_id=staff_id)
    
    month = request.GET.get('month')
    if month:
        salaries = salaries.filter(month=month)
    
    year = request.GET.get('year')
    if year:
        salaries = salaries.filter(year=year)
    
    paginator = Paginator(salaries, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    total_amount = salaries.aggregate(total=Sum('total_amount'))['total'] or 0
    pending_count = salaries.count()
    
    staff_list = User.objects.filter(salaries__status='pending').distinct()
    
    context = {
        'salaries': page_obj,
        'staff_list': staff_list,
        'months': Salary.MONTH_CHOICES,
        'years': range(2020, timezone.now().year + 1),
        'total_amount': total_amount,
        'pending_count': pending_count,
        'current_filters': {
            'staff': staff_id,
            'month': month,
            'year': year,
        },
    }
    
    return render(request, 'finance/salary_approve_list.html', context)


@login_required
def salary_pay(request, pk):
    """Pay salary"""
    salary = get_object_or_404(Salary, pk=pk)
    
    if salary.status != 'approved':
        messages.error(request, 'This salary must be approved before payment.')
        return redirect('finance:salary_list')
    
    if request.method == 'POST':
        try:
            payment_reference = request.POST.get('payment_reference', '')
            payment_method = request.POST.get('payment_method')
            notes = request.POST.get('notes', '')
            
            salary.status = 'paid'
            salary.paid_date = timezone.now()
            salary.paid_by = request.user
            salary.payment_reference = payment_reference
            if notes:
                salary.notes = notes
            salary.save()
            
            FinancialTransaction.objects.create(
                transaction_type='salary',
                category='staff',
                amount=salary.total_amount,
                description=f"Salary payment - {salary.staff.username} - {salary.get_month_display()} {salary.year}",
                salary=salary,
                payment_method=payment_method,
                payment_reference=payment_reference,
                recipient_name=salary.staff.get_full_name() or salary.staff.username,
                created_by=request.user
            )
            
            messages.success(request, f'Salary paid to {salary.staff.get_full_name() or salary.staff.username} - KSH {salary.total_amount}')
            return redirect('finance:salary_list')
            
        except Exception as e:
            messages.error(request, f'Error paying salary: {str(e)}')
            return redirect('finance:salary_pay', pk=pk)
    
    context = {
        'salary': salary,
        'staff_name': salary.staff.get_full_name() or salary.staff.username,
        'period': f"{salary.get_month_display()} {salary.year}",
        'total_amount': salary.total_amount,
    }
    
    return render(request, 'finance/salary_pay.html', context)


@login_required
def salary_pay_list(request):
    """List all salaries approved and ready for payment"""
    salaries = Salary.objects.filter(
        status='approved'
    ).select_related('staff', 'created_by').order_by('-year', '-month')
    
    staff_id = request.GET.get('staff')
    if staff_id:
        salaries = salaries.filter(staff_id=staff_id)
    
    month = request.GET.get('month')
    if month:
        salaries = salaries.filter(month=month)
    
    year = request.GET.get('year')
    if year:
        salaries = salaries.filter(year=year)
    
    paginator = Paginator(salaries, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    staff_list = User.objects.filter(salaries__status='approved').distinct()
    total_amount = salaries.aggregate(total=Sum('total_amount'))['total'] or 0
    
    context = {
        'salaries': page_obj,
        'staff_list': staff_list,
        'months': Salary.MONTH_CHOICES,
        'years': range(2020, timezone.now().year + 1),
        'total_amount': total_amount,
        'approved_count': salaries.count(),
        'current_filters': {
            'staff': staff_id,
            'month': month,
            'year': year,
        },
    }
    
    return render(request, 'finance/salary_pay_list.html', context)


@login_required
def salary_history(request):
    """View all salary history with filters"""
    salaries = Salary.objects.select_related('staff', 'created_by', 'paid_by').all()
    
    status = request.GET.get('status')
    if status:
        salaries = salaries.filter(status=status)
    
    staff_id = request.GET.get('staff')
    if staff_id:
        salaries = salaries.filter(staff_id=staff_id)
    
    month = request.GET.get('month')
    if month:
        salaries = salaries.filter(month=month)
    
    year = request.GET.get('year')
    if year:
        salaries = salaries.filter(year=year)
    
    paginator = Paginator(salaries, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    staff_list = User.objects.filter(salaries__isnull=False).distinct()
    
    total_base_salary = salaries.aggregate(total=Sum('base_salary'))['total'] or 0
    total_bonus = salaries.aggregate(total=Sum('bonus'))['total'] or 0
    total_deductions = salaries.aggregate(total=Sum('deductions'))['total'] or 0
    total_amount = salaries.aggregate(total=Sum('total_amount'))['total'] or 0
    
    context = {
        'salaries': page_obj,
        'staff_list': staff_list,
        'months': Salary.MONTH_CHOICES,
        'years': range(2020, timezone.now().year + 1),
        'current_filters': {
            'status': status,
            'staff': staff_id,
            'month': month,
            'year': year,
        },
        'total_base_salary': total_base_salary,
        'total_bonus': total_bonus,
        'total_deductions': total_deductions,
        'total_amount': total_amount,
    }
    
    return render(request, 'finance/salary_history.html', context)



# ============================================
# COMMISSION MANAGEMENT VIEWS
# ============================================

@login_required
def commission_request_list(request):
    """
    Request Commissions page - Show transactions where commission is not set yet.
    """
    from credit.models import CreditTransaction, SellerCommission
    from django.db.models import Q
    
    # Show transactions where commission_status is not_set
    transactions_needing_commission = CreditTransaction.objects.filter(
        Q(commission_status='not_set') | 
        Q(commission_status__isnull=True) | 
        Q(commission_status='')
    ).select_related(
        'dealer', 'product', 'customer', 'credit_company'
    ).order_by('-transaction_date')
    
    # Create missing SellerCommission records
    for trans in transactions_needing_commission:
        commission_exists = SellerCommission.objects.filter(transaction=trans).exists()
        if not commission_exists:
            SellerCommission.objects.create(
                seller=trans.dealer,
                transaction=trans,
                amount=0,
                status='pending',
                notes="Auto-created - awaiting commission amount"
            )
    
    context = {
        'transactions_needing_commission': transactions_needing_commission,
        'total_pending': transactions_needing_commission.count(),
    }
    
    return render(request, 'finance/commission_request_list.html', context)


@login_required
def commission_transaction_search(request):
    """Search for transaction by SKU or Transaction ID"""
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
        
        can_request = transaction.commission_status == 'not_set'
        
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
                    'can_request': can_request,
                }
            }
        }
        
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def commission_request_submit(request, pk):
    """Submit commission request for a transaction (not_set -> requested)"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})
    
    transaction = get_object_or_404(CreditTransaction, pk=pk)
    
    if transaction.commission_status != 'not_set':
        return JsonResponse({
            'success': False, 
            'error': f'Commission already {transaction.get_commission_status_display()}'
        })
    
    try:
        commission_amount = Decimal(request.POST.get('commission_amount', '0'))
        notes = request.POST.get('notes', '')
        
        if commission_amount <= 0:
            return JsonResponse({'success': False, 'error': 'Amount must be greater than 0'})
        
        if commission_amount > transaction.ceiling_price:
            return JsonResponse({'success': False, 'error': 'Amount cannot exceed total price'})
        
        # Update transaction
        transaction.commission_amount = commission_amount
        transaction.commission_status = 'requested'
        transaction.commission_notes = notes
        transaction.save()
        
        # Create or update commission record
        SellerCommission.objects.update_or_create(
            transaction=transaction,
            defaults={
                'seller': transaction.dealer,
                'amount': commission_amount,
                'status': 'pending',
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
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def commission_list(request):
    """List all commissions with filtering"""
    commissions = SellerCommission.objects.filter(
        amount__gt=0
    ).select_related(
        'seller', 'transaction', 'paid_by',
        'transaction__customer', 'transaction__product'
    ).order_by('-created_at')
    
    # Apply filters
    status = request.GET.get('status')
    if status:
        commissions = commissions.filter(status=status)
    
    seller_id = request.GET.get('seller')
    if seller_id:
        commissions = commissions.filter(seller_id=seller_id)
    
    date_from = request.GET.get('date_from')
    if date_from:
        try:
            date_from_aware = timezone.make_aware(datetime.strptime(date_from, '%Y-%m-%d'))
            commissions = commissions.filter(created_at__date__gte=date_from_aware)
        except:
            pass
    
    date_to = request.GET.get('date_to')
    if date_to:
        try:
            date_to_aware = timezone.make_aware(datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
            commissions = commissions.filter(created_at__lt=date_to_aware)
        except:
            pass
    
    paginator = Paginator(commissions, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    sellers = User.objects.filter(commissions_earned__amount__gt=0).distinct()
    
    totals = {
        'all': commissions.aggregate(total=Sum('amount'))['total'] or 0,
        'pending': commissions.filter(status='pending').aggregate(total=Sum('amount'))['total'] or 0,
        'approved': commissions.filter(status='approved').aggregate(total=Sum('amount'))['total'] or 0,
        'paid': commissions.filter(status='paid').aggregate(total=Sum('amount'))['total'] or 0,
        'cancelled': commissions.filter(status='cancelled').aggregate(total=Sum('amount'))['total'] or 0,
    }
    
    counts = {
        'all': commissions.count(),
        'pending': commissions.filter(status='pending').count(),
        'approved': commissions.filter(status='approved').count(),
        'paid': commissions.filter(status='paid').count(),
        'cancelled': commissions.filter(status='cancelled').count(),
    }
    
    status_choices = [
        ('', 'All Statuses'),
        ('pending', 'Pending Approval'),
        ('approved', 'Approved (Ready for Payment)'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled/Rejected'),
    ]
    
    context = {
        'commissions': page_obj,
        'sellers': sellers,
        'totals': totals,
        'counts': counts,
        'status_choices': status_choices,
        'current_filters': {
            'status': status,
            'seller': seller_id,
            'date_from': date_from,
            'date_to': date_to,
        },
    }
    
    return render(request, 'finance/commission_list.html', context)


@login_required
def commission_approve_list(request):
    """List pending commissions awaiting approval (status='pending')"""
    commissions = SellerCommission.objects.filter(
        status='pending',
        amount__gt=0
    ).select_related(
        'seller', 'transaction',
        'transaction__customer', 'transaction__product'
    ).order_by('-created_at')
    
    # Apply filters
    seller_id = request.GET.get('seller')
    if seller_id:
        commissions = commissions.filter(seller_id=seller_id)
    
    date_from = request.GET.get('date_from')
    if date_from:
        try:
            date_from_aware = timezone.make_aware(datetime.strptime(date_from, '%Y-%m-%d'))
            commissions = commissions.filter(created_at__date__gte=date_from_aware)
        except:
            pass
    
    date_to = request.GET.get('date_to')
    if date_to:
        try:
            date_to_aware = timezone.make_aware(datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
            commissions = commissions.filter(created_at__lt=date_to_aware)
        except:
            pass
    
    paginator = Paginator(commissions, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    sellers = User.objects.filter(
        commissions_earned__status='pending',
        commissions_earned__amount__gt=0
    ).distinct()
    
    total_pending = commissions.aggregate(total=Sum('amount'))['total'] or 0
    
    context = {
        'commissions': page_obj,
        'sellers': sellers,
        'total_pending': total_pending,
        'pending_count': commissions.count(),
        'current_filters': {
            'seller': seller_id,
            'date_from': date_from,
            'date_to': date_to,
        },
    }
    
    return render(request, 'finance/commission_approve_list.html', context)


@login_required
def commission_pay_list(request):
    """List approved commissions ready for payment (status='approved')"""
    commissions = SellerCommission.objects.filter(
        status='approved'
    ).select_related(
        'seller', 'transaction',
        'transaction__customer', 'transaction__product'
    ).order_by('-approved_at')
    
    # Apply filters
    seller_id = request.GET.get('seller')
    if seller_id:
        commissions = commissions.filter(seller_id=seller_id)
    
    date_from = request.GET.get('date_from')
    if date_from:
        try:
            date_from_aware = timezone.make_aware(datetime.strptime(date_from, '%Y-%m-%d'))
            commissions = commissions.filter(approved_at__date__gte=date_from_aware)
        except:
            pass
    
    date_to = request.GET.get('date_to')
    if date_to:
        try:
            date_to_aware = timezone.make_aware(datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
            commissions = commissions.filter(approved_at__lt=date_to_aware)
        except:
            pass
    
    paginator = Paginator(commissions, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    sellers = User.objects.filter(commissions_earned__status='approved').distinct()
    total_approved = commissions.aggregate(total=Sum('amount'))['total'] or 0
    
    context = {
        'commissions': page_obj,
        'sellers': sellers,
        'total_approved': total_approved,
        'approved_count': commissions.count(),
        'current_filters': {
            'seller': seller_id,
            'date_from': date_from,
            'date_to': date_to,
        },
    }
    
    return render(request, 'finance/commission_pay_list.html', context)


@login_required
def commission_history(request):
    """View commission payment history (status='paid')"""
    commissions = SellerCommission.objects.filter(
        status='paid'
    ).select_related('seller', 'transaction', 'paid_by').order_by('-paid_date')
    
    seller_id = request.GET.get('seller')
    if seller_id:
        commissions = commissions.filter(seller_id=seller_id)
    
    date_from = request.GET.get('date_from')
    if date_from:
        commissions = commissions.filter(paid_date__date__gte=date_from)
    
    date_to = request.GET.get('date_to')
    if date_to:
        commissions = commissions.filter(paid_date__date__lte=date_to)
    
    paginator = Paginator(commissions, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    total_paid = commissions.aggregate(total=Sum('amount'))['total'] or 0
    sellers = User.objects.filter(commissions_earned__isnull=False).distinct()
    
    context = {
        'commissions': page_obj,
        'total_paid': total_paid,
        'sellers': sellers,
        'current_filters': {
            'seller': seller_id,
            'date_from': date_from,
            'date_to': date_to,
        },
    }
    
    return render(request, 'finance/commission_history.html', context)


@login_required
def commission_detail(request, pk):
    """View commission details"""
    commission = get_object_or_404(
        SellerCommission.objects.select_related(
            'seller', 'transaction', 'paid_by',
            'transaction__customer', 'transaction__product', 
            'transaction__credit_company'
        ),
        pk=pk
    )
    
    context = {
        'commission': commission,
    }
    
    return render(request, 'finance/commission_detail.html', context)


@login_required
def commission_approve_page(request, pk):
    """Approve a pending commission (status='pending' -> 'approved')"""
    commission = get_object_or_404(SellerCommission, pk=pk)
    
    if commission.status != 'pending':
        messages.error(request, f'Only pending commissions can be approved. Current status: {commission.get_status_display()}')
        return redirect('finance:commission_approve_list')
    
    if request.method == 'POST':
        try:
            notes = request.POST.get('notes', '')
            
            # Update commission to approved
            commission.status = 'approved'
            commission.approved_by = request.user
            commission.approved_at = timezone.now()
            if notes:
                commission.notes = f"{commission.notes}\nApproval notes: {notes}" if commission.notes else f"Approval notes: {notes}"
            commission.save()
            
            # Update transaction
            transaction = commission.transaction
            transaction.commission_status = 'approved'
            transaction.commission_notes = f"Approved by {request.user.username}: {notes}" if notes else f"Approved by {request.user.username}"
            transaction.save()
            
            # Create log
            CreditTransactionLog.objects.create(
                transaction=transaction,
                action='commission_approved',
                performed_by=request.user,
                notes=f"Commission of KES {commission.amount} approved"
            )
            
            messages.success(request, f'Commission #{commission.id} approved successfully! It is now ready for payment.')
            return redirect('finance:commission_approve_list')
            
        except Exception as e:
            messages.error(request, f'Error approving commission: {str(e)}')
            return redirect('finance:commission_approve_page', pk=pk)
    
    context = {
        'commission': commission,
    }
    return render(request, 'finance/commission_approve.html', context)


@login_required
def commission_pay_page(request, pk):
    """Pay an approved commission (status='approved' -> 'paid')"""
    commission = get_object_or_404(SellerCommission, pk=pk)
    
    if commission.status != 'approved':
        messages.error(request, f'Only approved commissions can be paid. Current status: {commission.get_status_display()}')
        return redirect('finance:commission_pay_list')
    
    if request.method == 'POST':
        try:
            payment_method = request.POST.get('payment_method')
            payment_reference = request.POST.get('payment_reference', '')
            notes = request.POST.get('notes', '')
            
            if payment_method not in ['cash', 'bank', 'mpesa']:
                messages.error(request, 'Invalid payment method')
                return redirect('finance:commission_pay_page', pk=pk)
            
            # Update commission to paid
            commission.status = 'paid'
            commission.paid_by = request.user
            commission.paid_date = timezone.now()
            commission.payment_reference = payment_reference
            commission.payment_method = payment_method
            if notes:
                commission.notes = f"{commission.notes}\nPayment notes: {notes}" if commission.notes else f"Payment notes: {notes}"
            commission.save()
            
            # Update transaction
            transaction = commission.transaction
            transaction.commission_status = 'paid'
            transaction.commission_paid_date = timezone.now()
            transaction.commission_paid_by = request.user
            transaction.payment_reference = payment_reference
            transaction.save()
            
            # Create financial transaction
            FinancialTransaction.objects.create(
                transaction_type='expense',
                category='commission',
                amount=commission.amount,
                description=f"Commission payment to {commission.seller.get_full_name() or commission.seller.username}",
                payment_method=payment_method,
                payment_reference=payment_reference,
                recipient_name=commission.seller.get_full_name() or commission.seller.username,
                created_by=request.user,
                notes=f"Commission for transaction {transaction.transaction_id}. {notes}"
            )
            
            # Update account balance
            if payment_method == 'cash':
                cash_account, _ = CashAccount.objects.get_or_create(id=1)
                cash_account.update_balance(commission.amount, 'expense', request.user)
            else:
                bank_account, _ = BankAccount.objects.get_or_create(id=1)
                bank_account.update_balance(commission.amount, 'expense', request.user)
            
            # Create log
            CreditTransactionLog.objects.create(
                transaction=transaction,
                action='commission_paid',
                performed_by=request.user,
                notes=f"Commission of KES {commission.amount} paid. Ref: {payment_reference}"
            )
            
            messages.success(request, f'Commission #{commission.id} paid successfully!')
            return redirect('finance:commission_pay_list')
            
        except Exception as e:
            messages.error(request, f'Error paying commission: {str(e)}')
            return redirect('finance:commission_pay_page', pk=pk)
    
    context = {
        'commission': commission,
    }
    return render(request, 'finance/commission_pay.html', context)


@login_required
def commission_reject_page(request, pk):
    """Reject a pending commission (status='pending' -> 'cancelled')"""
    commission = get_object_or_404(SellerCommission, pk=pk)
    
    if commission.status != 'pending':
        messages.error(request, f'Only pending commissions can be rejected. Current status: {commission.get_status_display()}')
        return redirect('finance:commission_approve_list')
    
    if request.method == 'POST':
        try:
            rejection_reason = request.POST.get('rejection_reason', '')
            notes = request.POST.get('notes', '')
            
            if not rejection_reason:
                messages.error(request, 'Please provide a rejection reason')
                return redirect('finance:commission_reject_page', pk=pk)
            
            # Update commission to cancelled
            commission.status = 'cancelled'
            commission.notes = f"Rejected: {rejection_reason}\n{notes}" if notes else f"Rejected: {rejection_reason}"
            commission.save()
            
            # Update transaction
            transaction = commission.transaction
            transaction.commission_status = 'cancelled'
            transaction.commission_notes = f"Rejected: {rejection_reason}"
            transaction.save()
            
            # Create log
            CreditTransactionLog.objects.create(
                transaction=transaction,
                action='commission_cancelled',
                performed_by=request.user,
                notes=f"Commission rejected. Reason: {rejection_reason}"
            )
            
            messages.success(request, f'Commission #{commission.id} rejected successfully!')
            return redirect('finance:commission_approve_list')
            
        except Exception as e:
            messages.error(request, f'Error rejecting commission: {str(e)}')
            return redirect('finance:commission_reject_page', pk=pk)
    
    context = {
        'commission': commission,
    }
    return render(request, 'finance/commission_reject.html', context)




@login_required
def commission_approve_seller(request, seller_id):
    """Legacy: Approve all pending commissions for a seller"""
    seller = get_object_or_404(User, id=seller_id)
    pending_commissions = SellerCommission.objects.filter(
        seller=seller,
        status='pending'
    )
    
    if request.method == 'POST':
        notes = request.POST.get('notes', '')
        total_amount = Decimal('0.00')
        
        for commission in pending_commissions:
            commission.status = 'approved'
            commission.approved_by = request.user
            commission.approved_at = timezone.now()
            commission.notes = f"Approved: {notes}" if notes else "Approved"
            commission.save()
            total_amount += commission.amount
        
        messages.success(request, f'Approved {pending_commissions.count()} commissions for {seller.username} - Total KSH {total_amount}')
        return redirect('finance:commission_approve_list')
    
    total_amount = sum(c.amount for c in pending_commissions)
    
    context = {
        'seller': seller,
        'pending_commissions': pending_commissions,
        'total_amount': total_amount,
        'count': pending_commissions.count(),
    }
    
    return render(request, 'finance/commission_approve_seller.html', context)


@login_required
def commission_pay_seller(request, seller_id):
    """Legacy: Pay all approved commissions for a specific seller"""
    seller = get_object_or_404(User, id=seller_id)
    approved_commissions = SellerCommission.objects.filter(
        seller=seller,
        status='approved'
    )
    
    if request.method == 'POST':
        payment_reference = request.POST.get('payment_reference', '')
        payment_method = request.POST.get('payment_method')
        notes = request.POST.get('notes', '')
        
        total_amount = Decimal('0.00')
        paid_commissions = []
        
        for commission in approved_commissions:
            commission.status = 'paid'
            commission.paid_by = request.user
            commission.paid_date = timezone.now()
            commission.payment_reference = payment_reference
            commission.payment_method = payment_method
            commission.save()
            total_amount += commission.amount
            paid_commissions.append(commission)
        
        FinancialTransaction.objects.create(
            transaction_type='commission',
            category='commission',
            amount=total_amount,
            description=f"Commission payment - {seller.username} - {len(paid_commissions)} transactions",
            payment_method=payment_method,
            payment_reference=payment_reference,
            recipient_name=seller.get_full_name() or seller.username,
            created_by=request.user,
            notes=f"Paid commissions for {len(paid_commissions)} transactions. {notes}"
        )
        
        messages.success(request, f'Commission paid to {seller.username} - KSH {total_amount}')
        return redirect('finance:commission_pay_list')
    
    total_amount = sum(c.amount for c in approved_commissions)
    
    context = {
        'seller': seller,
        'approved_commissions': approved_commissions,
        'total_amount': total_amount,
        'count': approved_commissions.count(),
    }
    
    return render(request, 'finance/commission_pay_seller.html', context)


@login_required
def commission_summary(request):
    """Summary of commissions by seller"""
    sellers = User.objects.filter(commissions_earned__isnull=False).distinct()
    
    seller_summaries = []
    total_all_commissions = 0
    total_paid = 0
    total_pending = 0
    
    for seller in sellers:
        commissions = SellerCommission.objects.filter(seller=seller)
        
        pending_amount = commissions.filter(status='pending').aggregate(
            total=Coalesce(Sum('amount'), Value(0, output_field=DecimalField()))
        )['total']
        
        approved_amount = commissions.filter(status='approved').aggregate(
            total=Coalesce(Sum('amount'), Value(0, output_field=DecimalField()))
        )['total']
        
        paid_amount = commissions.filter(status='paid').aggregate(
            total=Coalesce(Sum('amount'), Value(0, output_field=DecimalField()))
        )['total']
        
        rejected_amount = commissions.filter(status='cancelled').aggregate(
            total=Coalesce(Sum('amount'), Value(0, output_field=DecimalField()))
        )['total']
        
        total_commission = commissions.aggregate(
            total=Coalesce(Sum('amount'), Value(0, output_field=DecimalField()))
        )['total']
        
        total_all_commissions += total_commission
        total_paid += paid_amount
        total_pending += (pending_amount + approved_amount)
        
        seller_summaries.append({
            'seller': seller,
            'pending_amount': pending_amount,
            'approved_amount': approved_amount,
            'paid_amount': paid_amount,
            'rejected_amount': rejected_amount,
            'total_commission': total_commission,
            'transaction_count': commissions.count(),
            'pending_count': commissions.filter(status='pending').count(),
            'approved_count': commissions.filter(status='approved').count(),
            'paid_count': commissions.filter(status='paid').count(),
            'rejected_count': commissions.filter(status='cancelled').count(),
        })
    
    seller_summaries.sort(key=lambda x: x['total_commission'], reverse=True)
    
    context = {
        'seller_summaries': seller_summaries,
        'total_sellers': len(seller_summaries),
        'total_all_commissions': total_all_commissions,
        'total_paid': total_paid,
        'total_pending': total_pending,
    }
    
    return render(request, 'finance/commission_summary.html', context)


@login_required
def commission_export(request):
    """Export commissions to CSV"""
    import csv
    from django.http import HttpResponse
    
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'success': False, 'error': 'Permission denied'})
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="commissions_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    
    writer.writerow([
        'Date', 'Transaction ID', 'Seller Name', 'Seller Username',
        'Customer Name', 'Product Name', 'Product SKU', 'Sale Amount',
        'Commission Amount', 'Status', 'Approved By', 'Paid By',
        'Paid Date', 'Payment Reference', 'Notes'
    ])
    
    commissions = SellerCommission.objects.select_related(
        'seller', 'transaction', 'paid_by', 'approved_by',
        'transaction__customer', 'transaction__product'
    ).order_by('-created_at')
    
    seller_id = request.GET.get('seller')
    if seller_id:
        commissions = commissions.filter(seller_id=seller_id)
    
    status = request.GET.get('status')
    if status:
        commissions = commissions.filter(status=status)
    
    date_from = request.GET.get('date_from')
    if date_from:
        date_from_aware = timezone.make_aware(datetime.strptime(date_from, '%Y-%m-%d'))
        commissions = commissions.filter(created_at__date__gte=date_from_aware)
    
    date_to = request.GET.get('date_to')
    if date_to:
        date_to_aware = timezone.make_aware(datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
        commissions = commissions.filter(created_at__lt=date_to_aware)
    
    for commission in commissions:
        writer.writerow([
            commission.created_at.strftime('%Y-%m-%d %H:%M'),
            commission.transaction.transaction_id,
            commission.seller.get_full_name() or commission.seller.username,
            commission.seller.username,
            commission.transaction.customer.full_name,
            commission.transaction.product.name,
            commission.transaction.product.product_code,
            f'{commission.transaction.ceiling_price:.2f}',
            f'{commission.amount:.2f}',
            commission.get_status_display(),
            commission.approved_by.get_full_name() if commission.approved_by else '',
            commission.paid_by.get_full_name() if commission.paid_by else '',
            commission.paid_date.strftime('%Y-%m-%d %H:%M') if commission.paid_date else '',
            commission.payment_reference or '',
            commission.notes or ''
        ])
    
    return response


# ============================================
# FINANCIAL TRANSACTIONS VIEW - FIXED
# ============================================
@login_required
def financial_transactions(request):
    """List all financial transactions including salary, commission, and account transactions"""
    from decimal import Decimal
    from django.core.paginator import Paginator
    from datetime import datetime, timedelta
    from django.utils import timezone
    
    def to_date(dt):
        """Convert datetime or date to date object"""
        if hasattr(dt, 'date'):
            return dt.date()
        return dt
    
    # ============================================
    # GET DATE FILTERS FROM REQUEST (for profit calculation)
    # ============================================
    date_from_str = request.GET.get('date_from')
    date_to_str = request.GET.get('date_to')
    
    date_from = None
    date_to = None
    if date_from_str:
        try:
            date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
        except:
            pass
    if date_to_str:
        try:
            date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
        except:
            pass
    
    date_from_aware = timezone.make_aware(datetime.combine(date_from, datetime.min.time())) if date_from else None
    date_to_aware = timezone.make_aware(datetime.combine(date_to, datetime.max.time())) if date_to else None
    
    transactions = []
    
    # ============================================
    # SALARY TRANSACTIONS (Expenses)
    # ============================================
    salaries = Salary.objects.filter(status='paid').select_related('staff', 'paid_by').all()
    for salary in salaries:
        trans_date = salary.paid_date or salary.created_at
        transactions.append({
            'id': f'salary_{salary.id}',
            'transaction_date': trans_date,
            'sort_date': to_date(trans_date),
            'source': 'salary',
            'transaction_type': 'expense',
            'description': f"Salary payment - {salary.staff.get_full_name() or salary.staff.username} - {salary.get_month_display()} {salary.year}",
            'amount': salary.total_amount,
            'reference': salary.payment_reference or f"SAL-{salary.id}",
            'notes': salary.notes,
            'created_by': salary.paid_by or salary.created_by,
        })
    
    # ============================================
    # COMMISSION TRANSACTIONS (Expenses)
    # ============================================
    commissions = SellerCommission.objects.filter(status='paid').select_related('seller', 'paid_by')
    for commission in commissions:
        trans_date = commission.paid_date or commission.created_at
        transactions.append({
            'id': f'commission_{commission.id}',
            'transaction_date': trans_date,
            'sort_date': to_date(trans_date),
            'source': 'commission',
            'transaction_type': 'expense',
            'description': f"Commission payment - {commission.seller.get_full_name() or commission.seller.username} - {commission.transaction.transaction_id}",
            'amount': commission.amount,
            'reference': f"COMM-{commission.id}",
            'notes': commission.notes,
            'created_by': commission.paid_by,
        })
    
    # ============================================
    # ACCOUNT TRANSACTIONS (Manual entries)
    # ============================================
    account_transactions = AccountTransaction.objects.select_related('created_by').all()
    for acc_trans in account_transactions:
        transactions.append({
            'id': f'account_{acc_trans.id}',
            'transaction_date': acc_trans.transaction_date,
            'sort_date': to_date(acc_trans.transaction_date),
            'source': f"{acc_trans.account_type}_account",
            'transaction_type': acc_trans.transaction_type,
            'description': acc_trans.description,
            'amount': acc_trans.amount,
            'reference': acc_trans.reference or f"ACC-{acc_trans.id}",
            'notes': acc_trans.notes,
            'created_by': acc_trans.created_by,
        })
    
    # ============================================
    # SALES INCOME (Direct sales)
    # ============================================
    sales = Sale.objects.filter(is_reversed=False).select_related('seller')
    for sale in sales:
        transactions.append({
            'id': f'sale_{sale.sale_id}',
            'transaction_date': sale.sale_date,
            'sort_date': to_date(sale.sale_date),
            'source': 'sales',
            'transaction_type': 'income',
            'description': f"Sale {sale.sale_id} - {sale.buyer_name or 'Walk-in Customer'}",
            'amount': sale.total_amount,
            'reference': sale.sale_id,
            'notes': f"Items: {sale.items.count()} | Paid via: {sale.payment_method}",
            'created_by': sale.seller,
        })
    
    # ============================================
    # CREDIT PAYMENTS (From CompanyPayment)
    # ============================================
    from credit.models import CompanyPayment
    
    credit_payments = CompanyPayment.objects.filter(
        payment_method__in=['bank', 'mpesa', 'cash']
    ).select_related('credit_company', 'created_by')
    
    for payment in credit_payments:
        payment_date = payment.payment_date
        transactions.append({
            'id': f'credit_payment_{payment.id}',
            'transaction_date': payment.payment_date,
            'sort_date': payment.payment_date,
            'source': 'credit_payment',
            'transaction_type': 'income',
            'description': f"Credit payment from {payment.credit_company.name} - {payment.payment_id}",
            'amount': payment.amount,
            'reference': payment.payment_reference,
            'notes': f"Payment for {payment.transactions.count()} transactions. {payment.notes}",
            'created_by': payment.created_by,
        })
    
    # ============================================
    # SORT TRANSACTIONS (Newest first using sort_date)
    # ============================================
    transactions.sort(key=lambda x: x['sort_date'], reverse=True)
    
    # ============================================
    # APPLY FILTERS
    # ============================================
    transaction_type = request.GET.get('type')
    if transaction_type:
        transactions = [t for t in transactions if t['transaction_type'] == transaction_type]
    
    account_filter = request.GET.get('account')
    if account_filter:
        transactions = [t for t in transactions if t['source'] == account_filter]
    
    if date_from_str:
        try:
            date_from_obj = datetime.strptime(date_from_str, '%Y-%m-%d').date()
            transactions = [t for t in transactions if t['sort_date'] >= date_from_obj]
        except:
            pass
    
    if date_to_str:
        try:
            date_to_obj = datetime.strptime(date_to_str, '%Y-%m-%d').date()
            transactions = [t for t in transactions if t['sort_date'] <= date_to_obj]
        except:
            pass
    
    # ============================================
    # PAGINATION
    # ============================================
    paginator = Paginator(transactions, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # ============================================
    # CALCULATE TOTALS FROM FILTERED TRANSACTIONS
    # ============================================
    total_income = sum(t['amount'] for t in transactions if t['transaction_type'] == 'income')
    total_expenses = sum(t['amount'] for t in transactions if t['transaction_type'] == 'expense')
    net_balance = total_income - total_expenses
    
    # ============================================
    # CALCULATE PROFIT FROM FILTERED DATE RANGE
    # ============================================
    
    # Filter sales by date range for profit calculation
    filtered_sales = Sale.objects.filter(is_reversed=False)
    if date_from_aware:
        filtered_sales = filtered_sales.filter(sale_date__gte=date_from_aware)
    if date_to_aware:
        filtered_sales = filtered_sales.filter(sale_date__lte=date_to_aware)
    
    total_sales_profit = Decimal('0.00')
    for sale in filtered_sales:
        for item in sale.items.all():
            if item.product and item.product.buying_price:
                profit = (item.unit_price - item.product.buying_price) * item.quantity
                total_sales_profit += profit
    
    # Filter credit payments by date range
    filtered_credit_payments = CompanyPayment.objects.all()
    if date_from:
        filtered_credit_payments = filtered_credit_payments.filter(payment_date__gte=date_from)
    if date_to:
        filtered_credit_payments = filtered_credit_payments.filter(payment_date__lte=date_to)
    
    total_credit_profit = filtered_credit_payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    total_profit = total_sales_profit + total_credit_profit
    
    # ============================================
    # CONTEXT
    # ============================================
    context = {
        'transactions': page_obj,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net_balance': net_balance,
        'total_profit': total_profit,
        'transaction_types': [
            ('income', 'Income'),
            ('expense', 'Expense'),
        ],
        'account_types': [
            ('salary', 'Salary'),
            ('commission', 'Commission'),
            ('cash_account', 'Cash Account'),
            ('bank_account', 'Bank Account'),
            ('credit_account', 'Credit Account'),
            ('sales', 'Sales Income'),
            ('credit_payment', 'Credit Payment'),
        ],
    }
    
    return render(request, 'finance/transactions.html', context)



# ============================================
# INCOME AND EXPENSE VIEWS
# ============================================

@login_required
def financial_income(request):
    """List all income transactions only"""
    from decimal import Decimal
    from django.core.paginator import Paginator
    from datetime import datetime, timedelta
    
    transactions = []
    
    # Sales Income
    sales = Sale.objects.filter(is_reversed=False).select_related('seller')
    for sale in sales:
        # Keep the original sale_id with # for database lookup
        transactions.append({
            'id': f'sale_{sale.sale_id}',  # Keep the original ID with #
            'date': sale.sale_date,
            'source': 'sales',
            'description': f"Sale {sale.sale_id} - {sale.buyer_name or 'Walk-in Customer'}",
            'amount': sale.total_amount,
            'reference': sale.sale_id,
            'created_by': sale.seller,
            'payment_method': sale.payment_method,
            'category': 'Sales Income'
        })
    
    # Credit Sales Income
    credit_sales = CreditTransaction.objects.filter(payment_status='paid').select_related('dealer', 'customer', 'credit_company')
    for credit in credit_sales:
        # Keep the original transaction_id with # for database lookup
        transactions.append({
            'id': f'credit_{credit.transaction_id}',  # Keep the original ID with #
            'date': credit.paid_date or credit.transaction_date,
            'source': 'credit_sales',
            'description': f"Credit Sale {credit.transaction_id} - {credit.customer.full_name} ({credit.credit_company.name})",
            'amount': credit.ceiling_price,
            'reference': credit.transaction_id,
            'created_by': credit.dealer,
            'payment_method': 'Credit',
            'category': 'Credit Income'
        })
    
    # Account Income (manual entries)
    account_income = AccountTransaction.objects.filter(
        transaction_type='income'
    ).select_related('created_by')
    
    for acc_trans in account_income:
        transactions.append({
            'id': f'account_{acc_trans.id}',
            'date': acc_trans.transaction_date,
            'source': f"{acc_trans.account_type}_account",
            'description': acc_trans.description,
            'amount': acc_trans.amount,
            'reference': acc_trans.reference or f"ACC-{acc_trans.id}",
            'created_by': acc_trans.created_by,
            'payment_method': acc_trans.account_type,
            'category': 'Manual Entry',
            'notes': acc_trans.notes
        })
    
    # Sort by date (newest first)
    transactions.sort(key=lambda x: x['date'], reverse=True)
    
    # Apply filters
    date_from = request.GET.get('date_from')
    if date_from:
        try:
            date_from_aware = timezone.make_aware(datetime.strptime(date_from, '%Y-%m-%d'))
            transactions = [t for t in transactions if t['date'] >= date_from_aware]
        except:
            pass
    
    date_to = request.GET.get('date_to')
    if date_to:
        try:
            date_to_aware = timezone.make_aware(datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
            transactions = [t for t in transactions if t['date'] <= date_to_aware]
        except:
            pass
    
    source_filter = request.GET.get('source')
    if source_filter:
        transactions = [t for t in transactions if t['source'] == source_filter]
    
    # Pagination
    paginator = Paginator(transactions, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Calculate totals
    total_income = sum(t['amount'] for t in transactions)
    
    # Source types for filter
    source_types = [
        ('sales', 'Sales Income'),
        ('credit_sales', 'Credit Sales'),
        ('cash_account', 'Cash Account'),
        ('bank_account', 'Bank Account'),
        ('credit_account', 'Credit Account'),
    ]
    
    context = {
        'transactions': page_obj,
        'total_income': total_income,
        'source_types': source_types,
        'current_filters': {
            'date_from': date_from,
            'date_to': date_to,
            'source': source_filter,
        },
        'page_title': 'Income Transactions',
        'page_icon': 'fa-money-bill-wave',
        'transaction_type': 'income',
    }
    
    return render(request, 'finance/financial_income.html', context)



    


@login_required
def financial_expenses(request):
    """List all expense transactions only"""
    from decimal import Decimal
    from django.core.paginator import Paginator
    from datetime import datetime, timedelta
    
    transactions = []
    
    # Salary expenses
    salaries = Salary.objects.filter(status='paid').select_related('staff', 'paid_by')
    for salary in salaries:
        transactions.append({
            'id': f'salary_{salary.id}',
            'date': salary.paid_date or salary.created_at,
            'source': 'salary',
            'description': f"Salary payment - {salary.staff.get_full_name() or salary.staff.username} - {salary.get_month_display()} {salary.year}",
            'amount': salary.total_amount,
            'reference': salary.payment_reference or f"SAL-{salary.id}",
            'created_by': salary.paid_by or salary.created_by,
            'payment_method': 'Bank/Cash',
            'category': 'Salary',
            'notes': salary.notes
        })
    
    # Commission expenses
    commissions = SellerCommission.objects.filter(status='paid').select_related('seller', 'paid_by')
    for commission in commissions:
        transactions.append({
            'id': f'commission_{commission.id}',
            'date': commission.paid_date or commission.created_at,
            'source': 'commission',
            'description': f"Commission payment - {commission.seller.get_full_name() or commission.seller.username} - {commission.transaction.transaction_id}",
            'amount': commission.amount,
            'reference': f"COMM-{commission.id}",
            'created_by': commission.paid_by,
            'payment_method': commission.payment_method or 'Bank/Cash',
            'category': 'Commission',
            'notes': commission.notes
        })
    
    # Account Expenses (manual entries)
    account_expenses = AccountTransaction.objects.filter(
        transaction_type='expense'
    ).select_related('created_by')
    
    for acc_trans in account_expenses:
        transactions.append({
            'id': f'account_{acc_trans.id}',
            'date': acc_trans.transaction_date,
            'source': f"{acc_trans.account_type}_account",
            'description': acc_trans.description,
            'amount': acc_trans.amount,
            'reference': acc_trans.reference or f"ACC-{acc_trans.id}",
            'created_by': acc_trans.created_by,
            'payment_method': acc_trans.account_type,
            'category': 'Manual Expense',
            'notes': acc_trans.notes
        })
    
    # Sort by date (newest first)
    transactions.sort(key=lambda x: x['date'], reverse=True)
    
    # Apply filters
    date_from = request.GET.get('date_from')
    if date_from:
        try:
            date_from_aware = timezone.make_aware(datetime.strptime(date_from, '%Y-%m-%d'))
            transactions = [t for t in transactions if t['date'] >= date_from_aware]
        except:
            pass
    
    date_to = request.GET.get('date_to')
    if date_to:
        try:
            date_to_aware = timezone.make_aware(datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
            transactions = [t for t in transactions if t['date'] <= date_to_aware]
        except:
            pass
    
    source_filter = request.GET.get('source')
    if source_filter:
        transactions = [t for t in transactions if t['source'] == source_filter]
    
    # Pagination
    paginator = Paginator(transactions, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Calculate totals
    total_expenses = sum(t['amount'] for t in transactions)
    
    # Source types for filter
    source_types = [
        ('salary', 'Salary Payments'),
        ('commission', 'Commission Payments'),
        ('cash_account', 'Cash Account'),
        ('bank_account', 'Bank Account'),
        ('credit_account', 'Credit Account'),
    ]
    
    context = {
        'transactions': page_obj,
        'total_expenses': total_expenses,
        'source_types': source_types,
        'current_filters': {
            'date_from': date_from,
            'date_to': date_to,
            'source': source_filter,
        },
        'page_title': 'Expense Transactions',
        'page_icon': 'fa-receipt',
        'transaction_type': 'expense',
    }
    
    return render(request, 'finance/financial_expenses.html', context)





@login_required
def bank_account(request):
    """Bank account dashboard with bank sales and credit payments"""
    from .models import BankAccount, AccountTransaction
    from credit.models import CompanyPayment
    from sales.models import Sale
    from decimal import Decimal
    from datetime import datetime
    from django.utils import timezone
    
    bank_account, created = BankAccount.objects.get_or_create(id=1)
    
    # ============================================
    # CALCULATE TOTALS FOR THE CARDS
    # ============================================
    
    # Calculate Total Income
    bank_sales_total = Sale.objects.filter(
        payment_method__in=['M-Pesa', 'Card', 'Bank'],
        is_reversed=False
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    credit_bank_total = CompanyPayment.objects.filter(
        payment_method__in=['bank', 'mpesa']
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    manual_income_total = AccountTransaction.objects.filter(
        account_type='bank',
        transaction_type='income'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    total_income = bank_sales_total + credit_bank_total + manual_income_total
    
    # Calculate Total Expenses
    manual_expense_total = AccountTransaction.objects.filter(
        account_type='bank',
        transaction_type='expense'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    total_expenses = manual_expense_total
    
    # ============================================
    # NET BALANCE = CURRENT BALANCE (from the account)
    # ============================================
    net_balance = bank_account.balance  # This is the actual current balance
    
    # ============================================
    # BUILD TRANSACTIONS LIST FOR DISPLAY
    # ============================================
    transactions = []
    
    # Add bank sales
    bank_sales = Sale.objects.filter(
        payment_method__in=['M-Pesa', 'Card', 'Bank'],
        is_reversed=False
    ).select_related('seller')
    
    for sale in bank_sales:
        transactions.append({
            'date': sale.sale_date,
            'type': 'income',
            'description': f"{sale.payment_method} Sale - {sale.sale_id} - {sale.buyer_name or 'Walk-in Customer'}",
            'amount': sale.total_amount,
            'reference': sale.sale_id,
            'created_by': sale.seller,
            'source': 'bank_sale'
        })
    
    # Add manual transactions
    manual_trans = AccountTransaction.objects.filter(
        account_type='bank'
    ).select_related('created_by')
    
    for t in manual_trans:
        transactions.append({
            'date': t.transaction_date,
            'type': t.transaction_type,
            'description': t.description,
            'amount': t.amount,
            'reference': t.reference or '',
            'created_by': t.created_by,
            'source': 'manual'
        })
    
    # Add credit payments
    credit_payments = CompanyPayment.objects.filter(
        payment_method__in=['bank', 'mpesa']
    ).select_related('credit_company', 'created_by')
    
    for payment in credit_payments:
        payment_date = datetime.combine(payment.payment_date, datetime.min.time())
        if timezone.is_naive(payment_date):
            payment_date = timezone.make_aware(payment_date)
        transactions.append({
            'date': payment_date,
            'type': 'income',
            'description': f'Credit payment - {payment.credit_company.name}',
            'amount': payment.amount,
            'reference': payment.payment_reference,
            'created_by': payment.created_by,
            'source': 'credit_payment'
        })
    
    # Add money transfers
    transfers_in = MoneyTransfer.objects.filter(
        to_account='bank',
        status='completed'
    ).order_by('-created_at')
    
    transfers_out = MoneyTransfer.objects.filter(
        from_account='bank',
        status='completed'
    ).order_by('-created_at')
    
    for transfer in transfers_in:
        transactions.append({
            'date': transfer.created_at,
            'type': 'transfer',
            'description': f'Transfer from {transfer.get_from_account_display()} to Bank - {transfer.description}',
            'amount': transfer.amount,
            'reference': transfer.transfer_reference,
            'created_by': transfer.requested_by,
            'source': 'transfer_in'
        })
    
    for transfer in transfers_out:
        transactions.append({
            'date': transfer.created_at,
            'type': 'transfer',
            'description': f'Transfer from Bank to {transfer.get_to_account_display()} - {transfer.description}',
            'amount': transfer.amount,
            'reference': transfer.transfer_reference,
            'created_by': transfer.requested_by,
            'source': 'transfer_out'
        })
    
    # Sort by date
    transactions.sort(key=lambda x: x['date'], reverse=True)
    recent_transactions = transactions[:50]
    
    context = {
        'account': bank_account,
        'transactions': recent_transactions,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net_balance': net_balance,  # This is the current balance
        'account_type': 'Bank Account',
        'account_icon': 'fa-university',
        'account_color': 'primary',
    }
    
    return render(request, 'finance/account_detail.html', context)







@login_required
def cash_account(request):
    """Cash account dashboard with cash sales and credit payments"""
    from .models import CashAccount, AccountTransaction
    from credit.models import CompanyPayment
    from sales.models import Sale
    from decimal import Decimal
    from datetime import datetime
    from django.utils import timezone
    
    cash_account, created = CashAccount.objects.get_or_create(id=1)
    
    # ============================================
    # CALCULATE TOTALS FOR THE CARDS
    # ============================================
    
    # Calculate Total Income (for the green card)
    cash_sales_total = Sale.objects.filter(
        payment_method='Cash',
        is_reversed=False
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    credit_cash_total = CompanyPayment.objects.filter(
        payment_method='cash'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    manual_income_total = AccountTransaction.objects.filter(
        account_type='cash',
        transaction_type='income'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    total_income = cash_sales_total + credit_cash_total + manual_income_total
    
    # Calculate Total Expenses (for the red card)
    manual_expense_total = AccountTransaction.objects.filter(
        account_type='cash',
        transaction_type='expense'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    total_expenses = manual_expense_total
    
    # ============================================
    # NET BALANCE = CURRENT BALANCE (from the account)
    # ============================================
    net_balance = cash_account.balance  # This is the actual current balance
    
    # ============================================
    # BUILD TRANSACTIONS LIST FOR DISPLAY
    # ============================================
    transactions = []
    
    # Add cash sales (income)
    cash_sales = Sale.objects.filter(
        payment_method='Cash',
        is_reversed=False
    ).select_related('seller')
    
    for sale in cash_sales:
        transactions.append({
            'date': sale.sale_date,
            'type': 'income',
            'description': f"Cash Sale - {sale.sale_id} - {sale.buyer_name or 'Walk-in Customer'}",
            'amount': sale.total_amount,
            'reference': sale.sale_id,
            'created_by': sale.seller,
            'source': 'cash_sale'
        })
    
    # Add manual transactions
    manual_trans = AccountTransaction.objects.filter(
        account_type='cash'
    ).select_related('created_by')
    
    for t in manual_trans:
        transactions.append({
            'date': t.transaction_date,
            'type': t.transaction_type,
            'description': t.description,
            'amount': t.amount,
            'reference': t.reference or '',
            'created_by': t.created_by,
            'source': 'manual',
            'notes': t.notes
        })
    
    # Add credit company cash payments (income)
    cash_payments = CompanyPayment.objects.filter(
        payment_method='cash'
    ).select_related('credit_company', 'created_by')
    
    for payment in cash_payments:
        payment_date = datetime.combine(payment.payment_date, datetime.min.time())
        if timezone.is_naive(payment_date):
            payment_date = timezone.make_aware(payment_date)
        transactions.append({
            'date': payment_date,
            'type': 'income',
            'description': f'Credit payment (cash) - {payment.credit_company.name}',
            'amount': payment.amount,
            'reference': payment.payment_reference,
            'created_by': payment.created_by,
            'source': 'credit_payment'
        })
    
    # Add money transfers (for display only)
    transfers_in = MoneyTransfer.objects.filter(
        to_account='cash',
        status='completed'
    ).order_by('-created_at')
    
    transfers_out = MoneyTransfer.objects.filter(
        from_account='cash',
        status='completed'
    ).order_by('-created_at')
    
    for transfer in transfers_in:
        transactions.append({
            'date': transfer.created_at,
            'type': 'transfer',
            'description': f'Transfer from {transfer.get_from_account_display()} to Cash - {transfer.description}',
            'amount': transfer.amount,
            'reference': transfer.transfer_reference,
            'created_by': transfer.requested_by,
            'source': 'transfer_in'
        })
    
    for transfer in transfers_out:
        transactions.append({
            'date': transfer.created_at,
            'type': 'transfer',
            'description': f'Transfer from Cash to {transfer.get_to_account_display()} - {transfer.description}',
            'amount': transfer.amount,
            'reference': transfer.transfer_reference,
            'created_by': transfer.requested_by,
            'source': 'transfer_out'
        })
    
    # Sort by date (newest first)
    transactions.sort(key=lambda x: x['date'], reverse=True)
    recent_transactions = transactions[:50]
    
    context = {
        'account': cash_account,
        'transactions': recent_transactions,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net_balance': net_balance,  # This is the current balance
        'account_type': 'Cash Account',
        'account_icon': 'fa-wallet',
        'account_color': 'success',
    }
    
    return render(request, 'finance/account_detail.html', context)




@login_required
def credit_account(request):
    """Credit account dashboard"""
    from .models import CreditAccount, AccountTransaction
    from decimal import Decimal
    
    credit_account, created = CreditAccount.objects.get_or_create(id=1, defaults={'credit_limit': 1000000})
    
    transactions = AccountTransaction.objects.filter(
        account_type='credit'
    ).order_by('-transaction_date')[:50]
    
    # Create transaction list for display
    transaction_list = []
    for t in transactions:
        transaction_list.append({
            'date': t.transaction_date,
            'type': t.transaction_type,
            'description': t.description,
            'amount': t.amount,
            'reference': t.reference or '',
            'created_by': t.created_by,
            'source': 'manual'
        })
    
    total_credit_taken = AccountTransaction.objects.filter(
        account_type='credit',
        transaction_type='expense'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    total_payments_made = AccountTransaction.objects.filter(
        account_type='credit',
        transaction_type='income'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    net_balance = total_credit_taken - total_payments_made
    
    context = {
        'account': credit_account,
        'transactions': transaction_list,
        'total_income': total_payments_made,
        'total_expenses': total_credit_taken,
        'net_balance': net_balance,
        'account_type': 'Credit Account',
        'account_icon': 'fa-credit-card',
        'account_color': 'warning',
        'is_credit_account': True,
    }
    
    return render(request, 'finance/account_detail.html', context)


@login_required
def add_account_transaction(request):
    """Add transaction to account"""
    from .models import CashAccount, BankAccount, CreditAccount, AccountTransaction
    
    if request.method == 'POST':
        try:
            account_type = request.POST.get('account_type')
            transaction_type = request.POST.get('transaction_type')
            amount = Decimal(request.POST.get('amount', '0'))
            description = request.POST.get('description', '')
            reference = request.POST.get('reference', '')
            notes = request.POST.get('notes', '')
            
            if amount <= 0:
                messages.error(request, 'Amount must be greater than 0')
                return redirect('finance:add_account_transaction')
            
            if not description:
                messages.error(request, 'Description is required')
                return redirect('finance:add_account_transaction')
            
            transaction = AccountTransaction.objects.create(
                account_type=account_type,
                transaction_type=transaction_type,
                amount=amount,
                description=description,
                reference=reference,
                notes=notes,
                created_by=request.user
            )
            
            if account_type == 'cash':
                account, _ = CashAccount.objects.get_or_create(id=1)
                account.update_balance(amount, transaction_type, request.user)
                redirect_url = 'finance:cash_account'
            elif account_type == 'bank':
                account, _ = BankAccount.objects.get_or_create(id=1)
                account.update_balance(amount, transaction_type, request.user)
                redirect_url = 'finance:bank_account'
            elif account_type == 'credit':
                account, _ = CreditAccount.objects.get_or_create(id=1)
                account.update_balance(amount, transaction_type, request.user)
                redirect_url = 'finance:credit_account'
            else:
                redirect_url = 'finance:dashboard'
            
            messages.success(request, f'Transaction added successfully: {description}')
            return redirect(redirect_url)
            
        except Exception as e:
            messages.error(request, f'Error adding transaction: {str(e)}')
            return redirect('finance:add_account_transaction')
    
    context = {
        'account_type': request.GET.get('account', ''),
    }
    return render(request, 'finance/add_transaction.html', context)


@login_required
def credit_company_payment(request, company_id):
    """Record a payment from a credit company - NO finance creation here"""
    from credit.models import CreditCompany, CreditTransaction, CompanyPayment
    
    company = get_object_or_404(CreditCompany, id=company_id)
    pending_transactions = CreditTransaction.objects.filter(
        credit_company=company,
        payment_status='pending'
    )
    
    if request.method == 'POST':
        try:
            payment_amount = Decimal(request.POST.get('amount', '0'))
            payment_method = request.POST.get('payment_method')
            payment_reference = request.POST.get('payment_reference', '')
            notes = request.POST.get('notes', '')
            
            # Mark transactions as paid
            for transaction in pending_transactions:
                transaction.mark_as_paid(
                    payment_ref=payment_reference,
                    paid_by=request.user
                )
            
            # Create company payment record
            payment = CompanyPayment.objects.create(
                credit_company=company,
                amount=payment_amount,
                payment_method=payment_method,
                payment_reference=payment_reference,
                payment_date=timezone.now().date(),
                notes=notes,
                created_by=request.user
            )
            payment.transactions.set(pending_transactions)
            
            messages.success(
                request,
                f'✅ Payment of KES {payment_amount:,.2f} recorded from {company.name}. '
                f'{pending_transactions.count()} transactions marked as paid.'
            )
            
            return redirect('credit:company_detail', pk=company.id)
            
        except Exception as e:
            messages.error(request, f'Error processing payment: {str(e)}')
            return redirect('credit:company_payment', company_id=company.id)
    
    context = {
        'company': company,
        'pending_transactions': pending_transactions,
        'total_amount': pending_transactions.aggregate(total=models.Sum('ceiling_price'))['total'] or 0,
        'transaction_count': pending_transactions.count(),
    }
    
    return render(request, 'credit/company_payment.html', context)


@login_required
def credit_company_payments_dashboard(request):
    """Dashboard showing payments from credit companies"""
    from credit.models import CreditTransaction, CreditCompany
    from django.db.models import Sum
    
    paid_credit_transactions = CreditTransaction.objects.filter(
        payment_status='paid'
    ).select_related('credit_company', 'customer', 'dealer')
    
    company_payments = {}
    for trans in paid_credit_transactions:
        company = trans.credit_company
        if company.id not in company_payments:
            company_payments[company.id] = {
                'company': company,
                'total_paid': Decimal('0.00'),
                'transactions': [],
                'total_commission': Decimal('0.00')
            }
        company_payments[company.id]['total_paid'] += trans.ceiling_price
        company_payments[company.id]['total_commission'] += trans.commission_amount
        company_payments[company.id]['transactions'].append(trans)
    
    total_received = sum(p['total_paid'] for p in company_payments.values())
    total_commission_earned = sum(p['total_commission'] for p in company_payments.values())
    
    context = {
        'company_payments': company_payments.values(),
        'total_received': total_received,
        'total_commission_earned': total_commission_earned,
        'total_companies': len(company_payments),
    }
    
    return render(request, 'finance/credit_company_payments.html', context)







@login_required
def expenses_detail(request, transaction_id):
    """View detailed expense information"""
    from decimal import Decimal
    
    expense_data = {}
    related_transactions = []
    
    if transaction_id.startswith('salary_'):
        salary_id = transaction_id.replace('salary_', '')
        try:
            salary = Salary.objects.select_related('staff', 'paid_by', 'created_by').get(id=salary_id)
            expense_data = {
                'id': f'salary_{salary.id}',
                'date': salary.paid_date or salary.created_at,
                'source': 'salary',
                'description': f"Salary payment - {salary.staff.get_full_name() or salary.staff.username} - {salary.get_month_display()} {salary.year}",
                'amount': salary.total_amount,
                'reference': salary.payment_reference or f"SAL-{salary.id}",
                'payment_method': 'bank' if salary.payment_reference else 'cash',
                'created_by': salary.paid_by or salary.created_by,
                'created_at': salary.created_at,
                'updated_at': salary.updated_at,  # ✅ Salary has updated_at
                'notes': salary.notes,
                'salary_data': {
                    'staff_name': salary.staff.get_full_name() or salary.staff.username,
                    'period': f"{salary.get_month_display()} {salary.year}",
                    'base_salary': salary.base_salary,
                    'bonus': salary.bonus,
                    'deductions': salary.deductions,
                    'total_amount': salary.total_amount,
                }
            }
        except Salary.DoesNotExist:
            messages.error(request, 'Salary record not found')
            return redirect('finance:financial_expenses')
            
    elif transaction_id.startswith('commission_'):
        commission_id = transaction_id.replace('commission_', '')
        try:
            commission = SellerCommission.objects.select_related(
                'seller', 'paid_by', 'transaction',
                'transaction__customer', 'transaction__product'
            ).get(id=commission_id)
            expense_data = {
                'id': f'commission_{commission.id}',
                'date': commission.paid_date or commission.created_at,
                'source': 'commission',
                'description': f"Commission payment - {commission.seller.get_full_name() or commission.seller.username} - {commission.transaction.transaction_id}",
                'amount': commission.amount,
                'reference': commission.payment_reference or f"COMM-{commission.id}",
                'payment_method': commission.payment_method or 'bank',
                'created_by': commission.paid_by,
                'created_at': commission.created_at,
                'updated_at': getattr(commission, 'updated_at', commission.created_at),  # ✅ Safe fallback
                'notes': commission.notes,
                'commission_data': {
                    'seller_name': commission.seller.get_full_name() or commission.seller.username,
                    'transaction_id': commission.transaction.transaction_id,
                    'customer_name': commission.transaction.customer.full_name,
                    'product_name': commission.transaction.product.name,
                    'sale_amount': commission.transaction.ceiling_price,
                    'commission_rate': (commission.amount / commission.transaction.ceiling_price * 100) if commission.transaction.ceiling_price > 0 else 0,
                }
            }
        except SellerCommission.DoesNotExist:
            messages.error(request, 'Commission record not found')
            return redirect('finance:financial_expenses')
            
    elif transaction_id.startswith('account_'):
        account_id = transaction_id.replace('account_', '')
        try:
            acc_trans = AccountTransaction.objects.select_related('created_by').get(id=account_id)
            expense_data = {
                'id': f'account_{acc_trans.id}',
                'date': acc_trans.transaction_date,
                'source': f"{acc_trans.account_type}_account",
                'description': acc_trans.description,
                'amount': acc_trans.amount,
                'reference': acc_trans.reference or f"ACC-{acc_trans.id}",
                'payment_method': acc_trans.account_type,
                'created_by': acc_trans.created_by,
                'created_at': acc_trans.created_at,
                # ❌ AccountTransaction has NO updated_at field - don't include it
                'notes': acc_trans.notes,
            }
        except AccountTransaction.DoesNotExist:
            messages.error(request, 'Account transaction not found')
            return redirect('finance:financial_expenses')
    
    else:
        messages.error(request, 'Invalid expense record')
        return redirect('finance:financial_expenses')
    
    # Get related transactions (same date or same source)
    if expense_data:
        expense_date = expense_data['date']
        if hasattr(expense_date, 'date'):
            expense_date = expense_date.date()
        
        # Find other expenses on the same day
        all_transactions = []
        
        # Get salaries on same day
        salaries = Salary.objects.filter(
            paid_date__date=expense_date,
            status='paid'
        )
        if expense_data.get('source') == 'salary':
            current_id = expense_data.get('id', '').replace('salary_', '')
            if current_id.isdigit():
                salaries = salaries.exclude(id=int(current_id))
        
        for sal in salaries[:5]:
            all_transactions.append({
                'date': sal.paid_date,
                'description': f"Salary - {sal.staff.get_full_name() or sal.staff.username} - {sal.get_month_display()} {sal.year}",
                'amount': sal.total_amount,
                'type': 'expense'
            })
        
        # Get commissions on same day
        commissions = SellerCommission.objects.filter(
            paid_date__date=expense_date,
            status='paid'
        )
        if expense_data.get('source') == 'commission':
            current_id = expense_data.get('id', '').replace('commission_', '')
            if current_id.isdigit():
                commissions = commissions.exclude(id=int(current_id))
        
        for comm in commissions[:5]:
            all_transactions.append({
                'date': comm.paid_date,
                'description': f"Commission - {comm.seller.get_full_name() or comm.seller.username} - {comm.transaction.transaction_id}",
                'amount': comm.amount,
                'type': 'expense'
            })
        
        # Get account expenses on same day
        account_expenses = AccountTransaction.objects.filter(
            transaction_date__date=expense_date,
            transaction_type='expense'
        )
        if expense_data.get('source', '').endswith('_account'):
            current_id = expense_data.get('id', '').replace('account_', '')
            if current_id.isdigit():
                account_expenses = account_expenses.exclude(id=int(current_id))
        
        for acc_exp in account_expenses[:5]:
            all_transactions.append({
                'date': acc_exp.transaction_date,
                'description': acc_exp.description,
                'amount': acc_exp.amount,
                'type': 'expense'
            })
        
        # Sort by amount descending
        all_transactions.sort(key=lambda x: x['amount'], reverse=True)
        related_transactions = all_transactions[:5]
    
    context = {
        'expense': expense_data,
        'related_transactions': related_transactions,
    }
    
    return render(request, 'finance/expenses_detail.html', context)






@login_required
def income_detail(request, transaction_id):
    """View detailed income information"""
    
    income_data = {}
    
    # Handle credit sale IDs
    if transaction_id.startswith('credit_'):
        # Remove 'credit_' prefix to get the actual transaction_id
        actual_id = transaction_id.replace('credit_', '')
        
        try:
            from credit.models import CreditTransaction
            credit = CreditTransaction.objects.select_related(
                'dealer', 'customer', 'credit_company', 'product'
            ).get(transaction_id=actual_id)
            
            income_data = {
                'id': f'credit_{credit.transaction_id}',
                'date': credit.paid_date or credit.transaction_date,
                'source': 'credit_sales',
                'description': f"Credit Sale {credit.transaction_id} - {credit.customer.full_name} ({credit.credit_company.name})",
                'amount': credit.ceiling_price,
                'reference': credit.transaction_id,
                'created_by': credit.dealer,
                'created_at': credit.transaction_date,
                'payment_method': 'Credit',
                'credit_data': {
                    'customer_name': credit.customer.full_name,
                    'customer_phone': credit.customer.phone_number,
                    'customer_id': credit.customer.id_number,
                    'company_name': credit.credit_company.name,
                    'product_name': credit.product.name,
                    'product_code': credit.product.product_code,
                    'quantity': getattr(credit, 'quantity', 1),
                    'paid_date': credit.paid_date,
                    'transaction_date': credit.transaction_date,
                    'ceiling_price': credit.ceiling_price,
                    'commission_amount': credit.commission_amount,
                    'commission_status': credit.get_commission_status_display(),
                    'down_payment': getattr(credit, 'down_payment', 0),
                    'total_paid': getattr(credit, 'total_paid', credit.partial_payment_amount if hasattr(credit, 'partial_payment_amount') else 0),
                    'balance': getattr(credit, 'remaining_balance', (credit.ceiling_price - (credit.partial_payment_amount if hasattr(credit, 'partial_payment_amount') else 0))),
                    'payment_status': credit.get_payment_status_display(),
                    'payment_reference': credit.payment_reference,
                    'etr_receipt_number': credit.etr_receipt_number,
                }
            }
            
        except CreditTransaction.DoesNotExist:
            messages.error(request, f'Credit record not found with ID: {actual_id}')
            return redirect('finance:financial_income')
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
            return redirect('finance:financial_income')
    
    # Handle sale IDs
    elif transaction_id.startswith('sale_'):
        # Remove 'sale_' prefix to get the actual sale_id
        actual_id = transaction_id.replace('sale_', '')
        
        try:
            from sales.models import Sale
            sale = Sale.objects.select_related('seller').get(sale_id=actual_id)
            
            income_data = {
                'id': f'sale_{sale.sale_id}',
                'date': sale.sale_date,
                'source': 'sales',
                'description': f"Sale {sale.sale_id} - {sale.buyer_name or 'Walk-in Customer'}",
                'amount': sale.total_amount,
                'reference': sale.sale_id,
                'created_by': sale.seller,
                'created_at': sale.sale_date,
                'payment_method': sale.payment_method,
                'items_count': sale.items.count(),
                'sale_data': {
                    'buyer_name': sale.buyer_name or 'Walk-in Customer',
                    'buyer_phone': sale.buyer_phone or 'N/A',
                    'buyer_id_number': sale.buyer_id_number or 'N/A',
                    'total_items': sale.items.count(),
                    'payment_method': sale.payment_method,
                    'subtotal': sale.subtotal,
                    'tax_amount': sale.tax_amount,
                    'amount_paid': sale.amount_paid,
                    'change': sale.change,
                    'balance': sale.balance,
                    'etr_receipt_number': sale.etr_receipt_number or 'Not issued',
                    'is_credit': sale.is_credit,
                    'credit_sale_id': sale.credit_sale_id or 'N/A',
                    'points_redeemed': sale.points_redeemed,
                    'points_discount': sale.points_discount,
                }
            }
            
        except Sale.DoesNotExist:
            messages.error(request, f'Sale record not found with ID: {actual_id}')
            return redirect('finance:financial_income')
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
            return redirect('finance:financial_income')
    
    # Handle account transactions
    elif transaction_id.startswith('account_'):
        account_id = transaction_id.replace('account_', '')
        try:
            acc_trans = AccountTransaction.objects.select_related('created_by').get(id=account_id)
            income_data = {
                'id': f'account_{acc_trans.id}',
                'date': acc_trans.transaction_date,
                'source': f"{acc_trans.account_type}_account",
                'description': acc_trans.description,
                'amount': acc_trans.amount,
                'reference': acc_trans.reference or f"ACC-{acc_trans.id}",
                'created_by': acc_trans.created_by,
                'created_at': acc_trans.created_at,
                'payment_method': acc_trans.account_type,
                'notes': acc_trans.notes,
            }
        except AccountTransaction.DoesNotExist:
            messages.error(request, 'Account transaction not found')
            return redirect('finance:financial_income')
    
    else:
        messages.error(request, 'Invalid income record')
        return redirect('finance:financial_income')
    
    context = {
        'income': income_data,
    }
    
    return render(request, 'finance/income_detail.html', context)






@login_required
def stock_purchase_expenses(request):
    """View all stock purchase expenses"""
    from inventory.models import StockEntry
    from decimal import Decimal
    from django.core.paginator import Paginator
    from datetime import datetime, timedelta
    from django.db.models import Sum, Q
    
    # Get all purchase stock entries
    stock_purchases = StockEntry.objects.filter(
        quantity__gt=0,
        entry_type__in=['purchase', 'adjustment']
    ).select_related(
        'product_sku', 'product_unit__product', 'created_by'
    ).order_by('-created_at')
    
    # Apply filters
    date_from = request.GET.get('date_from')
    if date_from:
        try:
            stock_purchases = stock_purchases.filter(created_at__date__gte=date_from)
        except:
            pass
    
    date_to = request.GET.get('date_to')
    if date_to:
        try:
            stock_purchases = stock_purchases.filter(created_at__date__lte=date_to)
        except:
            pass
    
    search = request.GET.get('search')
    if search:
        stock_purchases = stock_purchases.filter(
            Q(product_sku__sku_code__icontains=search) |
            Q(product_sku__name__icontains=search) |
            Q(product_unit__product__sku_code__icontains=search) |
            Q(product_unit__product__name__icontains=search)
        )
    
    # Calculate totals
    total_purchase_value = stock_purchases.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_items_purchased = stock_purchases.aggregate(total=Sum('quantity'))['total'] or 0
    
    # Pagination
    paginator = Paginator(stock_purchases, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Enhance each entry
    for entry in page_obj:
        if entry.product_sku:
            entry.product_display = entry.product_sku.name
            entry.sku_display = entry.product_sku.sku_code
            entry.item_type = 'Bulk Item'
        elif entry.product_unit:
            entry.product_display = entry.product_unit.product.name
            entry.sku_display = entry.product_unit.product.sku_code
            entry.item_type = 'Single Unit'
        else:
            entry.product_display = 'Unknown'
            entry.sku_display = 'N/A'
            entry.item_type = 'Unknown'
    
    context = {
        'purchases': page_obj,
        'total_purchase_value': total_purchase_value,
        'total_items_purchased': total_items_purchased,
        'date_from': date_from,
        'date_to': date_to,
        'search': search,
    }
    
    return render(request, 'finance/stock_purchase_expenses.html', context)










# ============================================
# M-PESA PAYMENT INTEGRATION - COMPLETE
# ============================================

# TEMPORARY CART STORAGE FOR M-PESA PAYMENTS
@login_required
def store_mpesa_cart(request):
    """Store cart data temporarily while waiting for M-Pesa payment"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'})
    
    try:
        data = json.loads(request.body)
        checkout_id = data.get('checkout_id')
        cart_data = data.get('cart_data')
        
        if not checkout_id or not cart_data:
            return JsonResponse({'success': False, 'error': 'Missing checkout_id or cart_data'})
        
        # Store in cache for 30 minutes
        cache_key = f'mpesa_cart_{checkout_id}'
        cache.set(cache_key, cart_data, timeout=1800)
        
        logger.info(f"Stored cart data for checkout: {checkout_id}")
        return JsonResponse({'success': True})
        
    except Exception as e:
        logger.error(f"Error storing cart: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})





@login_required
def get_mpesa_cart(request, checkout_id):
    """Retrieve stored cart data after payment confirmation"""
    try:
        cache_key = f'mpesa_cart_{checkout_id}'
        cart_data = cache.get(cache_key)
        
        if not cart_data:
            return JsonResponse({'success': False, 'error': 'Cart data expired or not found'})
        
        # Delete after retrieval (one-time use)
        cache.delete(cache_key)
        
        return JsonResponse({
            'success': True,
            'cart_data': cart_data
        })
        
    except Exception as e:
        logger.error(f"Error retrieving cart: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})




async def clear_mpesa_cart_data(checkout_id):
    """Clear cart data after timeout or failure"""
    try:
        cache_key = f'mpesa_cart_{checkout_id}'
        cache.delete(cache_key)
    except Exception as e:
        logger.error(f"Error clearing cart: {str(e)}")





@csrf_exempt
@require_http_methods(["POST"])
def stk_push_only(request):
    """Send STK push to customer's phone"""
    
    # ADD THIS DEBUG LINE AT THE VERY TOP:
    print("=" * 60)
    print("STK_PUSH_ONLY VIEW WAS CALLED!")
    print(f"User authenticated: {request.user.is_authenticated if hasattr(request, 'user') else 'No user object'}")
    print(f"Request method: {request.method}")
    print(f"Request path: {request.path}")
    print("=" * 60)
    
    try:
        data = json.loads(request.body)
        phone_number = data.get('phone_number', '').strip()
        amount = Decimal(str(data.get('amount', 0)))
        account_reference = data.get('account_reference', f"TEMP-{int(timezone.now().timestamp())}")
        
        if not phone_number:
            return JsonResponse({'success': False, 'error': 'Phone number required'})
        
        if amount <= 0:
            return JsonResponse({'success': False, 'error': 'Amount must be greater than 0'})
        
        cleaned_phone = clean_phone_number(phone_number)
        
        # Check for pending transaction
        if check_pending_transaction(cleaned_phone):
            return JsonResponse({
                'success': False,
                'error': 'There is already a pending request for this phone number. Please wait 2-3 minutes.',
                'error_code': '429'
            })
        
        # Initiate STK Push
        result = stk_push_request(
            phone_number=cleaned_phone,
            amount=float(amount),
            account_reference=account_reference,
            transaction_desc=f"Payment for {account_reference}"
        )
        
        if result.get('ResponseCode') == '0':
            checkout_id = result.get('CheckoutRequestID')
            
            # Create transaction record
            MpesaTransaction.objects.create(
                merchant_request_id=result.get('MerchantRequestID', ''),
                checkout_request_id=checkout_id,
                amount=amount,
                phone_number=cleaned_phone,
                account_reference=account_reference,
                transaction_desc=f"STK Push for {account_reference}",
                status='pending',
            )
            
            return JsonResponse({
                'success': True,
                'checkout_request_id': checkout_id,
                'message': 'STK Push sent successfully'
            })
        else:
            error_msg = result.get('ResponseDescription', 'Failed to initiate payment')
            # FIXED: removed extra quote
            return JsonResponse({'success': False, 'error': error_msg})
            
    except Exception as e:
        logger.error(f"STK push error: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)})


def mpesa_status_check(request, checkout_request_id):
    """Check status of M-Pesa transaction"""
    try:
        transaction = MpesaTransaction.objects.filter(
            checkout_request_id=checkout_request_id
        ).first()
        
        if not transaction:
            return JsonResponse({
                'success': False,
                'status': 'not_found',
                'error': 'Transaction not found'
            })
        
        # Update sale if transaction is completed
        if transaction.status == 'completed' and transaction.sale:
            if transaction.sale.amount_paid == 0:
                transaction.sale.amount_paid = transaction.amount
                transaction.sale.payment_method = 'M-Pesa'
                transaction.sale.save()
                logger.info(f"Updated sale {transaction.sale.sale_id} during status check")
        
        return JsonResponse({
            'success': True,
            'status': transaction.status,
            'ResultCode': '0' if transaction.status == 'completed' else '1',
            'amount': float(transaction.amount) if transaction.amount else 0,
            'receipt_number': transaction.mpesa_receipt_number,
            'sale_id': transaction.sale.sale_id if transaction.sale else None
        })
        
    except Exception as e:
        logger.error(f"Status check error: {str(e)}")
        return JsonResponse({'success': False, 'status': 'error', 'error': str(e)})



def mpesa_transaction_detail(request, reference):
    """Get M-Pesa transaction details by reference"""
    try:
        transaction = MpesaTransaction.objects.filter(
            checkout_request_id=reference
        ).first()
        
        if not transaction:
            return JsonResponse({'status': 'not_found'}, status=404)
        
        return JsonResponse({
            'status': transaction.status,
            'amount': float(transaction.amount) if transaction.amount else 0,
            'phone_number': transaction.phone_number,
            'receipt_number': transaction.mpesa_receipt_number,
            'result_code': transaction.result_code,
            'created_at': transaction.created_at.isoformat()
        })
        
    except Exception as e:
        logger.error(f"Transaction detail error: {str(e)}")
        return JsonResponse({'status': 'error', 'error': str(e)}, status=500)


@csrf_exempt
def mpesa_callback(request):
    """Handle Kopo Kopo webhook callbacks"""
    if request.method != 'POST':
        return HttpResponse("Method not allowed", status=405)
    
    try:
        data = json.loads(request.body)
        logger.info("=" * 50)
        logger.info("MPESA CALLBACK RECEIVED")
        logger.info(f"Callback data: {json.dumps(data, indent=2)}")
        
        # Extract data - handle both formats
        if 'data' in data and isinstance(data['data'], dict):
            # Kopo Kopo format
            resource = data['data'].get('attributes', {})
            payment_id = data['data'].get('id')
            status = resource.get('status')
            amount = resource.get('amount')
            receipt = resource.get('reference')
            phone_number = resource.get('sender_phone_number')
            metadata = resource.get('metadata', {})
            account_reference = metadata.get('reference', '')
        else:
            # Alternative format
            event = data.get('event', {})
            resource = event.get('resource', {})
            payment_id = resource.get('id')
            status = resource.get('status')
            amount = resource.get('amount')
            receipt = resource.get('reference')
            phone_number = resource.get('sender_phone_number')
            metadata = data.get('metadata', {})
            account_reference = metadata.get('reference', '')
        
        logger.info(f"Payment ID: {payment_id}, Status: {status}, Amount: {amount}")
        logger.info(f"Account Reference: {account_reference}")
        
        # Find the sale by account_reference
        sale = None
        if account_reference:
            sale_id_value = account_reference.replace('SALE', '').replace('sale', '')
            try:
                from sales.models import Sale
                sale = Sale.objects.filter(sale_id=sale_id_value).first()
                if sale:
                    logger.info(f"✅ Found sale: {sale.sale_id}")
                else:
                    logger.warning(f"❌ Sale not found for reference: {account_reference}")
            except Exception as e:
                logger.error(f"Error finding sale: {e}")
        
        # Create or update transaction
        transaction, created = MpesaTransaction.objects.get_or_create(
            checkout_request_id=payment_id,
            defaults={
                'merchant_request_id': payment_id,
                'amount': Decimal(str(amount)) if amount else Decimal('0'),
                'phone_number': phone_number or '',
                'account_reference': account_reference,
                'transaction_desc': f"Payment for {account_reference}",
                'sale': sale,
                'status': 'completed' if status == 'Success' else 'failed',
                'mpesa_receipt_number': receipt,
                'result_code': 0 if status == 'Success' else 1,
                'result_desc': f"Status: {status}",
                'callback_raw_data': data
            }
        )
        
        if not created:
            transaction.status = 'completed' if status == 'Success' else 'failed'
            transaction.sale = sale
            transaction.mpesa_receipt_number = receipt
            transaction.callback_raw_data = data
            transaction.save()
            logger.info(f"Updated transaction {transaction.id} - Status: {transaction.status}")
        
        # Update sale if payment successful
        if sale and status == 'Success' and amount:
            sale.amount_paid = Decimal(str(amount))
            sale.payment_method = 'M-Pesa'
            sale.save()
            logger.info(f"✅✅✅ Updated sale {sale.sale_id} with amount {amount}")
        
        return JsonResponse({"ResultCode": 0, "ResultDesc": "OK"})
        
    except Exception as e:
        logger.error(f"Callback error: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"ResultCode": 0, "ResultDesc": "OK"})










# ============================================
# MONEY TRANSFER VIEWS
# ============================================
# finance/views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.core.paginator import Paginator
from decimal import Decimal
from .models import MoneyTransfer, CashAccount, BankAccount

@staff_member_required
def money_transfer_list(request):
    """List all internal money transfers (NOT income/expense)"""
    transfers = MoneyTransfer.objects.all().order_by('-created_at')
    
    # Apply filters
    status = request.GET.get('status')
    if status:
        transfers = transfers.filter(status=status)
    
    from_account = request.GET.get('from_account')
    if from_account:
        transfers = transfers.filter(from_account=from_account)
    
    to_account = request.GET.get('to_account')
    if to_account:
        transfers = transfers.filter(to_account=to_account)
    
    # Pagination
    paginator = Paginator(transfers, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'transfers': page_obj,
        'status_choices': MoneyTransfer.STATUS_CHOICES,
        'account_choices': MoneyTransfer.ACCOUNT_CHOICES,
        'title': 'Internal Money Transfers'
    }
    return render(request, 'finance/money_transfer_list.html', context)


@staff_member_required
def money_transfer_create(request):
    """Create new internal money transfer"""
    
    if request.method == 'POST':
        from_account = request.POST.get('from_account')
        to_account = request.POST.get('to_account')
        amount = request.POST.get('amount')
        description = request.POST.get('description')
        notes = request.POST.get('notes', '')
        
        # Validate
        if from_account == to_account:
            messages.error(request, 'Source and destination accounts cannot be the same')
            return redirect('finance:money_transfer_create')
        
        try:
            amount_decimal = Decimal(amount)
            if amount_decimal <= 0:
                messages.error(request, 'Amount must be greater than zero')
                return redirect('finance:money_transfer_create')
        except:
            messages.error(request, 'Invalid amount')
            return redirect('finance:money_transfer_create')
        
        # Check balance
        if from_account == 'cash':
            cash = CashAccount.objects.first()
            if not cash or cash.balance < amount_decimal:
                messages.error(request, f'Insufficient cash balance. Available: KES {cash.balance if cash else 0:,.2f}')
                return redirect('finance:money_transfer_create')
        elif from_account == 'bank':
            bank = BankAccount.objects.first()
            if not bank or bank.balance < amount_decimal:
                messages.error(request, f'Insufficient bank balance. Available: KES {bank.balance if bank else 0:,.2f}')
                return redirect('finance:money_transfer_create')
        
        # Create transfer
        transfer = MoneyTransfer.objects.create(
            from_account=from_account,
            to_account=to_account,
            amount=amount_decimal,
            description=description,
            notes=notes,
            requested_by=request.user
        )
        
        # Complete the transfer (internal - no income/expense)
        if transfer.complete_transfer(approved_by=request.user):
            messages.success(
                request, 
                f'✅ Internal transfer of KES {amount_decimal:,.2f} from {transfer.get_from_account_display()} to {transfer.get_to_account_display()} completed successfully!'
            )
        else:
            messages.error(request, 'Transfer failed due to insufficient balance')
        
        return redirect('finance:money_transfer_list')
    
    # GET request
    cash = CashAccount.objects.first()
    bank = BankAccount.objects.first()
    
    context = {
        'cash_balance': cash.balance if cash else 0,
        'bank_balance': bank.balance if bank else 0,
    }
    return render(request, 'finance/money_transfer_form.html', context)


@staff_member_required
def money_transfer_detail(request, pk):
    """View transfer details"""
    transfer = get_object_or_404(MoneyTransfer, pk=pk)
    return render(request, 'finance/money_transfer_detail.html', {'transfer': transfer})


@staff_member_required
def money_transfer_cancel(request, pk):
    """Cancel a pending transfer"""
    transfer = get_object_or_404(MoneyTransfer, pk=pk, status='pending')
    
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        transfer.cancel(cancelled_by=request.user, reason=reason)
        messages.warning(request, f'Transfer {transfer.transfer_reference} has been cancelled.')
        return redirect('finance:money_transfer_list')
    
    return render(request, 'finance/money_transfer_cancel.html', {'transfer': transfer})






from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q, F, DecimalField, ExpressionWrapper
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from .models import (
    IncomeAccount, PurchaseAccount, ProfitAccount, 
    IncomeTransaction, PurchaseTransaction, ProfitTransaction
)
from sales.models import Sale, SaleItem
from inventory.models import Product, StockEntry


@login_required
def sales_income_page(request):
    """Display sales income and profit analysis with comparisons"""
    
    # Get filter parameters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    period = request.GET.get('period', 'month')
    
    # Initialize variables
    days_diff = 30
    start_date = None
    end_date = None
    previous_start = None
    previous_end = None
    
    # Set date range based on period
    today = timezone.now().date()
    
    if period == 'day':
        start_date = today
        end_date = today
        days_diff = 1
        previous_start = today - timedelta(days=1)
        previous_end = today - timedelta(days=1)
    elif period == 'week':
        start_date = today - timedelta(days=7)
        end_date = today
        days_diff = 7
        previous_start = start_date - timedelta(days=7)
        previous_end = end_date - timedelta(days=7)
    elif period == 'month':
        start_date = today - timedelta(days=30)
        end_date = today
        days_diff = 30
        previous_start = start_date - timedelta(days=30)
        previous_end = end_date - timedelta(days=30)
    elif period == 'year':
        start_date = today - timedelta(days=365)
        end_date = today
        days_diff = 365
        previous_start = start_date - timedelta(days=365)
        previous_end = end_date - timedelta(days=365)
    else:
        start_date = today - timedelta(days=30)
        end_date = today
        days_diff = 30
        previous_start = start_date - timedelta(days=30)
        previous_end = end_date - timedelta(days=30)
    
    # Apply custom date filters if provided
    if date_from:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        if date_to:
            end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
            days_diff = (end_date - start_date).days
            if days_diff <= 0:
                days_diff = 1
        else:
            end_date = start_date + timedelta(days=days_diff)
    
    if date_to and not date_from:
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
        start_date = end_date - timedelta(days=days_diff)
    
    # Calculate previous period
    if previous_start is None or previous_end is None:
        previous_start = start_date - timedelta(days=days_diff)
        previous_end = end_date - timedelta(days=days_diff)
    
    # ============================================
    # USE STOCKENTRY FOR CONSISTENT DATA (matches Inventory Expenses)
    # ============================================
    from inventory.models import StockEntry, ProductUnit
    from decimal import Decimal
    from django.db.models import Sum, F
    
    # Get sales from StockEntry
    period_sales_entries = StockEntry.objects.filter(
        entry_type='sale',
        quantity__lt=0,
        created_at__date__gte=start_date,
        created_at__date__lte=end_date
    )
    
    # Calculate total sales revenue (VOGS)
    period_total_income = abs(period_sales_entries.aggregate(total=Sum('total_amount'))['total'] or Decimal('0'))
    
    # ============================================
    # FIXED: Calculate COGS using CORRECTED buying prices
    # ============================================
    period_cogs = Decimal('0')
    period_total_quantity = 0
    
    for entry in period_sales_entries:
        qty = abs(entry.quantity)
        period_total_quantity += qty
        
        if entry.product_sku:
            # For bulk items - use product's current buying price (CORRECTED)
            period_cogs += qty * (entry.product_sku.buying_price or Decimal('0'))
        elif entry.product_unit:
            # For single items - use unit's buying price or product's buying price
            buying_price = entry.product_unit.unit_buying_price or entry.product_unit.product.buying_price or Decimal('0')
            period_cogs += qty * buying_price
    
    period_profit = period_total_income - period_cogs
    period_margin = (period_profit / period_total_income * 100) if period_total_income > 0 else 0
    period_sales_count = period_sales_entries.count()
    
    # ============================================
    # PREVIOUS PERIOD using same logic
    # ============================================
    prev_sales_entries = StockEntry.objects.filter(
        entry_type='sale',
        quantity__lt=0,
        created_at__date__gte=previous_start,
        created_at__date__lte=previous_end
    )
    
    prev_total_income = abs(prev_sales_entries.aggregate(total=Sum('total_amount'))['total'] or Decimal('0'))
    
    prev_cogs = Decimal('0')
    for entry in prev_sales_entries:
        qty = abs(entry.quantity)
        if entry.product_sku:
            prev_cogs += qty * (entry.product_sku.buying_price or Decimal('0'))
        elif entry.product_unit:
            buying_price = entry.product_unit.unit_buying_price or entry.product_unit.product.buying_price or Decimal('0')
            prev_cogs += qty * buying_price
    
    prev_profit = prev_total_income - prev_cogs
    prev_margin = (prev_profit / prev_total_income * 100) if prev_total_income > 0 else 0
    
    # Calculate percentage changes
    income_change = ((period_total_income - prev_total_income) / prev_total_income * 100) if prev_total_income > 0 else 100 if period_total_income > 0 else 0
    profit_change = ((period_profit - prev_profit) / prev_profit * 100) if prev_profit > 0 else 100 if period_profit > 0 else 0
    margin_change = period_margin - prev_margin
    
    # ============================================
    # TOP SELLING PRODUCTS (from SaleItem for names)
    # ============================================
    from sales.models import SaleItem
    
    top_products = SaleItem.objects.filter(
        sale__sale_date__date__gte=start_date,
        sale__sale_date__date__lte=end_date,
        sale__is_reversed=False
    ).values(
        'product_name', 'product_code'
    ).annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('total_price')
    ).order_by('-total_revenue')[:5]
    
    # Previous period top products
    prev_top_products = SaleItem.objects.filter(
        sale__sale_date__date__gte=previous_start,
        sale__sale_date__date__lte=previous_end,
        sale__is_reversed=False
    ).values(
        'product_name', 'product_code'
    ).annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('total_price')
    ).order_by('-total_revenue')[:5]
    
    # ============================================
    # DAILY SALES DATA FOR CHART
    # ============================================
    daily_data = []
    current_date = start_date
    
    while current_date <= end_date:
        day_sales = StockEntry.objects.filter(
            entry_type='sale',
            quantity__lt=0,
            created_at__date=current_date
        )
        
        day_income = abs(day_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0'))
        
        day_cogs = Decimal('0')
        for entry in day_sales:
            qty = abs(entry.quantity)
            if entry.product_sku:
                day_cogs += qty * (entry.product_sku.buying_price or Decimal('0'))
            elif entry.product_unit:
                buying_price = entry.product_unit.unit_buying_price or entry.product_unit.product.buying_price or Decimal('0')
                day_cogs += qty * buying_price
        
        day_profit = day_income - day_cogs
        
        daily_data.append({
            'date': current_date.strftime('%Y-%m-%d'),
            'income': float(day_income),
            'profit': float(day_profit),
            'cogs': float(day_cogs)
        })
        current_date += timedelta(days=1)
    
    # ============================================
    # RECENT SALES (from StockEntry, limited to 5)
    # ============================================
    recent_sales_entries = period_sales_entries.order_by('-created_at')[:5]
    
    # ============================================
    # Get account balances
    # ============================================
    from .models import IncomeAccount, PurchaseAccount, ProfitAccount
    
    income_account = IncomeAccount.get_or_create_account()
    purchase_account = PurchaseAccount.get_or_create_account()
    profit_account = ProfitAccount.get_or_create_account()
    
    context = {
        'title': 'Sales Income Report',
        # Account balances
        'income_account': income_account,
        'purchase_account': purchase_account,
        'profit_account': profit_account,
        # Current period totals
        'period_income': period_total_income,
        'period_cogs': period_cogs,
        'period_profit': period_profit,
        'period_margin': period_margin,
        'period_sales_count': period_sales_count,
        'period_total_quantity': period_total_quantity,
        # Previous period totals
        'prev_income': prev_total_income,
        'prev_cogs': prev_cogs,
        'prev_profit': prev_profit,
        'prev_margin': prev_margin,
        # Changes
        'income_change': income_change,
        'profit_change': profit_change,
        'margin_change': margin_change,
        # Top products
        'top_products': top_products,
        'prev_top_products': prev_top_products,
        # Chart data
        'daily_data': daily_data,
        # Recent sales
        'recent_sales_entries': recent_sales_entries,
        # Date info
        'start_date': start_date,
        'end_date': end_date,
        'previous_start': previous_start,
        'previous_end': previous_end,
        'selected_period': period,
        'period_name': period,
    }
    
    return render(request, 'finance/sales_income.html', context)





@login_required
def inventory_expenses_page(request):
    """Display inventory purchase expenses and cost analysis with comparisons"""
    
    # Get filter parameters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    period = request.GET.get('period', 'month')
    
    # Initialize variables
    days_diff = 30
    start_date = None
    end_date = None
    previous_start = None
    previous_end = None
    
    # Set date range based on period
    today = timezone.now().date()
    
    if period == 'day':
        start_date = today
        end_date = today
        days_diff = 1
        previous_start = today - timedelta(days=1)
        previous_end = today - timedelta(days=1)
    elif period == 'week':
        start_date = today - timedelta(days=7)
        end_date = today
        days_diff = 7
        previous_start = start_date - timedelta(days=7)
        previous_end = end_date - timedelta(days=7)
    elif period == 'month':
        start_date = today - timedelta(days=30)
        end_date = today
        days_diff = 30
        previous_start = start_date - timedelta(days=30)
        previous_end = end_date - timedelta(days=30)
    elif period == 'year':
        start_date = today - timedelta(days=365)
        end_date = today
        days_diff = 365
        previous_start = start_date - timedelta(days=365)
        previous_end = end_date - timedelta(days=365)
    else:
        start_date = today - timedelta(days=30)
        end_date = today
        days_diff = 30
        previous_start = start_date - timedelta(days=30)
        previous_end = end_date - timedelta(days=30)
    
    # Apply custom date filters if provided
    if date_from:
        start_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        if date_to:
            end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
            days_diff = (end_date - start_date).days
            if days_diff <= 0:
                days_diff = 1
        else:
            end_date = start_date + timedelta(days=days_diff)
    
    if date_to and not date_from:
        end_date = datetime.strptime(date_to, '%Y-%m-%d').date()
        start_date = end_date - timedelta(days=days_diff)
    
    # Calculate previous period
    if previous_start is None or previous_end is None:
        previous_start = start_date - timedelta(days=days_diff)
        previous_end = end_date - timedelta(days=days_diff)
    
    # ============================================
    # CALCULATIONS FROM INVENTORY WITH CORRECTED PRICES
    # ============================================
    active_products = Product.objects.filter(is_active=True, is_discontinued=False)
    
    # CURRENT VALUES (what you have now) - USING CORRECTED PRODUCT PRICES
    current_cost_value = Decimal('0')
    current_retail_value = Decimal('0')
    total_units = 0
    low_stock_products = []
    
    for product in active_products:
        if product.category.is_single_item:
            stock = product.available_quantity or 0
        else:
            stock = product.bulk_quantity or 0
        
        total_units += stock
        # THESE NOW USE THE CORRECTED PRICES (from inventory)
        current_cost_value += stock * (product.buying_price or Decimal('0'))
        current_retail_value += stock * (product.selling_price or Decimal('0'))
        
        if stock <= product.reorder_level and stock > 0:
            low_stock_products.append({
                'name': product.name,
                'sku_code': product.sku_code,
                'stock_quantity': stock,
                'buying_price': product.buying_price,
                'selling_price': product.selling_price,
                'reorder_level': product.reorder_level,
                'category': product.category.name
            })
    
    # ============================================
    # FIXED: TOTAL PURCHASES - Use CORRECTED unit_price from StockEntry
    # ============================================
    total_purchases_cost = StockEntry.objects.filter(
        entry_type='purchase',
        quantity__gt=0
    ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or Decimal('0')
    
    # Calculate average markup
    if current_cost_value > 0:
        markup_ratio = current_retail_value / current_cost_value
        total_retail_value = total_purchases_cost * markup_ratio
    else:
        total_retail_value = total_purchases_cost * Decimal('2.5')
    
    # Calculate COGS (Cost of Goods Sold - what has been sold)
    cogs = total_purchases_cost - current_cost_value
    
    # Calculate VOGS (Value of Goods Sold - revenue from sold items)
    total_sales_value = StockEntry.objects.filter(
        entry_type='sale',
        quantity__lt=0
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
    vogs = abs(total_sales_value)
    
    # Calculate profits
    total_potential_profit = total_retail_value - total_purchases_cost
    current_potential_profit = current_retail_value - current_cost_value
    realized_profit = vogs - cogs
    
    # Calculate percentages
    current_margin_percentage = (current_potential_profit / current_retail_value * 100) if current_retail_value > 0 else 0
    current_cost_percentage = (current_cost_value / current_retail_value * 100) if current_retail_value > 0 else 0
    
    # Limit low stock products to 5
    low_stock_products = low_stock_products[:5]
    
    # ============================================
    # PERIOD PURCHASES (from PurchaseTransaction)
    # ============================================
    period_purchases = PurchaseTransaction.objects.filter(
        transaction_type__in=['cogs', 'stock'],
        transaction_date__date__gte=start_date,
        transaction_date__date__lte=end_date
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    prev_purchases = PurchaseTransaction.objects.filter(
        transaction_type__in=['cogs', 'stock'],
        transaction_date__date__gte=previous_start,
        transaction_date__date__lte=previous_end
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    purchase_change = ((period_purchases - prev_purchases) / prev_purchases * 100) if prev_purchases > 0 else 100 if period_purchases > 0 else 0
    
    # ============================================
    # TOP STOCK PURCHASES (Limited to 5)
    # ============================================
    stock_purchases = PurchaseTransaction.objects.filter(
        transaction_type='cogs',
        transaction_date__date__gte=start_date,
        transaction_date__date__lte=end_date
    ).values('reference').annotate(
        total_cost=Sum('amount'),
        transaction_count=Count('id')
    ).order_by('-total_cost')[:5]
    
    # ============================================
    # MONTHLY EXPENSE TREND
    # ============================================
    monthly_data = []
    current_date = start_date.replace(day=1)
    month_count = 0
    
    while current_date <= end_date and month_count < 12:
        month_start = current_date
        if current_date.month == 12:
            month_end = current_date.replace(year=current_date.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = current_date.replace(month=current_date.month + 1, day=1) - timedelta(days=1)
        
        month_purchases = PurchaseTransaction.objects.filter(
            transaction_type__in=['cogs', 'stock'],
            transaction_date__date__gte=month_start,
            transaction_date__date__lte=month_end
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        monthly_data.append({
            'month': month_start.strftime('%B %Y'),
            'amount': float(month_purchases),
        })
        
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1, day=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1, day=1)
        month_count += 1
    
    # ============================================
    # PURCHASE TRANSACTIONS (Limited to 5)
    # ============================================
    purchase_transactions = PurchaseTransaction.objects.filter(
        transaction_type__in=['cogs', 'stock'],
        transaction_date__date__gte=start_date,
        transaction_date__date__lte=end_date
    ).order_by('-transaction_date')[:5]
    
    # Get account balances
    purchase_account = PurchaseAccount.get_or_create_account()
    income_account = IncomeAccount.get_or_create_account()
    profit_account = ProfitAccount.get_or_create_account()
    
    context = {
        'title': 'Inventory Expenses Report',
        # Account balances
        'purchase_account': purchase_account,
        'income_account': income_account,
        'profit_account': profit_account,
        # TOTAL VALUES
        'total_purchases': total_purchases_cost,
        'total_retail_value': total_retail_value,
        'total_potential_profit': total_potential_profit,
        # CURRENT VALUES
        'current_cost_value': current_cost_value,
        'current_retail_value': current_retail_value,
        'current_potential_profit': current_potential_profit,
        # Other metrics
        'cogs': cogs,
        'vogs': vogs,
        'realized_profit': realized_profit,
        # Percentages
        'margin_percentage': current_margin_percentage,
        'cost_percentage': current_cost_percentage,
        'total_units': total_units,
        # Period data
        'period_purchases': period_purchases,
        'prev_purchases': prev_purchases,
        'purchase_change': purchase_change,
        'trend': 'up' if purchase_change > 0 else 'down' if purchase_change < 0 else 'stable',
        # Tables and charts
        'stock_purchases': stock_purchases,
        'monthly_data': monthly_data,
        'purchase_transactions': purchase_transactions,
        'low_stock_products': low_stock_products,
        # Date info
        'start_date': start_date,
        'end_date': end_date,
        'previous_start': previous_start,
        'previous_end': previous_end,
        'selected_period': period,
        'period_name': period,
    }
    
    return render(request, 'finance/inventory_expenses.html', context)




from .models import CapitalInjection, CapitalInjectionRepayment, CapitalAccount

@login_required
def capital_injection_list(request):
    """List all capital injections"""
    from decimal import Decimal
    from django.db.models import Sum, F
    from sales.models import Sale
    from inventory.models import StockEntry
    
    injections = CapitalInjection.objects.all().order_by('-transaction_date')
    capital_account = CapitalAccount.get_or_create_account()
    
    # ============================================
    # FIXED: Calculate Inventory Purchases from StockEntry with corrected prices
    # ============================================
    total_inventory_purchases = StockEntry.objects.filter(
        entry_type='purchase',
        quantity__gt=0
    ).aggregate(total=Sum(F('quantity') * F('unit_price')))['total'] or Decimal('0')
    
    # Calculate sales revenue
    total_sales_revenue = Sale.objects.filter(
        is_reversed=False
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
    
    # Calculate loan totals
    total_loan_amount = Decimal('0')
    total_repaid_amount = Decimal('0')
    total_loan_balance = Decimal('0')
    
    for injection in injections:
        if injection.is_loan:
            # Calculate repaid amount for this loan
            repaid = injection.repayments.aggregate(total=Sum('amount'))['total'] or Decimal('0')
            injection.total_repaid = repaid
            injection.remaining_balance = injection.amount - repaid
            
            total_loan_amount += injection.amount
            total_repaid_amount += repaid
            total_loan_balance += injection.remaining_balance
    
    # Calculate Net Capital Position
    total_capital_injected = injections.filter(status='completed').aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0')
    
    net_capital = total_capital_injected - total_inventory_purchases - total_repaid_amount + total_sales_revenue
    
    # Update capital account
    capital_account.total_capital_injected = total_capital_injected
    capital_account.total_purchases = total_inventory_purchases
    capital_account.total_sales_revenue = total_sales_revenue
    capital_account.total_loan_repayments = total_repaid_amount
    capital_account.net_capital = net_capital
    capital_account.save()
    
    context = {
        'injections': injections,
        'capital_account': capital_account,
        'total_sales_revenue': total_sales_revenue,
        'total_loan_amount': total_loan_amount,
        'total_repaid_amount': total_repaid_amount,
        'total_loan_balance': total_loan_balance,
        'total_inventory_purchases': total_inventory_purchases,  # Add this
        'title': 'Capital Account'
    }
    return render(request, 'finance/capital_injections.html', context)


@login_required
def capital_injection_create(request):
    """Create a new capital injection"""
    if request.method == 'POST':
        source_type = request.POST.get('source_type')
        source_name = request.POST.get('source_name')
        amount = Decimal(request.POST.get('amount'))
        payment_method = request.POST.get('payment_method')
        target_account = request.POST.get('target_account')
        is_loan = request.POST.get('is_loan') == 'on'
        interest_rate = Decimal(request.POST.get('interest_rate', 0))
        repayment_term = int(request.POST.get('repayment_term', 0))
        notes = request.POST.get('notes', '')
        
        # Calculate monthly repayment for loans
        monthly_repayment = Decimal('0')
        if is_loan and repayment_term > 0:
            monthly_repayment = amount / Decimal(repayment_term)
        
        injection = CapitalInjection.objects.create(
            source_type=source_type,
            source_name=source_name,
            amount=amount,
            payment_method=payment_method,
            target_account=target_account,
            is_loan=is_loan,
            interest_rate=interest_rate,
            repayment_term_months=repayment_term,
            monthly_repayment=monthly_repayment,
            notes=notes,
            created_by=request.user,
            status='completed'
        )
        
        # Process the injection
        injection.process_injection(request.user)
        
        messages.success(request, f'Capital injection of KES {amount:,.2f} added successfully!')
        return redirect('finance:capital_injection_list')
    
    return render(request, 'finance/capital_injection_form.html')


@login_required
def capital_injection_detail(request, injection_id):
    """View capital injection details"""
    from decimal import Decimal
    from django.db.models import Sum
    
    injection = get_object_or_404(CapitalInjection, injection_id=injection_id)
    repayments = injection.repayments.all()
    
    # Calculate total repaid safely (handle None)
    total_repaid = repayments.aggregate(total=Sum('amount'))['total']
    if total_repaid is None:
        total_repaid = Decimal('0')
    
    remaining_balance = injection.amount - total_repaid
    
    context = {
        'injection': injection,
        'repayments': repayments,
        'total_repaid': total_repaid,
        'remaining_balance': remaining_balance,
    }
    return render(request, 'finance/capital_injection_detail.html', context)


@login_required
def loan_repayment_create(request, injection_id):
    """Record a loan repayment"""
    injection = get_object_or_404(CapitalInjection, injection_id=injection_id)
    
    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount'))
        payment_reference = request.POST.get('payment_reference', '')
        notes = request.POST.get('notes', '')
        
        repayment = CapitalInjectionRepayment.objects.create(
            capital_injection=injection,
            amount=amount,
            payment_reference=payment_reference,
            notes=notes,
            created_by=request.user
        )
        
        # Create financial transaction for repayment (expense)
        fin_trans = FinancialTransaction.objects.create(
            transaction_type='expense',
            category='other',
            amount=amount,
            description=f"Loan Repayment: {injection.source_name} - {injection.injection_id}",
            payment_method='bank',
            payment_reference=payment_reference,
            recipient_name=injection.source_name,
            created_by=request.user
        )
        repayment.financial_transaction = fin_trans
        repayment.save()
        
        # Update bank/cash balance (money going out)
        bank_account, _ = BankAccount.objects.get_or_create(id=1)
        bank_account.update_balance(amount, 'expense', request.user)
        
        messages.success(request, f'Repayment of KES {amount:,.2f} recorded for {injection.injection_id}')
        return redirect('finance:capital_injection_detail', injection_id=injection.injection_id)
    
    context = {
        'injection': injection,
        'suggested_amount': injection.monthly_repayment
    }
    return render(request, 'finance/loan_repayment_form.html', context)