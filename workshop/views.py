from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import JsonResponse
from datetime import timedelta
from decimal import Decimal
import json
import logging

from .models import RepairJob, RepairJobExpense
from shops.models import ShopBranch
from staff.models import Staff
from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)


# ============================================
# WORKSHOP DASHBOARD
# ============================================

@login_required
def dashboard(request):
    """Main workshop dashboard"""
    
    jobs = RepairJob.objects.select_related('shop').all()
    
    # Statistics
    total_jobs = jobs.count()
    pending_jobs = jobs.filter(status='pending').count()
    in_progress_jobs = jobs.filter(status='in_progress').count()
    completed_jobs = jobs.filter(status='completed').count()
    picked_up_jobs = jobs.filter(status='picked_up').count()
    
    # Financial stats
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_paid = jobs.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    total_balance = jobs.aggregate(total=Sum('remaining_balance'))['total'] or Decimal('0.00')
    total_material = jobs.aggregate(total=Sum('material_cost'))['total'] or Decimal('0.00')
    
    # Recent jobs
    recent_jobs = jobs.order_by('-created_at')[:10]
    
    # Chart data (last 7 days)
    chart_labels = []
    revenue_data = []
    
    for i in range(6, -1, -1):
        date = timezone.now().date() - timedelta(days=i)
        chart_labels.append(date.strftime('%a, %d %b'))
        day_revenue = jobs.filter(created_at__date=date).aggregate(total=Sum('total_amount'))['total'] or 0
        revenue_data.append(float(day_revenue))
    
    context = {
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        'in_progress_jobs': in_progress_jobs,
        'completed_jobs': completed_jobs,
        'picked_up_jobs': picked_up_jobs,
        'total_revenue': total_revenue,
        'total_paid': total_paid,
        'total_balance': total_balance,
        'total_material': total_material,
        'net_profit': total_revenue - total_material,
        'recent_jobs': recent_jobs,
        'chart_labels': json.dumps(chart_labels),
        'revenue_data': json.dumps(revenue_data),
    }
    
    return render(request, 'workshop/dashboard.html', context)


# ============================================
# JOB MANAGEMENT
# ============================================

