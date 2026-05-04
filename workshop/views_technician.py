from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import JsonResponse
from datetime import timedelta
from decimal import Decimal
import logging

from .models import RepairJob, RepairJobExpense
from shops.models import ShopBranch

# Import staff-related models for integration
from staff.models import Staff
from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)


def is_technician(user):
    """Check if user is a technician (has technician role or is in tech group)"""
    if user.is_superuser:
        return True
    
    # Check if user has technician profile
    try:
        staff = Staff.objects.get(user=user)
        if staff.position and 'technician' in staff.position.lower():
            return True
    except:
        pass
    
    # Check if user is in Technician group
    if user.groups.filter(name__icontains='technician').exists():
        return True
    
    return False


@login_required
def technician_dashboard(request):
    """Main dashboard for technicians - shows assigned repair jobs"""
    
    # Check if user is technician
    if not is_technician(request.user):
        messages.error(request, "Access denied. Technician privileges required.")
        return redirect('staff:staff_dashboard')
    
    # Get technician's staff profile
    try:
        staff_profile = Staff.objects.get(user=request.user)
        technician_name = staff_profile.user.get_full_name() or staff_profile.user.username
        assigned_shop = staff_profile.assigned_shop
    except:
        technician_name = request.user.get_full_name() or request.user.username
        assigned_shop = None
    
    # Get filter parameters
    status_filter = request.GET.get('status', '')
    shop_filter = request.GET.get('shop', '')
    
    # Base queryset - jobs assigned to this technician OR all jobs if manager
    if request.user.is_superuser or request.user.groups.filter(name__icontains='manager').exists():
        # Managers/superusers see all jobs
        jobs = RepairJob.objects.select_related('shop').all()
    else:
        # Regular technicians see only their assigned jobs
        jobs = RepairJob.objects.filter(technician_name=technician_name).select_related('shop')
    
    # Apply filters
    if status_filter:
        jobs = jobs.filter(status=status_filter)
    if shop_filter:
        jobs = jobs.filter(shop_id=shop_filter)
    
    # Statistics
    total_jobs = jobs.count()
    pending_jobs = jobs.filter(status='pending').count()
    in_progress_jobs = jobs.filter(status='in_progress').count()
    completed_jobs = jobs.filter(status='completed').count()
    picked_up_jobs = jobs.filter(status='picked_up').count()
    
    # Financial stats for technician's jobs
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_paid = jobs.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    total_balance = jobs.aggregate(total=Sum('remaining_balance'))['total'] or Decimal('0.00')
    
    # Recent jobs (last 10)
    recent_jobs = jobs.order_by('-created_at')[:10]
    
    # Jobs that need attention (overdue or pending for > 3 days)
    three_days_ago = timezone.now() - timedelta(days=3)
    urgent_jobs = jobs.filter(
        status__in=['pending', 'in_progress'],
        created_at__lte=three_days_ago
    ).count()
    
    # All shops for filter dropdown
    shops = ShopBranch.objects.filter(is_active=True)
    
    # Weekly performance chart data
    last_7_days = []
    jobs_by_day = []
    revenue_by_day = []
    
    for i in range(6, -1, -1):
        date = timezone.now().date() - timedelta(days=i)
        last_7_days.append(date.strftime('%a, %d %b'))
        
        day_jobs = jobs.filter(created_at__date=date)
        jobs_by_day.append(day_jobs.count())
        
        day_revenue = day_jobs.aggregate(total=Sum('total_amount'))['total'] or 0
        revenue_by_day.append(float(day_revenue))
    
    context = {
        'technician_name': technician_name,
        'assigned_shop': assigned_shop,
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        'in_progress_jobs': in_progress_jobs,
        'completed_jobs': completed_jobs,
        'picked_up_jobs': picked_up_jobs,
        'total_revenue': total_revenue,
        'total_paid': total_paid,
        'total_balance': total_balance,
        'recent_jobs': recent_jobs,
        'urgent_jobs': urgent_jobs,
        'shops': shops,
        'status_filter': status_filter,
        'shop_filter': shop_filter,
        'chart_labels': last_7_days,
        'chart_data': jobs_by_day,
        'revenue_data': revenue_by_day,
        'today': timezone.now().date(),
    }
    
    return render(request, 'workshop/technician/dashboard.html', context)


