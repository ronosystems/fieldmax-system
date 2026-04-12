# shops/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.db import models
from decimal import Decimal

from .models import (
    ShopBranch, BankAccount, MpesaAccount, DailyShopReport, 
    BankClosingBalance, ShopExpense, MpesaDailySummary, DynamicChoice
)
from .forms import (
    ShopBranchForm, BankAccountForm, MpesaAccountForm, DailyShopReportForm,
    BankClosingBalanceForm, ShopExpenseForm, MpesaDailySummaryForm, 
    DynamicChoiceForm, BankClosingFormSet, ExpenseFormSet
)


def is_staff_or_admin(user):
    """Check if user is staff or admin"""
    return user.is_staff or user.is_superuser

def is_superuser(user):
    """Check if user is superuser"""
    return user.is_superuser

def filter_by_user_queryset(request, queryset, user_field='submitted_by'):
    """
    Filter queryset based on user permissions:
    - Superusers can see all data
    - Regular users can only see their own data
    """
    if request.user.is_superuser:
        return queryset
    return queryset.filter(**{user_field: request.user})


# ==================== DASHBOARD & REPORTS VIEWS ====================

@login_required
@user_passes_test(is_staff_or_admin)
def shop_dashboard(request):
    """Dashboard showing shops and reports - filtered by user"""
    from django.db.models import Sum
    from django.utils import timezone
    from datetime import timedelta
    
    shops = ShopBranch.objects.filter(is_active=True)
    today = timezone.now().date()
    month_ago = today - timedelta(days=30)
    
    # Get user's assigned shop for regular users
    assigned_shop = None
    if not request.user.is_superuser:
        if hasattr(request.user, 'staff_profile') and request.user.staff_profile:
            assigned_shop = request.user.staff_profile.assigned_shop
    
    # Filter reports based on user permissions
    if request.user.is_superuser:
        today_reports = DailyShopReport.objects.filter(report_date=today)
        recent_reports = DailyShopReport.objects.all().order_by('-submission_time')[:5]
        total_transactions_today = today_reports.aggregate(total=Sum('shop_sales'))['total'] or 0
        reports_today = today_reports.count()
        monthly_transactions = 0
        monthly_expenses = 0
    else:
        # Regular users only see their own reports
        today_reports = DailyShopReport.objects.filter(
            report_date=today,
            submitted_by=request.user
        )
        recent_reports = DailyShopReport.objects.filter(
            submitted_by=request.user
        ).order_by('-submission_time')[:5]
        total_transactions_today = today_reports.aggregate(total=Sum('shop_sales'))['total'] or 0
        reports_today = today_reports.count()
        
        # Calculate monthly transactions and expenses for regular user
        monthly_reports = DailyShopReport.objects.filter(
            submitted_by=request.user,
            report_date__gte=month_ago,
            report_date__lte=today
        )
        monthly_transactions = monthly_reports.aggregate(total=Sum('shop_sales'))['total'] or 0
        monthly_expenses = monthly_reports.aggregate(total=Sum('total_expenses'))['total'] or 0
    
    context = {
        'shops': shops,
        'today_reports': today_reports,
        'recent_reports': recent_reports,
        'today': today,
        'total_shops': shops.count(),
        'reports_today': reports_today,
        'total_transactions_today': int(total_transactions_today),
        'assigned_shop': assigned_shop,
        'monthly_transactions': int(monthly_transactions) if not request.user.is_superuser else 0,
        'monthly_expenses': float(monthly_expenses) if not request.user.is_superuser else 0,
    }
    return render(request, 'shops/dashboard.html', context)