@login_required
def job_list(request):
    """List all repair jobs"""
    
    jobs = RepairJob.objects.select_related('shop').all()
    
    # Search and filters
    search = request.GET.get('search', '')
    if search:
        jobs = jobs.filter(
            Q(customer_name__icontains=search) |
            Q(customer_phone__icontains=search) |
            Q(device_type__icontains=search)
        )
    
    status_filter = request.GET.get('status', '')
    if status_filter:
        jobs = jobs.filter(status=status_filter)
    
    shop_filter = request.GET.get('shop', '')
    if shop_filter:
        jobs = jobs.filter(shop_id=shop_filter)
    
    # Stats
    pending_count = RepairJob.objects.filter(status='pending').count()
    in_progress_count = RepairJob.objects.filter(status='in_progress').count()
    completed_count = RepairJob.objects.filter(status='completed').count()
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    # Pagination
    paginator = Paginator(jobs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    shops = ShopBranch.objects.filter(is_active=True)
    
    context = {
        'jobs': page_obj,
        'search_query': search,
        'status_filter': status_filter,
        'shop_filter': shop_filter,
        'shops': shops,
        'pending_count': pending_count,
        'in_progress_count': in_progress_count,
        'completed_count': completed_count,
        'total_revenue': total_revenue,
    }
    
    return render(request, 'workshop/job_list.html', context)


@login_required
def job_create(request):
    """Create new repair job"""
    
    if request.method == 'POST':
        try:
            # Get form data
            customer_name = request.POST.get('customer_name')
            customer_phone = request.POST.get('customer_phone')
            device_type = request.POST.get('device_type')
            device_model = request.POST.get('device_model')
            issue_description = request.POST.get('issue_description')
            shop_id = request.POST.get('shop')
            technician_id = request.POST.get('technician_id')  # ADD THIS LINE
            material_cost = Decimal(request.POST.get('material_cost', 0))
            labor_cost = Decimal(request.POST.get('labor_cost', 0))
            amount_paid = Decimal(request.POST.get('amount_paid', 0))
            warranty_days = request.POST.get('warranty_days', 30)
            status = request.POST.get('status', 'pending')  # ADD THIS LINE
            notes = request.POST.get('notes', '')
            
            # Validate required fields
            if not all([customer_name, device_type, issue_description, shop_id]):
                messages.error(request, 'Please fill in all required fields.')
                shops = ShopBranch.objects.filter(is_active=True)
                return render(request, 'workshop/job_form.html', {'shops': shops, 'is_edit': False})
            
            # Get shop
            shop = ShopBranch.objects.get(id=shop_id)
            
            # Get technician name if selected
            technician_name = None
            if technician_id:
                try:
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    technician = User.objects.get(id=technician_id)
                    technician_name = technician.get_full_name() or technician.username
                except User.DoesNotExist:
                    pass
            
            # Calculate totals
            total_amount = material_cost + labor_cost
            remaining_balance = total_amount - amount_paid
            
            # Create job with all fields
            job = RepairJob.objects.create(
                customer_name=customer_name,
                customer_phone=customer_phone,
                device_type=device_type,
                device_model=device_model,
                issue_description=issue_description,
                shop=shop,
                technician_name=technician_name,
                material_cost=material_cost,
                labor_cost=labor_cost,
                total_amount=total_amount,
                amount_paid=amount_paid,
                remaining_balance=remaining_balance,
                warranty_days=warranty_days,
                status=status,
                notes=notes
            )
            
            messages.success(request, f'Job #{job.id} created successfully!')
            return redirect('workshop:job_detail', job_id=job.id)
            
        except ShopBranch.DoesNotExist:
            messages.error(request, 'Selected shop does not exist.')
        except Exception as e:
            messages.error(request, f'Error creating job: {str(e)}')
            import traceback
            traceback.print_exc()
    
    # GET request - show form
    shops = ShopBranch.objects.filter(is_active=True)
    return render(request, 'workshop/job_form.html', {'shops': shops, 'is_edit': False})





@login_required
def job_detail(request, job_id):
    """View job details"""
    
    job = get_object_or_404(RepairJob, id=job_id)
    expenses = job.expenses.all()
    payment_percentage = (job.amount_paid / job.total_amount * 100) if job.total_amount > 0 else 0
    
    context = {
        'job': job,
        'expenses': expenses,
        'payment_percentage': payment_percentage,
    }
    
    return render(request, 'workshop/job_detail.html', context)





@login_required
def job_edit(request, job_id):
    """Edit repair job"""
    
    job = get_object_or_404(RepairJob, id=job_id)
    
    if request.method == 'POST':
        try:
            # Get form data
            customer_name = request.POST.get('customer_name')
            customer_phone = request.POST.get('customer_phone')
            device_type = request.POST.get('device_type')
            device_model = request.POST.get('device_model')
            issue_description = request.POST.get('issue_description')
            shop_id = request.POST.get('shop')
            technician_id = request.POST.get('technician_id')
            material_cost = Decimal(request.POST.get('material_cost', 0))
            labor_cost = Decimal(request.POST.get('labor_cost', 0))
            amount_paid = Decimal(request.POST.get('amount_paid', 0))
            warranty_days = request.POST.get('warranty_days', 30)
            status = request.POST.get('status', 'pending')
            notes = request.POST.get('notes', '')
            
            # Update job fields
            job.customer_name = customer_name
            job.customer_phone = customer_phone
            job.device_type = device_type
            job.device_model = device_model
            job.issue_description = issue_description
            job.material_cost = material_cost
            job.labor_cost = labor_cost
            job.amount_paid = amount_paid
            job.warranty_days = warranty_days
            job.status = status
            job.notes = notes
            
            # Recalculate totals
            job.total_amount = job.material_cost + job.labor_cost
            job.remaining_balance = job.total_amount - job.amount_paid
            
            # Update shop if changed
            if shop_id:
                job.shop = ShopBranch.objects.get(id=shop_id)
            
            # Update technician if changed
            if technician_id:
                try:
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    technician = User.objects.get(id=technician_id)
                    job.technician_name = technician.get_full_name() or technician.username
                except User.DoesNotExist:
                    pass
            else:
                job.technician_name = None
            
            job.save()
            
            messages.success(request, f'Job #{job.id} updated successfully!')
            return redirect('workshop:job_detail', job_id=job.id)
            
        except Exception as e:
            messages.error(request, f'Error updating job: {str(e)}')
    
    shops = ShopBranch.objects.filter(is_active=True)
    context = {
        'job': job,
        'shops': shops,
        'is_edit': True,
    }
    return render(request, 'workshop/job_form.html', context)






@login_required
def job_delete(request, job_id):
    """Delete repair job"""
    
    job = get_object_or_404(RepairJob, id=job_id)
    
    if request.method == 'POST':
        job.delete()
        messages.success(request, f'Job #{job_id} deleted!')
        return redirect('workshop:job_list')
    
    return render(request, 'workshop/job_confirm_delete.html', {'job': job})







@login_required
def add_payment(request, job_id):
    """Add payment to job"""
    
    job = get_object_or_404(RepairJob, id=job_id)
    
    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount', 0))
        
        if amount <= 0:
            messages.error(request, 'Invalid amount')
        elif amount > job.remaining_balance:
            messages.error(request, f'Amount exceeds balance of KSH {job.remaining_balance:.2f}')
        else:
            job.amount_paid += amount
            job.remaining_balance = job.total_amount - job.amount_paid
            job.save()
            messages.success(request, f'Payment of KSH {amount:.2f} added!')
        
        return redirect('workshop:job_detail', job_id=job.id)
    
    return render(request, 'workshop/add_payment.html', {'job': job})







@login_required
def job_receipt(request, job_id):
    """Print receipt"""
    
    job = get_object_or_404(RepairJob, id=job_id)
    return render(request, 'workshop/job_receipt.html', {'job': job})






# ============================================
# TECHNICIAN VIEWS
# ============================================

def is_technician(user):
    """Check if user is a technician"""
    if user.is_superuser:
        return True
    try:
        staff = Staff.objects.get(user=user)
        return staff.position and 'technician' in staff.position.lower()
    except:
        return user.groups.filter(name__icontains='technician').exists()





@login_required
def technician_dashboard(request):
    """Technician dashboard"""
    
    if not is_technician(request.user):
        messages.error(request, "Access denied")
        return redirect('workshop:dashboard')
    
    # Get technician name
    try:
        staff = Staff.objects.get(user=request.user)
        tech_name = staff.user.get_full_name() or staff.user.username
    except:
        tech_name = request.user.get_full_name() or request.user.username
    
    # Get jobs assigned to this technician
    jobs = RepairJob.objects.filter(technician_name=tech_name)
    
    pending_jobs = jobs.filter(status='pending').count()
    in_progress_jobs = jobs.filter(status='in_progress').count()
    completed_jobs = jobs.filter(status='completed').count()
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    # Get lists for each status
    pending_list = jobs.filter(status='pending')[:10]
    in_progress_list = jobs.filter(status='in_progress')[:10]
    completed_list = jobs.filter(status='completed')[:10]
    
    context = {
        'technician_name': tech_name,
        'total_jobs': jobs.count(),
        'pending_jobs': pending_jobs,
        'in_progress_jobs': in_progress_jobs,
        'completed_jobs': completed_jobs,
        'total_revenue': total_revenue,
        'pending_jobs_list': pending_list,
        'in_progress_jobs_list': in_progress_list,
        'completed_jobs_list': completed_list,
    }
    
    return render(request, 'workshop/technician_dashboard.html', context)






@login_required
def technician_jobs(request):
    """List jobs for technician"""
    
    if not is_technician(request.user):
        messages.error(request, "Access denied")
        return redirect('workshop:dashboard')
    
    # Get technician name
    try:
        staff = Staff.objects.get(user=request.user)
        tech_name = staff.user.get_full_name() or staff.user.username
    except:
        tech_name = request.user.get_full_name() or request.user.username
    
    jobs = RepairJob.objects.filter(technician_name=tech_name)
    
    # Filters
    search = request.GET.get('search', '')
    if search:
        jobs = jobs.filter(
            Q(customer_name__icontains=search) |
            Q(customer_phone__icontains=search) |
            Q(device_type__icontains=search)
        )
    
    status_filter = request.GET.get('status', '')
    if status_filter:
        jobs = jobs.filter(status=status_filter)
    
    # Pagination
    paginator = Paginator(jobs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Stats
    total_jobs = jobs.count()
    pending_count = jobs.filter(status='pending').count()
    in_progress_count = jobs.filter(status='in_progress').count()
    completed_count = jobs.filter(status='completed').count()
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    shops = ShopBranch.objects.filter(is_active=True)
    
    context = {
        'jobs': page_obj,
        'technician_name': tech_name,
        'search_query': search,
        'status_filter': status_filter,
        'shops': shops,
        'total_jobs': total_jobs,
        'pending_count': pending_count,
        'in_progress_count': in_progress_count,
        'completed_count': completed_count,
        'total_revenue': total_revenue,
    }
    
    return render(request, 'workshop/technician_jobs.html', context)






@login_required
def technician_update_job_status(request, job_id):
    """Update job status for technician via AJAX"""
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        job = get_object_or_404(RepairJob, id=job_id)
        
        # Get technician name
        try:
            staff = Staff.objects.get(user=request.user)
            tech_name = staff.user.get_full_name() or staff.user.username
        except:
            tech_name = request.user.get_full_name() or request.user.username
        
        # Parse request
        data = json.loads(request.body)
        new_status = data.get('status')
        
        # Map status values
        if new_status in ['accept', 'start', 'in_progress', 'inprogress']:
            new_status = 'in_progress'
        elif new_status in ['complete', 'finish', 'completed']:
            new_status = 'completed'
        
        # Validate
        valid_statuses = ['pending', 'in_progress', 'completed', 'picked_up']
        if new_status not in valid_statuses:
            return JsonResponse({'error': f'Invalid status: {new_status}'}, status=400)
        
        # Update job
        old_status = job.status
        job.status = new_status
        
        if new_status == 'in_progress' and not job.technician_name:
            job.technician_name = tech_name
        
        if new_status == 'completed' and not job.completed_at:
            job.completed_at = timezone.now()
        
        job.save()
        
        status_display = dict(job._meta.get_field('status').choices).get(new_status, new_status)
        
        return JsonResponse({
            'success': True,
            'message': f'Job #{job.id} updated to {status_display}',
            'new_status': new_status,
            'status_display': status_display
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    





@login_required
def technician_performance(request):
    """Technician performance report"""
    
    if not is_technician(request.user):
        messages.error(request, "Access denied")
        return redirect('workshop:dashboard')
    
    # Get technician name
    try:
        staff = Staff.objects.get(user=request.user)
        tech_name = staff.user.get_full_name() or staff.user.username
    except:
        tech_name = request.user.get_full_name() or request.user.username
    
    # Date range
    today = timezone.now().date()
    date_from = request.GET.get('date_from', (today - timedelta(days=30)).isoformat())
    date_to = request.GET.get('date_to', today.isoformat())
    
    jobs = RepairJob.objects.filter(
        technician_name=tech_name,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to
    )
    
    total_jobs = jobs.count()
    completed_jobs = jobs.filter(status='completed').count()
    in_progress_jobs = jobs.filter(status='in_progress').count()
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_material = jobs.aggregate(total=Sum('material_cost'))['total'] or Decimal('0.00')
    net_profit = total_revenue - total_material
    
    completion_rate = (completed_jobs / total_jobs * 100) if total_jobs > 0 else 0
    
    # Monthly chart
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
        month_revenue = month_jobs.aggregate(total=Sum('total_amount'))['total'] or 0
        monthly_revenue.append(float(month_revenue))
    
    context = {
        'technician_name': tech_name,
        'date_from': date_from,
        'date_to': date_to,
        'total_jobs': total_jobs,
        'completed_jobs': completed_jobs,
        'in_progress_jobs': in_progress_jobs,
        'total_revenue': total_revenue,
        'total_material_cost': total_material,
        'net_profit': net_profit,
        'completion_rate': completion_rate,
        'monthly_labels': json.dumps(monthly_labels),
        'monthly_jobs': monthly_jobs,
        'monthly_revenue': monthly_revenue,
        'recent_jobs': jobs.order_by('-created_at')[:10],
    }
    
    return render(request, 'workshop/technician_performance.html', context)


# ============================================
# PICKUP VIEWS
# ============================================

@login_required
def pickup_page(request):
    """Customer pickup page"""
    return render(request, 'workshop/pickup.html')


@login_required
def search_job_for_pickup(request):
    """Search job for pickup (AJAX)"""
    
    job_id = request.GET.get('job_id')
    
    if not job_id:
        return JsonResponse({'success': False, 'error': 'Job ID required'})
    
    try:
        job = RepairJob.objects.get(id=job_id)
        
        if job.status != 'completed':
            return JsonResponse({
                'success': False,
                'error': f'Job not ready for pickup. Status: {job.get_status_display()}'
            })
        
        return JsonResponse({
            'success': True,
            'job': {
                'id': job.id,
                'customer_name': job.customer_name,
                'customer_phone': job.customer_phone,
                'device_type': job.device_type,
                'device_model': job.device_model,
                'issue_description': job.issue_description,
                'shop_name': job.shop.name if job.shop else 'N/A',
                'technician_name': job.technician_name or 'Not assigned',
                'total_amount': float(job.total_amount),
                'amount_paid': float(job.amount_paid),
                'remaining_balance': float(job.remaining_balance),
                'warranty_days': job.warranty_days,
            }
        })
        
    except RepairJob.DoesNotExist:
        return JsonResponse({'success': False, 'error': f'Job #{job_id} not found'})


@login_required
def process_pickup(request, job_id):
    """Process customer pickup (AJAX)"""
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        job = RepairJob.objects.get(id=job_id)
        
        if job.status != 'completed':
            return JsonResponse({'error': 'Job not ready for pickup'}, status=400)
        
        job.status = 'picked_up'
        job.picked_up_at = timezone.now()
        job.save()
        
        return JsonResponse({'success': True, 'message': f'Job #{job.id} marked as picked up'})
        
    except RepairJob.DoesNotExist:
        return JsonResponse({'error': 'Job not found'}, status=404)


# ============================================
# REPORTS VIEWS
# ============================================
@login_required
def reports(request):
    """Workshop reports"""
    
    today = timezone.now().date()
    month_ago = today - timedelta(days=30)  # Add this line
    
    date_from = request.GET.get('date_from', month_ago.isoformat())
    date_to = request.GET.get('date_to', today.isoformat())
    
    jobs = RepairJob.objects.filter(
        created_at__date__gte=date_from,
        created_at__date__lte=date_to
    )
    
    total_jobs = jobs.count()
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_paid = jobs.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    total_material = jobs.aggregate(total=Sum('material_cost'))['total'] or Decimal('0.00')
    net_profit = total_revenue - total_material
    
    # Status distribution
    status_data = [
        jobs.filter(status='pending').count(),
        jobs.filter(status='in_progress').count(),
        jobs.filter(status='completed').count(),
        jobs.filter(status='picked_up').count(),
    ]
    
    # Chart data
    chart_labels = []
    revenue_data = []
    
    for i in range(29, -1, -1):
        date = today - timedelta(days=i)
        chart_labels.append(date.strftime('%d %b'))
        day_revenue = jobs.filter(created_at__date=date).aggregate(total=Sum('total_amount'))['total'] or 0
        revenue_data.append(float(day_revenue))
    
    # Get shops for filter
    shops = ShopBranch.objects.filter(is_active=True)
    
    context = {
        'date_from': date_from,
        'date_to': date_to,
        'month_ago': month_ago.isoformat(),  # Add this line
        'today': today.isoformat(),  # Add this line
        'total_jobs': total_jobs,
        'total_revenue': total_revenue,
        'total_paid': total_paid,
        'total_material': total_material,
        'net_profit': net_profit,
        'status_data': json.dumps(status_data),
        'chart_labels': json.dumps(chart_labels),
        'revenue_data': json.dumps(revenue_data),
        'recent_jobs': jobs.order_by('-created_at')[:10],
        'shops': shops,  # Add shops for the filter dropdown
    }
    
    return render(request, 'workshop/reports.html', context)


# ============================================
# HELPER VIEWS
# ============================================

@login_required
def get_technicians_by_shop(request):
    """Get technicians for a shop (AJAX)"""
    
    shop_id = request.GET.get('shop_id')
    
    if not shop_id:
        return JsonResponse({'technicians': []})
    
    technicians = Staff.objects.filter(
        assigned_shop_id=shop_id,
        position__icontains='technician',
        user__is_active=True
    ).select_related('user')
    
    tech_list = [{
        'id': tech.user.id,
        'name': tech.user.get_full_name() or tech.user.username,
        'position': tech.position,
    } for tech in technicians]
    
    return JsonResponse({'technicians': tech_list})