@login_required
def technician_jobs(request):
    """List view of jobs for technician"""
    
    if not is_technician(request.user):
        messages.error(request, "Access denied.")
        return redirect('staff:staff_dashboard')
    
    # Get technician name
    try:
        staff_profile = Staff.objects.get(user=request.user)
        technician_name = staff_profile.user.get_full_name() or staff_profile.user.username
    except:
        technician_name = request.user.get_full_name() or request.user.username
    
    # Base queryset
    if request.user.is_superuser or request.user.groups.filter(name__icontains='manager').exists():
        jobs = RepairJob.objects.select_related('shop').all()
    else:
        jobs = RepairJob.objects.filter(technician_name=technician_name).select_related('shop')
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        jobs = jobs.filter(
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query) |
            Q(device_type__icontains=search_query) |
            Q(device_model__icontains=search_query) |
            Q(issue_description__icontains=search_query)
        )
    
    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        jobs = jobs.filter(status=status_filter)
    
    # Filter by shop
    shop_filter = request.GET.get('shop', '')
    if shop_filter:
        jobs = jobs.filter(shop_id=shop_filter)
    
    # Pagination
    paginator = Paginator(jobs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get all shops for filter
    shops = ShopBranch.objects.filter(is_active=True)
    
    context = {
        'jobs': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'shop_filter': shop_filter,
        'shops': shops,
        'technician_name': technician_name,
    }
    
    return render(request, 'workshop/technician/jobs_list.html', context)


@login_required
def technician_job_detail(request, job_id):
    """View job details for technician"""
    
    if not is_technician(request.user):
        messages.error(request, "Access denied.")
        return redirect('staff:staff_dashboard')
    
    job = get_object_or_404(RepairJob, id=job_id)
    
    # Check permission (if not manager/superuser, only their jobs)
    if not (request.user.is_superuser or request.user.groups.filter(name__icontains='manager').exists()):
        try:
            staff_profile = Staff.objects.get(user=request.user)
            technician_name = staff_profile.user.get_full_name() or staff_profile.user.username
            if job.technician_name != technician_name:
                messages.error(request, "You don't have permission to view this job.")
                return redirect('workshop:technician_dashboard')
        except:
            if job.technician_name != (request.user.get_full_name() or request.user.username):
                messages.error(request, "You don't have permission to view this job.")
                return redirect('workshop:technician_dashboard')
    
    # Get expenses for this job
    expenses = job.expenses.all()
    
    # Calculate progress percentage
    progress_percentage = 0
    if job.status == 'pending':
        progress_percentage = 25
    elif job.status == 'in_progress':
        progress_percentage = 50
    elif job.status == 'completed':
        progress_percentage = 75
    elif job.status == 'picked_up':
        progress_percentage = 100
    
    context = {
        'job': job,
        'expenses': expenses,
        'progress_percentage': progress_percentage,
    }
    
    return render(request, 'workshop/technician/job_detail.html', context)


@login_required
def technician_update_status(request, job_id):
    """Update job status (AJAX or POST)"""
    
    if not is_technician(request.user):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    job = get_object_or_404(RepairJob, id=job_id)
    
    # Check permission
    if not (request.user.is_superuser or request.user.groups.filter(name__icontains='manager').exists()):
        try:
            staff_profile = Staff.objects.get(user=request.user)
            technician_name = staff_profile.user.get_full_name() or staff_profile.user.username
            if job.technician_name != technician_name:
                return JsonResponse({'error': 'Permission denied'}, status=403)
        except:
            if job.technician_name != (request.user.get_full_name() or request.user.username):
                return JsonResponse({'error': 'Permission denied'}, status=403)
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        notes = request.POST.get('notes', '')
        
        if new_status in dict(RepairJob._meta.get_field('status').choices):
            old_status = job.status
            job.status = new_status
            job.notes = notes if notes else job.notes
            job.save()
            
            # If job is completed, also update completed_at
            if new_status == 'completed' and not job.completed_at:
                job.completed_at = timezone.now()
                job.save()
            
            # If job is picked up, update picked_up_at
            if new_status == 'picked_up' and not job.picked_up_at:
                job.picked_up_at = timezone.now()
                job.save()
            
            logger.info(f"Job #{job.id} status updated from {old_status} to {new_status} by {request.user.username}")
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Job status updated to {job.get_status_display()}',
                    'new_status': new_status,
                    'status_display': job.get_status_display(),
                })
            else:
                messages.success(request, f'Job status updated to {job.get_status_display()}')
                return redirect('workshop:technician_job_detail', job_id=job.id)
    
    return redirect('workshop:technician_job_detail', job_id=job.id)