@login_required
def get_previous_closing_balance(request):
    """AJAX endpoint to get previous day's closing balance"""
    try:
        shop_id = request.GET.get('shop_id')
        report_date = request.GET.get('report_date')
        
        if shop_id and report_date:
            from datetime import datetime, timedelta
            report_date = datetime.strptime(report_date, '%Y-%m-%d').date()
            previous_date = report_date - timedelta(days=1)
            
            # For regular users, only show their own reports
            if request.user.is_superuser:
                previous_report = DailyShopReport.objects.filter(
                    shop_id=shop_id,
                    report_date=previous_date
                ).first()
                
                # If no report on exact previous date, get most recent before selected date
                if not previous_report:
                    previous_report = DailyShopReport.objects.filter(
                        shop_id=shop_id,
                        report_date__lt=report_date
                    ).order_by('-report_date').first()
            else:
                # For regular users, ONLY get THEIR reports
                previous_report = DailyShopReport.objects.filter(
                    shop_id=shop_id,
                    report_date=previous_date,
                    submitted_by=request.user
                ).first()
                
                # If no report on exact previous date, get their most recent report before selected date
                if not previous_report:
                    previous_report = DailyShopReport.objects.filter(
                        shop_id=shop_id,
                        report_date__lt=report_date,
                        submitted_by=request.user
                    ).order_by('-report_date').first()
            
            closing_balance = float(previous_report.total_closing_balance) if previous_report else 0
            
            return JsonResponse({
                'success': True,
                'closing_balance': closing_balance,
                'has_previous': previous_report is not None
            })
        return JsonResponse({'success': False, 'error': 'Missing parameters'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})






def get_running_balance(reports):
    """Calculate running balance for a series of reports"""
    running_balance = 0
    balances = []
    dates = []
    
    for report in reports.order_by('report_date'):
        opening = running_balance
        net_change = report.total_closing_balance - running_balance
        balances.append({
            'date': report.report_date,
            'opening': opening,
            'closing': report.total_closing_balance,
            'expenses': report.total_expenses,
            'net_change': net_change
        })
        running_balance = report.total_closing_balance
        dates.append(report.report_date)
    
    return balances, dates




@login_required
@user_passes_test(is_staff_or_admin)
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
@user_passes_test(is_staff_or_admin)
def create_daily_report(request):
    """Create a new daily report for a shop"""
    
    # Get user's assigned shop (for non-superusers)
    assigned_shop = None
    user_can_select_shop = request.user.is_superuser
    
    if not user_can_select_shop:
        # Get assigned shop from staff profile
        if hasattr(request.user, 'staff_profile') and request.user.staff_profile:
            assigned_shop = request.user.staff_profile.assigned_shop
        
        # If no assigned shop, try to get from recent reports
        if not assigned_shop:
            recent_report = DailyShopReport.objects.filter(
                submitted_by=request.user
            ).order_by('-report_date').first()
            if recent_report:
                assigned_shop = recent_report.shop
    
    if request.method == 'POST':
        form = DailyShopReportForm(request.POST)
        
        # For non-superusers, force the shop to their assigned shop
        if not user_can_select_shop and assigned_shop:
            form.data = form.data.copy()
            form.data['shop'] = assigned_shop.id
        
        if form.is_valid():
            # Check if a report already exists for this shop and date
            shop = form.cleaned_data.get('shop')
            report_date = form.cleaned_data.get('report_date')
            
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
                    report.save()
                    
                    # Process bank accounts from POST data
                    for key, value in request.POST.items():
                        if key.startswith('bank_account_') and value:
                            index = key.split('_')[-1]
                            closing_balance_key = f'bank_closing_balance_{index}'
                            closing_balance = request.POST.get(closing_balance_key)
                            
                            if closing_balance and float(closing_balance) > 0:
                                try:
                                    BankClosingBalance.objects.create(
                                        daily_report=report,
                                        bank_account_id=int(value),
                                        closing_balance=Decimal(str(closing_balance))
                                    )
                                except (ValueError, BankAccount.DoesNotExist) as e:
                                    print(f"Error creating bank closing balance: {e}")
                    
                    # Process expenses from POST data (updated for new format)
                    expense_total = 0
                    for key, value in request.POST.items():
                        if key.startswith('expense_description_') and value:
                            index = key.split('_')[-1]
                            amount_key = f'expense_amount_{index}'
                            amount = request.POST.get(amount_key)
                            
                            if amount and float(amount) > 0:
                                try:
                                    expense = ShopExpense.objects.create(
                                        daily_report=report,
                                        expense_category='Other',  # Default category since removed from form
                                        description=value,
                                        amount=Decimal(str(amount)),
                                        payment_method='cash'
                                    )
                                    expense_total += float(amount)
                                except (ValueError, TypeError) as e:
                                    print(f"Error creating expense: {e}")
                    
                    # Update report with totals
                    report.total_expenses = expense_total
                    
                    # Calculate total closing balance
                    mpesa_float = float(report.closing_mpesa_float) if report.closing_mpesa_float else 0
                    mpesa_cash = float(report.closing_mpesa_cash) if report.closing_mpesa_cash else 0
                    
                    bank_total = BankClosingBalance.objects.filter(daily_report=report).aggregate(
                        total=models.Sum('closing_balance')
                    )['total'] or 0
                    
                    report.total_closing_balance = mpesa_float + mpesa_cash + float(bank_total)
                    report.save()
                    
                    messages.success(
                        request, 
                        f'Daily report for {report.shop.name} submitted successfully! '
                        f'Total transactions recorded: {int(report.shop_sales):,}'
                    )
                    return redirect('shops:report_detail', report_id=report.id)
                    
            except Exception as e:
                messages.error(request, f'Error saving report: {str(e)}')
                import traceback
                print(traceback.format_exc())
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        messages.error(request, error)
                    else:
                        messages.error(request, f'{field}: {error}')
    else:
        form = DailyShopReportForm()
        # Pre-select shop for non-superusers
        if not user_can_select_shop and assigned_shop:
            form.fields['shop'].initial = assigned_shop.id
            form.fields['shop'].widget.attrs['readonly'] = True
    
    context = {
        'form': form,
        'title': 'Create Daily Report',
        'assigned_shop': assigned_shop,
        'user_can_select_shop': user_can_select_shop,
    }
    return render(request, 'shops/report_form.html', context)





