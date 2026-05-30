from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum, Count, Q  # Add Q here
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import JsonResponse
from decimal import Decimal
from datetime import timedelta
import logging

from .models import RepairJob, RepairJobExpense
from shops.models import ShopBranch
from staff.models import Staff  # Add this import

logger = logging.getLogger(__name__)



def dashboard(request):
    """Main dashboard with overview statistics"""
    from django.utils import timezone
    from datetime import timedelta
    from decimal import Decimal
    from shops.models import ShopBranch
    
    # Get filter from request
    shop_id = request.GET.get('shop')
    
    # Base queryset
    jobs = RepairJob.objects.all()
    
    # Apply shop filter if selected
    selected_shop = None
    if shop_id:
        selected_shop = get_object_or_404(ShopBranch, id=shop_id)
        jobs = jobs.filter(shop=selected_shop)
    
    # Statistics
    total_jobs = jobs.count()
    pending_jobs = jobs.filter(status='pending').count()
    in_progress_jobs = jobs.filter(status='in_progress').count()
    completed_jobs = jobs.filter(status='completed').count()
    picked_up_jobs = jobs.filter(status='picked_up').count()
    
    # Financial totals
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_paid = jobs.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    total_balance = jobs.aggregate(total=Sum('remaining_balance'))['total'] or Decimal('0.00')
    total_material_cost = jobs.aggregate(total=Sum('material_cost'))['total'] or Decimal('0.00')
    total_labor_cost = jobs.aggregate(total=Sum('labor_cost'))['total'] or Decimal('0.00')
    
    # Calculations
    net_profit = total_revenue - total_material_cost
    profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
    collection_percentage = (total_paid / total_revenue * 100) if total_revenue > 0 else 0
    material_percentage = (total_material_cost / total_revenue * 100) if total_revenue > 0 else 0
    labor_percentage = (total_labor_cost / total_revenue * 100) if total_revenue > 0 else 0
    
    # Recent jobs (last 10)
    recent_jobs = jobs.select_related('shop').order_by('-created_at')[:10]
    
    # Chart data (last 7 days)
    today = timezone.now().date()
    chart_labels = []
    revenue_data = []
    
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        chart_labels.append(f"'{date.strftime('%a, %d %b')}'")
        day_revenue = jobs.filter(created_at__date=date).aggregate(
            total=Sum('total_amount')
        )['total'] or 0
        revenue_data.append(float(day_revenue))
    
    # All shops for filter dropdown
    shops = ShopBranch.objects.filter(is_active=True)
    
    context = {
        # Stats
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        'in_progress_jobs': in_progress_jobs,
        'completed_jobs': completed_jobs,
        'picked_up_jobs': picked_up_jobs,
        
        # Financial
        'total_revenue': total_revenue,
        'total_paid': total_paid,
        'total_balance': total_balance,
        'total_material_cost': total_material_cost,
        'total_labor_cost': total_labor_cost,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        'collection_percentage': collection_percentage,
        'material_percentage': material_percentage,
        'labor_percentage': labor_percentage,
        
        # Data
        'recent_jobs': recent_jobs,
        'shops': shops,
        'selected_shop': selected_shop,
        
        # Chart
        'chart_labels': chart_labels,
        'revenue_data': revenue_data,
        
        # Date
        'today': today,
    }
    
    return render(request, 'workshop/dashboard.html', context)