@login_required
def technician_add_expense(request, job_id):
    """Add expense for a repair job"""
    
    if not is_technician(request.user):
        messages.error(request, "Access denied.")
        return redirect('staff:staff_dashboard')
    
    job = get_object_or_404(RepairJob, id=job_id)
    
    # Check permission
    if not (request.user.is_superuser or request.user.groups.filter(name__icontains='manager').exists()):
        try:
            staff_profile = Staff.objects.get(user=request.user)
            technician_name = staff_profile.user.get_full_name() or staff_profile.user.username
            if job.technician_name != technician_name:
                messages.error(request, "Permission denied.")
                return redirect('workshop:technician_dashboard')
        except:
            if job.technician_name != (request.user.get_full_name() or request.user.username):
                messages.error(request, "Permission denied.")
                return redirect('workshop:technician_dashboard')
    
    if request.method == 'POST':
        description = request.POST.get('description')
        amount = Decimal(request.POST.get('amount', 0))
        
        if description and amount > 0:
            expense = RepairJobExpense.objects.create(
                repair_job=job,
                description=description,
                amount=amount
            )
            messages.success(request, f'Expense added: {description} - ${amount}')
            
            # Update material cost if it's a material expense
            if 'material' in description.lower():
                job.material_cost += amount
                job.save()
                messages.info(request, f'Material cost updated to ${job.material_cost}')
            
            return redirect('workshop:technician_job_detail', job_id=job.id)
        else:
            messages.error(request, 'Please provide description and valid amount')
    
    context = {
        'job': job,
    }
    return render(request, 'workshop/technician/add_expense.html', context)