@login_required
@user_passes_test(is_staff_or_admin)
def edit_daily_report(request, report_id):
    """Edit an existing daily report - users can only edit their own reports"""
    report = get_object_or_404(DailyShopReport, id=report_id)
    
    # Check if user is allowed to edit this report
    if not request.user.is_superuser and report.submitted_by != request.user:
        messages.error(request, 'You can only edit your own reports.')
        return redirect('shops:reports_list')
    
    if report.is_finalized:
        messages.warning(request, 'This report is finalized and cannot be edited.')
        return redirect('shops:report_detail', report_id=report.id)
    
    # Get user's assigned shop (for non-superusers)
    assigned_shop = None
    user_can_select_shop = request.user.is_superuser
    previous_net_balance = 0
    
    if not user_can_select_shop:
        # Get assigned shop from staff profile
        if hasattr(request.user, 'staff_profile') and request.user.staff_profile:
            assigned_shop = request.user.staff_profile.assigned_shop
        
        # If no assigned shop, use the report's shop
        if not assigned_shop:
            assigned_shop = report.shop
    
    if request.method == 'POST':
        form = DailyShopReportForm(request.POST, instance=report)
        
        # For non-superusers, force the shop to their assigned shop
        if not user_can_select_shop and assigned_shop:
            form.data = form.data.copy()
            form.data['shop'] = assigned_shop.id
        
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Save the main report
                    report = form.save(commit=False)
                    report.save()
                    
                    # Delete existing bank closings and recreate
                    BankClosingBalance.objects.filter(daily_report=report).delete()
                    
                    # Process bank accounts from POST data
                    for key, value in request.POST.items():
                        if key.startswith('bank_account_') and value:
                            index = key.split('_')[-1]
                            closing_balance_key = f'bank_closing_balance_{index}'
                            closing_balance = request.POST.get(closing_balance_key)
                            
                            if closing_balance and float(closing_balance) > 0:
                                try:
                                    BankClosingBalance.objects.create(
                                        daily_report=report,
                                        bank_account_id=int(value),
                                        closing_balance=Decimal(str(closing_balance))
                                    )
                                except (ValueError, BankAccount.DoesNotExist) as e:
                                    print(f"Error creating bank closing balance: {e}")
                    
                    # Delete existing expenses and recreate
                    ShopExpense.objects.filter(daily_report=report).delete()
                    
                    # Process expenses from POST data
                    expense_total = 0
                    for key, value in request.POST.items():
                        if key.startswith('expense_description_') and value:
                            index = key.split('_')[-1]
                            amount_key = f'expense_amount_{index}'
                            amount = request.POST.get(amount_key)
                            
                            if amount and float(amount) > 0:
                                try:
                                    expense = ShopExpense.objects.create(
                                        daily_report=report,
                                        expense_category='Other',
                                        description=value,
                                        amount=Decimal(str(amount)),
                                        payment_method='cash'
                                    )
                                    expense_total += float(amount)
                                except (ValueError, TypeError) as e:
                                    print(f"Error creating expense: {e}")
                    
                    # Update report with totals
                    report.total_expenses = expense_total
                    
                    # Calculate total closing balance
                    mpesa_float = float(report.closing_mpesa_float) if report.closing_mpesa_float else 0
                    mpesa_cash = float(report.closing_mpesa_cash) if report.closing_mpesa_cash else 0
                    
                    bank_total = BankClosingBalance.objects.filter(daily_report=report).aggregate(
                        total=models.Sum('closing_balance')
                    )['total'] or 0
                    
                    report.total_closing_balance = mpesa_float + mpesa_cash + float(bank_total)
                    report.save()
                    
                    messages.success(request, f'Report for {report.shop.name} updated successfully!')
                    return redirect('shops:report_detail', report_id=report.id)
                    
            except Exception as e:
                messages.error(request, f'Error updating report: {str(e)}')
                import traceback
                print(traceback.format_exc())
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = DailyShopReportForm(instance=report)
        # For non-superusers, make the shop field readonly and pre-select
        if not user_can_select_shop and assigned_shop:
            form.fields['shop'].initial = assigned_shop.id
            form.fields['shop'].widget.attrs['readonly'] = True
    
    # Get existing data for the template - IMPORTANT: Pass these to template
    bank_closings = report.bank_closings.filter(is_active=True)
    expenses = report.expenses.all()
    
    context = {
        'form': form,
        'report': report,
        'bank_closings': bank_closings,
        'expenses': expenses,
        'title': 'Edit Daily Report',
        'assigned_shop': assigned_shop,
        'user_can_select_shop': user_can_select_shop,
        'previous_net_balance': float(previous_net_balance), 
    }
    return render(request, 'shops/report_form.html', context)