def job_list(request):
    """List all repair jobs with filtering and pagination"""
    jobs = RepairJob.objects.select_related('shop').all().order_by('-created_at')
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        jobs = jobs.filter(
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query) |
            Q(device_type__icontains=search_query) |
            Q(device_model__icontains=search_query) |
            Q(technician_name__icontains=search_query)
        )
    
    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        jobs = jobs.filter(status=status_filter)
    
    # Filter by shop
    shop_filter = request.GET.get('shop', '')
    if shop_filter:
        jobs = jobs.filter(shop_id=shop_filter)
    
    # Calculate counts for stats summary
    pending_count = jobs.filter(status='pending').count()
    in_progress_count = jobs.filter(status='in_progress').count()
    completed_count = jobs.filter(status='completed').count()
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    # Pagination
    paginator = Paginator(jobs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get all shops for filter dropdown
    shops = ShopBranch.objects.filter(is_active=True)
    
    context = {
        'jobs': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'shop_filter': shop_filter,
        'shops': shops,
        'pending_count': pending_count,
        'in_progress_count': in_progress_count,
        'completed_count': completed_count,
        'total_revenue': total_revenue,
    }
    
    return render(request, 'workshop/job_list.html', context)



# Add this import at the top of workshop/views.py
from django.http import JsonResponse
from staff.models import Staff
from django.contrib.auth.models import Group
from django.db.models import Q

def job_create(request):
    """Create a new repair job and show receipt"""
    from staff.models import Staff
    from django.contrib.auth.models import Group
    
    if request.method == 'POST':
        shop_id = request.POST.get('shop')
        shop = None
        if shop_id:
            try:
                shop = ShopBranch.objects.get(id=shop_id)
            except ShopBranch.DoesNotExist:
                pass
        
        # Get technician ID
        technician_id = request.POST.get('technician_id')
        technician_name = ''
        
        if technician_id:
            try:
                staff_member = Staff.objects.get(id=technician_id)
                technician_name = staff_member.user.get_full_name() or staff_member.user.username
            except Staff.DoesNotExist:
                pass
        
        # Create the job
        job = RepairJob.objects.create(
            shop=shop,
            customer_name=request.POST.get('customer_name'),
            customer_phone=request.POST.get('customer_phone', ''),
            device_type=request.POST.get('device_type'),
            device_model=request.POST.get('device_model', ''),
            issue_description=request.POST.get('issue_description'),
            material_cost=Decimal(request.POST.get('material_cost', 0)),
            labor_cost=Decimal(request.POST.get('labor_cost', 0)),
            amount_paid=Decimal(request.POST.get('amount_paid', 0)),
            technician_name=technician_name,
            status=request.POST.get('status', 'pending'),
            warranty_days=int(request.POST.get('warranty_days', 30)),
            notes=request.POST.get('notes', ''),
        )
        
        messages.success(request, f'✅ Repair job for {job.customer_name} created successfully!')
        
        # Redirect to receipt page
        return redirect('workshop:job_receipt', job_id=job.id)
    
    # GET request - show form
    shops = ShopBranch.objects.filter(is_active=True)
    
    # Get technicians
    from staff.models import Staff
    from django.contrib.auth.models import Group
    
    technicians = Staff.objects.filter(
        Q(position__icontains='Technician') |
        Q(position__icontains='Tech')
    ).select_related('user', 'assigned_shop')
    
    technician_groups = Group.objects.filter(name__in=['Technician', 'Senior Technician', 'Workshop Technician'])
    if technician_groups.exists():
        group_technicians = Staff.objects.filter(user__groups__in=technician_groups)
        technicians = technicians | group_technicians
    
    technicians = technicians.distinct().order_by('user__first_name')
    
    context = {
        'shops': shops,
        'technicians': technicians,
        'title': 'Create Repair Job',
    }
    return render(request, 'workshop/job_form.html', context)


# Add this new view for receipt
def job_receipt(request, job_id):
    """Show receipt after creating a repair job"""
    job = get_object_or_404(RepairJob, id=job_id)
    
    context = {
        'job': job,
        'today': timezone.now(),
    }
    return render(request, 'workshop/job_receipt.html', context)


# Add this AJAX endpoint to get technicians by shop
def get_technicians_by_shop(request):
    """AJAX endpoint to get technicians filtered by shop"""
    shop_id = request.GET.get('shop_id')
    
    if not shop_id:
        return JsonResponse({'technicians': []})
    
    try:
        shop = ShopBranch.objects.get(id=shop_id)
    except ShopBranch.DoesNotExist:
        return JsonResponse({'technicians': []})
    
    # Get technicians assigned to this shop OR unassigned technicians
    from staff.models import Staff
    from django.contrib.auth.models import Group
    from django.db.models import Q
    
    # Get technicians by position
    technicians = Staff.objects.filter(
        Q(position__icontains='Technician') |
        Q(position__icontains='Tech')
    ).filter(
        Q(assigned_shop=shop) | Q(assigned_shop__isnull=True)
    ).select_related('user', 'assigned_shop')
    
    # Also get users in Technician groups
    technician_groups = Group.objects.filter(name__in=['Technician', 'Senior Technician', 'Workshop Technician'])
    if technician_groups.exists():
        group_technicians = Staff.objects.filter(
            user__groups__in=technician_groups
        ).filter(
            Q(assigned_shop=shop) | Q(assigned_shop__isnull=True)
        )
        technicians = technicians | group_technicians
    
    technicians = technicians.distinct().order_by('user__first_name')
    
    technicians_list = []
    for tech in technicians:
        tech_name = tech.user.get_full_name() or tech.user.username
        technicians_list.append({
            'id': tech.id,
            'name': tech_name,
            'position': tech.position or 'Technician',
            'shop_name': tech.assigned_shop.name if tech.assigned_shop else 'Unassigned',
            'shop_id': tech.assigned_shop.id if tech.assigned_shop else None,
        })
    
    return JsonResponse({'technicians': technicians_list})




def job_edit(request, job_id):
    """Edit an existing repair job"""
    job = get_object_or_404(RepairJob, id=job_id)
    
    if request.method == 'POST':
        # Update shop
        shop_id = request.POST.get('shop')
        if shop_id:
            try:
                job.shop = ShopBranch.objects.get(id=shop_id)
            except ShopBranch.DoesNotExist:
                job.shop = None
        else:
            job.shop = None
        
        # Get technician ID
        technician_id = request.POST.get('technician_id')
        technician_name = ''
        
        if technician_id:
            try:
                staff_member = Staff.objects.get(id=technician_id)
                technician_name = staff_member.user.get_full_name() or staff_member.user.username
            except Staff.DoesNotExist:
                pass
        else:
            technician_name = request.POST.get('technician_name', '')
        
        # Update all fields
        job.customer_name = request.POST.get('customer_name')
        job.customer_phone = request.POST.get('customer_phone', '')
        job.device_type = request.POST.get('device_type')
        job.device_model = request.POST.get('device_model', '')
        job.issue_description = request.POST.get('issue_description')
        job.material_cost = Decimal(request.POST.get('material_cost', 0))
        job.labor_cost = Decimal(request.POST.get('labor_cost', 0))
        job.amount_paid = Decimal(request.POST.get('amount_paid', 0))
        job.technician_name = technician_name
        job.status = request.POST.get('status', 'pending')
        job.warranty_days = int(request.POST.get('warranty_days', 30))
        job.notes = request.POST.get('notes', '')
        
        # Save will auto-calculate total_amount and remaining_balance
        job.save()
        
        messages.success(request, f'✅ Job for {job.customer_name} updated successfully!')
        return redirect('workshop:job_detail', job_id=job.id)
    
    # GET request - show form with existing data
    shops = ShopBranch.objects.filter(is_active=True)
    
    from staff.models import Staff
    from django.contrib.auth.models import Group
    
    technicians = Staff.objects.filter(
        Q(position__icontains='Technician') |
        Q(position__icontains='Tech')
    ).select_related('user')
    
    technician_group = Group.objects.filter(name__in=['Technician', 'Senior Technician', 'Workshop Technician']).first()
    if technician_group:
        group_technicians = Staff.objects.filter(user__groups=technician_group)
        technicians = technicians | group_technicians
    
    technicians = technicians.distinct().order_by('user__first_name')
    
    context = {
        'job': job,
        'shops': shops,
        'technicians': technicians,
        'title': 'Edit Repair Job',
    }
    return render(request, 'workshop/job_form.html', context)


def job_detail(request, job_id):
    """View detailed information about a repair job"""
    job = get_object_or_404(RepairJob, id=job_id)
    return render(request, 'workshop/job_detail.html', {'job': job})




def job_delete(request, job_id):
    """Delete a repair job"""
    job = get_object_or_404(RepairJob, id=job_id)
    
    if request.method == 'POST':
        customer_name = job.customer_name
        job.delete()
        messages.success(request, f'✅ Job for {customer_name} deleted successfully!')
        return redirect('workshop:job_list')
    
    return render(request, 'workshop/job_confirm_delete.html', {'job': job})


def add_payment(request, job_id):
    """Add a payment to a repair job"""
    job = get_object_or_404(RepairJob, id=job_id)
    
    if request.method == 'POST':
        additional_payment = Decimal(request.POST.get('additional_payment', 0))
        payment_method = request.POST.get('payment_method', 'cash')
        mpesa_code = request.POST.get('mpesa_code', '')
        
        if additional_payment > 0:
            job.amount_paid += additional_payment
            job.payment_method = payment_method
            if mpesa_code:
                job.mpesa_transaction_code = mpesa_code
            job.save()
            
            messages.success(request, f'✅ Payment of ${additional_payment} added for {job.customer_name}')
            if job.remaining_balance == 0:
                messages.info(request, '🎉 This job is now fully paid!')
        else:
            messages.error(request, 'Please enter a valid payment amount')
        
        return redirect('workshop:job_detail', job_id=job.id)
    
    return render(request, 'workshop/add_payment.html', {'job': job})


def shop_jobs(request, shop_id):
    """View all jobs for a specific shop"""
    shop = get_object_or_404(ShopBranch, id=shop_id)
    jobs = shop.repair_jobs.all().order_by('-created_at')
    
    context = {
        'shop': shop,
        'jobs': jobs,
    }
    return render(request, 'workshop/shop_jobs.html', context)

def reports(request):
    """Generate financial reports with charts and analytics"""
    from django.utils import timezone
    from datetime import timedelta
    from decimal import Decimal
    from django.db.models import Sum, Count, Q
    from shops.models import ShopBranch
    
    today = timezone.now().date()
    default_from = today - timedelta(days=30)
    
    # Get filter parameters
    date_from = request.GET.get('date_from', default_from.isoformat())
    date_to = request.GET.get('date_to', today.isoformat())
    shop_filter = request.GET.get('shop', '')
    
    # Base queryset
    jobs = RepairJob.objects.all()
    
    # Apply date filters
    if date_from:
        jobs = jobs.filter(created_at__date__gte=date_from)
    if date_to:
        jobs = jobs.filter(created_at__date__lte=date_to)
    
    # Apply shop filter
    selected_shop_id = shop_filter
    if shop_filter:
        jobs = jobs.filter(shop_id=shop_filter)
    
    # Statistics
    total_jobs = jobs.count()
    pending_jobs = jobs.filter(status='pending').count()
    in_progress_jobs = jobs.filter(status='in_progress').count()
    completed_jobs = jobs.filter(status='completed').count()
    picked_up_jobs = jobs.filter(status='picked_up').count()
    
    # Financial totals
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_paid = jobs.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    total_balance = jobs.aggregate(total=Sum('remaining_balance'))['total'] or Decimal('0.00')
    total_material_cost = jobs.aggregate(total=Sum('material_cost'))['total'] or Decimal('0.00')
    total_labor_cost = jobs.aggregate(total=Sum('labor_cost'))['total'] or Decimal('0.00')
    
    # Calculations
    net_profit = total_revenue - total_material_cost
    profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
    collection_percentage = (total_paid / total_revenue * 100) if total_revenue > 0 else 0
    material_percentage = (total_material_cost / total_revenue * 100) if total_revenue > 0 else 0
    labor_percentage = (total_labor_cost / total_revenue * 100) if total_revenue > 0 else 0
    avg_job_value = total_revenue / total_jobs if total_jobs > 0 else 0
    
    # Monthly target
    monthly_revenue = jobs.filter(created_at__month=today.month).aggregate(
        total=Sum('total_amount')
    )['total'] or Decimal('0.00')
    monthly_target = Decimal('10000.00')
    monthly_progress = (monthly_revenue / monthly_target * 100) if monthly_target > 0 else 0
    monthly_remaining = monthly_target - monthly_revenue
    
    # Chart data - Daily revenue (last 30 days)
    chart_labels = []
    revenue_data = []
    for i in range(29, -1, -1):
        date = today - timedelta(days=i)
        chart_labels.append(f"'{date.strftime('%d %b')}'")
        day_revenue = jobs.filter(created_at__date=date).aggregate(
            total=Sum('total_amount')
        )['total'] or 0
        revenue_data.append(float(day_revenue))
    
    # Status distribution data
    status_data = [pending_jobs, in_progress_jobs, completed_jobs, picked_up_jobs]
    
    # Shop performance
    shop_performance = []
    shop_labels = []
    shop_revenue_data = []
    
    shops = ShopBranch.objects.filter(is_active=True)
    for shop in shops:
        shop_jobs = jobs.filter(shop=shop)
        shop_total = shop_jobs.aggregate(total=Sum('total_amount'))['total'] or 0
        shop_material = shop_jobs.aggregate(total=Sum('material_cost'))['total'] or 0
        shop_completed = shop_jobs.filter(status='completed').count()
        
        shop_performance.append({
            'name': shop.name,
            'total_jobs': shop_jobs.count(),
            'completed_jobs': shop_completed,
            'total_revenue': shop_total,
            'total_material': shop_material,
            'net_profit': shop_total - shop_material,
            'avg_job_value': shop_total / shop_jobs.count() if shop_jobs.count() > 0 else 0,
        })
        shop_labels.append(f"'{shop.name[:10]}'")
        shop_revenue_data.append(float(shop_total))
    
    # Technician performance
    technician_performance = []
    technicians = RepairJob.objects.exclude(technician_name__isnull=True).exclude(
        technician_name=''
    ).values_list('technician_name', flat=True).distinct()
    
    for tech in technicians:
        tech_jobs = jobs.filter(technician_name=tech)
        tech_completed = tech_jobs.filter(status='completed')
        
        # Calculate average completion time
        avg_hours = 0
        if tech_completed.exists():
            total_hours = 0
            for job in tech_completed:
                if job.completed_at:
                    time_diff = job.completed_at - job.created_at
                    total_hours += time_diff.total_seconds() / 3600
            avg_hours = total_hours / tech_completed.count()
        
        technician_performance.append({
            'name': tech,
            'completed_jobs': tech_completed.count(),
            'in_progress_jobs': tech_jobs.filter(status='in_progress').count(),
            'total_revenue': tech_jobs.aggregate(total=Sum('total_amount'))['total'] or 0,
            'avg_completion_hours': round(avg_hours, 1),
        })
    
    # Device type statistics
    device_stats = jobs.values('device_type').annotate(
        count=Count('id')
    ).order_by('-count')[:5]
    
    device_labels = [f"'{d['device_type']}'" for d in device_stats]
    device_data = [d['count'] for d in device_stats]
    
    # Recent completed jobs
    recent_completed = jobs.filter(status='completed').order_by('-completed_at')[:10]
    
    context = {
        # Date info
        'today': today.isoformat(),
        'date_from': date_from,
        'date_to': date_to,
        'month_ago': (today - timedelta(days=30)).isoformat(),
        'selected_shop_id': selected_shop_id,
        
        # Statistics
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        'in_progress_jobs': in_progress_jobs,
        'completed_jobs': completed_jobs,
        'picked_up_jobs': picked_up_jobs,
        
        # Financial
        'total_revenue': total_revenue,
        'total_paid': total_paid,
        'total_balance': total_balance,
        'total_material_cost': total_material_cost,
        'total_labor_cost': total_labor_cost,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        'collection_percentage': collection_percentage,
        'material_percentage': material_percentage,
        'labor_percentage': labor_percentage,
        'avg_job_value': avg_job_value,
        
        # Monthly targets
        'monthly_revenue': monthly_revenue,
        'monthly_target': monthly_target,
        'monthly_progress': monthly_progress,
        'monthly_remaining': monthly_remaining,
        
        # Chart data
        'chart_labels': chart_labels,
        'revenue_data': revenue_data,
        'status_data': status_data,
        'shop_labels': shop_labels,
        'shop_revenue_data': shop_revenue_data,
        'device_labels': device_labels,
        'device_data': device_data,
        
        # Tables
        'shop_performance': shop_performance,
        'technician_performance': technician_performance,
        'recent_completed': recent_completed,
        
        # Filter dropdown
        'shops': shops,
    }
    
    return render(request, 'workshop/reports.html', context)

def shop_jobs(request, shop_id):
    """View all jobs for a specific shop"""
    from shops.models import ShopBranch
    
    shop = get_object_or_404(ShopBranch, id=shop_id)
    jobs = shop.repair_jobs.all().order_by('-created_at')
    
    context = {
        'shop': shop,
        'jobs': jobs,
    }
    return render(request, 'workshop/shop_jobs.html', context)


# staff/views.py
import json
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from workshop.models import RepairJob
from staff.models import Staff
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

@login_required
def technician_update_job_status(request, job_id):
    """Update job status for technician via AJAX"""
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        job = get_object_or_404(RepairJob, id=job_id)
        
        # Get technician name
        try:
            staff_profile = Staff.objects.get(user=request.user)
            technician_name = staff_profile.user.get_full_name() or staff_profile.user.username
        except:
            technician_name = request.user.get_full_name() or request.user.username
        
        # Parse request body - handle both JSON and form data
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                new_status = data.get('status')
            except json.JSONDecodeError:
                return JsonResponse({'error': 'Invalid JSON data'}, status=400)
        else:
            new_status = request.POST.get('status')
        
        # Log for debugging
        logger.info(f"Received status update for job {job_id}: {new_status}")
        
        # Valid statuses - map common variations
        status_mapping = {
            'in_progress': 'in_progress',
            'inprogress': 'in_progress',
            'completed': 'completed',
            'complete': 'completed',
            'pending': 'pending',
            'picked_up': 'picked_up',
            'pickedup': 'picked_up',
        }
        
        # Get the correct status value
        new_status = status_mapping.get(new_status, new_status)
        
        # Validate status
        valid_statuses = ['pending', 'in_progress', 'completed', 'picked_up']
        if new_status not in valid_statuses:
            return JsonResponse({
                'error': f'Invalid status: {new_status}. Valid statuses: {valid_statuses}'
            }, status=400)
        
        # Update status
        old_status = job.status
        job.status = new_status
        
        # If moving to in_progress, assign technician
        if new_status == 'in_progress' and not job.technician_name:
            job.technician_name = technician_name
        
        # Set completion dates
        if new_status == 'completed' and not job.completed_at:
            job.completed_at = timezone.now()
        
        if new_status == 'picked_up' and not job.picked_up_at:
            job.picked_up_at = timezone.now()
        
        job.save()
        
        # Get status display name
        status_display = dict(job._meta.get_field('status').choices).get(new_status, new_status)
        
        logger.info(f"Job #{job.id} status updated from {old_status} to {new_status} by {request.user.username}")
        
        return JsonResponse({
            'success': True,
            'message': f'Job status updated to {status_display}',
            'new_status': new_status,
            'status_display': status_display
        })
        
    except Exception as e:
        logger.error(f"Error updating job status: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
    


def pickup_page(request):
    """Page to search for jobs ready for pickup"""
    return render(request, 'workshop/pickup.html')


def search_job_for_pickup(request):
    """AJAX endpoint to search for job by ID for pickup"""
    from django.http import JsonResponse
    
    job_id = request.GET.get('job_id')
    if not job_id:
        return JsonResponse({'error': 'Please enter Job ID'}, status=400)
    
    try:
        job = RepairJob.objects.get(id=job_id)
    except RepairJob.DoesNotExist:
        return JsonResponse({'error': 'Job not found'}, status=404)
    
    # Check if job is completed (ready for pickup)
    if job.status != 'completed':
        return JsonResponse({
            'error': f'This job is currently {job.get_status_display()}. Only completed jobs can be picked up.',
            'current_status': job.status
        }, status=400)
    
    # Return job details
    return JsonResponse({
        'success': True,
        'job': {
            'id': job.id,
            'customer_name': job.customer_name,
            'customer_phone': job.customer_phone or 'Not provided',
            'device_type': job.device_type,
            'device_model': job.device_model or 'Not specified',
            'issue_description': job.issue_description,
            'technician_name': job.technician_name or 'Not assigned',
            'total_amount': str(job.total_amount),
            'amount_paid': str(job.amount_paid),
            'remaining_balance': str(job.remaining_balance),
            'warranty_days': job.warranty_days,
            'completed_at': job.completed_at.strftime('%Y-%m-%d %H:%M') if job.completed_at else None,
            'shop_name': job.shop.name if job.shop else 'Not assigned',
            'notes': job.notes or '',
        }
    })


def process_pickup(request, job_id):
    """Process job pickup - change status from completed to picked_up"""
    from django.http import JsonResponse
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        job = get_object_or_404(RepairJob, id=job_id)
        
        # Check if job is completed
        if job.status != 'completed':
            return JsonResponse({
                'error': f'Job is currently {job.get_status_display()}. Only completed jobs can be picked up.'
            }, status=400)
        
        # Update status to picked_up
        job.status = 'picked_up'
        job.picked_up_at = timezone.now()
        job.save()
        
        return JsonResponse({
            'success': True,
            'message': f'Job #{job.id} has been successfully handed over to {job.customer_name}',
            'job_id': job.id,
            'customer_name': job.customer_name
        })
        
    except Exception as e:
        logger.error(f"Error processing pickup: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)