@login_required
def technician_my_performance(request):
    """Performance report for technician"""
    
    if not is_technician(request.user):
        messages.error(request, "Access denied.")
        return redirect('staff:staff_dashboard')
    
    # Get technician name
    try:
        staff_profile = Staff.objects.get(user=request.user)
        technician_name = staff_profile.user.get_full_name() or staff_profile.user.username
    except:
        technician_name = request.user.get_full_name() or request.user.username
    
    # Get date range filters
    today = timezone.now().date()
    date_from = request.GET.get('date_from', (today - timedelta(days=30)).isoformat())
    date_to = request.GET.get('date_to', today.isoformat())
    
    # Filter jobs by date range
    jobs = RepairJob.objects.filter(
        technician_name=technician_name,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to
    )
    
    # Statistics
    total_jobs = jobs.count()
    completed_jobs = jobs.filter(status='completed').count()
    in_progress_jobs = jobs.filter(status='in_progress').count()
    
    # Financial performance
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_material_cost = jobs.aggregate(total=Sum('material_cost'))['total'] or Decimal('0.00')
    total_labor_cost = jobs.aggregate(total=Sum('labor_cost'))['total'] or Decimal('0.00')
    net_profit = total_revenue - total_material_cost
    
    # Average job value
    avg_job_value = total_revenue / total_jobs if total_jobs > 0 else 0
    
    # Average completion time (for completed jobs)
    completed_jobs_list = jobs.filter(status='completed', completed_at__isnull=False)
    avg_completion_hours = 0
    if completed_jobs_list.exists():
        total_hours = 0
        for job in completed_jobs_list:
            time_diff = job.completed_at - job.created_at
            total_hours += time_diff.total_seconds() / 3600
        avg_completion_hours = total_hours / completed_jobs_list.count()
    
    # Jobs by status pie chart data
    status_counts = {
        'pending': jobs.filter(status='pending').count(),
        'in_progress': jobs.filter(status='in_progress').count(),
        'completed': jobs.filter(status='completed').count(),
        'picked_up': jobs.filter(status='picked_up').count(),
    }
    
    # Monthly performance chart (last 6 months)
    monthly_labels = []
    monthly_jobs = []
    monthly_revenue = []
    
    for i in range(5, -1, -1):
        month_date = today.replace(day=1) - timedelta(days=30*i)
        month_start = month_date.replace(day=1)
        if month_date.month == 12:
            month_end = month_date.replace(year=month_date.year+1, month=1, day=1) - timedelta(days=1)
        else:
            month_end = month_date.replace(month=month_date.month+1, day=1) - timedelta(days=1)
        
        monthly_labels.append(month_date.strftime('%b %Y'))
        
        month_jobs = jobs.filter(
            created_at__date__gte=month_start,
            created_at__date__lte=month_end
        )
        monthly_jobs.append(month_jobs.count())
        monthly_revenue.append(float(month_jobs.aggregate(total=Sum('total_amount'))['total'] or 0))
    
    context = {
        'technician_name': technician_name,
        'date_from': date_from,
        'date_to': date_to,
        'total_jobs': total_jobs,
        'completed_jobs': completed_jobs,
        'in_progress_jobs': in_progress_jobs,
        'total_revenue': total_revenue,
        'total_material_cost': total_material_cost,
        'total_labor_cost': total_labor_cost,
        'net_profit': net_profit,
        'avg_job_value': avg_job_value,
        'avg_completion_hours': round(avg_completion_hours, 1),
        'status_counts': status_counts,
        'monthly_labels': monthly_labels,
        'monthly_jobs': monthly_jobs,
        'monthly_revenue': monthly_revenue,
    }
    
    return render(request, 'workshop/technician/performance.html', context)


# Quick AJAX endpoints for technician dashboard
@login_required
def technician_take_job(request, job_id):
    """Assign a job to current technician (take ownership)"""
    
    if not is_technician(request.user):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    job = get_object_or_404(RepairJob, id=job_id)
    
    # Check if job is already assigned
    if job.technician_name:
        return JsonResponse({'error': 'Job already assigned to another technician'}, status=400)
    
    # Get technician name
    try:
        staff_profile = Staff.objects.get(user=request.user)
        technician_name = staff_profile.user.get_full_name() or staff_profile.user.username
    except:
        technician_name = request.user.get_full_name() or request.user.username
    
    # Assign job
    job.technician_name = technician_name
    job.status = 'in_progress'
    job.save()
    
    logger.info(f"Job #{job.id} taken by technician {technician_name}")
    
    return JsonResponse({
        'success': True,
        'message': f'Job #{job.id} assigned to you',
        'technician_name': technician_name
    })


@login_required
def technician_search_customer(request):
    """Search for customers by phone or name (AJAX)"""
    
    if not is_technician(request.user):
        return JsonResponse({'error': 'Access denied'}, status=403)
    
    search_term = request.GET.get('q', '').strip()
    
    if len(search_term) < 2:
        return JsonResponse({'results': []})
    
    # Search in RepairJob model
    jobs = RepairJob.objects.filter(
        Q(customer_name__icontains=search_term) |
        Q(customer_phone__icontains=search_term)
    ).values('customer_name', 'customer_phone', 'device_type', 'status').distinct()[:10]
    
    results = []
    for job in jobs:
        results.append({
            'name': job['customer_name'],
            'phone': job['customer_phone'],
            'device': job['device_type'],
            'status': job['status'],
        })
    
    return JsonResponse({'results': results})