@login_required
def report_detail(request, report_id):
    """View detailed report - users can only view their own reports unless superuser"""
    from django.db.models import Sum
    
    report = get_object_or_404(DailyShopReport, id=report_id)
    
    # Check if user is allowed to view this report
    if not request.user.is_superuser and report.submitted_by != request.user:
        messages.error(request, 'You can only view your own reports.')
        return redirect('shops:reports_list')
    
    # Get previous day's report for opening balance
    previous_report = report.get_previous_day_report()
    opening_balance = previous_report.total_closing_balance if previous_report else 0
    
    # Calculate net position = Opening Balance - Today's Expenses
    net_position = opening_balance - report.total_expenses
    
    # Get M-Pesa summary if exists
    mpesa_summary = MpesaDailySummary.objects.filter(
        shop=report.shop, 
        report_date=report.report_date
    ).first()
    
    # Get bank closings
    bank_closings = report.bank_closings.filter(is_active=True)
    
    # Calculate bank total
    bank_total = bank_closings.aggregate(total=Sum('closing_balance'))['total'] or 0
    bank_total = float(bank_total)
    
    # Calculate total M-Pesa
    total_mpesa = float(report.closing_mpesa_float or 0) + float(report.closing_mpesa_cash or 0)
    
    context = {
        'report': report,
        'bank_closings': bank_closings,
        'bank_total': bank_total,
        'total_mpesa': total_mpesa,
        'net_position': net_position,  # Changed from net_profit
        'opening_balance': opening_balance,  # New
        'previous_report': previous_report,  # New
        'expenses': report.expenses.all(),
        'mpesa_summary': mpesa_summary,
    }
    return render(request, 'shops/report_detail.html', context)




