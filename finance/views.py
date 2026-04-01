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

logger = logging.getLogger(__name__)


# ============================================
# FINANCE DASHBOARD
# ============================================

@login_required
def finance_dashboard(request):
    """Finance dashboard overview"""
    from decimal import Decimal
    from django.db.models import Sum, Q
    from datetime import datetime, timedelta
    from .models import AccountTransaction
    
    today = timezone.now().date()
    current_month = today.month
    current_year = today.year
    
    # Get month start and end dates
    month_start = datetime(current_year, current_month, 1)
    if current_month == 12:
        month_end = datetime(current_year + 1, 1, 1) - timedelta(seconds=1)
    else:
        month_end = datetime(current_year, current_month + 1, 1) - timedelta(seconds=1)
    
    month_start_aware = timezone.make_aware(month_start)
    month_end_aware = timezone.make_aware(month_end)
    
    # ============================================
    # INCOME (Money coming IN)
    # ============================================
    
    # 1. Sales Income (from sales app)
    sales_income = Sale.objects.filter(
        sale_date__range=[month_start_aware, month_end_aware],
        is_reversed=False
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    # 2. Credit Sales Income (from credit app)
    credit_income = CreditTransaction.objects.filter(
        paid_date__range=[month_start_aware, month_end_aware],
        payment_status='paid'
    ).aggregate(total=Sum('ceiling_price'))['total'] or Decimal('0.00')
    
    # 3. Account Income (from cash/bank/credit accounts - manual entries)
    account_income = AccountTransaction.objects.filter(
        transaction_date__range=[month_start_aware, month_end_aware],
        transaction_type='income'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    total_income = sales_income + credit_income + account_income
    
    # ============================================
    # EXPENSES (Money going OUT)
    # ============================================
    
    # 1. Salary Expenses (paid salaries)
    salary_expenses = Salary.objects.filter(
        paid_date__range=[month_start_aware, month_end_aware],
        status='paid'
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    # 2. Commission Expenses (paid commissions)
    commission_expenses = SellerCommission.objects.filter(
        paid_date__range=[month_start_aware, month_end_aware],
        status='paid'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    # 3. Account Expenses (manual expense entries)
    account_expenses = AccountTransaction.objects.filter(
        transaction_date__range=[month_start_aware, month_end_aware],
        transaction_type='expense'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    total_expenses = salary_expenses + commission_expenses + account_expenses
    
    # ============================================
    # NET PROFIT
    # ============================================
    net_profit = total_income - total_expenses
    profit_margin = (net_profit / total_income * 100) if total_income > 0 else 0
    
    # ============================================
    # SALARY SUMMARY
    # ============================================
    current_month_salaries = Salary.objects.filter(
        month=current_month,
        year=current_year
    ).select_related('staff')
    
    total_base_salary = current_month_salaries.aggregate(total=Sum('base_salary'))['total'] or 0
    total_bonus = current_month_salaries.aggregate(total=Sum('bonus'))['total'] or 0
    total_deductions = current_month_salaries.aggregate(total=Sum('deductions'))['total'] or 0
    total_salary_amount = current_month_salaries.aggregate(total=Sum('total_amount'))['total'] or 0
    
    salaries_pending = current_month_salaries.filter(status='pending').aggregate(total=Sum('total_amount'))['total'] or 0
    salaries_approved = current_month_salaries.filter(status='approved').aggregate(total=Sum('total_amount'))['total'] or 0
    salaries_paid = current_month_salaries.filter(status='paid').aggregate(total=Sum('total_amount'))['total'] or 0
    salaries_paid_count = current_month_salaries.filter(status='paid').count()
    
    # ============================================
    # COMMISSION SUMMARY
    # ============================================
    commissions_pending = SellerCommission.objects.filter(
        status='pending'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    commissions_approved = SellerCommission.objects.filter(
        status='approved'
    ).aggregate(total=Sum('amount'))['total'] or 0
    
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
    # CHART DATA (Last 30 days)
    # ============================================
    thirty_days_ago = today - timedelta(days=30)
    chart_labels = []
    income_data = []
    expense_data = []
    profit_data = []
    
    for i in range(30):
        day = thirty_days_ago + timedelta(days=i)
        day_start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
        day_end = timezone.make_aware(datetime.combine(day, datetime.max.time()))
        
        # Daily income
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
        
        # Daily expenses
        day_salaries = Salary.objects.filter(
            paid_date__range=[day_start, day_end],
            status='paid'
        ).aggregate(total=Sum('total_amount'))['total'] or 0
        
        day_commissions = SellerCommission.objects.filter(
            paid_date__range=[day_start, day_end],
            status='paid'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        day_account_expenses = AccountTransaction.objects.filter(
            transaction_date__range=[day_start, day_end],
            transaction_type='expense'
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        daily_expense = day_salaries + day_commissions + day_account_expenses
        
        chart_labels.append(day.strftime('%d %b'))
        income_data.append(float(daily_income))
        expense_data.append(float(daily_expense))
        profit_data.append(float(daily_income - daily_expense))
    
    # ============================================
    # EXPENSE DISTRIBUTION (for pie chart)
    # ============================================
    salary_expenses_total = salary_expenses
    commission_expenses_total = commission_expenses
    operational_expenses = account_expenses
    other_expenses = Decimal('0.00')
    
    # ============================================
    # RECENT TRANSACTIONS (Last 10)
    # ============================================
    recent_transactions = FinancialTransaction.objects.select_related('created_by').order_by('-transaction_date')[:10]
    
    # ============================================
    # DEBUG PRINT - To verify values
    # ============================================
    print("=" * 60)
    print("FINANCE DASHBOARD SUMMARY")
    print(f"Month: {calendar.month_name[current_month]} {current_year}")
    print(f"Sales Income: KSH {sales_income:,.2f}")
    print(f"Credit Income: KSH {credit_income:,.2f}")
    print(f"Account Income: KSH {account_income:,.2f}")
    print(f"TOTAL INCOME: KSH {total_income:,.2f}")
    print("-" * 40)
    print(f"Salary Expenses: KSH {salary_expenses:,.2f}")
    print(f"Commission Expenses: KSH {commission_expenses:,.2f}")
    print(f"Account Expenses: KSH {account_expenses:,.2f}")
    print(f"TOTAL EXPENSES: KSH {total_expenses:,.2f}")
    print("-" * 40)
    print(f"NET PROFIT: KSH {net_profit:,.2f}")
    print(f"PROFIT MARGIN: {profit_margin:.1f}%")
    print("=" * 60)
    
    # ============================================
    # CONTEXT
    # ============================================
    context = {
        # Summary cards
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        
        # Salaries
        'salaries_pending': salaries_pending,
        'salaries_approved': salaries_approved,
        'salaries_paid': salaries_paid,
        'salaries_paid_count': salaries_paid_count,
        'current_month_salaries': current_month_salaries,
        'total_base_salary': total_base_salary,
        'total_bonus': total_bonus,
        'total_deductions': total_deductions,
        'total_salary_amount': total_salary_amount,
        
        # Commissions
        'commissions_pending': commissions_pending,
        'commissions_approved': commissions_approved,
        'commissions_paid': commissions_paid,
        'sellers_with_pending': sellers_with_pending,
        'pending_commissions': pending_commissions,
        'total_pending_commissions': total_pending_commissions,
        
        # Chart data
        'chart_labels': chart_labels,
        'income_data': income_data,
        'expense_data': expense_data,
        'profit_data': profit_data,
        
        # Expense distribution
        'salary_expenses': salary_expenses_total,
        'commission_expenses': commission_expenses_total,
        'operational_expenses': operational_expenses,
        'other_expenses': other_expenses,
        
        # Recent transactions
        'recent_transactions': recent_transactions,
        
        'current_month': calendar.month_name[current_month],
        'current_year': current_year,
        'today': today,
    }
    
    return render(request, 'finance/dashboard.html', context)


# ============================================
# SALARY MANAGEMENT VIEWS
# ============================================

@login_required
def salary_list(request):
    """List all staff salaries"""
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
    
    # Pagination
    paginator = Paginator(salaries, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get staff list for filter
    staff_list = User.objects.filter(is_active=True)
    
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
# FINANCIAL TRANSACTIONS VIEW
# ============================================

@login_required
def financial_transactions(request):
    """List all financial transactions including salary, commission, and account transactions"""
    from decimal import Decimal
    from django.core.paginator import Paginator
    from datetime import datetime, timedelta
    
    transactions = []
    
    # Salary transactions
    salaries = Salary.objects.filter(status='paid').select_related('staff', 'paid_by').all()
    for salary in salaries:
        transactions.append({
            'id': f'salary_{salary.id}',
            'transaction_date': salary.paid_date or salary.created_at,
            'source': 'salary',
            'transaction_type': 'expense',
            'description': f"Salary payment - {salary.staff.get_full_name() or salary.staff.username} - {salary.get_month_display()} {salary.year}",
            'amount': salary.total_amount,
            'reference': salary.payment_reference or f"SAL-{salary.id}",
            'notes': salary.notes,
            'created_by': salary.paid_by or salary.created_by,
        })
    
    # Commission transactions
    commissions = SellerCommission.objects.filter(status='paid').select_related('seller', 'paid_by')
    for commission in commissions:
        transactions.append({
            'id': f'commission_{commission.id}',
            'transaction_date': commission.paid_date or commission.created_at,
            'source': 'commission',
            'transaction_type': 'expense',
            'description': f"Commission payment - {commission.seller.get_full_name() or commission.seller.username} - {commission.transaction.transaction_id}",
            'amount': commission.amount,
            'reference': f"COMM-{commission.id}",
            'notes': commission.notes,
            'created_by': commission.paid_by,
        })
    
    # Account transactions
    account_transactions = AccountTransaction.objects.select_related('created_by').all()
    for acc_trans in account_transactions:
        source = f"{acc_trans.account_type}_account"
        transactions.append({
            'id': f'account_{acc_trans.id}',
            'transaction_date': acc_trans.transaction_date,
            'source': source,
            'transaction_type': acc_trans.transaction_type,
            'description': acc_trans.description,
            'amount': acc_trans.amount,
            'reference': acc_trans.reference or f"ACC-{acc_trans.id}",
            'notes': acc_trans.notes,
            'created_by': acc_trans.created_by,
        })
    
    # Sales Income
    sales = Sale.objects.filter(is_reversed=False).select_related('seller')
    for sale in sales:
        transactions.append({
            'id': f'sale_{sale.sale_id}',
            'transaction_date': sale.sale_date,
            'source': 'sales',
            'transaction_type': 'income',
            'description': f"Sale {sale.sale_id} - {sale.buyer_name or 'Walk-in Customer'}",
            'amount': sale.total_amount,
            'reference': sale.sale_id,
            'notes': f"Items: {sale.items.count()} | Paid via: {sale.payment_method}",
            'created_by': sale.seller,
        })
    
    # Credit Sales Income
    credit_sales = CreditTransaction.objects.filter(payment_status='paid').select_related('dealer', 'customer')
    for credit in credit_sales:
        transactions.append({
            'id': f'credit_{credit.transaction_id}',
            'transaction_date': credit.paid_date or credit.transaction_date,
            'source': 'credit_sales',
            'transaction_type': 'income',
            'description': f"Credit Sale {credit.transaction_id} - {credit.customer.full_name} ({credit.credit_company.name})",
            'amount': credit.ceiling_price,
            'reference': credit.transaction_id,
            'notes': f"Product: {credit.product_name} | Commission: KSH {credit.commission_amount}",
            'created_by': credit.dealer,
        })
    
    transactions.sort(key=lambda x: x['transaction_date'], reverse=True)
    
    transaction_type = request.GET.get('type')
    if transaction_type:
        transactions = [t for t in transactions if t['transaction_type'] == transaction_type]
    
    account_filter = request.GET.get('account')
    if account_filter:
        transactions = [t for t in transactions if t['source'] == account_filter]
    
    date_from = request.GET.get('date_from')
    if date_from:
        try:
            date_from_aware = timezone.make_aware(datetime.strptime(date_from, '%Y-%m-%d'))
            transactions = [t for t in transactions if t['transaction_date'] >= date_from_aware]
        except:
            pass
    
    date_to = request.GET.get('date_to')
    if date_to:
        try:
            date_to_aware = timezone.make_aware(datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
            transactions = [t for t in transactions if t['transaction_date'] <= date_to_aware]
        except:
            pass
    
    paginator = Paginator(transactions, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    total_income = sum(t['amount'] for t in transactions if t['transaction_type'] == 'income')
    total_expenses = sum(t['amount'] for t in transactions if t['transaction_type'] == 'expense')
    net_balance = total_income - total_expenses
    
    total_sales_profit = Decimal('0.00')
    for sale in sales:
        for item in sale.items.all():
            if item.product and item.product.buying_price:
                profit = (item.unit_price - item.product.buying_price) * item.quantity
                total_sales_profit += profit
    
    total_credit_profit = CreditTransaction.objects.filter(
        payment_status='paid'
    ).aggregate(total=Sum('commission_amount'))['total'] or Decimal('0.00')
    
    total_profit = total_sales_profit + total_credit_profit
    
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
            ('cash', 'Cash Account'),
            ('bank', 'Bank Account'),
            ('credit', 'Credit Account'),
            ('sales', 'Sales Income'),
            ('credit_sales', 'Credit Sales'),
        ],
    }
    
    return render(request, 'finance/transactions.html', context)


# ============================================
# FINANCE ACCOUNTS VIEWS
# ============================================

@login_required
def bank_account(request):
    """Bank account dashboard with integrated credit payments"""
    from .models import BankAccount, AccountTransaction
    from credit.models import CompanyPayment, CreditTransaction
    from decimal import Decimal
    from django.db.models import Sum, Q
    from datetime import datetime, timedelta
    from django.utils import timezone
    
    bank_account, created = BankAccount.objects.get_or_create(id=1)
    
    transactions = []
    
    manual_trans = AccountTransaction.objects.filter(
        account_type='bank'
    ).select_related('created_by')
    
    for t in manual_trans:
        transactions.append({
            'id': f'manual_{t.id}',
            'date': t.transaction_date,
            'type': t.transaction_type,
            'description': t.description,
            'amount': t.amount,
            'reference': t.reference or '',
            'created_by': t.created_by,
            'source': 'manual'
        })
    
    credit_payments = CompanyPayment.objects.filter(
        payment_method__in=['bank', 'mpesa', 'cash']
    ).select_related('credit_company', 'created_by')
    
    for payment in credit_payments:
        payment_date = datetime.combine(payment.payment_date, datetime.min.time())
        if timezone.is_naive(payment_date):
            payment_date = timezone.make_aware(payment_date)
            
        transactions.append({
            'id': f'credit_{payment.id}',
            'date': payment_date,
            'type': 'income',
            'description': f'Credit company payment - {payment.credit_company.name} - {payment.payment_id}',
            'amount': payment.amount,
            'reference': payment.payment_reference,
            'created_by': payment.created_by,
            'source': 'credit',
            'payment_id': payment.payment_id,
            'company': payment.credit_company.name
        })
    
    paid_credits = CreditTransaction.objects.filter(
        payment_status='paid'
    ).select_related('credit_company', 'customer', 'dealer')
    
    for credit in paid_credits:
        credit_date = credit.paid_date or credit.transaction_date
        if isinstance(credit_date, date) and not isinstance(credit_date, datetime):
            credit_date = datetime.combine(credit_date, datetime.min.time())
            if timezone.is_naive(credit_date):
                credit_date = timezone.make_aware(credit_date)
        
        transactions.append({
            'id': f'credit_trans_{credit.id}',
            'date': credit_date,
            'type': 'income',
            'description': f'Credit sale payment - {credit.transaction_id} - {credit.customer.full_name} ({credit.credit_company.name})',
            'amount': credit.ceiling_price,
            'reference': credit.transaction_id,
            'created_by': credit.dealer,
            'source': 'credit_sale',
            'commission': credit.commission_amount,
            'company': credit.credit_company.name
        })
    
    transactions.sort(key=lambda x: x['date'], reverse=True)
    recent_transactions = transactions[:50]
    
    total_income = sum(t['amount'] for t in transactions if t['type'] == 'income')
    total_expenses = sum(t['amount'] for t in transactions if t['type'] == 'expense')
    net_balance = total_income - total_expenses
    
    context = {
        'account': bank_account,
        'transactions': recent_transactions,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net_balance': net_balance,
        'account_type': 'Bank Account',
        'account_icon': 'fa-university',
        'account_color': 'primary',
    }
    
    return render(request, 'finance/account_detail.html', context)


@login_required
def cash_account(request):
    """Cash account dashboard with integrated credit payments"""
    from .models import CashAccount, AccountTransaction
    from credit.models import CompanyPayment, CreditTransaction
    from decimal import Decimal
    from datetime import datetime
    from django.utils import timezone
    
    cash_account, created = CashAccount.objects.get_or_create(id=1)
    
    transactions = []
    
    manual_trans = AccountTransaction.objects.filter(
        account_type='cash'
    ).select_related('created_by')
    
    for t in manual_trans:
        transactions.append({
            'id': f'manual_{t.id}',
            'date': t.transaction_date,
            'type': t.transaction_type,
            'description': t.description,
            'amount': t.amount,
            'reference': t.reference or '',
            'created_by': t.created_by,
            'source': 'manual'
        })
    
    cash_payments = CompanyPayment.objects.filter(
        payment_method='cash'
    ).select_related('credit_company', 'created_by')
    
    for payment in cash_payments:
        payment_date = datetime.combine(payment.payment_date, datetime.min.time())
        if timezone.is_naive(payment_date):
            payment_date = timezone.make_aware(payment_date)
            
        transactions.append({
            'id': f'credit_{payment.id}',
            'date': payment_date,
            'type': 'income',
            'description': f'Credit company payment (cash) - {payment.credit_company.name} - {payment.payment_id}',
            'amount': payment.amount,
            'reference': payment.payment_reference,
            'created_by': payment.created_by,
            'source': 'credit'
        })
    
    transactions.sort(key=lambda x: x['date'], reverse=True)
    recent_transactions = transactions[:50]
    
    total_income = sum(t['amount'] for t in transactions if t['type'] == 'income')
    total_expenses = sum(t['amount'] for t in transactions if t['type'] == 'expense')
    net_balance = total_income - total_expenses
    
    context = {
        'account': cash_account,
        'transactions': recent_transactions,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net_balance': net_balance,
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
        'transactions': transactions,
        'total_credit_taken': total_credit_taken,
        'total_payments_made': total_payments_made,
        'net_balance': net_balance,
        'available_credit': credit_account.available_credit,
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
    """Record a payment from a credit company and update finance accounts"""
    from credit.models import CreditCompany, CreditTransaction
    
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
            
            for transaction in pending_transactions:
                transaction.mark_as_paid(
                    payment_ref=payment_reference,
                    paid_by=request.user
                )
            
            from credit.models import CompanyPayment
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
            
            from finance.models import CashAccount, BankAccount
            
            if payment_method == 'cash':
                cash_account, _ = CashAccount.objects.get_or_create(id=1)
                cash_account.update_balance(payment_amount, 'income', request.user)
            else:
                bank_account, _ = BankAccount.objects.get_or_create(id=1)
                bank_account.update_balance(payment_amount, 'income', request.user)
            
            messages.success(
                request,
                f'Payment of KES {payment_amount:,.2f} recorded from {company.name}. '
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