@login_required
@user_passes_test(is_staff_or_admin)
def finalize_report(request, report_id):
    """Finalize a report (cannot be edited after finalization)"""
    report = get_object_or_404(DailyShopReport, id=report_id)
    
    # Check if user is allowed to finalize this report
    if not request.user.is_superuser and report.submitted_by != request.user:
        messages.error(request, 'You can only finalize your own reports.')
        return redirect('shops:reports_list')
    
    if request.method == 'POST':
        report.is_finalized = True
        report.finalized_by = request.user  # Track who finalized
        report.finalized_at = timezone.now()  # Track when it was finalized
        report.save()
        messages.success(request, f'Report for {report.report_date} has been finalized!')
    
    return redirect('shops:report_detail', report_id=report.id)




@login_required
@user_passes_test(is_superuser)  # Only superusers can unfinalize
def unfinalize_report(request, report_id):
    """Revert a finalized report back to draft (can be edited again)"""
    report = get_object_or_404(DailyShopReport, id=report_id)
    
    # Check if user is allowed to unfinalize this report
    if not request.user.is_superuser:
        messages.error(request, 'Only superusers can revert finalized reports.')
        return redirect('shops:report_detail', report_id=report.id)
    
    if not report.is_finalized:
        messages.warning(request, 'This report is already in draft status.')
        return redirect('shops:report_detail', report_id=report.id)
    
    if request.method == 'POST':
        report.is_finalized = False
        report.finalized_by = None
        report.finalized_at = None
        report.save()
        messages.success(request, f'Report for {report.report_date} has been reverted to draft and can now be edited.')
    
    return redirect('shops:report_detail', report_id=report.id)





@login_required
def reports_list(request):
    """List all reports - filtered by user"""
    from django.db.models import Sum
    
    # Filter reports based on user permissions
    if request.user.is_superuser:
        reports = DailyShopReport.objects.all()
    else:
        reports = DailyShopReport.objects.filter(submitted_by=request.user)
    
    # Store original queryset for stats (before pagination)
    all_reports = reports
    
    # Filter by shop (only if superuser or if user has access to shop)
    shop_id = request.GET.get('shop')
    if shop_id:
        if request.user.is_superuser:
            reports = reports.filter(shop_id=shop_id)
            all_reports = all_reports.filter(shop_id=shop_id)
        else:
            # Regular users can only filter by shops they've submitted reports for
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
    
    # Calculate statistics from the filtered queryset
    finalized_count = all_reports.filter(is_finalized=True).count()
    draft_count = all_reports.filter(is_finalized=False).count()
    total_sales_value = all_reports.aggregate(total=Sum('shop_sales'))['total'] or 0
    
    # Pagination
    paginator = Paginator(reports, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # For shop filter dropdown - show only relevant shops
    if request.user.is_superuser:
        shops = ShopBranch.objects.filter(is_active=True)
    else:
        # Regular users see only shops they've submitted reports for
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
    }
    return render(request, 'shops/reports_list.html', context)


# ==================== SHOP BRANCH MANAGEMENT ====================

@login_required
@user_passes_test(is_superuser)
def shop_branches(request):
    """Manage shop branches - Superuser only"""
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


# ==================== BANK ACCOUNT MANAGEMENT ====================

@login_required
@user_passes_test(is_superuser)
def bank_accounts(request):
    """View all bank accounts - Superuser only"""
    accounts = BankAccount.objects.all()
    shops = ShopBranch.objects.filter(is_active=True)
    
    context = {
        'accounts': accounts,
        'shops': shops,
    }
    return render(request, 'shops/bank_accounts.html', context)


@login_required
@user_passes_test(is_superuser)
def add_bank_account(request):
    """Add a new bank account - Superuser only"""
    if request.method == 'POST':
        form = BankAccountForm(request.POST)
        if form.is_valid():
            form.save()
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
    """Edit a bank account - Superuser only"""
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


# ==================== M-PESA ACCOUNT MANAGEMENT ====================

@login_required
@user_passes_test(is_superuser)
def mpesa_accounts(request):
    """View all M-Pesa accounts - Superuser only"""
    accounts = MpesaAccount.objects.all()
    shops = ShopBranch.objects.filter(is_active=True)
    
    context = {
        'accounts': accounts,
        'shops': shops,
    }
    return render(request, 'shops/mpesa_accounts.html', context)


@login_required
@user_passes_test(is_superuser)
def add_mpesa_account(request):
    """Add a new M-Pesa account - Superuser only"""
    if request.method == 'POST':
        form = MpesaAccountForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'M-Pesa account added successfully!')
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
    """Edit an M-Pesa account - Superuser only"""
    account = get_object_or_404(MpesaAccount, id=account_id)
    
    if request.method == 'POST':
        form = MpesaAccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, 'M-Pesa account updated successfully!')
            return redirect('shops:mpesa_accounts')
    else:
        form = MpesaAccountForm(instance=account)
    
    context = {
        'form': form,
        'account': account,
        'title': 'Edit M-Pesa Account',
    }
    return render(request, 'shops/mpesa_account_form.html', context)


# ==================== M-PESA DAILY SUMMARY ====================

@login_required
@user_passes_test(is_superuser)
def mpesa_daily_summary(request, report_id):
    """Add or edit M-Pesa summary for a daily report - Superuser only"""
    daily_report = get_object_or_404(DailyShopReport, id=report_id)
    
    # Check if user is allowed
    if not request.user.is_superuser and daily_report.submitted_by != request.user:
        messages.error(request, 'You can only manage summaries for your own reports.')
        return redirect('shops:reports_list')
    
    # Check if summary already exists
    summary, created = MpesaDailySummary.objects.get_or_create(
        shop=daily_report.shop,
        report_date=daily_report.report_date,
        defaults={'daily_report': daily_report}
    )
    
    if request.method == 'POST':
        form = MpesaDailySummaryForm(request.POST, instance=summary)
        if form.is_valid():
            summary = form.save(commit=False)
            summary.daily_report = daily_report
            summary.save()
            
            # Update the daily report with M-Pesa closing balances
            daily_report.closing_mpesa_float = summary.closing_float
            daily_report.closing_mpesa_cash = summary.closing_cash
            daily_report.save()
            
            messages.success(request, 'M-Pesa summary saved successfully!')
            return redirect('shops:report_detail', report_id=report_id)
    else:
        form = MpesaDailySummaryForm(instance=summary)
    
    context = {
        'form': form,
        'daily_report': daily_report,
        'summary': summary,
        'mpesa_transactions': [],
    }
    return render(request, 'shops/mpesa_summary_form.html', context)


@login_required
@user_passes_test(is_superuser)
def reconcile_mpesa(request, summary_id):
    """Reconcile M-Pesa summary - Superuser only"""
    summary = get_object_or_404(MpesaDailySummary, id=summary_id)
    
    # Check permission
    if not request.user.is_superuser and summary.daily_report.submitted_by != request.user:
        messages.error(request, 'You can only reconcile your own summaries.')
        return redirect('shops:reports_list')
    
    if request.method == 'POST':
        # Calculate variances
        summary.calculate_variances()
        summary.is_reconciled = True
        summary.reconciled_by = request.user
        summary.reconciliation_date = timezone.now()
        summary.save()
        
        messages.success(request, f'M-Pesa summary for {summary.report_date} reconciled successfully!')
        return redirect('shops:report_detail', report_id=summary.daily_report.id)
    
    context = {
        'summary': summary,
    }
    return render(request, 'shops/reconcile_mpesa.html', context)


# ==================== DYNAMIC CHOICES MANAGEMENT ====================

@login_required
@user_passes_test(is_superuser)
def manage_choices(request):
    """Manage dynamic choices - Superuser only"""
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
    
    # Get all choices grouped by type
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
    """Soft delete a dynamic choice - Superuser only"""
    choice = get_object_or_404(DynamicChoice, id=choice_id)
    choice.is_active = False
    choice.save()
    messages.success(request, f'Choice "{choice.value}" deactivated successfully!')
    return redirect('shops:manage_choices')


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
        mpesa_accounts = shop.mpesa_accounts.filter(is_active=True)
        
        mpesa_data = [{
            'id': account.id,
            'name': account.account_name,
            'number': account.account_number,
            'type': account.account_type,
            'phone': account.phone_number,
        } for account in mpesa_accounts]
        
        return JsonResponse({'success': True, 'mpesa_accounts': mpesa_data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_report_summary(request, report_id):
    """AJAX endpoint to get report summary data for charts"""
    try:
        report = get_object_or_404(DailyShopReport, id=report_id)
        
        # Check permission
        if not request.user.is_superuser and report.submitted_by != request.user:
            return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
        
        # Get bank closing totals
        bank_closings = report.bank_closings.filter(is_active=True)
        bank_data = [{
            'bank': bc.bank_account.bank_name,
            'balance': float(bc.closing_balance)
        } for bc in bank_closings]
        
        # Get expense breakdown
        expenses_by_category = report.expenses.values('expense_category').annotate(
            total=models.Sum('amount')
        )
        expense_data = [{
            'category': item['expense_category'],
            'amount': float(item['total'])
        } for item in expenses_by_category]
        
        data = {
            'report_date': str(report.report_date),
            'shop_name': report.shop.name,
            'total_closing': float(report.total_closing_balance),
            'total_expenses': float(report.total_expenses),
            'shop_sales': float(report.shop_sales),
            'mpesa_float': float(report.closing_mpesa_float),
            'mpesa_cash': float(report.closing_mpesa_cash),
            'bank_breakdown': bank_data,
            'expense_breakdown': expense_data,
        }
        
        return JsonResponse({'success': True, 'data': data})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def weekly_sales_data(request):
    """AJAX endpoint for weekly sales chart data - filtered by user"""
    try:
        end_date = timezone.now().date()
        start_date = end_date - timezone.timedelta(days=6)
        
        # Get sales data for last 7 days - filtered by user
        sales_data = []
        days = []
        
        for i in range(7):
            current_date = start_date + timezone.timedelta(days=i)
            days.append(current_date.strftime('%a, %b %d'))
            
            # Filter reports based on user permissions
            if request.user.is_superuser:
                daily_total = DailyShopReport.objects.filter(
                    report_date=current_date,
                    is_finalized=True
                ).aggregate(total=models.Sum('shop_sales'))['total'] or 0
            else:
                daily_total = DailyShopReport.objects.filter(
                    report_date=current_date,
                    is_finalized=True,
                    submitted_by=request.user
                ).aggregate(total=models.Sum('shop_sales'))['total'] or 0
            
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




# shops/views.py - Add this function

@login_required
def weekly_transactions_data(request):
    """AJAX endpoint for weekly transactions chart data"""
    try:
        end_date = timezone.now().date()
        start_date = end_date - timezone.timedelta(days=6)
        
        # Get transaction data for last 7 days
        transactions_data = []
        days = []
        
        # Apply user filter (non-superusers only see their own data)
        if request.user.is_superuser:
            reports = DailyShopReport.objects.all()
        else:
            reports = DailyShopReport.objects.filter(submitted_by=request.user)
        
        for i in range(7):
            current_date = start_date + timezone.timedelta(days=i)
            days.append(current_date.strftime('%a, %b %d'))
            
            daily_total = reports.filter(
                report_date=current_date,
                is_finalized=True
            ).aggregate(total=models.Sum('shop_sales'))['total'] or 0
            
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





# ==================== EXPORT AND REPORTING VIEWS ====================

@login_required
@user_passes_test(is_superuser)
def export_reports_csv(request):
    """Export filtered reports to CSV - Superuser only"""
    import csv
    from django.http import HttpResponse
    
    reports = DailyShopReport.objects.all()
    
    # Apply same filters as reports_list
    shop_id = request.GET.get('shop')
    if shop_id:
        reports = reports.filter(shop_id=shop_id)
    
    from_date = request.GET.get('from_date')
    to_date = request.GET.get('to_date')
    
    if from_date:
        reports = reports.filter(report_date__gte=from_date)
    if to_date:
        reports = reports.filter(report_date__lte=to_date)
    
    # Create the HttpResponse object with CSV header
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="shop_reports.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Date', 'Shop', 'Submitted By', 'Shop Sales', 'M-Pesa Float', 
        'M-Pesa Cash', 'Total Bank Balance', 'Total Expenses', 
        'Total Closing Balance', 'Finalized'
    ])
    
    for report in reports:
        writer.writerow([
            report.report_date,
            report.shop.name,
            report.submitted_by.username,
            report.shop_sales,
            report.closing_mpesa_float,
            report.closing_mpesa_cash,
            sum([bc.closing_balance for bc in report.bank_closings.all()]),
            report.total_expenses,
            report.total_closing_balance,
            'Yes' if report.is_finalized else 'No'
        ])
    
    return response


# ==================== STATISTICS AND ANALYTICS ====================

@login_required
@user_passes_test(is_staff_or_admin)
def shop_statistics(request):
    """View statistics and analytics for shops - filtered by user"""
    from django.db.models import Sum, Avg, Count
    
    # Get date range from request or default to last 30 days
    end_date = timezone.now().date()
    start_date = request.GET.get('start_date', (end_date - timezone.timedelta(days=30)).isoformat())
    end_date = request.GET.get('end_date', end_date.isoformat())
    
    # Filter reports based on user permissions
    if request.user.is_superuser:
        reports = DailyShopReport.objects.filter(
            report_date__gte=start_date,
            report_date__lte=end_date,
            is_finalized=True
        )
    else:
        reports = DailyShopReport.objects.filter(
            report_date__gte=start_date,
            report_date__lte=end_date,
            is_finalized=True,
            submitted_by=request.user
        )
    
    # Overall statistics
    total_reports = reports.count()
    total_transactions = reports.aggregate(total=Sum('shop_sales'))['total'] or 0
    total_expenses = reports.aggregate(total=Sum('total_expenses'))['total'] or 0
    avg_transactions = reports.aggregate(avg=Avg('shop_sales'))['avg'] or 0
    
    # Statistics by shop - only shops user has access to
    if request.user.is_superuser:
        shops = ShopBranch.objects.filter(is_active=True)
    else:
        user_shop_ids = DailyShopReport.objects.filter(
            submitted_by=request.user
        ).values_list('shop_id', flat=True).distinct()
        shops = ShopBranch.objects.filter(id__in=user_shop_ids, is_active=True)
    
    shop_stats = []
    for shop in shops:
        shop_reports = reports.filter(shop=shop)
        shop_stats.append({
            'shop': shop,
            'report_count': shop_reports.count(),
            'total_transactions': shop_reports.aggregate(total=Sum('shop_sales'))['total'] or 0,
            'avg_transactions': shop_reports.aggregate(avg=Avg('shop_sales'))['avg'] or 0,
            'total_expenses': shop_reports.aggregate(total=Sum('total_expenses'))['total'] or 0,
        })
    
    context = {
        'start_date': start_date,
        'end_date': end_date,
        'total_reports': total_reports,
        'total_transactions': total_transactions,
        'total_expenses': total_expenses,
        'avg_transactions': avg_transactions,
        'shop_stats': shop_stats,
    }
    return render(request, 'shops/statistics.html', context)


@login_required
def expense_distribution(request):
    """AJAX endpoint for expense distribution chart data - filtered by user"""
    try:
        from django.db.models import Sum
        
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        
        # Filter expenses based on user permissions
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
        
        # Group by category
        expense_data = expenses.values('expense_category').annotate(
            total=Sum('amount')
        ).order_by('-total')
        
        categories = [item['expense_category'] for item in expense_data]
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