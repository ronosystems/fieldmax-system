from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.utils import timezone
from django.http import JsonResponse
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.contrib.auth import get_user_model
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Sum, Count, Q, Avg
from datetime import timedelta
from .models import StaffApplication
from django.contrib.auth import logout
from django.views.decorators.http import require_POST
from .models import OTPVerification
from .utils import send_otp_email, requires_otp, get_user_role
from django.db.models import F
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count
from inventory.models import StockAlert, ReturnRequest, Product
from django.contrib.auth.decorators import user_passes_test
from .models import Staff
from datetime import timedelta
from django.utils import timezone
import logging
import os
from decimal import Decimal
from .models import Staff 
from .utils.email_verification import send_itp_verification_email, generate_verification_code 
from credit.models import SellerCommission, CreditTransaction, CompanyPayment
import queue
import threading
import time
import sys
from django.contrib.auth.models import User, Group
from django.contrib.auth.hashers import make_password
from staff.models import UserProfile
import random
import re
import string
import sys
from functools import wraps
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import UserProfile
from finance.utils import UnifiedFinanceCalculator
email_queue = queue.Queue()
worker_running = True
worker_thread = None



logger = logging.getLogger(__name__)
User = get_user_model()



def email_worker():
    """Worker that handles both SMTP (local) and API (Render) emails"""
    global worker_running
    logger.info("🚀 Email worker thread STARTED")
    
    while worker_running:
        try:
            task = email_queue.get(timeout=1)
            if task:
                method, subject, message, recipient_list, html_message, retry_count = task
                logger.info(f"📤 PROCESSING email for: {recipient_list} via {method}")
                
                try:
                    if method == 'api' and os.environ.get('RENDER'):
                        # Use SendGrid API on Render
                        from utils.sendgrid_api import send_email_via_api
                        success = send_email_via_api(
                            recipient_list[0] if recipient_list else None,
                            subject, 
                            html_message or message,
                            message
                        )
                        if success:
                            logger.info(f"✅ API email sent to {recipient_list}")
                        else:
                            raise Exception("API send failed")
                    else:
                        # Use SMTP locally
                        send_mail(
                            subject=subject,
                            message=message,
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            recipient_list=recipient_list,
                            html_message=html_message,
                            fail_silently=False,
                        )
                        logger.info(f"✅ SMTP email sent to {recipient_list}")
                    
                    email_queue.task_done()
                    
                except Exception as e:
                    logger.error(f"❌ Email failed: {str(e)}")
                    # Retry logic for network errors
                    if retry_count < 3:
                        logger.info(f"🔄 Retry {retry_count+1}/3 for {recipient_list}")
                        email_queue.put((method, subject, message, recipient_list, html_message, retry_count + 1))
                        time.sleep(2 ** retry_count)
                    else:
                        email_queue.task_done()
                        
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"❌ WORKER ERROR: {e}")
            time.sleep(1)

def queue_email(subject, message, recipient_list, html_message=None):
    """Add email to queue - will use API on Render, SMTP locally"""
    if os.environ.get('RENDER'):  # Detect if running on Render
        # On Render: use API (port 443)
        email_queue.put(('api', subject, message, recipient_list, html_message, 0))
    else:
        # Locally: use SMTP (works fine)
        email_queue.put(('smtp', subject, message, recipient_list, html_message, 0))
    
    logger.info(f"📦 Email queued for {recipient_list} - Queue size: {email_queue.qsize()}")

def get_correct_dashboard_url(user):
    """Get the correct dashboard URL for a user based on their groups"""
    
    # Get user's groups
    user_groups = user.groups.values_list('name', flat=True)
    
    # Priority order (first match wins)
    dashboard_map = [
        (['Administrator'], 'staff:admin_dashboard'),
        (['Sales Manager'], 'staff:sales_manager_dashboard'),
        (['Store Manager', 'Inventory Manager'], 'staff:store_manager_dashboard'),
        (['Credit Manager'], 'staff:credit_manager_dashboard'),
        (['Credit Officer'], 'staff:credit_officer_dashboard'),
        (['Finance Manager'], 'staff:finance_manager_dashboard'),
        (['Sales Agent'], 'staff:sales_agent_dashboard'),
        (['Cashier'], 'staff:cashier_dashboard'),
        (['Customer Service'], 'staff:customer_service_dashboard'),
        (['Security Officer'], 'staff:security_dashboard'),
        (['Cleaner'], 'staff:cleaner_dashboard'),
        (['M-Pesa Agent'], 'staff:mpesa_agent_dashboard'),
    ]
    
    for groups, dashboard_url in dashboard_map:
        if any(group in user_groups for group in groups):
            return dashboard_url
    
    return 'staff:staff_stats_dashboard'

def dashboard_for_role(*allowed_roles):
    """
    Decorator that checks if user has the right role for this dashboard.
    If not, automatically redirects to their correct dashboard.
    
    Usage:
        @dashboard_for_role('Store Manager', 'Inventory Manager')
        def store_manager_dashboard(request):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Must be logged in
            if not request.user.is_authenticated:
                return redirect('login')
            
            # Superusers can access everything
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            # Get user's groups
            user_groups = set(request.user.groups.values_list('name', flat=True))
            
            # Check if user has any of the allowed roles
            has_permission = bool(set(allowed_roles) & user_groups)
            
            if not has_permission:
                # User doesn't have permission for this dashboard
                # Get their correct dashboard
                correct_dashboard = get_correct_dashboard_url(request.user)
                
                # Get readable names for the message
                current_dashboard_name = view_func.__name__.replace('_dashboard', '').replace('_', ' ').title()
                correct_dashboard_name = correct_dashboard.split(':')[-1].replace('_dashboard', '').replace('_', ' ').title()
                
                # Log the redirect
                logger.info(f"Redirecting {request.user.username} from {current_dashboard_name} to {correct_dashboard_name}")
                
                # Add friendly message (optional - remove if you don't want messages)
                messages.info(
                    request,
                    f"👋 You were trying to access the {current_dashboard_name} Dashboard. "
                    f"We've redirected you to your {correct_dashboard_name} Dashboard."
                )
                
                return redirect(correct_dashboard)
            
            # User has permission - show the view
            return view_func(request, *args, **kwargs)
        
        return _wrapped_view
    return decorator




# ============================================
# Start the worker thread
# ============================================
worker_thread = threading.Thread(target=email_worker, daemon=True)
worker_thread.start()
logger.info(f"✅ Worker thread started. Alive: {worker_thread.is_alive()}")




#====================================
# VERIFICATION  VIEW
#===================================
@login_required
def otp_verify(request):
    # Write to stderr immediately (bypasses Django logging)
    sys.stderr.write(f"\n🔴🔴🔴 OTP VIEW STARTED for {request.user.username}\n")
    sys.stderr.flush()
    
    logger.info(f"🔴 OTP VIEW ACCESSED by {request.user.username}")
    
    # If user doesn't require OTP, redirect to dashboard
    if not requires_otp(request.user):
        logger.info(f"🔴 User {request.user.username} does not require OTP")
        return redirect('staff:staff_dashboard')
    
    # Get intended dashboard URL from session
    intended_url = request.session.get('intended_dashboard_url', 'staff:staff_dashboard')
    
    # Handle POST (OTP submission)
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code', '').strip()
        logger.info(f"🔴 POST request with OTP: {otp_code}")
        
        # Verify OTP
        success, message = OTPVerification.verify_otp(
            request.user, 
            otp_code, 
            purpose='dashboard_access'
        )
        
        if success:
            request.session['otp_verified'] = True
            request.session['otp_verified_at'] = timezone.now().isoformat()
            messages.success(request, message)
            logger.info(f"🔴 OTP verified successfully for {request.user.username}")
            return redirect(intended_url)
        else:
            messages.error(request, message)
            logger.info(f"🔴 OTP verification failed for {request.user.username}")
    
    # Handle GET (first time loading the page) or resend
    if request.method == 'GET':
        logger.info(f"🔴 GET request - generating new OTP for {request.user.username}")
        
        # Generate OTP
        otp = OTPVerification.generate_otp(request.user, purpose='dashboard_access')
        logger.info(f"🔴 OTP GENERATED: {otp.otp_code} for {request.user.email}")
        
        # Prepare email content
        user_name = request.user.get_full_name() or request.user.username
        subject = '🔐 FieldMax - Your Dashboard Access Code'
        
        # Plain text message
        plain_message = f"""
        Dear {user_name},
        
        Your One-Time Password (OTP) for dashboard access is: {otp.otp_code}
        
        This code will expire in 5 minutes.
        
        If you did not request this code, please contact your system administrator immediately.
        
        Regards,
        FieldMax Security Team
        """
        
        # Create HTML email
        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #17a2b8 0%, #138496 100%); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f8f9fa; padding: 30px; border: 1px solid #dee2e6; }}
                .otp-code {{ font-size: 32px; font-weight: bold; color: #17a2b8; text-align: center; padding: 20px; background: white; border-radius: 10px; margin: 20px 0; letter-spacing: 5px; }}
                .footer {{ text-align: center; padding: 20px; color: #6c757d; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>FieldMax Dashboard Access</h2>
                </div>
                <div class="content">
                    <p>Dear <strong>{user_name}</strong>,</p>
                    <p>Your One-Time Password (OTP) for dashboard access is:</p>
                    <div class="otp-code">{otp.otp_code}</div>
                    <p>This code will expire in <strong>5 minutes</strong>.</p>
                    <p><small>If you did not request this code, please contact your system administrator immediately.</small></p>
                </div>
                <div class="footer">
                    <p>&copy; {timezone.now().year} FieldMax. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Queue the email
        logger.info(f"🔴 Queuing email for {request.user.email}")
        queue_email(subject, plain_message, [request.user.email], html_message)
        logger.info(f"🔴 Email queued. Queue size: {email_queue.qsize()}")
        
        messages.success(request, f'✅ A 6-digit OTP has been sent to {request.user.email}')
    
    context = {
        'user_role': get_user_role(request.user),
        'user_email': request.user.email,
    }
    return render(request, 'staff/otp_verify.html', context)

@login_required
def otp_resend(request):
    """Resend OTP code"""
    if request.method == 'POST':
        otp = OTPVerification.generate_otp(request.user, purpose='dashboard_access')
        
        # Prepare email content
        user_name = request.user.get_full_name() or request.user.username
        subject = 'FieldMax - New OTP Code'
        plain_message = f"""
        Dear {user_name},
        
        Your new One-Time Password (OTP) for dashboard access is: {otp.otp_code}
        
        This code will expire in 5 minutes.
        
        Regards,
        FieldMax Security Team
        """
        
        # Create HTML email
        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #17a2b8 0%, #138496 100%); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f8f9fa; padding: 30px; border: 1px solid #dee2e6; }}
                .otp-code {{ font-size: 32px; font-weight: bold; color: #17a2b8; text-align: center; padding: 20px; background: white; border-radius: 10px; margin: 20px 0; letter-spacing: 5px; }}
                .footer {{ text-align: center; padding: 20px; color: #6c757d; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>FieldMax Dashboard Access</h2>
                </div>
                <div class="content">
                    <p>Dear <strong>{user_name}</strong>,</p>
                    <p>Your new One-Time Password (OTP) is:</p>
                    <div class="otp-code">{otp.otp_code}</div>
                    <p>This code will expire in <strong>5 minutes</strong>.</p>
                </div>
                <div class="footer">
                    <p>&copy; {timezone.now().year} FieldMax. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        logger.info(f"📧 Adding OTP email to queue for: {request.user.email}")
        
        # Send email via queue
        queue_email(subject, plain_message, [request.user.email], html_message)
        
        logger.info(f"📧 Email queued. Queue size: {email_queue.qsize()}")
        
        return JsonResponse({
            'success': True, 
            'message': 'A new OTP has been sent to your email',
        })
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})

@login_required
def email_queue_status(request):
    """Check email queue status (admin only)"""
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    return JsonResponse({
        'queue_size': email_queue.qsize(),
        'worker_running': worker_running,
        'worker_alive': worker_thread.is_alive() if worker_thread else False,
    })

def custom_logout(request):
    """Custom logout view that handles POST requests"""
    logout(request)
    messages.success(request, "You have been successfully logged out.")
    return redirect('website:home') 

@login_required
def notifications_page(request):
    """Display all notifications for the user - WITHOUT SALES/PURCHASES"""
    
    # Get current time for time calculations
    now = timezone.now()
    last_24h = now - timedelta(hours=24)
    last_week = now - timedelta(days=7)
    
    # ============================================
    # STOCK ALERTS
    # ============================================
    stock_alerts = StockAlert.objects.filter(
        is_active=True,
        is_dismissed=False
    ).select_related('product').order_by('-severity', '-created_at')
    
    # Count alerts by severity
    critical_alerts = stock_alerts.filter(severity__in=['critical', 'danger']).count()
    warning_alerts = stock_alerts.filter(severity='warning').count()
    info_alerts = stock_alerts.filter(severity='info').count()
    
    # ============================================
    # RETURN REQUESTS (for managers/staff)
    # ============================================
    if request.user.is_staff or request.user.is_superuser:
        pending_returns = ReturnRequest.objects.filter(
            status='submitted'
        ).select_related('product', 'requested_by').order_by('-requested_at')
        
        verified_returns = ReturnRequest.objects.filter(
            status='verified'
        ).select_related('product', 'requested_by', 'verified_by').order_by('-verified_at')
    else:
        # Regular users see their own returns
        pending_returns = ReturnRequest.objects.filter(
            requested_by=request.user,
            status='submitted'
        ).order_by('-requested_at')
        
        verified_returns = ReturnRequest.objects.filter(
            requested_by=request.user,
            status='verified'
        ).order_by('-requested_at')
    
    # ============================================
    # REMOVED: RECENT ACTIVITY (Sales & Purchases)
    # COMMENTED OUT - NO LONGER SHOWING SALES/PURCHASES
    # ============================================
    # from inventory.models import StockEntry
    # recent_activity = StockEntry.objects.select_related(
    #     'product_sku', 'product_unit', 'created_by'
    # ).filter(
    #     created_at__gte=last_week
    # ).order_by('-created_at')[:20]
    
    # ============================================
    # LOW STOCK PRODUCTS - FIXED
    # ============================================
    from django.db.models import Q
    
    # For bulk items: check bulk_quantity
    bulk_low_stock = Product.objects.filter(
        category__item_type='bulk',
        is_active=True,
        is_discontinued=False,
        bulk_quantity__lte=F('reorder_level'),
        bulk_quantity__gt=0
    )
    
    # For single items: check available_quantity
    single_low_stock = Product.objects.filter(
        category__item_type='single',
        is_active=True,
        is_discontinued=False,
        available_quantity__lte=F('reorder_level'),
        available_quantity__gt=0
    )
    
    # Combine both
    low_stock_products = (bulk_low_stock | single_low_stock).select_related('category')[:10]
    
    # ============================================
    # OUT OF STOCK PRODUCTS - FIXED
    # ============================================
    bulk_out_of_stock = Product.objects.filter(
        category__item_type='bulk',
        is_active=True,
        bulk_quantity=0
    )
    
    single_out_of_stock = Product.objects.filter(
        category__item_type='single',
        is_active=True,
        available_quantity=0
    )
    
    out_of_stock_products = (bulk_out_of_stock | single_out_of_stock).select_related('category')[:10]
    
    # ============================================
    # STAFF NOTIFICATIONS (for superusers/staff)
    # ============================================
    from .models import Staff, StaffApplication
    
    pending_verifications = []
    pending_applications = []
    
    if request.user.is_superuser or request.user.is_staff:
        # Pending staff verifications
        pending_verifications = Staff.objects.filter(
            verification_submitted_at__isnull=False,
            is_identity_verified=False
        ).select_related('user')[:10]
        
        # Pending staff applications
        pending_applications = StaffApplication.objects.filter(
            status='pending'
        ).order_by('-application_date')[:10]
    
    # ============================================
    # CREDIT TRANSACTIONS ALERTS (for managers)
    # ============================================
    credit_transactions_pending = []
    if hasattr(request.user, 'credit_transactions'):
        from credit.models import CreditTransaction
        credit_transactions_pending = CreditTransaction.objects.filter(
            Q(payment_status='pending_payment') | Q(commission_status='pending')
        ).select_related('product', 'customer')[:10]
    
    # ============================================
    # NOTIFICATION COUNTS BY TYPE
    # ============================================
    notification_counts = {
        'total': stock_alerts.count() + pending_returns.count(),
        'stock_alerts': stock_alerts.count(),
        'critical_alerts': critical_alerts,
        'warning_alerts': warning_alerts,
        'info_alerts': info_alerts,
        'pending_returns': pending_returns.count(),
        'verified_returns': verified_returns.count(),
        'low_stock': low_stock_products.count(),
        'out_of_stock': out_of_stock_products.count(),
        'pending_verifications': pending_verifications.count(),
        'pending_applications': pending_applications.count(),
        'credit_pending': credit_transactions_pending.count(),
    }
    
    context = {
        'stock_alerts': stock_alerts,
        'pending_returns': pending_returns,
        'verified_returns': verified_returns,
        # 'recent_activity': recent_activity,  # REMOVED - No longer passing sales/purchases
        'low_stock_products': low_stock_products,
        'out_of_stock_products': out_of_stock_products,
        'pending_verifications': pending_verifications,
        'pending_applications': pending_applications,
        'credit_transactions_pending': credit_transactions_pending,
        'notification_counts': notification_counts,
        'now': now,
        'last_24h': last_24h,
        'last_week': last_week,
    }
    
    return render(request, 'staff/notifications_page.html', context)

@staff_member_required
def user_list(request):
    """View to list all users in the system with staff information"""
    users = User.objects.all().order_by('-date_joined')
    
    # Annotate users with staff profile info
    from staff.models import Staff
    for user in users:
        try:
            staff_profile = Staff.objects.get(user=user)
            user.staff_id = staff_profile.staff_id
            user.staff_id_number = staff_profile.id_number
            user.assigned_shop = staff_profile.assigned_shop.name if staff_profile.assigned_shop else None
        except Staff.DoesNotExist:
            user.staff_id = None
            user.staff_id_number = None
            user.assigned_shop = None
    
    # Calculate regular users (non-staff, non-superuser)
    regular_users = users.filter(is_staff=False, is_superuser=False).count()
    
    return render(request, 'staff/users/list.html', {
        'users': users,
        'total_users': users.count(),
        'active_users': users.filter(is_active=True).count(),
        'staff_users': users.filter(is_staff=True).count(),
        'regular_users': regular_users,
        'title': 'System Users'
    })

@staff_member_required
def user_detail(request, pk):
    """View details of a specific user"""
    user = get_object_or_404(User, pk=pk)
    
    context = {
        'user': user,
    }
    return render(request, 'staff/users/detail.html', context)

@login_required
def verify_identity(request, staff_id):
    """ITP Identity Verification View"""
    staff = get_object_or_404(Staff, id=staff_id, user=request.user)
    
    # Check if already verified
    if staff.is_identity_verified:
        messages.success(request, "Your identity is already verified! Redirecting to dashboard...")
        return redirect('staff:staff_dashboard')
    
    # Check if verification is pending approval
    if staff.verification_submitted_at and not staff.is_identity_verified:
        messages.info(request, "Your verification documents have been submitted and are pending admin approval. You'll be notified once verified.")
        return render(request, 'staff/pending_approval.html', {
            'staff': staff,
            'pending_approval': True
        })
    
    # Check if verification code exists and is not expired
    from django.utils import timezone
    from datetime import timedelta
    
    is_expired = False
    time_remaining = None
    
    if staff.verification_code and staff.verification_sent_at:
        time_diff = timezone.now() - staff.verification_sent_at
        is_expired = time_diff > timedelta(hours=24)
        
        if not is_expired:
            expiry_time = staff.verification_sent_at + timedelta(hours=24)
            remaining = expiry_time - timezone.now()
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60
            time_remaining = f"{hours}h {minutes}m"
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # Handle resend verification code
        if action == 'resend':
            staff.verification_code = generate_verification_code()
            staff.verification_sent_at = timezone.now()
            staff.verification_attempts = 0
            staff.save(update_fields=['verification_code', 'verification_sent_at', 'verification_attempts'])
            
            from .utils.email_verification import send_itp_verification_email
            send_itp_verification_email(staff, request)
            
            messages.success(request, "A new 6-digit verification code has been sent to your email!")
            return redirect('staff:verify_identity', staff_id=staff.id)
        
        # Handle verification submission
        verification_code = request.POST.get('verification_code', '').strip()
        id_front = request.FILES.get('id_front')
        id_back = request.FILES.get('id_back')
        live_photo = request.FILES.get('live_photo')
        
        # Check expiration
        if is_expired:
            messages.error(request, "Verification code has expired. Please request a new one.")
            return render(request, 'staff/verify_identity.html', {
                'staff': staff,
                'is_expired': True,
                'time_remaining': time_remaining
            })
        
        # Verify code
        if verification_code != staff.verification_code:
            staff.verification_attempts += 1
            staff.save(update_fields=['verification_attempts'])
            
            if staff.verification_attempts >= 5:
                messages.error(request, "Too many failed attempts. Please request a new verification code.")
                return redirect('staff:resend_verification')
            else:
                remaining_attempts = 5 - staff.verification_attempts
                messages.error(request, f"Invalid verification code. {remaining_attempts} attempts remaining.")
                return render(request, 'staff/verify_identity.html', {
                    'staff': staff,
                    'is_expired': is_expired,
                    'time_remaining': time_remaining,
                    'remaining_attempts': remaining_attempts
                })
        
        # Validate required files
        if not all([id_front, id_back, live_photo]):
            messages.error(request, "Please upload all required documents: ID Front, ID Back, and Live Photo.")
            return render(request, 'staff/verify_identity.html', {
                'staff': staff,
                'is_expired': is_expired,
                'time_remaining': time_remaining
            })
        
        # Validate file types and sizes
        from django.core.exceptions import ValidationError
        from django.core.validators import FileExtensionValidator
        
        valid_extensions = ['.jpg', '.jpeg', '.png', '.webp']
        max_size = 5 * 1024 * 1024  # 5MB
        
        for file in [id_front, id_back, live_photo]:
            # Check extension
            ext = os.path.splitext(file.name)[1].lower()
            if ext not in valid_extensions:
                messages.error(request, f"Invalid file type: {file.name}. Only JPG, PNG, and WEBP are allowed.")
                return render(request, 'staff/verify_identity.html', {
                    'staff': staff,
                    'is_expired': is_expired,
                    'time_remaining': time_remaining
                })
            
            # Check size
            if file.size > max_size:
                messages.error(request, f"File too large: {file.name}. Maximum size is 5MB.")
                return render(request, 'staff/verify_identity.html', {
                    'staff': staff,
                    'is_expired': is_expired,
                    'time_remaining': time_remaining
                })
        
        # Save documents
        staff.id_front = id_front
        staff.id_back = id_back
        staff.live_photo = live_photo
        staff.verification_submitted_at = timezone.now()
        staff.verification_attempts += 1
        staff.save()
        
        # Send admin notification (commented out as per your preference)
        # send_verification_admin_notification(staff, request)
        
        messages.success(
            request, 
            "✅ Documents uploaded successfully! Your verification is pending admin review. "
            "You'll receive an email notification once verified. This usually takes 24-48 hours."
        )
        
        return render(request, 'staff/pending_approval.html', {
            'staff': staff,
            'pending_approval': True
        })
    
    # GET request - show verification form
    context = {
        'staff': staff,
        'verification_code': staff.verification_code,
        'is_expired': is_expired,
        'time_remaining': time_remaining,
        'attempts_remaining': max(0, 5 - staff.verification_attempts) if staff.verification_attempts else 5,
    }
    return render(request, 'staff/verify_identity.html', context)

@login_required
def resend_verification(request):
    """Resend verification email"""
    if request.method == 'POST':
        try:
            staff = request.user.staff_profile
            
            # Generate new code
            staff.verification_code = generate_verification_code()
            staff.verification_sent_at = timezone.now()
            staff.verification_attempts = 0
            staff.save(update_fields=['verification_code', 'verification_sent_at', 'verification_attempts'])
            
            # 🚫 EMAIL PAUSED - Commented out for now
            # Send email
            # from .utils.email_verification import send_itp_verification_email
            # if send_itp_verification_email(staff, request):
            #     messages.success(request, "✅ New 6-digit verification code sent to your email!")
            #     return JsonResponse({
            #         'success': True,
            #         'message': 'Verification code resent successfully'
            #     })
            # else:
            #     return JsonResponse({
            #         'success': False,
            #         'message': 'Failed to send verification email. Please try again.'
            #     })
            
            # ✅ TEMPORARY: Show code in response
            messages.success(request, f"🔧 DEV MODE - Verification code: {staff.verification_code}")
            return JsonResponse({
                'success': True,
                'message': 'Verification code generated',
                'verification_code': staff.verification_code,
                'dev_mode': True
            })
            
        except Exception as e:
            logger.error(f"Error resending verification: {str(e)}")
            return JsonResponse({
                'success': False,
                'message': f'Error: {str(e)}'
            })
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'})

def send_verification_admin_notification(staff, request=None):
    """Notify admins about pending verification"""
    try:
        from django.urls import reverse
        
        # Get admin review URL
        if request:
            admin_url = request.build_absolute_uri(
                reverse('admin:staff_staff_change', args=[staff.id])
            )
        else:
            admin_url = f"{settings.SITE_URL}/admin/staff/staff/{staff.id}/change/"
        
        subject = f"🔐 PENDING VERIFICATION: {staff.user.get_full_name()} - {staff.staff_id}"
        
        # Get attempt info
        attempt_info = f"Attempt {staff.verification_attempts} of 5"
        
        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #dc3545; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f8f9fa; padding: 30px; border: 1px solid #dee2e6; }}
                .info {{ background: white; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                .label {{ font-weight: bold; color: #495057; }}
                .button {{ display: inline-block; background: #007bff; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin-top: 20px; }}
                .footer {{ text-align: center; padding: 20px; color: #6c757d; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>🔐 Identity Verification Pending</h2>
                </div>
                <div class="content">
                    <p>A staff member has submitted identity verification documents for review.</p>
                    
                    <div class="info">
                        <h3>Staff Details:</h3>
                        <p><span class="label">Name:</span> {staff.user.get_full_name()}</p>
                        <p><span class="label">Staff ID:</span> {staff.staff_id}</p>
                        <p><span class="label">Email:</span> {staff.user.email}</p>
                        <p><span class="label">Position:</span> {staff.position}</p>
                        <p><span class="label">Submitted:</span> {staff.verification_submitted_at.strftime('%Y-%m-%d %H:%M')}</p>
                        <p><span class="label">Attempt:</span> {attempt_info}</p>
                    </div>
                    
                    <div class="info">
                        <h3>Documents Submitted:</h3>
                        <ul>
                            <li>✅ ID Front</li>
                            <li>✅ ID Back</li>
                            <li>✅ Live Photo</li>
                        </ul>
                    </div>
                    
                    <div style="text-align: center;">
                        <a href="{admin_url}" class="button">🔍 Review Documents</a>
                    </div>
                    
                    <p style="margin-top: 30px; padding: 15px; background: #fff3cd; border-left: 4px solid #ffc107;">
                        <strong>⏰ Time Sensitive:</strong> Please review within 24-48 hours to ensure good user experience.
                    </p>
                </div>
                <div class="footer">
                    <p>This is an automated notification from FieldMax Staff Portal</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        plain_message = f"""
        PENDING VERIFICATION: {staff.user.get_full_name()}
        
        Staff Details:
        - Name: {staff.user.get_full_name()}
        - Staff ID: {staff.staff_id}
        - Email: {staff.user.email}
        - Position: {staff.position}
        - Submitted: {staff.verification_submitted_at.strftime('%Y-%m-%d %H:%M')}
        - Attempt: {attempt_info}
        
        Documents Submitted:
        - ID Front
        - ID Back
        - Live Photo
        
        Review at: {admin_url}
        
        Please review within 24-48 hours.
        """
        
        # Send to all admins
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        # Get all admin users
        admins = User.objects.filter(is_superuser=True, is_active=True)
        
        for admin in admins:
            try:
                send_mail(
                    subject=subject,
                    message=plain_message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[admin.email],
                    html_message=html_message,
                    fail_silently=True,
                )
                logger.info(f"Admin notification sent to {admin.email}")
            except Exception as e:
                logger.error(f"Failed to send admin notification to {admin.email}: {str(e)}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to send admin verification notification: {str(e)}")
        return False

@staff_member_required
def admin_verify_list(request):
    """List all staff members pending verification"""
    staff_list = Staff.objects.filter(
        verification_submitted_at__isnull=False
    ).select_related('user').order_by('-verification_submitted_at')
    
    # Apply filters
    status = request.GET.get('status')
    if status == 'verified':
        staff_list = staff_list.filter(is_identity_verified=True)
    elif status == 'pending':
        staff_list = staff_list.filter(is_identity_verified=False)
    elif status == 'rejected':
        staff_list = staff_list.filter(verification_notes__icontains='rejected')
    
    # Date filters
    date_from = request.GET.get('date_from')
    if date_from:
        staff_list = staff_list.filter(verification_submitted_at__date__gte=date_from)
    
    date_to = request.GET.get('date_to')
    if date_to:
        staff_list = staff_list.filter(verification_submitted_at__date__lte=date_to)
    
    # Search
    search = request.GET.get('search')
    if search:
        staff_list = staff_list.filter(
            Q(user__first_name__icontains=search) |
            Q(user__last_name__icontains=search) |
            Q(user__email__icontains=search) |
            Q(staff_id__icontains=search)
        )
    
    # Pagination
    paginator = Paginator(staff_list, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Statistics
    pending_count = Staff.objects.filter(
        verification_submitted_at__isnull=False,
        is_identity_verified=False
    ).count()
    
    today = timezone.now().date()
    verified_today = Staff.objects.filter(
        verified_at__date=today,
        is_identity_verified=True
    ).count()
    
    total_verified = Staff.objects.filter(is_identity_verified=True).count()
    rejected_count = Staff.objects.filter(verification_notes__icontains='rejected').count()
    
    context = {
        'staff_list': page_obj,
        'pending_count': pending_count,
        'verified_today': verified_today,
        'total_verified': total_verified,
        'rejected_count': rejected_count,
    }
    return render(request, 'staff/admin_verify_list.html', context)

@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_staff)
def admin_verify_staff(request, staff_id):
    """Admin review page for staff identity verification"""
    # Try to find by database ID first, then by staff_id field
    try:
        # Try as integer (database primary key)
        staff = get_object_or_404(Staff, id=int(staff_id))
    except (ValueError, TypeError):
        # If not integer, try as staff_id string
        staff = get_object_or_404(Staff, staff_id=staff_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        notes = request.POST.get('notes', '')
        
        if action == 'approve':
            staff.is_identity_verified = True
            staff.verified_at = timezone.now()
            staff.verified_by = request.user
            staff.verification_notes = notes
            
            messages.success(request, f'Staff {staff.user.get_full_name()} has been verified successfully.')
            
        elif action == 'reject':
            staff.is_identity_verified = False
            staff.verified_at = timezone.now()
            staff.verified_by = request.user
            staff.verification_notes = notes
            staff.verification_attempts = 0
            staff.verification_code = None
            staff.verification_sent_at = None
            
            messages.warning(request, f'Staff {staff.user.get_full_name()} verification rejected.')
        
        staff.save()
        return redirect('staff:admin_verify_list')
    
    context = {
        'staff': staff,
    }
    return render(request, 'staff/admin_verify_staff.html', context)

def send_verification_result_email(staff, approved=True, notes=''):
    """Send verification result notification to staff"""
    try:
        if approved:
            subject = "✅ FieldMax - Your Identity Has Been Verified!"
            template = 'staff/email/verification_approved.html'
        else:
            subject = "⚠️ FieldMax - Identity Verification Update"
            template = 'staff/email/verification_rejected.html'
        
        context = {
            'staff': staff,
            'staff_name': staff.user.get_full_name(),
            'notes': notes,
            'login_url': f"{settings.SITE_URL}/staff/login/",
            'support_email': settings.SUPPORT_EMAIL,
        }
        
        html_message = render_to_string(template, context)
        plain_message = f"""
        Dear {staff.user.get_full_name()},
        
        {'Your identity has been verified! You can now access the staff portal.' if approved else 'Your identity verification was not approved.'}
        
        {'Reason: ' + notes if notes else ''}
        
        {'Login here: ' + settings.SITE_URL + '/staff/login/' if approved else 'Please contact support for assistance.'}
        
        Regards,
        FieldMax HR Team
        """
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[staff.user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        logger.info(f"Verification result email sent to {staff.user.email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send verification result email: {str(e)}")
        return False






# ============================================
# HELPER FUNCTION FOR DASHBOARD WELCOME MESSAGES
# ============================================
def prepare_dashboard_messages(request, dashboard_name=None):
    """
    Clear logout messages and add welcome message for all dashboards
    """
    # Clear any existing messages (like the logout message)
    storage = messages.get_messages(request)
    storage.used = True  # Mark all messages as read/cleared
    
    # Add welcome message for first login of the session
    if not request.session.get('welcome_shown', False):
        # Get user's name
        user_name = request.user.get_full_name() or request.user.username
        
        # Get dashboard display name if not provided
        if not dashboard_name:
            # Try to determine from user's groups
            user_groups = request.user.groups.values_list('name', flat=True)
            if 'Administrator' in user_groups:
                dashboard_name = 'Admin'
            elif 'Sales Manager' in user_groups:
                dashboard_name = 'Sales Manager'
            elif 'Sales Agent' in user_groups:
                dashboard_name = 'Sales'
            elif 'Cashier' in user_groups:
                dashboard_name = 'Cashier'
            elif 'Store Manager' in user_groups:
                dashboard_name = 'Store Manager'
            elif 'Credit Manager' in user_groups:
                dashboard_name = 'Credit Manager'
            elif 'Credit Officer' in user_groups:
                dashboard_name = 'Credit Officer'
            elif 'Customer Service' in user_groups:
                dashboard_name = 'Customer Service'
            elif 'Finance Manager' in user_groups:
                dashboard_name = 'Finance Manager'
            elif 'Security Officer' in user_groups:
                dashboard_name = 'Security'
            elif 'M-Pesa Agent' in user_groups:
                dashboard_name = 'M-Pesa Agent'
            elif 'Cleaner' in user_groups:
                dashboard_name = 'Cleaner'
            else:
                dashboard_name = 'Staff'
        
        # Add welcome message
        messages.success(
            request, 
            f'👋 Welcome back, {user_name}! Ready to manage your {dashboard_name} Dashboard?'
        )
        
        # Mark welcome as shown for this session
        request.session['welcome_shown'] = True
        
        return True
    
    return False







# ====================================
# STATISTICS DASHBOARD VIEW (Rename this)
# ====================================
@login_required
def staff_stats_dashboard(request):
    """Staff dashboard with statistics (fallback for users without specific roles)"""
    from datetime import timedelta, date
    import json
    
    # Basic stats
    total_applications = StaffApplication.objects.count()
    pending_count = StaffApplication.objects.filter(status='pending').count()
    approved_count = StaffApplication.objects.filter(status='approved').count()
    rejected_count = StaffApplication.objects.filter(status='rejected').count()
    under_review_count = StaffApplication.objects.filter(status='under_review').count()
    
    # Recent applications
    recent_applications = StaffApplication.objects.order_by('-application_date')[:5]
    
    # Position statistics
    position_stats = []
    for pos_code, pos_name in StaffApplication.POSITION_CHOICES:
        count = StaffApplication.objects.filter(position=pos_code).count()
        if count > 0:
            position_stats.append({
                'code': pos_code,
                'name': pos_name,
                'count': count
            })
    
    # Chart data (last 30 days)
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)
    
    chart_labels = []
    applications_data = []
    
    for i in range(30):
        day = thirty_days_ago + timedelta(days=i)
        count = StaffApplication.objects.filter(
            application_date__date=day
        ).count()
        
        chart_labels.append(day.strftime('%d %b'))
        applications_data.append(count)
    
    context = {
        'total_applications': total_applications,
        'pending_count': pending_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
        'under_review_count': under_review_count,
        'recent_applications': recent_applications,
        'position_stats': position_stats,
        'chart_labels': json.dumps(chart_labels),
        'applications_data': json.dumps(applications_data),
    }
    
    return render(request, 'staff/dashboard.html', context)

# ============================================
# MAIN DASHBOARD REDIRECT (Based on Groups)
# ============================================
@login_required
def staff_dashboard(request):
    """Main dashboard that redirects to role-specific dashboard"""

    prepare_dashboard_messages(request, 'Staff')
    
    # ============================================
    # STEP 1: Check if user has staff profile
    # ============================================
    try:
        staff_profile = request.user.staff_profile
    except AttributeError:
        messages.error(request, "Staff profile not found. Please contact administrator.")
        return redirect('logout')
    
    # ============================================
    # STEP 2: Check if user is active
    # ============================================
    if not request.user.is_active:
        messages.error(request, "Your account is inactive. Please contact administrator.")
        return redirect('logout')
    
    # ============================================
    # STEP 3: Check ITP Verification Status
    # ============================================
    if not staff_profile.is_identity_verified:
        # Check if verification is pending (documents submitted but not verified by admin)
        if staff_profile.verification_submitted_at and not staff_profile.is_identity_verified:
            messages.info(request, "Your identity verification is pending admin approval. You'll be notified once verified.")
            return render(request, 'staff/pending_approval.html', {
                'staff_profile': staff_profile,
                'message': 'Your documents are under review. This usually takes 24-48 hours.'
            })
        
        # Check if verification code exists and is not expired (24 hours)
        from django.utils import timezone
        from datetime import timedelta
        
        if staff_profile.verification_code and staff_profile.verification_sent_at:
            time_diff = timezone.now() - staff_profile.verification_sent_at
            is_expired = time_diff > timedelta(hours=24)
            
            if is_expired:
                staff_profile.verification_code = generate_verification_code()
                staff_profile.verification_sent_at = timezone.now()
                staff_profile.verification_attempts = 0
                staff_profile.save(update_fields=['verification_code', 'verification_sent_at', 'verification_attempts'])
                
                from .utils.email_verification import send_itp_verification_email
                send_itp_verification_email(staff_profile, request)
                
                messages.warning(request, "Your previous verification code has expired. A new 6-digit code has been sent to your email.")
            else:
                hours_remaining = 24 - (time_diff.seconds // 3600)
                minutes_remaining = (time_diff.seconds % 3600) // 60
                messages.warning(
                    request, 
                    f"Please complete identity verification to access the dashboard. "
                    f"Your verification code expires in {hours_remaining}h {minutes_remaining}m."
                )
        else:
            from .utils.email_verification import send_itp_verification_email
            from django.utils import timezone
            
            staff_profile.verification_code = generate_verification_code()
            staff_profile.verification_sent_at = timezone.now()
            staff_profile.verification_attempts = 0
            staff_profile.save(update_fields=['verification_code', 'verification_sent_at', 'verification_attempts'])
            
            send_itp_verification_email(staff_profile, request)
            messages.info(request, "Welcome! Please verify your identity to access the dashboard. A 6-digit verification code has been sent to your email.")
        
        request.session['intended_dashboard_url'] = request.path
        return redirect('staff:verify_identity', staff_id=staff_profile.id)
    
    # ============================================
    # STEP 4: CHECK GROUPS FIRST (BEFORE SUPERUSER!)
    # ============================================
    # Get user's groups
    user_groups = request.user.groups.values_list('name', flat=True)
    logger.info(f"🔴 DASHBOARD - User {request.user.username} groups: {list(user_groups)}")
    
    # Define group to dashboard mapping (PRIORITY ORDER)
    dashboard_routes = {
        'Technician': 'staff:technician_dashboard', 
        'Senior Technician': 'staff:technician_dashboard', 
        'Workshop Technician': 'staff:technician_dashboard', 
        'Cashier': 'staff:cashier_dashboard',
        'Sales Agent': 'staff:sales_agent_dashboard',
        'Sales Manager': 'staff:sales_manager_dashboard',
        'Store Manager': 'staff:store_manager_dashboard',
        'Inventory Manager': 'staff:store_manager_dashboard',
        'Credit Manager': 'staff:credit_manager_dashboard',
        'Credit Officer': 'staff:credit_officer_dashboard',
        'Customer Service': 'staff:customer_service_dashboard',
        'Finance Manager': 'staff:finance_manager_dashboard',
        'Security Officer': 'staff:security_dashboard',
        'M-Pesa Agent': 'staff:mpesa_agent_dashboard',
        'Cleaner': 'staff:cleaner_dashboard',
        'Assistant Manager': 'staff:supervisor_dashboard',
        'Administrator': 'staff:admin_dashboard',
    }
    
    # Find matching dashboard based on group (FIRST MATCH WINS)
    intended_url = None
    for group_name, dashboard_url in dashboard_routes.items():
        if group_name in user_groups:
            intended_url = dashboard_url
            logger.info(f"🔴 DASHBOARD - Matched group '{group_name}' to dashboard: {dashboard_url}")
            break
    
    # ============================================
    # STEP 5: If no group found, THEN check superuser
    # ============================================
    if not intended_url:
        if request.user.is_superuser:
            intended_url = 'staff:admin_dashboard'
            logger.info(f"🔴 DASHBOARD - No groups found, using superuser admin dashboard")
        else:
            intended_url = 'staff:staff_stats_dashboard'  # Default fallback
            logger.info(f"🔴 DASHBOARD - No groups found, using default stats dashboard")
    
    logger.info(f"🔴 DASHBOARD - Final intended URL for {request.user.username}: {intended_url}")
    
    # ============================================
    # STEP 6: OTP CHECK (commented out)
    # ============================================
    # OTP bypassed for now
    
    # ============================================
    # STEP 7: Redirect to the intended dashboard
    # ============================================
    return redirect(intended_url)







# ==========================================
# ADMIN DASHBOARD - COMPREHENSIVE STATISTICS
# ==========================================
@login_required
@dashboard_for_role('Administrator')
def admin_dashboard(request):
    """Admin dashboard with full system overview - includes active sales, returns, and reversals"""
    from django.contrib.auth import get_user_model
    from inventory.models import Product, Category, StockAlert, ReturnRequest
    from sales.models import Sale, SaleItem
    from credit.models import CreditTransaction, CreditCustomer, CreditCompany
    from finance.models import NetAccount, SavingsAccount, InjectionAccount
    from finance.utils import UnifiedFinanceCalculator  # ← ADD THIS IMPORT
    from django.db.models import Sum, Count, Q, F, Avg, DecimalField, Case, When, Value, IntegerField, ExpressionWrapper
    from django.utils import timezone
    from datetime import timedelta
    from decimal import Decimal
    
    User = get_user_model()

    prepare_dashboard_messages(request, 'Admin')
    
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Get current month range
    current_year = today.year
    current_month = today.month
    
    # ============================================
    # USE UNIFIED FINANCE CALCULATOR FOR ACCURATE MONTHLY DATA
    # ============================================
    
    # Get current month data using UnifiedFinanceCalculator
    month_data = UnifiedFinanceCalculator.get_period_data('month')
    
    # Get previous month for comparison
    if current_month == 1:
        prev_month_start = timezone.datetime(current_year - 1, 12, 1).date()
        prev_month_end = timezone.datetime(current_year - 1, 12, 31).date()
    else:
        import calendar
        prev_month_start = timezone.datetime(current_year, current_month - 1, 1).date()
        last_day = calendar.monthrange(current_year, current_month - 1)[1]
        prev_month_end = timezone.datetime(current_year, current_month - 1, last_day).date()
    
    prev_month_revenue = UnifiedFinanceCalculator.calculate_revenue(prev_month_start, prev_month_end)
    prev_month_cogs = UnifiedFinanceCalculator.calculate_cogs(prev_month_start, prev_month_end)
    prev_month_profit = prev_month_revenue - prev_month_cogs
    
    # Calculate monthly percentage change
    if prev_month_revenue > 0:
        monthly_percentage_change = ((month_data['revenue'] - prev_month_revenue) / prev_month_revenue) * 100
    else:
        monthly_percentage_change = 100 if month_data['revenue'] > 0 else 0
    
    # Get finance accounts for overall totals
    net = NetAccount.get_account()
    savings = SavingsAccount.get_account()
    injection = InjectionAccount.get_account()
    
    # ============================================
    # GET RETURNED SALE IDs (to exclude from active sales)
    # ============================================
    returned_sale_ids = ReturnRequest.objects.filter(
        ~Q(status='rejected')
    ).exclude(
        Q(sale_id__isnull=True) | Q(sale_id='')
    ).values_list('sale_id', flat=True).distinct()
    
    # ============================================
    # ACTIVE SALES (exclude reversed AND returned)
    # ============================================
    active_sales = Sale.objects.filter(
        is_reversed=False
    ).exclude(
        sale_id__in=returned_sale_ids
    )
    
    # ============================================
    # CURRENT MONTH'S SALES (using date filtering)
    # ============================================
    current_month_sales = active_sales.filter(
        sale_date__year=current_year,
        sale_date__month=current_month
    )
    
    # CORRECT current month values from filtered queryset
    current_month_sales_value_db = current_month_sales.aggregate(
        total=Sum('total_amount')
    )['total'] or Decimal('0')
    
    current_month_sales_count = current_month_sales.count()
    current_month_items_sold = SaleItem.objects.filter(
        sale__in=current_month_sales
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    # Use unified calculator values (should match database values)
    current_month_sales_value = month_data['revenue']
    current_month_profit = month_data['net_profit']
    current_month_cogs = month_data['cogs']
    
    # Get month name
    month_name = timezone.now().strftime('%B')
    
    # ============================================
    # SYSTEM OVERVIEW
    # ============================================
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    total_staff = User.objects.filter(is_staff=True).count()
    total_products = Product.objects.count()
    total_categories = Category.objects.count()
    
    # ============================================
    # PRODUCT STATS - CORRECTED FOR BULK ITEMS
    # ============================================
    
    total_item_count = 0
    total_inventory_value = Decimal('0')
    total_inventory_cost = Decimal('0')
    zero_stock_products = 0
    out_of_stock = 0
    single_items = 0
    bulk_items = 0
    active_products = 0
    inactive_products = 0
    
    for product in Product.objects.all():
        if product.category.is_single_item:
            single_items += 1
            quantity = product.total_quantity or 0
        else:
            bulk_items += 1
            quantity = product.bulk_quantity or 0
        
        if product.is_active:
            active_products += 1
        else:
            inactive_products += 1
        
        total_item_count += quantity
        
        if product.is_active:
            selling_price = product.selling_price or Decimal('0')
            buying_price = product.buying_price or Decimal('0')
            
            total_inventory_value += selling_price * quantity
            total_inventory_cost += buying_price * quantity
        
        if quantity == 0:
            zero_stock_products += 1
            out_of_stock += 1
    
    potential_profit = total_inventory_value - total_inventory_cost
    
    if total_inventory_value > 0:
        profit_margin_percentage = (potential_profit / total_inventory_value) * Decimal('100')
    else:
        profit_margin_percentage = Decimal('0')
    
    products_added_this_month = Product.objects.filter(
        created_at__year=current_year,
        created_at__month=current_month
    ).count()
    
    low_stock_products = Product.objects.filter(
        category__item_type='bulk',
        is_active=True,
        bulk_quantity__gt=0,
        bulk_quantity__lte=F('reorder_level')
    ).count()
    
    active_alerts = StockAlert.objects.filter(
        is_active=True,
        is_dismissed=False
    ).count()
    critical_alerts = StockAlert.objects.filter(
        is_active=True,
        is_dismissed=False,
        severity__in=['critical', 'danger']
    ).count()
    
    # ============================================
    # TODAY'S STATS
    # ============================================
    today_sales = active_sales.filter(sale_date__date=today).aggregate(
        total=Sum('total_amount')
    )['total'] or Decimal('0')
    today_sales_count = active_sales.filter(sale_date__date=today).count()
    today_items_sold = SaleItem.objects.filter(
        sale__in=active_sales.filter(sale_date__date=today)
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    # ============================================
    # OVERALL SALES STATS (using unified calculator for consistency)
    # ============================================
    total_sales_count = active_sales.count()
    total_items_sold = SaleItem.objects.filter(
        sale__in=active_sales
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    # Get all-time totals from unified calculator
    all_time_revenue = UnifiedFinanceCalculator.calculate_revenue()
    all_time_cogs = UnifiedFinanceCalculator.calculate_cogs()
    all_time_profit = all_time_revenue - all_time_cogs
    
    if total_sales_count > 0:
        avg_transaction_value = all_time_revenue / Decimal(str(total_sales_count))
    else:
        avg_transaction_value = Decimal('0')
    
    # ============================================
    # REVERSAL STATS
    # ============================================
    reversed_sales = Sale.objects.filter(is_reversed=True)
    reversed_count = reversed_sales.count()
    reversed_amount = reversed_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
    
    # ============================================
    # RETURN STATS
    # ============================================
    all_returns = ReturnRequest.objects.all()
    total_returns = all_returns.count()
    total_refund_amount = all_returns.aggregate(total=Sum('refund_amount'))['total'] or Decimal('0')
    
    returns_by_status = all_returns.filter(status__in=['submitted', 'verified']).count()
    approved_returns = all_returns.filter(status='approved').count()
    processed_returns = all_returns.filter(status='processed').count()
    rejected_returns = all_returns.filter(status='rejected').count()
    damaged_returns = all_returns.filter(status='damaged_loss').count()
    
    damaged_loss = all_returns.filter(status='damaged_loss').aggregate(
        total=Sum('refund_amount')
    )['total'] or Decimal('0')
    
    # ============================================
    # CREDIT STATS
    # ============================================
    total_credit = CreditTransaction.objects.aggregate(
        total=Sum('ceiling_price')
    )['total'] or Decimal('0')
    
    total_pending_credit_value = CreditTransaction.objects.filter(
        payment_status='pending'
    ).aggregate(
        total=Sum('ceiling_price')
    )['total'] or Decimal('0')
    
    total_paid_credit_value = CreditTransaction.objects.filter(
        payment_status='paid'
    ).aggregate(
        total=Sum('ceiling_price')
    )['total'] or Decimal('0')
    
    pending_credit = CreditTransaction.objects.filter(payment_status='pending').count()
    paid_credit = CreditTransaction.objects.filter(payment_status='paid').count()
    overdue_credit = CreditTransaction.objects.filter(
        payment_status='pending',
        transaction_date__date__lte=month_ago
    ).count()
    
    if total_credit > 0:
        payment_completion_percentage = (total_paid_credit_value / total_credit) * Decimal('100')
    else:
        payment_completion_percentage = Decimal('0')
    
    overdue_credit_amount = CreditTransaction.objects.filter(
        payment_status='pending',
        transaction_date__date__lte=month_ago
    ).aggregate(
        total=Sum('ceiling_price')
    )['total'] or Decimal('0')
    
    # ============================================
    # CUSTOMER STATS
    # ============================================
    total_customers = CreditCustomer.objects.count()
    active_customers = CreditCustomer.objects.filter(is_active=True).count()
    new_customers_today = CreditCustomer.objects.filter(
        created_at__date=today
    ).count()
    
    # ============================================
    # STAFF BY POSITION
    # ============================================
    from staff.models import Staff
    staff_by_position = Staff.objects.values('position').annotate(
        count=Count('id')
    ).order_by('position')
    
    total_staff_count = Staff.objects.count()
    
    # ============================================
    # RECENT ACTIVITIES
    # ============================================
    recent_sales = active_sales.select_related('seller').order_by('-sale_date')[:10]
    recent_returns = ReturnRequest.objects.select_related(
        'requested_by', 'product'
    ).order_by('-requested_at')[:10]
    recent_users = User.objects.order_by('-date_joined')[:10]
    recent_credits = CreditTransaction.objects.select_related(
        'customer', 'dealer'
    ).order_by('-transaction_date')[:10]
    
    # ============================================
    # CHART DATA (last 7 days)
    # ============================================
    labels = []
    sales_data = []
    credit_data = []
    return_data = []
    
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        labels.append(date.strftime('%d %b'))
        
        # Use UnifiedFinanceCalculator for daily sales
        day_sales = UnifiedFinanceCalculator.calculate_revenue(date, date)
        sales_data.append(float(day_sales))
        
        day_credit = CreditTransaction.objects.filter(
            paid_date__date=date,
            payment_status='paid'
        ).aggregate(
            total=Sum('ceiling_price')
        )['total'] or Decimal('0')
        credit_data.append(float(day_credit))
        
        day_returns = ReturnRequest.objects.filter(
            requested_at__date=date
        ).aggregate(
            total=Sum('refund_amount')
        )['total'] or Decimal('0')
        return_data.append(float(day_returns))
    
    # ============================================
    # TOP SELLING PRODUCTS
    # ============================================
    top_products = SaleItem.objects.filter(
        sale__in=active_sales
    ).values('product_name', 'product_code').annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('total_price')
    ).order_by('-total_quantity')[:10]
    
    # ============================================
    # TOP SELLERS
    # ============================================
    top_sellers = User.objects.filter(
        sales_made__in=active_sales
    ).annotate(
        sales_count=Count('sales_made'),
        total_sales=Sum('sales_made__total_amount'),
        avg_sale=Avg('sales_made__total_amount')
    ).order_by('-total_sales')[:10]
    
    # ============================================
    # PAYMENT METHOD BREAKDOWN
    # ============================================
    payment_methods = []
    for method in ['Cash', 'M-Pesa', 'Card', 'Points', 'Credit']:
        method_sales = active_sales.filter(payment_method=method)
        count = method_sales.count()
        amount = method_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        if all_time_revenue > 0:
            percentage = float((amount / all_time_revenue) * Decimal('100'))
        else:
            percentage = 0
        
        payment_methods.append({
            'name': method,
            'count': count,
            'amount': float(amount),
            'percentage': percentage
        })
    
    # ============================================
    # SUMMARY CARD DATA
    # ============================================
    context = {
        # System Overview
        'total_users': total_users,
        'active_users': active_users,
        'total_staff': total_staff,
        'total_staff_count': total_staff_count,
        'total_products': total_products,
        'total_categories': total_categories,
        
        # Product Stats (CORRECTED)
        'total_item_count': total_item_count,
        'total_inventory_value': float(total_inventory_value),
        'total_inventory_cost': float(total_inventory_cost),
        'potential_profit': float(potential_profit),
        'profit_margin_percentage': float(profit_margin_percentage),
        'products_added_this_month': products_added_this_month,
        'zero_stock_products': zero_stock_products,
        'active_products': active_products,
        'inactive_products': inactive_products,
        'single_items': single_items,
        'bulk_items': bulk_items,
        'out_of_stock': out_of_stock,
        'low_stock_products': low_stock_products,
        'active_alerts': active_alerts,
        'critical_alerts': critical_alerts,
        
        # Today's Stats
        'today_sales': float(today_sales),
        'today_sales_count': today_sales_count,
        'today_items_sold': today_items_sold,
        
        # Current Month's Stats - CORRECTED using unified calculator
        'current_month_sales_value': float(month_data['revenue']),  # ← CORRECT
        'current_month_sales_count': current_month_sales_count,
        'current_month_items_sold': current_month_items_sold,
        'current_month_profit': float(month_data['net_profit']),  # ← CORRECT
        'current_month_cogs': float(month_data['cogs']),  # ← CORRECT
        'month_name': month_name,
        'monthly_percentage_change': float(monthly_percentage_change),
        'previous_month_sales': float(prev_month_revenue),
        
        # Sales Overview - CORRECTED using unified calculator
        'total_sales_value': float(all_time_revenue),  # ← CORRECT
        'total_sales_count': total_sales_count,
        'total_items_sold': total_items_sold,
        'avg_transaction_value': float(avg_transaction_value),
        'total_profit': float(all_time_profit),  # ← CORRECT
        'total_cogs': float(all_time_cogs),  # ← CORRECT
        'total_injections': float(injection.total_injected_all_time),
        
        # Reversal Stats
        'reversed_count': reversed_count,
        'reversed_amount': float(reversed_amount),
        'reversal_percentage': (reversed_count / (total_sales_count + reversed_count) * 100) if (total_sales_count + reversed_count) > 0 else 0,
        
        # Return Stats
        'total_returns': total_returns,
        'total_refund_amount': float(total_refund_amount),
        'pending_returns': returns_by_status,
        'approved_returns': approved_returns,
        'processed_returns': processed_returns,
        'rejected_returns': rejected_returns,
        'damaged_returns': damaged_returns,
        'damaged_loss': float(damaged_loss),
        
        # Credit Stats
        'total_credit': float(total_credit),
        'total_pending_credit_value': float(total_pending_credit_value),
        'total_paid_credit_value': float(total_paid_credit_value),
        'pending_credit': pending_credit,
        'paid_credit': paid_credit,
        'overdue_credit': overdue_credit,
        'overdue_credit_amount': float(overdue_credit_amount),
        'payment_completion_percentage': float(payment_completion_percentage),
        
        # Customer Stats
        'total_customers': total_customers,
        'active_customers': active_customers,
        'new_customers_today': new_customers_today,
        
        # Staff Stats
        'staff_by_position': staff_by_position,
        
        # Recent Activities
        'recent_sales': recent_sales,
        'recent_returns': recent_returns,
        'recent_users': recent_users,
        'recent_credits': recent_credits,
        
        # Chart Data
        'chart_labels': labels,
        'sales_data': sales_data,
        'credit_data': credit_data,
        'return_data': return_data,
        
        # Top Performers
        'top_products': top_products,
        'top_sellers': top_sellers,
        'payment_methods': payment_methods,
    }
    
    return render(request, 'staff/dashboards/admin_dashboard.html', context)





# ============================================
# STORE MANAGER DASHBOARD - FIXED WITH STOCK ALERTS
# ============================================
@login_required
@dashboard_for_role('Store Manager', 'Inventory Manager')
def store_manager_dashboard(request):
    """Dashboard for store manager"""
    from inventory.models import Product, Category, StockAlert, StockEntry, ProductUnit
    from sales.models import SaleItem
    from django.db.models import Sum, Count, Q, F, Case, When, Value, IntegerField, DecimalField
    from django.contrib import messages
    from django.utils import timezone
    from datetime import timedelta
    from decimal import Decimal
    
    prepare_dashboard_messages(request, 'Store Manager')

    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    
    # ============================================
    # INVENTORY OVERVIEW
    # ============================================
    total_products = Product.objects.count()
    total_categories = Category.objects.count()
    
    # Stock value calculation - using current_stock property
    products = Product.objects.filter(is_active=True).select_related('category')
    total_stock_value = Decimal('0.00')
    for product in products:
        if product.category.is_bulk_item:
            stock = product.bulk_quantity
        else:
            stock = product.available_quantity
        if product.buying_price:
            total_stock_value += product.buying_price * stock
    
    # ============================================
    # STOCK ALERTS - USING STOCKALERT MODEL
    # ============================================
    # Get active alerts that are not dismissed (only bulk items)
    active_alerts = StockAlert.objects.filter(
        is_active=True,
        is_dismissed=False,
        product__category__item_type='bulk'  # Only bulk items have stock alerts
    ).select_related('product', 'product__category').order_by(
        '-severity',  # Critical first
        '-last_alerted'
    )
    
    # Count alerts by type
    low_stock_alerts_count = active_alerts.filter(alert_type='lowstock').count()
    needs_reorder_count = active_alerts.filter(alert_type='needs_reorder').count()
    out_of_stock_count = active_alerts.filter(alert_type='outofstock').count()
    
    # Get low stock alerts for display (limit to 3)
    low_stock_alerts = active_alerts[:3]
    
    # ============================================
    # PRODUCT STATUS (using new model fields)
    # ============================================
    # For bulk items: check bulk_quantity vs reorder_level
    bulk_products = Product.objects.filter(category__item_type='bulk', is_active=True)
    available_bulk = bulk_products.filter(bulk_quantity__gt=0).count()
    low_stock_bulk = bulk_products.filter(
        bulk_quantity__gt=0,
        bulk_quantity__lte=F('reorder_level')
    ).count()
    out_of_stock_bulk = bulk_products.filter(bulk_quantity=0).count()
    
    # For single items: check available_quantity
    single_products = Product.objects.filter(category__item_type='single', is_active=True)
    available_single = single_products.filter(available_quantity__gt=0).count()
    out_of_stock_single = single_products.filter(available_quantity=0).count()
    
    # Total counts
    available_products = available_bulk + available_single
    low_stock_products = low_stock_bulk  # Single items don't have low stock alerts
    out_of_stock = out_of_stock_bulk + out_of_stock_single
    
    # Stolen/Lost units (from ProductUnit, not Product SKU)
    stolen_units_count = ProductUnit.objects.filter(status='stolen').count()
    lost_units_count = ProductUnit.objects.filter(status='lost').count()
    stolen_lost_count = stolen_units_count + lost_units_count
    
    # Damaged units (from ProductUnit)
    damaged_units_count = ProductUnit.objects.filter(status='damaged').count()
    
    # Overstock (products with bulk_quantity > 100)
    overstock = Product.objects.filter(
        category__item_type='bulk',
        bulk_quantity__gt=100
    ).count()
    
    # ============================================
    # RECENT STOCK MOVEMENTS
    # ============================================
    recent_movements = StockEntry.objects.select_related(
        'product_sku', 'product_unit', 'created_by'
    ).order_by('-created_at')[:3]
    
    # ============================================
    # CATEGORY-WISE STOCK
    # ============================================
    stock_by_category = []
    for category in Category.objects.filter(is_active=True):
        cat_products = category.products.filter(is_active=True)
        product_count = cat_products.count()
        
        # Calculate total stock based on category type
        if category.is_bulk_item:
            total_stock = cat_products.aggregate(total=Sum('bulk_quantity'))['total'] or 0
        else:
            total_stock = cat_products.aggregate(total=Sum('available_quantity'))['total'] or 0
        
        stock_by_category.append({
            'name': category.name,
            'product_count': product_count,
            'total_stock': total_stock
        })
    # Sort by total_stock descending
    stock_by_category = sorted(stock_by_category, key=lambda x: x['total_stock'], reverse=True)[:10]
    
    # ============================================
    # TOP SELLING PRODUCTS (using SKU code)
    # ============================================
    try:
        top_selling = SaleItem.objects.values(
            'product_name', 'product_code'
        ).annotate(
            total_sold=Sum('quantity'),
            total_revenue=Sum('total_price')
        ).order_by('-total_sold')[:3]
    except:
        top_selling = []
    
    # ============================================
    # RECENT PRODUCTS & NEW THIS WEEK
    # ============================================
    new_products_week = Product.objects.filter(created_at__date__gte=week_ago).count()
    recent_products = Product.objects.select_related('category').order_by('-created_at')[:3]
    
    # ============================================
    # PENDING RETURNS
    # ============================================
    try:
        from inventory.models import ReturnRequest
        pending_returns = ReturnRequest.objects.filter(
            status__in=['submitted', 'verified']
        ).select_related('product', 'requested_by').order_by('-requested_at')[:3]
        pending_returns_count = ReturnRequest.objects.filter(
            status__in=['submitted', 'verified']
        ).count()
        verified_returns_count = ReturnRequest.objects.filter(status='verified').count()
    except:
        pending_returns = []
        pending_returns_count = 0
        verified_returns_count = 0
    
    context = {
        # Basic counts
        'total_products': total_products,
        'total_categories': total_categories,
        'total_stock_value': total_stock_value,
        
        # Stock alerts
        'low_stock_alerts': low_stock_alerts,
        'low_stock_alerts_count': low_stock_alerts_count,
        'needs_reorder_count': needs_reorder_count,
        'out_of_stock_count': out_of_stock_count,
        
        # Product status counts
        'low_stock_products': low_stock_products,
        'out_of_stock': out_of_stock,
        'available_products': available_products,
        'stolen_lost_count': stolen_lost_count,
        'stolen_units_count': stolen_units_count,
        'lost_units_count': lost_units_count,
        'damaged_units_count': damaged_units_count,
        'overstock': overstock,
        
        # Recent data
        'recent_movements': recent_movements,
        'recent_products': recent_products,
        'new_products_week': new_products_week,
        
        # Category and sales data
        'stock_by_category': stock_by_category,
        'top_selling': top_selling,
        
        # Return data
        'pending_returns': pending_returns,
        'pending_returns_count': pending_returns_count,
        'verified_returns_count': verified_returns_count,
        
        # Date
        'today': today,
    }
    
    return render(request, 'staff/dashboards/store_manager_dashboard.html', context)




# ============================================
# SALES AGENT DASHBOARD - WITH PRODUCT LOOKUP (UPDATED FOR SKU SYSTEM)
# ============================================
@login_required
@dashboard_for_role('Sales Agent')
def sales_agent_dashboard(request):
    """Dashboard for sales agents with product price lookup - Updated for SKU system"""
    from sales.models import Sale, SaleItem
    from inventory.models import Product, Category
    from django.db.models import Sum, Count, Q, F, Value, DecimalField
    from django.db.models.functions import Coalesce
    from django.utils import timezone
    from datetime import timedelta
    from django.http import JsonResponse
    from decimal import Decimal
    import json
    
    # Check if this is an AJAX lookup request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.GET.get('action') == 'lookup':
        return product_lookup_api(request)
    
    prepare_dashboard_messages(request, 'Sales Agent')
    
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # My Sales Performance - FIXED: Added output_field for Decimal
    my_sales_today = Sale.objects.filter(
        seller=request.user,
        sale_date__date=today
    ).aggregate(
        total=Coalesce(Sum('total_amount'), Value(Decimal('0.00'), output_field=DecimalField())),
        count=Count('sale_id')
    )
    
    my_sales_week = Sale.objects.filter(
        seller=request.user,
        sale_date__date__gte=week_ago
    ).aggregate(
        total=Coalesce(Sum('total_amount'), Value(Decimal('0.00'), output_field=DecimalField())),
        count=Count('sale_id')
    )
    
    my_sales_month = Sale.objects.filter(
        seller=request.user,
        sale_date__date__gte=month_ago
    ).aggregate(
        total=Coalesce(Sum('total_amount'), Value(Decimal('0.00'), output_field=DecimalField())),
        count=Count('sale_id')
    )
    
    # Recent Sales
    recent_sales = Sale.objects.filter(
        seller=request.user
    ).select_related('seller').order_by('-sale_date')[:5]
    
    # Top Products I Sold - Use product relationship
    top_products = SaleItem.objects.filter(
        sale__seller=request.user
    ).values(
        'product__sku_code',
        'product_name'
    ).annotate(
        total_qty=Sum('quantity'),
        total_value=Sum('total_price')
    ).order_by('-total_qty')[:5]
    
    # Convert top_products to list with proper values
    top_products_list = []
    for product in top_products:
        top_products_list.append({
            'sku_code': product.get('product__sku_code', 'N/A'),
            'product_name': product.get('product_name', 'Unknown'),
            'total_qty': product.get('total_qty', 0),
            'total_value': float(product.get('total_value', 0)) if product.get('total_value') else 0,
        })
    
    # Get all categories for filter dropdown
    categories = Category.objects.filter(is_active=True)
    
    # Get low stock products count for notification
    low_stock_count = Product.objects.filter(
        is_active=True,
        is_discontinued=False,
        category__item_type='bulk',
        bulk_quantity__gt=0,
        bulk_quantity__lte=F('reorder_level')
    ).count()
    
    out_of_stock_count = Product.objects.filter(
        is_active=True,
        is_discontinued=False
    ).filter(
        Q(category__item_type='single', available_quantity=0) |
        Q(category__item_type='bulk', bulk_quantity=0)
    ).count()
    
    # Daily targets
    daily_target = Decimal('50000')  # KSH 50,000 as Decimal
    total_today = my_sales_today['total'] or Decimal('0')
    target_achievement = float((total_today / daily_target * 100)) if daily_target > 0 else 0
    
    context = {
        'my_sales_today': {
            'total': float(my_sales_today['total']),
            'count': my_sales_today['count']
        },
        'my_sales_week': {
            'total': float(my_sales_week['total']),
            'count': my_sales_week['count']
        },
        'my_sales_month': {
            'total': float(my_sales_month['total']),
            'count': my_sales_month['count']
        },
        'recent_sales': recent_sales,
        'top_products': top_products_list,
        'daily_target': float(daily_target),
        'target_achievement': target_achievement,
        'categories': categories,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
    }
    return render(request, 'staff/dashboards/sales_agent_dashboard.html', context)


# ============================================
# PRODUCT LOOKUP API - UPDATED FOR SKU SYSTEM
# ============================================
def product_lookup_api(request):
    """
    API endpoint for product lookup using new SKU system.
    Searches across: sku_code, name, brand, model, specifications
    """
    import logging
    from inventory.models import Product, Category
    from django.db.models import Q
    from decimal import Decimal
    
    logger = logging.getLogger(__name__)
    
    search_term = request.GET.get('q', '').strip()
    category_id = request.GET.get('category', '')
    
    if not search_term or len(search_term) < 2:
        return JsonResponse({
            'success': False,
            'message': 'Please enter at least 2 characters'
        })
    
    try:
        # Build search query using new Product model fields
        products = Product.objects.filter(
            Q(sku_code__icontains=search_term) |
            Q(name__icontains=search_term) |
            Q(brand__icontains=search_term) |
            Q(model__icontains=search_term) |
            Q(specifications__icontains=search_term)
        ).filter(
            is_active=True,
            is_discontinued=False
        ).select_related('category')
        
        # Apply category filter if provided
        if category_id:
            products = products.filter(category_id=category_id)
        
        # Only show products with available stock
        # For single items: check available_quantity > 0
        # For bulk items: check bulk_quantity > 0
        products = products.filter(
            Q(category__item_type='single', available_quantity__gt=0) |
            Q(category__item_type='bulk', bulk_quantity__gt=0)
        )[:20]
        
        # Log the count
        logger.info(f"🔍 Products found: {products.count()}")
        
        total_products = Product.objects.count()
        logger.info(f"🔍 Total products in database: {total_products}")
        
        if total_products == 0:
            return JsonResponse({
                'success': False,
                'message': 'No products in database'
            })
        
        if not products.exists():
            return JsonResponse({
                'success': False,
                'message': 'No products found matching your search'
            })
        
        # Build products list with new fields
        products_list = []
        for product in products:
            # Get available stock
            if product.category.is_single_item:
                available_stock = product.available_quantity
                stock_status = 'available'
            else:
                available_stock = product.bulk_quantity
                stock_status = 'bulk'
            
            # Format specifications
            specs = {}
            if product.specifications and isinstance(product.specifications, dict):
                specs = {
                    'ram': product.specifications.get('ram', ''),
                    'storage': product.specifications.get('storage', ''),
                    'color': product.specifications.get('color', ''),
                    'screen_size': product.specifications.get('screen_size', ''),
                }
            
            products_list.append({
                'id': product.id,
                'sku_code': product.sku_code,
                'name': product.name,
                'display_name': product.display_name,
                'selling_price': float(product.selling_price) if product.selling_price else 0,
                'buying_price': float(product.buying_price) if product.buying_price else 0,
                'best_price': float(product.best_price) if product.best_price else None,
                'brand': product.brand,
                'model': product.model,
                'available_stock': available_stock,
                'stock_status': stock_status,
                'category': product.category.name if product.category else '',
                'category_id': product.category.id if product.category else None,
                'is_single_item': product.category.is_single_item if product.category else False,
                'condition': product.get_condition_display() if hasattr(product, 'get_condition_display') else 'New',
                'warranty_months': product.warranty_months or 12,
                'specifications': specs,
                'has_image': bool(product.image),
                'image_url': product.image.url if product.image else None,
            })
        
        response_data = {
            'success': True,
            'products': products_list,
            'total_matches': len(products_list),
            'message': f'Found {len(products_list)} product(s)'
        }
        
        logger.info(f"🔍 Sending response with {len(products_list)} products")
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"🔍 Product lookup error: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'Error searching for products: {str(e)}'
        }, status=500)




# ============================================
# TECHNICIAN DASHBOARD - FIXED VERSION
# ============================================
@login_required
@dashboard_for_role('Technician', 'Senior Technician', 'Workshop Technician')
def technician_dashboard(request):
    """Dashboard for workshop technicians - shows assigned repair jobs"""
    from workshop.models import RepairJob
    from shops.models import ShopBranch
    from django.db.models import Sum, Count
    from decimal import Decimal
    from datetime import timedelta
    
    prepare_dashboard_messages(request, 'Technician')
    
    today = timezone.now().date()
    
    # Get technician's name from staff profile or user
    try:
        staff_profile = Staff.objects.get(user=request.user)
        technician_name = staff_profile.user.get_full_name() or staff_profile.user.username
        assigned_shop = staff_profile.assigned_shop
    except:
        technician_name = request.user.get_full_name() or request.user.username
        assigned_shop = None
    
    # Get jobs assigned to this technician
    jobs = RepairJob.objects.filter(technician_name=technician_name).select_related('shop')
    
    # Statistics
    total_jobs = jobs.count()
    pending_jobs = jobs.filter(status='pending').count()
    in_progress_jobs = jobs.filter(status='in_progress').count()
    completed_jobs = jobs.filter(status='completed').count()
    picked_up_jobs = jobs.filter(status='picked_up').count()
    
    # Financial stats
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    # Lists for each status
    pending_jobs_list = jobs.filter(status='pending').order_by('-created_at')
    in_progress_jobs_list = jobs.filter(status='in_progress').order_by('-updated_at')
    completed_jobs_list = jobs.filter(status='completed').order_by('-completed_at')
    
    context = {
        'technician_name': technician_name,
        'assigned_shop': assigned_shop,
        'total_jobs': total_jobs,
        'pending_jobs': pending_jobs,
        'in_progress_jobs': in_progress_jobs,
        'completed_jobs': completed_jobs,
        'picked_up_jobs': picked_up_jobs,
        'total_revenue': total_revenue,
        'pending_jobs_list': pending_jobs_list,
        'in_progress_jobs_list': in_progress_jobs_list,
        'completed_jobs_list': completed_jobs_list,
        'today': today,
    }
    
    return render(request, 'staff/dashboards/technician_dashboard.html', context)


# ============================================
# TECHNICIAN JOB UPDATE (AJAX)
# ============================================
@login_required
@dashboard_for_role('Technician', 'Senior Technician', 'Workshop Technician')
def technician_update_job_status(request, job_id):
    """Update job status via AJAX for technicians"""
    from workshop.models import RepairJob
    
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
        
        # Check if job belongs to this technician
        if job.technician_name != technician_name and not request.user.is_superuser:
            return JsonResponse({'error': 'You are not assigned to this job'}, status=403)
        
        new_status = request.POST.get('status')
        notes = request.POST.get('notes', '')
        
        if new_status in ['pending', 'in_progress', 'completed', 'picked_up']:
            old_status = job.status
            job.status = new_status
            
            if notes:
                job.notes = notes
            
            # Auto-set timestamps
            if new_status == 'completed' and not job.completed_at:
                job.completed_at = timezone.now()
            elif new_status == 'picked_up' and not job.picked_up_at:
                job.picked_up_at = timezone.now()
            
            job.save()
            
            logger.info(f"Technician {technician_name} updated job #{job.id} from {old_status} to {new_status}")
            
            return JsonResponse({
                'success': True,
                'message': f'Job status updated to {job.get_status_display()}',
                'new_status': new_status,
                'status_display': job.get_status_display()
            })
        else:
            return JsonResponse({'error': 'Invalid status'}, status=400)
            
    except Exception as e:
        logger.error(f"Error updating job status: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


# ============================================
# TECHNICIAN MY JOBS
# ============================================
@login_required
@dashboard_for_role('Technician', 'Senior Technician', 'Workshop Technician')
def technician_jobs(request):
    """List only jobs assigned to the logged-in technician"""
    from workshop.models import RepairJob
    from shops.models import ShopBranch
    from django.core.paginator import Paginator
    from decimal import Decimal
    
    prepare_dashboard_messages(request, 'Technician')
    
    # Get technician's name
    try:
        staff_profile = Staff.objects.get(user=request.user)
        technician_name = staff_profile.user.get_full_name() or staff_profile.user.username
    except:
        technician_name = request.user.get_full_name() or request.user.username
    
    today = timezone.now().date()
    
    # Get ONLY jobs assigned to this technician
    jobs = RepairJob.objects.filter(technician_name=technician_name).select_related('shop')
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        jobs = jobs.filter(
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query) |
            Q(device_type__icontains=search_query) |
            Q(device_model__icontains=search_query)
        )
    
    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        jobs = jobs.filter(status=status_filter)
    
    # Filter by shop
    shop_filter = request.GET.get('shop', '')
    if shop_filter:
        jobs = jobs.filter(shop_id=shop_filter)
    
    # Calculate stats
    total_jobs = jobs.count()
    pending_count = jobs.filter(status='pending').count()
    in_progress_count = jobs.filter(status='in_progress').count()
    completed_count = jobs.filter(status='completed').count()
    picked_up_count = jobs.filter(status='picked_up').count()
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    # Pagination
    paginator = Paginator(jobs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get shops for filter
    shops = ShopBranch.objects.filter(is_active=True)
    
    context = {
        'jobs': page_obj,
        'technician_name': technician_name,
        'search_query': search_query,
        'status_filter': status_filter,
        'shop_filter': shop_filter,
        'shops': shops,
        'total_jobs': total_jobs,
        'pending_count': pending_count,
        'in_progress_count': in_progress_count,
        'completed_count': completed_count,
        'picked_up_count': picked_up_count,
        'total_revenue': total_revenue,
        'today': today,
    }
    
    return render(request, 'workshop/technician_jobs.html', context)


# ============================================
# TECHNICIAN PERFORMANCE
# ============================================
@login_required
@dashboard_for_role('Technician', 'Senior Technician', 'Workshop Technician')
def technician_performance(request):
    """Performance report for technician"""
    from workshop.models import RepairJob
    from decimal import Decimal
    from datetime import timedelta
    
    # Get technician name
    try:
        staff_profile = Staff.objects.get(user=request.user)
        technician_name = staff_profile.user.get_full_name() or staff_profile.user.username
    except:
        technician_name = request.user.get_full_name() or request.user.username
    
    # Date range filters
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
    
    # Average completion time
    completed_jobs_list = jobs.filter(status='completed', completed_at__isnull=False)
    avg_completion_hours = 0
    if completed_jobs_list.exists():
        total_hours = 0
        for job in completed_jobs_list:
            time_diff = job.completed_at - job.created_at
            total_hours += time_diff.total_seconds() / 3600
        avg_completion_hours = total_hours / completed_jobs_list.count()
    
    # Monthly performance
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
        'monthly_labels': monthly_labels,
        'monthly_jobs': monthly_jobs,
        'monthly_revenue': monthly_revenue,
        'today': today,
    }
    
    return render(request, 'staff/dashboards/technician_performance.html', context)


# ============================================
# TECHNICIAN REPORTS - ONLY OWN DATA
# ============================================
@login_required
@dashboard_for_role('Technician', 'Senior Technician', 'Workshop Technician')
def technician_reports(request):
    """Reports for technician - shows only their own data"""
    from workshop.models import RepairJob
    from django.db.models import Sum, Count, Q
    from decimal import Decimal
    from datetime import timedelta
    import json
    
    today = timezone.now().date()
    
    # Get technician's name
    try:
        staff_profile = Staff.objects.get(user=request.user)
        technician_name = staff_profile.user.get_full_name() or staff_profile.user.username
    except:
        technician_name = request.user.get_full_name() or request.user.username
    
    # Date range filters
    date_from = request.GET.get('date_from', (today - timedelta(days=30)).isoformat())
    date_to = request.GET.get('date_to', today.isoformat())
    
    # Get ONLY jobs assigned to this technician
    jobs = RepairJob.objects.filter(
        technician_name=technician_name,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to
    )
    
    # ============================================
    # STATISTICS CARDS
    # ============================================
    total_jobs = jobs.count()
    completed_jobs = jobs.filter(status='completed').count()
    in_progress_jobs = jobs.filter(status='in_progress').count()
    pending_jobs = jobs.filter(status='pending').count()
    picked_up_jobs = jobs.filter(status='picked_up').count()
    
    # Financial stats
    total_revenue = jobs.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_paid = jobs.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    total_material_cost = jobs.aggregate(total=Sum('material_cost'))['total'] or Decimal('0.00')
    total_labor_cost = jobs.aggregate(total=Sum('labor_cost'))['total'] or Decimal('0.00')
    net_profit = total_revenue - total_material_cost
    profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
    avg_job_value = total_revenue / total_jobs if total_jobs > 0 else 0
    
    # ============================================
    # CHART DATA - Last 30 days (only technician's jobs)
    # ============================================
    chart_labels = []
    revenue_data = []
    jobs_data = []
    
    for i in range(29, -1, -1):
        date = today - timedelta(days=i)
        chart_labels.append(date.strftime('%d %b'))
        
        day_jobs = jobs.filter(created_at__date=date)
        day_revenue = day_jobs.aggregate(total=Sum('total_amount'))['total'] or 0
        revenue_data.append(float(day_revenue))
        jobs_data.append(day_jobs.count())
    
    # ============================================
    # STATUS DISTRIBUTION
    # ============================================
    status_data = {
        'pending': pending_jobs,
        'in_progress': in_progress_jobs,
        'completed': completed_jobs,
        'picked_up': picked_up_jobs,
    }
    
    # ============================================
    # MONTHLY PERFORMANCE (Last 6 months)
    # ============================================
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
    
    # ============================================
    # DEVICE TYPE BREAKDOWN
    # ============================================
    device_stats = jobs.values('device_type').annotate(
        count=Count('id'),
        revenue=Sum('total_amount')
    ).order_by('-count')[:5]
    
    device_labels = [d['device_type'] for d in device_stats]
    device_counts = [d['count'] for d in device_stats]
    device_revenue = [float(d['revenue'] or 0) for d in device_stats]
    
    # ============================================
    # RECENT JOBS
    # ============================================
    recent_jobs = jobs.order_by('-created_at')[:10]
    
    # ============================================
    # PERFORMANCE METRICS
    # ============================================
    # Average completion time
    completed_with_time = jobs.filter(status='completed', completed_at__isnull=False)
    avg_completion_hours = 0
    if completed_with_time.exists():
        total_hours = 0
        for job in completed_with_time:
            time_diff = job.completed_at - job.created_at
            total_hours += time_diff.total_seconds() / 3600
        avg_completion_hours = total_hours / completed_with_time.count()
    
    # Completion rate
    completion_rate = (completed_jobs / total_jobs * 100) if total_jobs > 0 else 0
    
    # Daily average
    days_with_jobs = jobs.dates('created_at', 'day').count()
    daily_avg = total_jobs / days_with_jobs if days_with_jobs > 0 else 0
    
    context = {
        'technician_name': technician_name,
        'date_from': date_from,
        'date_to': date_to,
        'today': today,
        
        # Stats
        'total_jobs': total_jobs,
        'completed_jobs': completed_jobs,
        'in_progress_jobs': in_progress_jobs,
        'pending_jobs': pending_jobs,
        'picked_up_jobs': picked_up_jobs,
        
        # Financial
        'total_revenue': total_revenue,
        'total_paid': total_paid,
        'total_material_cost': total_material_cost,
        'total_labor_cost': total_labor_cost,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        'avg_job_value': avg_job_value,
        
        # Performance metrics
        'avg_completion_hours': round(avg_completion_hours, 1),
        'completion_rate': round(completion_rate, 1),
        'daily_avg': round(daily_avg, 1),
        
        # Chart data
        'chart_labels': json.dumps(chart_labels),
        'revenue_data': json.dumps(revenue_data),
        'jobs_data': json.dumps(jobs_data),
        'status_data': json.dumps(status_data),
        'monthly_labels': json.dumps(monthly_labels),
        'monthly_jobs': monthly_jobs,
        'monthly_revenue': monthly_revenue,
        'device_labels': json.dumps(device_labels),
        'device_counts': device_counts,
        'device_revenue': device_revenue,
        
        # Recent jobs
        'recent_jobs': recent_jobs,
    }
    
    return render(request, 'workshop/technician_reports.html', context)


# ============================================
# SALES MANAGER DASHBOARD - COMPLETE CORRECTED VERSION
# ============================================
@login_required
@dashboard_for_role('Sales Manager')
def sales_manager_dashboard(request):
    """Dashboard for sales manager - oversees all sales team"""
    from sales.models import Sale, SaleItem
    from django.contrib.auth import get_user_model
    from django.db.models import Sum, Count, Q
    from django.utils import timezone
    from datetime import datetime, timedelta
    
    User = get_user_model()

    prepare_dashboard_messages(request, 'Sales Manager')
    
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Create timezone-aware datetime objects for filtering
    today_start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    today_end = timezone.make_aware(datetime.combine(today, datetime.max.time()))
    week_start = timezone.make_aware(datetime.combine(week_ago, datetime.min.time()))
    month_start = timezone.make_aware(datetime.combine(month_ago, datetime.min.time()))
    
    # Team Overview
    try:
        from staff.models import StaffApplication
        sales_team = StaffApplication.objects.filter(
            status='approved',
            position__in=['sales_agent', 'cashier']
        ).count()
    except:
        sales_team = User.objects.filter(
            groups__name__in=['Sales Agent', 'Cashier']
        ).count()
    
    # Team Performance Today
    today_sales = Sale.objects.filter(
        sale_date__range=[today_start, today_end],
        is_reversed=False
    )
    team_sales_today = today_sales.aggregate(
        total=Sum('total_amount'),
        count=Count('sale_id')
    )
    
    # Team Performance This Week
    week_sales = Sale.objects.filter(
        sale_date__range=[week_start, today_end],
        is_reversed=False
    )
    team_sales_week = week_sales.aggregate(
        total=Sum('total_amount'),
        count=Count('sale_id')
    )
    
    # Team Performance This Month
    month_sales = Sale.objects.filter(
        sale_date__range=[month_start, today_end],
        is_reversed=False
    )
    team_sales_month = month_sales.aggregate(
        total=Sum('total_amount'),
        count=Count('sale_id')
    )
    
    # Sales by team member (today)
    sales_by_member_today = today_sales.values(
        'seller__username', 
        'seller__first_name', 
        'seller__last_name'
    ).annotate(
        total_sales=Sum('total_amount'),
        transaction_count=Count('sale_id'),
        avg_ticket=Sum('total_amount') / Count('sale_id')
    ).order_by('-total_sales')[:10]
    
    # Convert to list with proper values
    sales_by_member_today_list = []
    for member in sales_by_member_today:
        sales_by_member_today_list.append({
            'seller__username': member['seller__username'],
            'seller__first_name': member['seller__first_name'],
            'seller__last_name': member['seller__last_name'],
            'total_sales': float(member['total_sales'] or 0),
            'transaction_count': member['transaction_count'] or 0,
            'avg_ticket': float(member['avg_ticket'] or 0),
        })
    
    # Sales by team member (this week) - FIXED: Added this
    sales_by_member_week = week_sales.values(
        'seller__username', 
        'seller__first_name', 
        'seller__last_name'
    ).annotate(
        total_sales=Sum('total_amount'),
        transaction_count=Count('sale_id'),
        avg_ticket=Sum('total_amount') / Count('sale_id')
    ).order_by('-total_sales')[:10]
    
    # Convert to list
    sales_by_member_week_list = []
    for member in sales_by_member_week:
        sales_by_member_week_list.append({
            'seller__username': member['seller__username'],
            'seller__first_name': member['seller__first_name'],
            'seller__last_name': member['seller__last_name'],
            'total_sales': float(member['total_sales'] or 0),
            'transaction_count': member['transaction_count'] or 0,
            'avg_ticket': float(member['avg_ticket'] or 0),
        })
    
    # Payment method distribution (today)
    payment_methods_today = today_sales.values('payment_method').annotate(
        count=Count('sale_id'),
        total=Sum('total_amount')
    ).order_by('-total')
    
    # Top selling products (today)
    top_products_today = SaleItem.objects.filter(
        sale__in=today_sales
    ).values('product_name', 'product_code').annotate(
        total_qty=Sum('quantity'),
        total_value=Sum('total_price'),
        transaction_count=Count('sale__sale_id')
    ).order_by('-total_qty')[:10]
    
    # Top selling products (this week) - FIXED: Added this
    top_products_week = SaleItem.objects.filter(
        sale__in=week_sales
    ).values('product_name', 'product_code').annotate(
        total_qty=Sum('quantity'),
        total_value=Sum('total_price'),
        transaction_count=Count('sale__sale_id')
    ).order_by('-total_qty')[:10]
    
    # Recent sales
    recent_sales = Sale.objects.filter(
        is_reversed=False
    ).select_related('seller').order_by('-sale_date')[:10]
    
    # Credit sales today
    credit_sales_today = today_sales.filter(
        is_credit=True
    ).aggregate(
        count=Count('sale_id'),
        total=Sum('total_amount')
    )
    
    # Calculate average ticket
    avg_ticket_today = team_sales_today['total'] / team_sales_today['count'] if team_sales_today['count'] else 0
    
    # ============================================
    # HOURLY SALES DATA
    # ============================================
    hourly_labels = []
    hourly_data = []
    
    # Create hour labels from 0 to 23
    for hour in range(24):
        hour_start = timezone.make_aware(datetime.combine(today, datetime.min.time().replace(hour=hour)))
        hour_end = timezone.make_aware(datetime.combine(today, datetime.min.time().replace(hour=hour+1))) if hour < 23 else today_end
        
        hourly_labels.append(f"{hour:02d}:00")
        
        hour_sales = Sale.objects.filter(
            sale_date__range=[hour_start, hour_end],
            is_reversed=False
        ).aggregate(
            total=Sum('total_amount'),
            count=Count('sale_id')
        )
        
        hourly_data.append(float(hour_sales['total'] or 0))
    
    # Optional: hourly sales with details
    hourly_sales = []
    for i, hour in enumerate(range(24)):
        hourly_sales.append({
            'hour': hour,
            'amount': hourly_data[i],
            'count': Sale.objects.filter(
                sale_date__hour=hour,
                sale_date__date=today,
                is_reversed=False
            ).count(),
        })
    
    # Top performer
    top_performer = sales_by_member_today_list[0] if sales_by_member_today_list else None
    
    context = {
        'today': today,
        
        # Team stats
        'sales_team': sales_team,
        'team_sales_today': {
            'total': float(team_sales_today['total'] or 0),
            'count': team_sales_today['count'] or 0,
        },
        'team_sales_week': {
            'total': float(team_sales_week['total'] or 0),
            'count': team_sales_week['count'] or 0,
        },
        'team_sales_month': {
            'total': float(team_sales_month['total'] or 0),
            'count': team_sales_month['count'] or 0,
        },
        
        # Sales by member
        'sales_by_member_today': sales_by_member_today_list,
        'sales_by_member_week': sales_by_member_week_list,
        
        # Payment methods
        'payment_methods_today': payment_methods_today,
        
        # Top products
        'top_products_today': top_products_today,
        'top_products_week': top_products_week,
        
        # Recent sales
        'recent_sales': recent_sales,
        
        # Credit/Cash stats
        'credit_sales_today': {
            'count': credit_sales_today['count'] or 0,
            'total': float(credit_sales_today['total'] or 0),
        },
        'cash_sales_today': {
            'count': (team_sales_today['count'] or 0) - (credit_sales_today['count'] or 0),
            'total': float((team_sales_today['total'] or 0) - (credit_sales_today['total'] or 0)),
        },
        
        # Chart data
        'hourly_labels': hourly_labels,
        'hourly_data': hourly_data,
        'hourly_sales': hourly_sales,
        
        # Top performer
        'top_performer': top_performer,
        
        # Averages
        'avg_ticket_today': float(avg_ticket_today),
    }
    
    return render(request, 'staff/dashboards/sales_manager_dashboard.html', context)


# ============================================
# CASHIER DASHBOARD
# ============================================
@login_required
@dashboard_for_role('Cashier')
def cashier_dashboard(request):
    """Dashboard for cashier desk"""
    from sales.models import Sale, SaleItem
    from django.db.models import F, Count, Sum, Q
    from staff.models import Staff
    from shops.models import ShopBranch
    from inventory.models import Product, ProductUnit
    from decimal import Decimal

    prepare_dashboard_messages(request, 'Cashier')
    
    today = timezone.now().date()
    
    # Get cart from session
    cart = request.session.get('sales_cart', [])
    subtotal = sum(item.get('total', 0) for item in cart)
    
    # ============================================
    # GET USER'S ASSIGNED SHOP FROM STAFF MODEL
    # ============================================
    current_shop = None
    try:
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
            current_shop = ShopBranch.objects.filter(is_active=True).first()
            if current_shop:
                logger.info(f"Using fallback shop: {current_shop.name}")
        except Exception as e:
            logger.error(f"Error getting fallback shop: {str(e)}")
    
    # ============================================
    # TODAY'S TRANSACTIONS
    # ============================================
    today_transactions = Sale.objects.filter(
        sale_date__date=today,
        is_reversed=False  # Exclude reversed sales
    ).aggregate(
        count=Count('sale_id'),
        cash_total=Sum('total_amount', filter=Q(payment_method='Cash')),
        mpesa_total=Sum('total_amount', filter=Q(payment_method='M-Pesa')),
        card_total=Sum('total_amount', filter=Q(payment_method='Card')),
        points_total=Sum('total_amount', filter=Q(payment_method='Points'))
    )
    
    # Initialize None values to 0
    for key in today_transactions:
        if today_transactions[key] is None:
            today_transactions[key] = Decimal('0')
    
    # ============================================
    # RECENT TRANSACTIONS
    # ============================================
    recent_transactions = Sale.objects.filter(
        sale_date__date=today,
        is_reversed=False
    ).select_related('seller').order_by('-sale_date')[:20]
    
    # ============================================
    # TOP SELLING PRODUCTS TODAY (Optional - for cashier insights)
    # ============================================
    top_products_today = SaleItem.objects.filter(
        sale__sale_date__date=today,
        sale__is_reversed=False
    ).values(
        'product_name', 'product_code'
    ).annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('total_price')
    ).order_by('-total_quantity')[:5]
    
    # ============================================
    # CASHIER PERFORMANCE TODAY
    # ============================================
    cashier_sales = Sale.objects.filter(
        sale_date__date=today,
        seller=request.user,
        is_reversed=False
    )
    
    cashier_stats = {
        'sales_count': cashier_sales.count(),
        'total_amount': cashier_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0'),
        'items_sold': SaleItem.objects.filter(sale__in=cashier_sales).aggregate(total=Sum('quantity'))['total'] or 0
    }
    
    context = {
        # Cart data
        'cart': cart,
        'subtotal': subtotal,
        'cart_count': len(cart),
        
        # Shop info
        'current_shop': current_shop,
        
        # Transaction stats
        'today_transactions': today_transactions,
        'recent_transactions': recent_transactions,
        
        # Additional cashier insights
        'top_products_today': top_products_today,
        'cashier_stats': cashier_stats,
        
        # Today's date
        'today': today,
    }
    
    return render(request, 'staff/dashboards/cashier_dashboard.html', context)


# ============================================
# CREDIT MANAGER DASHBOARD
# ============================================
@login_required
@dashboard_for_role('Credit Manager')
def credit_manager_dashboard(request):
    """Dashboard for Credit Manager - oversees all credit operations"""

    prepare_dashboard_messages(request, 'Credit Manager')
    
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Import credit models
    try:
        from credit.models import CreditCompany, CreditCustomer, CreditTransaction, CompanyPayment
    except ImportError as e:
        logger.error(f"Failed to import credit models: {e}")
        return render(request, 'staff/dashboards/credit_manager_dashboard.html', {
            'error': "Credit app not installed or models not found"
        })
    
    # ============================================
    # OVERALL CREDIT STATISTICS
    # ============================================
    
    # Total transactions
    total_transactions = CreditTransaction.objects.count()
    
    # Total amount (ceiling_price sum)
    total_amount = CreditTransaction.objects.aggregate(
        total=Sum('ceiling_price')
    )['total'] or Decimal('0.00')
    
    # Active transactions (pending payment)
    active_credits = CreditTransaction.objects.filter(
        payment_status='pending'
    ).count()
    
    # Total outstanding (pending amounts)
    total_outstanding = CreditTransaction.objects.filter(
        payment_status='pending'
    ).aggregate(
        total=Sum('ceiling_price')
    )['total'] or Decimal('0.00')
    
    # This month stats
    this_month_count = CreditTransaction.objects.filter(
        transaction_date__date__gte=month_ago
    ).count()
    
    this_month_total = CreditTransaction.objects.filter(
        transaction_date__date__gte=month_ago
    ).aggregate(total=Sum('ceiling_price'))['total'] or Decimal('0.00')
    
    # ============================================
    # STATUS BREAKDOWN
    # ============================================
    
    pending_approval = CreditTransaction.objects.filter(payment_status='pending').count()
    paid_count = CreditTransaction.objects.filter(payment_status='paid').count()
    cancelled_count = CreditTransaction.objects.filter(payment_status='cancelled').count()
    reversed_count = CreditTransaction.objects.filter(payment_status='reversed').count()
    
    # Overdue is not a status in your model, so we'll calculate based on date
    # Assuming transactions older than 30 days without payment are "overdue"
    overdue_count = CreditTransaction.objects.filter(
        payment_status='pending',
        transaction_date__date__lte=today - timedelta(days=30)
    ).count()
    
    # ============================================
    # OVERDUE ANALYSIS
    # ============================================
    
    high_risk = CreditTransaction.objects.filter(
        payment_status='pending',
        transaction_date__date__lte=today - timedelta(days=60)
    ).count()
    
    medium_risk = CreditTransaction.objects.filter(
        payment_status='pending',
        transaction_date__date__lte=today - timedelta(days=30),
        transaction_date__date__gt=today - timedelta(days=60)
    ).count()
    
    low_risk = CreditTransaction.objects.filter(
        payment_status='pending',
        transaction_date__date__lte=today - timedelta(days=15),
        transaction_date__date__gt=today - timedelta(days=30)
    ).count()
    
    # ============================================
    # COLLECTIONS TODAY
    # ============================================
    
    # Payments recorded today (CompanyPayment)
    collected_today = CompanyPayment.objects.filter(
        payment_date=today
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    # ============================================
    # DUE PAYMENTS
    # ============================================
    
    # Since there's no due_date field, we'll consider transactions older than 30 days as "due"
    due_today = CreditTransaction.objects.filter(
        payment_status='pending',
        transaction_date__date__lte=today - timedelta(days=30)
    ).count()
    
    # ============================================
    # CREDIT COMPANIES PERFORMANCE
    # ============================================
    
    companies = []
    for company in CreditCompany.objects.filter(is_active=True)[:5]:
        # Company statistics
        company_total = CreditTransaction.objects.filter(
            credit_company=company
        ).aggregate(total=Sum('ceiling_price'))['total'] or 0
        
        company_pending = CreditTransaction.objects.filter(
            credit_company=company,
            payment_status='pending'
        ).count()
        
        company_paid = CreditTransaction.objects.filter(
            credit_company=company,
            payment_status='paid'
        ).count()
        
        company_overdue = CreditTransaction.objects.filter(
            credit_company=company,
            payment_status='pending',
            transaction_date__date__lte=today - timedelta(days=30)
        ).count()
        
        company_customers = CreditTransaction.objects.filter(
            credit_company=company
        ).values('customer').distinct().count()
        
        # Calculate utilization based on total vs limit (if you have limit field)
        utilization = 0
        if hasattr(company, 'credit_limit') and company.credit_limit and company.credit_limit > 0:
            utilization = min(int((company_total / company.credit_limit) * 100), 100)
        
        companies.append({
            'id': company.id,
            'name': company.name,
            'code': company.code if hasattr(company, 'code') else 'CRD',
            'total_credit': company_total,
            'active': company_pending,
            'overdue': company_overdue,
            'customers': company_customers,
            'paid': company_paid,
            'utilization': utilization
        })
    
    # ============================================
    # DUE PAYMENTS LIST
    # ============================================
    
    due_payments_list = []
    # Get pending transactions older than 30 days
    due_payments = CreditTransaction.objects.filter(
        payment_status='pending',
        transaction_date__date__lte=today - timedelta(days=30)
    ).select_related('customer', 'credit_company').order_by('transaction_date')[:10]
    
    for payment in due_payments:
        due_payments_list.append({
            'id': payment.id,
            'customer_name': payment.customer.full_name if payment.customer else "Unknown",
            'amount': payment.ceiling_price,
            'company': payment.credit_company.name if payment.credit_company else "N/A",
            'due_date': payment.transaction_date,  # Using transaction_date as reference
            'customer_phone': payment.customer.phone_number if payment.customer else "",
        })
    
    # ============================================
    # RECENT TRANSACTIONS
    # ============================================
    
    recent_transactions_list = []
    recent_transactions = CreditTransaction.objects.select_related(
        'customer', 'credit_company', 'dealer'
    ).order_by('-transaction_date')[:10]
    
    for tx in recent_transactions:
        recent_transactions_list.append({
            'id': tx.id,
            'reference': tx.transaction_id,
            'customer_name': tx.customer.full_name if tx.customer else "Unknown",
            'customer_phone': tx.customer.phone_number if tx.customer else "",
            'amount': tx.ceiling_price,
            'company_name': tx.credit_company.name if tx.credit_company else "N/A",
            'status': tx.payment_status,
            'date': tx.transaction_date,
        })
    
    # ============================================
    # OVERDUE ACCOUNTS LIST
    # ============================================
    
    overdue_accounts_list = []
    overdue_accounts = CreditTransaction.objects.filter(
        payment_status='pending',
        transaction_date__date__lte=today - timedelta(days=30)
    ).select_related('customer', 'credit_company').order_by('transaction_date')[:10]
    
    for acc in overdue_accounts:
        days_overdue = (today - acc.transaction_date.date()).days
        overdue_accounts_list.append({
            'id': acc.id,
            'customer_name': acc.customer.full_name if acc.customer else "Unknown",
            'phone': acc.customer.phone_number if acc.customer else "",
            'amount': acc.ceiling_price,
            'days_overdue': days_overdue,
            'company': acc.credit_company.name if acc.credit_company else "N/A",
        })
    
    # ============================================
    # CHART DATA
    # ============================================
    
    chart_labels = []
    credit_data = []
    
    for i in range(30):
        date = month_ago + timedelta(days=i)
        day_total = CreditTransaction.objects.filter(
            transaction_date__date=date
        ).aggregate(total=Sum('ceiling_price'))['total'] or 0
        chart_labels.append(f"'{date.strftime('%d %b')}'")
        credit_data.append(float(day_total))
    
    context = {
        # Date info
        'today': today,
        
        # Overall stats
        'total_transactions': total_transactions,
        'total_outstanding': total_outstanding,
        'active_credits': active_credits,
        'total_amount': total_amount,
        
        # Monthly stats
        'this_month_total': this_month_total,
        'this_month_count': this_month_count,
        
        # Status breakdown
        'pending_approval': pending_approval,  # pending payments
        'approved_count': 0,  # Not applicable
        'active_count': active_credits,
        'overdue_count': overdue_count,
        'defaulted_count': 0,  # Not applicable
        'paid_count': paid_count,
        'rejected_count': cancelled_count + reversed_count,
        
        # Overdue breakdown
        'high_risk': high_risk,
        'medium_risk': medium_risk,
        'low_risk': low_risk,
        
        # Collections
        'collected_today': collected_today,
        
        # Due payments
        'due_today': due_today,
        
        # Companies
        'companies': companies,
        
        # Lists
        'due_payments': due_payments_list,
        'recent_transactions': recent_transactions_list,
        'overdue_accounts': overdue_accounts_list,
        
        # Chart data
        'chart_labels': chart_labels,
        'credit_data': credit_data,
    }
    
    return render(request, 'staff/dashboards/credit_manager_dashboard.html', context)



# ============================================
# CREDIT OFFICER DASHBOARD - SEARCH BY IMEI/SERIAL
# ============================================
@login_required
@dashboard_for_role('Credit Officer')
def credit_officer_dashboard(request):
    """Dashboard for credit officer - search available units by IMEI/Serial"""
    from credit.models import CreditTransaction, CreditCustomer, CreditCompany
    from inventory.models import Product, ProductUnit, Category
    from django.db.models import Sum, Count, Q
    from django.utils import timezone
    from datetime import timedelta
    import json
    from decimal import Decimal
    from django.core.serializers.json import DjangoJSONEncoder
    import logging

    prepare_dashboard_messages(request, 'Credit Officer')
    
    logger = logging.getLogger(__name__)
    
    today = timezone.now().date()
    thirty_days_ago = today - timedelta(days=30)
    
    # ============================================
    # Get current user
    # ============================================
    current_user = request.user
    
    # ============================================
    # Get search query for prospects
    # ============================================
    search_query = request.GET.get('search', '').strip()
    
    # ============================================
    # Get IDs of units that already have credit transactions
    # ============================================
    units_with_credit = CreditTransaction.objects.filter(
        product__isnull=False
    ).values_list('product_id', flat=True).distinct()
    
    # ============================================
    # AVAILABLE UNITS FOR CREDIT
    # ============================================
    available_units = ProductUnit.objects.filter(
        product__is_active=True,
        product__is_discontinued=False,
        product__category__item_type='single',
        status='available'
    ).exclude(
        id__in=units_with_credit
    ).select_related('product', 'product__category', 'supplier')[:100]
    
    # ============================================
    # CONVERT UNITS TO JSON FOR JAVASCRIPT
    # ============================================
    units_json = json.dumps([
        {
            'id': unit.id,
            'product_id': unit.product.id,
            'sku_code': unit.product.sku_code,
            'product_name': unit.product.display_name,
            'imei_number': unit.imei_number,
            'serial_number': unit.serial_number,
            'identifier': unit.unique_identifier,
            'selling_price': float(unit.effective_selling_price),
            'brand': unit.product.brand,
            'model': unit.product.model,
            'specifications': unit.product.specifications,
            'status': unit.status,
        } for unit in available_units
    ], cls=DjangoJSONEncoder)
    
    # ============================================
    # STATS CARDS
    # ============================================
    total_available_units = available_units.count()
    
    # Daily credit sales by this user
    daily_sales = CreditTransaction.objects.filter(
        dealer=current_user,
        transaction_date__date=today
    ).count()
    
    # Monthly credit sales by this user
    monthly_sales = CreditTransaction.objects.filter(
        dealer=current_user,
        transaction_date__date__gte=thirty_days_ago
    ).count()
    
    # ============================================
    # GET IDs of customers WITH active credit (to exclude)
    # ============================================
    customers_with_active_credit_ids = CreditTransaction.objects.filter(
        payment_status__in=['pending', 'partially_paid']
    ).values_list('customer_id', flat=True).distinct()
    
    # ============================================
    # CUSTOMERS FOR DROPDOWN - EXCLUDE THOSE WITH ACTIVE CREDIT
    # ============================================
    customers = CreditCustomer.objects.filter(
        Q(transactions__dealer=current_user) | Q(created_by=current_user),
        is_active=True
    ).exclude(
        id__in=customers_with_active_credit_ids
    ).distinct().order_by('-created_at')[:100]
    
    # ============================================
    # PROSPECTS FOR "MY PROSPECTS" TAB
    # All eligible customers (without active credit)
    # Superusers see all, regular users see only their own
    # ============================================
    if current_user.is_superuser:
        # Superusers see ALL eligible customers
        prospects = CreditCustomer.objects.filter(
            is_active=True
        ).exclude(
            id__in=customers_with_active_credit_ids
        ).order_by('-created_at')
    else:
        # Regular users see only customers they created or worked with
        prospects = CreditCustomer.objects.filter(
            Q(created_by=current_user) | Q(transactions__dealer=current_user),
            is_active=True
        ).exclude(
            id__in=customers_with_active_credit_ids
        ).distinct().order_by('-created_at')
    
    # Apply search filter if provided
    if search_query:
        prospects = prospects.filter(
            Q(full_name__icontains=search_query) |
            Q(phone_number__icontains=search_query) |
            Q(id_number__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    
    # Count prospects
    prospects_count = prospects.count()
    
    # ============================================
    # CREDIT OVERVIEW STATS
    # ============================================
    total_credit = CreditTransaction.objects.filter(
        dealer=current_user
    ).aggregate(
        total=Sum('ceiling_price')
    )['total'] or Decimal('0')
    
    total_paid = CreditTransaction.objects.filter(
        dealer=current_user,
        payment_status='paid'
    ).aggregate(total=Sum('ceiling_price'))['total'] or Decimal('0')
    
    total_pending = CreditTransaction.objects.filter(
        dealer=current_user,
        payment_status='pending'
    ).aggregate(total=Sum('ceiling_price'))['total'] or Decimal('0')
    
    # ============================================
    # COMPANIES FOR DROPDOWN
    # ============================================
    companies = CreditCompany.objects.filter(is_active=True)
    
    # ============================================
    # RECENT CREDIT TRANSACTIONS
    # ============================================
    recent_credits = CreditTransaction.objects.filter(
        dealer=current_user
    ).select_related(
        'customer', 'credit_company', 'product', 'product__product'
    ).order_by('-transaction_date')[:15]
    
    # ============================================
    # Count customers with active credit (for info message)
    # ============================================
    customers_with_active_count = customers_with_active_credit_ids.count()
    
    context = {
        # Stats
        'total_available_units': total_available_units,
        'daily_sales': daily_sales,
        'monthly_sales': monthly_sales,
        'total_customers': customers.count(),  # For dropdown eligible customers
        
        # Prospects for the "My Prospects" tab
        'prospects': prospects,
        'prospects_count': prospects_count,
        'search_query': search_query,
        
        # Credit Overview
        'total_credit': float(total_credit),
        'total_paid': float(total_paid),
        'total_pending': float(total_pending),
        
        # Data
        'units_json': units_json,
        'companies': companies,
        'customers': customers,
        'recent_credits': recent_credits,
        'customers_with_active_count': customers_with_active_count,
        'is_administrator': current_user.is_superuser or current_user.is_staff,
    }
    
    return render(request, 'staff/dashboards/credit_officer_dashboard.html', context)



# ============================================
# CUSTOMER SERVICE DASHBOARD
# ============================================
@login_required
@dashboard_for_role('Customer Service')
def customer_service_dashboard(request):
    """Dashboard for customer service"""
    from credit.models import CreditCustomer, CreditTransaction
    from django.db.models import Count, Q

    prepare_dashboard_messages(request, 'Customer Service')
    
    today = timezone.now().date()
    
    # New customers today
    new_customers_today = CreditCustomer.objects.filter(
        created_at__date=today
    ).count()
    
    # Total customers
    total_customers = CreditCustomer.objects.count()
    
    # Customers with active credit - FIXED: using 'transactions'
    credit_customers = CreditCustomer.objects.filter(
        transactions__isnull=False
    ).distinct().count()
    
    # Customers with pending credit - FIXED: using 'transactions'
    pending_credit_customers = CreditCustomer.objects.filter(
        transactions__payment_status='pending'
    ).distinct().count()
    
    # Recent customers
    recent_customers = CreditCustomer.objects.order_by('-created_at')[:10]
    
    context = {
        'new_customers_today': new_customers_today,
        'total_customers': total_customers,
        'credit_customers': credit_customers,
        'pending_credit_customers': pending_credit_customers,
        'recent_customers': recent_customers,
    }
    return render(request, 'staff/dashboards/customer_service_dashboard.html', context)


# ============================================
# FINANCE MANAGER DASHBOARD - Management & Approvals Focus
# ============================================
@login_required
@dashboard_for_role('Finance Manager')
def finance_manager_dashboard(request):
    """Finance Manager Dashboard - Focus on approvals, team management, and tasks"""
    from finance.models import Salary, FinancialTransaction
    from credit.models import SellerCommission
    from staff.models import StaffApplication, Staff, UserProfile
    from django.contrib.auth.models import User
    from decimal import Decimal
    from django.db.models import Sum, Q, Count
    from django.utils import timezone
    from datetime import datetime, timedelta
    
    today = timezone.now().date()
    current_month = today.month
    current_year = today.year
    
    # Get month start and end
    month_start = timezone.make_aware(datetime(current_year, current_month, 1))
    if current_month == 12:
        month_end = timezone.make_aware(datetime(current_year + 1, 1, 1)) - timedelta(seconds=1)
    else:
        month_end = timezone.make_aware(datetime(current_year, current_month + 1, 1)) - timedelta(seconds=1)
    
    # ============================================
    # PENDING APPROVALS COUNTS
    # ============================================
    
    # Pending Salary Approvals
    pending_salary_approvals = Salary.objects.filter(
        status='pending'
    ).count()
    
    # Pending Commission Approvals
    pending_commission_approvals = SellerCommission.objects.filter(
        status='pending'
    ).count()
    
    # Pending Staff Applications (using application_date instead of created_at)
    pending_applications = StaffApplication.objects.filter(
        status='pending'
    ).count()
    
    # Pending Identity Verifications (staff not verified)
    # Check if Staff model has verification field
    pending_verifications = Staff.objects.filter(
        is_verified=False
    ).count() if hasattr(Staff, 'is_verified') else 0
    
    # Pending Commission Requests
    pending_commission_requests = SellerCommission.objects.filter(
        status='pending'
    ).count()
    
    # ============================================
    # PENDING SALARIES TABLE DATA
    # ============================================
    pending_salaries = Salary.objects.filter(
        status='pending'
    ).select_related('staff').order_by('-created_at')[:10]
    
    # ============================================
    # PENDING COMMISSIONS TABLE DATA
    # ============================================
    pending_commissions = SellerCommission.objects.filter(
        status='pending'
    ).select_related('seller', 'transaction').order_by('-created_at')[:10]
    
    # ============================================
    # RECENT STAFF APPLICATIONS
    # ============================================
    # Use application_date instead of created_at
    recent_applications = StaffApplication.objects.filter(
        status='pending'
    ).order_by('-application_date')[:5]
    
    # ============================================
    # UNVERIFIED STAFF MEMBERS
    # ============================================
    # Get staff members who are not verified
    if hasattr(Staff, 'is_verified'):
        unverified_staff = Staff.objects.filter(
            is_verified=False
        ).select_related('user').order_by('-id')[:5]
    else:
        # Fallback: get recent staff members
        unverified_staff = Staff.objects.select_related('user').order_by('-id')[:5]
    
    # ============================================
    # TEAM PERFORMANCE DATA
    # ============================================
    
    # Team members by department/role
    departments = ['Sales', 'Finance', 'Credit', 'Customer Service', 'Management']
    team_members_data = []
    team_tasks_data = []
    
    # Count staff by position/department
    for dept in departments:
        # Count active staff members in this department
        # Adjust based on your Staff model fields (position, department, role)
        if hasattr(Staff, 'position'):
            member_count = Staff.objects.filter(
                position__icontains=dept
            ).count()
        else:
            # Fallback: count all staff and distribute
            total_staff = Staff.objects.count()
            member_count = total_staff // len(departments) if total_staff > 0 else 0
        team_members_data.append(member_count)
        
        # Count pending tasks for this department
        if dept == 'Sales':
            tasks = SellerCommission.objects.filter(status='pending').count()
        elif dept == 'Finance':
            tasks = Salary.objects.filter(status='pending').count()
        elif dept == 'Credit':
            tasks = SellerCommission.objects.filter(status='pending').count()
        else:
            tasks = 0
        team_tasks_data.append(tasks)
    
    # ============================================
    # NOTIFICATION COUNT
    # ============================================
    notification_count = (
        pending_salary_approvals + 
        pending_commission_approvals + 
        pending_applications + 
        pending_verifications
    )
    
    # ============================================
    # FINANCIAL SUMMARY (Quick Overview Cards)
    # ============================================
    
    # Salary totals for current month
    current_month_salaries_total = Salary.objects.filter(
        month=current_month,
        year=current_year
    ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    # Commission totals for current month
    current_month_commissions_total = SellerCommission.objects.filter(
        status='approved',
        created_at__range=[month_start, month_end]
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    # Total financial outflow (salaries + commissions)
    total_financial_outflow = current_month_salaries_total + current_month_commissions_total
    
    # ============================================
    # RECENT FINANCIAL TRANSACTIONS
    # ============================================
    recent_transactions = FinancialTransaction.objects.select_related(
        'created_by'
    ).order_by('-transaction_date')[:5]
    
    # ============================================
    # CONTEXT FOR TEMPLATE
    # ============================================
    
    context = {
        # Pending approvals (cards)
        'pending_salary_approvals': pending_salary_approvals,
        'pending_commission_approvals': pending_commission_approvals,
        'pending_applications': pending_applications,
        'pending_verifications': pending_verifications,
        'pending_commission_requests': pending_commission_requests,
        
        # Table data
        'pending_salaries': pending_salaries,
        'pending_commissions': pending_commissions,
        'recent_applications': recent_applications,
        'unverified_staff': unverified_staff,
        
        # Team performance chart data
        'team_labels': departments,
        'team_members_data': team_members_data,
        'team_tasks_data': team_tasks_data,
        
        # Notifications
        'notification_count': notification_count,
        
        # Financial summary (optional quick stats)
        'current_month_salaries_total': current_month_salaries_total,
        'current_month_commissions_total': current_month_commissions_total,
        'total_financial_outflow': total_financial_outflow,
        
        # Recent transactions
        'recent_transactions': recent_transactions,
        
        # Date info
        'current_month_name': datetime(current_year, current_month, 1).strftime('%B'),
        'current_year': current_year,
        'today': today,
    }
    
    return render(request, 'staff/dashboards/finance_manager_dashboard.html', context)


# ============================================
# SECURITY OFFICER DASHBOARD
# ============================================
@login_required
@dashboard_for_role('Security Officer')
def security_dashboard(request):
    """Dashboard for security officer"""
    from inventory.models import Product
    from sales.models import Sale

    prepare_dashboard_messages(request, 'Security')
    
    today = timezone.now().date()
    
    # High-value items
    high_value_items = Product.objects.filter(
        selling_price__gte=50000
    ).count()
    
    # Items with IMEI tracking
    tracked_items = Product.objects.exclude(
        sku_value__isnull=True
    ).exclude(sku_value='').count()
    
    # Today's high-value sales
    high_value_sales = Sale.objects.filter(
        sale_date__date=today,
        total_amount__gte=50000
    ).count()
    
    # Recent high-value transactions
    recent_high_value = Sale.objects.filter(
        total_amount__gte=50000
    ).order_by('-sale_date')[:10]
    
    context = {
        'high_value_items': high_value_items,
        'tracked_items': tracked_items,
        'high_value_sales': high_value_sales,
        'recent_high_value': recent_high_value,
    }
    return render(request, 'staff/dashboards/security_dashboard.html', context)


# ============================================
# MPESA DASHBOARD
# ============================================
@login_required
@dashboard_for_role('M-Pesa Agent')
def mpesa_agent_dashboard(request):
    """Dashboard for M-Pesa Agent - role-based view"""
    from shops.models import DailyShopReport, ShopBranch, MpesaAccount, BankClosingBalance
    from django.db.models import Sum, Q
    from django.utils import timezone
    from datetime import timedelta
    
    prepare_dashboard_messages(request, 'M-Pesa Agent')
    
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Get the agent's shop branch from staff profile
    assigned_shop = None
    if hasattr(request.user, 'staff_profile') and request.user.staff_profile:
        assigned_shop = request.user.staff_profile.assigned_shop
    
    # Initialize variables
    weekly_transactions = 0
    monthly_transactions = 0
    monthly_expenses = 0
    total_reports = 0
    total_shops = 0
    reports_today = 0
    total_transactions_today = 0
    total_mpesa_balance = 0
    unverified_reports_count = 0
    unverified_reports = []
    
    # For SUPERUSERS - show GLOBAL stats AND their own shop's unverified reports
    if request.user.is_superuser:
        # GLOBAL STATS (all shops)
        all_reports = DailyShopReport.objects.all()
        
        # Weekly transactions (all shops)
        weekly_transactions = all_reports.filter(
            report_date__gte=week_ago,
            report_date__lte=today
        ).aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
        
        # Monthly transactions (all shops)
        monthly_transactions = all_reports.filter(
            report_date__gte=month_ago,
            report_date__lte=today
        ).aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
        
        # Monthly expenses (all shops)
        monthly_expenses = all_reports.filter(
            report_date__gte=month_ago,
            report_date__lte=today
        ).aggregate(total=Sum('total_expenses'))['total'] or 0
        
        # Total reports (all shops)
        total_reports = all_reports.count()
        
        # Superuser stats
        total_shops = ShopBranch.objects.filter(is_active=True).count()
        reports_today = DailyShopReport.objects.filter(report_date=today).count()
        total_transactions_today = DailyShopReport.objects.filter(
            report_date=today
        ).aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
        
        # Total M-Pesa balance across all accounts
        total_mpesa_balance = MpesaAccount.objects.filter(
            is_active=True, 
            status='active'
        ).aggregate(total=Sum('current_balance'))['total'] or 0
        
        # Get unverified reports for superuser's ASSIGNED SHOP ONLY (if they have one)
        if assigned_shop:
            # Get all reports for this shop
            shop_reports = DailyShopReport.objects.filter(shop=assigned_shop).order_by('-report_date')
            
            # Calculate verification status for each report (same logic as reports_list)
            for report in shop_reports:
                # Get previous report for this shop
                previous_report = DailyShopReport.objects.filter(
                    shop=assigned_shop,
                    report_date__lt=report.report_date
                ).order_by('-report_date').first()
                
                if previous_report:
                    # Expected closing = Previous closing - Today's expenses
                    expected_closing = previous_report.total_closing_balance - report.total_expenses
                    difference = report.total_closing_balance - expected_closing
                    
                    # Check if unverified (surplus or deficit)
                    if abs(difference) >= 0.01:  # Not verified if difference > 0.01
                        unverified_reports.append(report)
                # First report is considered verified
            
            unverified_reports_count = len(unverified_reports)
            
    else:
        # REGULAR USER - show only their assigned shop data
        if assigned_shop:
            reports = DailyShopReport.objects.filter(shop=assigned_shop)
            
            # Weekly transactions
            weekly_transactions = reports.filter(
                report_date__gte=week_ago,
                report_date__lte=today
            ).aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
            
            # Monthly transactions
            monthly_transactions = reports.filter(
                report_date__gte=month_ago,
                report_date__lte=today
            ).aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
            
            # Monthly expenses
            monthly_expenses = reports.filter(
                report_date__gte=month_ago,
                report_date__lte=today
            ).aggregate(total=Sum('total_expenses'))['total'] or 0
            
            # Total reports
            total_reports = reports.count()
            
            # Today's reports
            reports_today = reports.filter(report_date=today).count()
            total_transactions_today = reports.filter(
                report_date=today
            ).aggregate(total=Sum('total_mpesa_amount'))['total'] or 0
            
            # Total M-Pesa balance for assigned shop
            total_mpesa_balance = MpesaAccount.objects.filter(
                shop=assigned_shop,
                is_active=True, 
                status='active'
            ).aggregate(total=Sum('current_balance'))['total'] or 0
            
            # Calculate unverified reports for regular user's shop
            shop_reports = reports.order_by('-report_date')
            for report in shop_reports:
                # Get previous report for this shop
                previous_report = DailyShopReport.objects.filter(
                    shop=assigned_shop,
                    report_date__lt=report.report_date
                ).order_by('-report_date').first()
                
                if previous_report:
                    expected_closing = previous_report.total_closing_balance - report.total_expenses
                    difference = report.total_closing_balance - expected_closing
                    
                    if abs(difference) >= 0.01:  # Unverified
                        unverified_reports.append(report)
            
            unverified_reports_count = len(unverified_reports)
            total_shops = 1  # Regular users only have access to their shop
    
    context = {
        # Common data
        'assigned_shop': assigned_shop,
        'today': today,
        'weekly_transactions': int(weekly_transactions),
        'monthly_transactions': int(monthly_transactions),
        'monthly_expenses': float(monthly_expenses),
        'total_reports': total_reports,
        'total_mpesa_balance': total_mpesa_balance,
        
        # Shop stats
        'total_shops': total_shops,
        'reports_today': reports_today,
        'total_transactions_today': int(total_transactions_today),
        
        # Unverified reports for THIS USER'S shop only
        'unverified_reports': unverified_reports[:5],  # Limit to 5 most recent
        'unverified_reports_count': unverified_reports_count,
    }
    
    return render(request, 'staff/dashboards/mpesa_agent_dashboard.html', context)


# ============================================
# CLEANER DASHBOARD
# ============================================
@login_required
@dashboard_for_role('Cleaner')
def cleaner_dashboard(request):
    """Dashboard for office cleaner"""
    # Simple dashboard with cleaning schedule, tasks, etc.

    prepare_dashboard_messages(request, 'Cleaner')
    
    today = timezone.now().date()
    
    # Cleaning tasks (you can create a CleaningTask model later)
    tasks = [
        {'area': 'Main Office', 'time': '08:00 AM', 'status': 'pending'},
        {'area': 'Sales Floor', 'time': '10:00 AM', 'status': 'pending'},
        {'area': 'Store Room', 'time': '12:00 PM', 'status': 'pending'},
        {'area': 'Kitchen', 'time': '02:00 PM', 'status': 'pending'},
        {'area': 'Restrooms', 'time': '04:00 PM', 'status': 'pending'},
    ]
    
    # Supplies status (you can create a Supplies model later)
    supplies = [
        {'item': 'Cleaning Liquid', 'quantity': '5 liters', 'status': 'good'},
        {'item': 'Disinfectant', 'quantity': '3 liters', 'status': 'low'},
        {'item': 'Gloves', 'quantity': '10 pairs', 'status': 'good'},
        {'item': 'Trash Bags', 'quantity': '50 pieces', 'status': 'good'},
    ]
    
    context = {
        'date': today,
        'tasks': tasks,
        'supplies': supplies,
    }
    return render(request, 'staff/dashboards/cleaner_dashboard.html', context)
















# ====================================
# PUBLIC APPLICATION FORM
# ====================================
def application_form(request):
    """Public form for staff applications with enhanced fields"""
    if request.method == 'POST':
        try:
            # Check if this is an AJAX request
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            
            # ============================================
            # SECTION 1: PERSONAL INFORMATION
            # ============================================
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()  # NEW: Email field
            id_number = request.POST.get('id_number', '').strip()
            phone = request.POST.get('phone', '').strip()
            password = request.POST.get('password', '')
            confirm_password = request.POST.get('confirm_password', '')
            
            # ============================================
            # SECTION 2: EMPLOYMENT DETAILS
            # ============================================
            resident = request.POST.get('resident', '').strip()
            former_employer = request.POST.get('former_employer', '').strip()
            preferred_salary = request.POST.get('preferred_salary', '').strip()
            
            # ============================================
            # SECTION 3: DOCUMENTS
            # ============================================
            passport_photo = request.FILES.get('passport_photo')
            id_front = request.FILES.get('id_front')
            id_back = request.FILES.get('id_back')
            other_documents = request.FILES.get('other_documents')
            
            # ============================================
            # SECTION 4: TERMS AND SIGNATURE
            # ============================================
            terms_read = request.POST.get('terms_read') == 'on'
            terms_accepted = request.POST.get('terms_accepted') == 'on'
            signature = request.POST.get('signature', '').strip()
            
            # Validate required fields
            errors = []
            
            # Section 1 validation
            if not all([first_name, last_name, email, id_number, phone]):  # Added email
                errors.append('Please fill in all personal information fields (First Name, Last Name, Email, ID Number, Phone).')
            
            # Email validation
            if email:
                import re
                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                if not re.match(email_pattern, email):
                    errors.append('Please enter a valid email address.')
            
            if not password or not confirm_password:
                errors.append('Please enter and confirm your password.')
            elif password != confirm_password:
                errors.append('Passwords do not match.')
            elif len(password) < 8:
                errors.append('Password must be at least 8 characters long.')
            
            # Section 2 validation
            if not all([resident, former_employer, preferred_salary]):
                errors.append('Please fill in all employment details.')
            
            # Section 3 validation
            if not all([passport_photo, id_front, id_back]):
                errors.append('Please upload all required documents.')
            
            # Section 4 validation
            if not terms_read:
                errors.append('You must confirm that you have read the terms and policy.')
            if not terms_accepted:
                errors.append('You must accept the terms and policy of this company.')
            if not signature:
                errors.append('Please provide your signature.')
            
            if errors:
                error_msg = '\n'.join(errors)
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_msg})
                for error in errors:
                    messages.error(request, error)
                return render(request, 'staff/apply.html', {
                    'form_data': request.POST
                })
            
            # ============================================
            # CHECK FOR EXISTING RECORDS
            # ============================================
            import re
            
            # Check if email already exists in User table
            if User.objects.filter(email=email).exists():
                error_msg = f'Email {email} is already registered in the system. Please use a different email.'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_msg})
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {'form_data': request.POST})
            
            # Check if phone already exists as username
            if User.objects.filter(username=phone).exists():
                error_msg = f'Phone number {phone} is already registered in the system.'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_msg})
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {'form_data': request.POST})
            
            # Check if email exists in pending applications
            pending_email = StaffApplication.objects.filter(
                email=email, 
                status__in=['pending', 'under_review']
            ).first()
            
            if pending_email:
                error_msg = f'Email {email} already has a pending application.'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_msg})
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {'form_data': request.POST})
            
            # Check if email exists in approved applications
            approved_email = StaffApplication.objects.filter(
                email=email, 
                status='approved'
            ).first()
            
            if approved_email:
                error_msg = f'Email {email} has already been approved. Please login to your account.'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_msg})
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {'form_data': request.POST})
            
            # Check ID number in applications
            existing_app = StaffApplication.objects.filter(id_number=id_number).first()
            if existing_app:
                status_msg = {
                    'pending': 'pending review',
                    'under_review': 'under review',
                    'approved': 'already approved',
                    'rejected': 'previously rejected'
                }.get(existing_app.status, 'exists')
                
                error_msg = f'An application with ID number {id_number} already exists (Status: {status_msg}).'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_msg})
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {'form_data': request.POST})
            
            # Check phone in pending applications
            pending_phone = StaffApplication.objects.filter(
                phone=phone, 
                status__in=['pending', 'under_review']
            ).first()
            
            if pending_phone:
                error_msg = f'Phone number {phone} already has a pending application.'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_msg})
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {'form_data': request.POST})
            
            # ============================================
            # CREATE APPLICATION WITH NEW FIELDS
            # ============================================
            
            # Store password temporarily in session
            request.session[f'pending_password_{id_number}'] = password
            
            # Create the application with all new fields
            application = StaffApplication.objects.create(
                first_name=first_name,
                last_name=last_name,
                email=email,  # Now using actual email
                phone=phone,
                id_number=id_number,
                position='pending',  # Default position until assigned
                address=resident,  # Using resident as address
                experience=f"Former Employer: {former_employer}\nPreferred Salary: {preferred_salary}",
                passport_photo=passport_photo,
                id_front=id_front,
                id_back=id_back,
                terms_accepted=terms_accepted,
                privacy_accepted=terms_read,
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                status='pending'
            )
            
            # Store additional data
            from .models import ApplicationExtraData
            
            extra_data = ApplicationExtraData.objects.create(
                application=application,
                resident=resident,
                former_employer=former_employer,
                preferred_salary=preferred_salary,
                signature=signature,
                other_documents=other_documents
            )
            
            logger.info(f"New staff application created: {application.full_name()} (ID: {application.id})")
            
            # Send confirmation email to applicant
            try:
                subject = "Application Received - FieldMax"
                html_message = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background: #007bff; color: white; padding: 20px; text-align: center; }}
                        .content {{ padding: 20px; }}
                        .footer {{ text-align: center; padding: 20px; color: #666; }}
                        .details {{ background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>Application Received</h2>
                        </div>
                        <div class="content">
                            <p>Dear <strong>{first_name} {last_name}</strong>,</p>
                            <p>Thank you for applying to join FieldMax. Your application has been received and is pending review.</p>
                            <div class="details">
                                <h3>Application Details:</h3>
                                <ul>
                                    <li><strong>Application ID:</strong> {application.id}</li>
                                    <li><strong>Name:</strong> {first_name} {last_name}</li>
                                    <li><strong>Email:</strong> {email}</li>
                                    <li><strong>ID Number:</strong> {id_number}</li>
                                    <li><strong>Phone:</strong> {phone}</li>
                                    <li><strong>Resident:</strong> {resident}</li>
                                    <li><strong>Former Employer:</strong> {former_employer}</li>
                                    <li><strong>Preferred Salary:</strong> KSH {preferred_salary}</li>
                                </ul>
                            </div>
                            <p>You will receive an email notification once your application has been reviewed.</p>
                            <p>Thank you for your interest in FieldMax!</p>
                        </div>
                        <div class="footer">
                            <p>&copy; {timezone.now().year} FieldMax. All rights reserved.</p>
                        </div>
                    </div>
                </body>
                </html>
                """
                queue_email(subject, f"Application received", [email], html_message)
                logger.info(f"Confirmation email sent to {email}")
            except Exception as e:
                logger.error(f"Failed to send confirmation email: {str(e)}")
            
            # Send notification to admins
            try:
                admin_emails = User.objects.filter(is_superuser=True).values_list('email', flat=True)
                if admin_emails:
                    admin_subject = f"New Staff Application - {first_name} {last_name}"
                    admin_html = f"""
                    <h2>New Staff Application Received</h2>
                    <p><strong>Name:</strong> {first_name} {last_name}</p>
                    <p><strong>Email:</strong> {email}</p>
                    <p><strong>ID Number:</strong> {id_number}</p>
                    <p><strong>Phone:</strong> {phone}</p>
                    <p><strong>Resident:</strong> {resident}</p>
                    <p><strong>Former Employer:</strong> {former_employer}</p>
                    <p><strong>Preferred Salary:</strong> KSH {preferred_salary}</p>
                    <p><strong>Application ID:</strong> {application.id}</p>
                    <p><a href="{request.build_absolute_uri('/admin/staff/staffapplication/')}">Review Application</a></p>
                    """
                    queue_email(admin_subject, f"New application from {first_name} {last_name}", list(admin_emails), admin_html)
                    logger.info(f"Admin notification sent to {len(admin_emails)} admins")
            except Exception as e:
                logger.error(f"Failed to send admin notification: {str(e)}")
            
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'message': 'Your application has been submitted successfully!',
                    'application_id': application.id
                })
            
            messages.success(request, 'Your application has been submitted successfully! You will receive a notification once reviewed.')
            return redirect('staff:application_success')
            
        except Exception as e:
            logger.error(f"Error creating staff application: {str(e)}", exc_info=True)
            error_msg = f'Error submitting application: {str(e)}'
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            
            messages.error(request, error_msg)
            return render(request, 'staff/apply.html', {'form_data': request.POST})
    
    # GET request - show form
    context = {
        'form_data': request.GET,
    }
    return render(request, 'staff/apply.html', context)

def application_success(request):
    """Application success page"""
    return render(request, 'staff/success.html')

@login_required
def application_list(request):
    """List all staff applications with new fields"""
    applications = StaffApplication.objects.all().order_by('-application_date')
    
    # Filters
    status = request.GET.get('status')
    if status:
        applications = applications.filter(status=status)
    
    position = request.GET.get('position')
    if position:
        applications = applications.filter(position=position)
    
    search = request.GET.get('search')
    if search:
        applications = applications.filter(
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search) |
            Q(email__icontains=search) |
            Q(id_number__icontains=search) |
            Q(phone__icontains=search)
        )
    
    # Pagination
    paginator = Paginator(applications, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get extra data for each application
    for app in page_obj:
        try:
            app.extra = app.extra_data
        except:
            app.extra = None
    
    context = {
        'applications': page_obj,
        'status_choices': StaffApplication.STATUS_CHOICES,
        'position_choices': StaffApplication.POSITION_CHOICES,
        'total_count': applications.count(),
        'pending_count': applications.filter(status='pending').count(),
        'approved_count': applications.filter(status='approved').count(),
        'rejected_count': applications.filter(status='rejected').count(),
        'under_review_count': applications.filter(status='under_review').count(),
    }
    return render(request, 'staff/list.html', context)

@login_required
def application_detail(request, pk):
    """View application details with all new fields"""
    application = get_object_or_404(StaffApplication, pk=pk)
    
    # Get extra data
    try:
        extra_data = application.extra_data
    except:
        extra_data = None
    
    # Calculate staff ID based on application status
    next_staff_id = None
    actual_staff_id = None
    
    from staff.models import Staff
    import re
    
    # If application is approved and has a user, get the actual staff ID
    if application.status == 'approved' and application.created_user:
        try:
            staff_profile = Staff.objects.get(user=application.created_user)
            actual_staff_id = staff_profile.staff_id
        except Staff.DoesNotExist:
            actual_staff_id = None
    else:
        # Only calculate next ID for pending applications
        last_staff = Staff.objects.order_by('-id').first()
        if last_staff and last_staff.staff_id:
            numbers = re.findall(r'\d+', last_staff.staff_id)
            if numbers:
                last_num = int(numbers[0])
                next_num = last_num + 1
                next_staff_id = f"FM{next_num:03d}"
            else:
                next_staff_id = "FM001"
        else:
            next_staff_id = "FM001"
    
    context = {
        'application': application,
        'extra_data': extra_data,
        'next_staff_id': next_staff_id,
        'actual_staff_id': actual_staff_id,
    }
    return render(request, 'staff/detail.html', context)



@login_required
def application_edit(request, pk):
    """Edit application details"""
    application = get_object_or_404(StaffApplication, pk=pk)
    
    if request.method == 'POST':
        try:
            # Update fields
            application.first_name = request.POST.get('first_name')
            application.last_name = request.POST.get('last_name')
            application.email = request.POST.get('email')
            application.phone = request.POST.get('phone')
            application.id_number = request.POST.get('id_number')
            application.address = request.POST.get('address', '')
            application.position = request.POST.get('position')
            application.experience = request.POST.get('experience', '')
            application.status = request.POST.get('status')
            application.review_notes = request.POST.get('review_notes', '')
            
            # Handle file uploads (only if new files are provided)
            if request.FILES.get('passport_photo'):
                application.passport_photo = request.FILES['passport_photo']
            if request.FILES.get('id_front'):
                application.id_front = request.FILES['id_front']
            if request.FILES.get('id_back'):
                application.id_back = request.FILES['id_back']
            
            application.save()
            
            messages.success(request, f'Application for {application.full_name()} updated successfully.')
            return redirect('staff:application_detail', pk=application.pk)
            
        except Exception as e:
            messages.error(request, f'Error updating application: {str(e)}')
    
    context = {
        'application': application,
        'status_choices': StaffApplication.STATUS_CHOICES,
        'position_choices': StaffApplication.POSITION_CHOICES,
    }
    return render(request, 'staff/edit.html', context)

@login_required
def application_delete(request, pk):
    """Delete an application"""
    application = get_object_or_404(StaffApplication, pk=pk)
    
    if request.method == 'POST':
        try:
            full_name = application.full_name()
            application.delete()
            messages.success(request, f'Application for {full_name} deleted successfully.')
            return redirect('staff:application_list')
        except Exception as e:
            messages.error(request, f'Error deleting application: {str(e)}')
            return redirect('staff:application_detail', pk=pk)
    
    context = {
        'application': application,
    }
    return render(request, 'staff/delete.html', context)

@login_required
def application_approve(request, pk):
    """Approve an application and create user account with Staff ID as username"""
    application = get_object_or_404(StaffApplication, pk=pk)
    
    # Get extra data
    try:
        extra_data = application.extra_data
    except:
        extra_data = None
    
    if request.method == 'POST':
        try:
            # Get form data
            group_id = request.POST.get('group')
            shop_id = request.POST.get('assigned_shop')
            notes = request.POST.get('review_notes', '')
            
            # ============================================
            # GENERATE STAFF ID FIRST (FM001, FM002, etc.)
            # ============================================
            from staff.models import Staff
            import re
            
            # Get the last staff member to generate sequential ID
            last_staff = Staff.objects.order_by('-id').first()
            if last_staff and last_staff.staff_id:
                numbers = re.findall(r'\d+', last_staff.staff_id)
                if numbers:
                    last_num = int(numbers[0])
                    next_num = last_num + 1
                    staff_id = f"FM{next_num:03d}"
                else:
                    staff_id = "FM001"
            else:
                staff_id = "FM001"
            
            # ============================================
            # USE STAFF ID AS USERNAME (THIS IS THE KEY FIX)
            # ============================================
            username = staff_id  # e.g., FM001, FM002, FM003
            
            # Ensure username is unique
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1
            
            # ============================================
            # GET APPLICANT'S PREFERRED PASSWORD FROM SESSION
            # ============================================
            password = request.session.get(f'pending_password_{application.id_number}')
            
            if not password:
                # Fallback to ID number if password not found
                password = application.id_number
                if len(password) < 8:
                    password = password.zfill(8)
            
            # ============================================
            # CHECK IF USER ALREADY EXISTS
            # ============================================
            user = None
            if User.objects.filter(email=application.email).exists():
                user = User.objects.get(email=application.email)
                # Update username to staff_id
                user.username = username
                user.save()
                logger.info(f"Existing user updated with username: {username}")
            else:
                # CREATE NEW USER ACCOUNT WITH STAFF ID AS USERNAME
                user = User.objects.create_user(
                    username=username,  # Staff ID as username
                    email=application.email,
                    password=password,
                    first_name=application.first_name,
                    last_name=application.last_name,
                    is_active=True,
                    is_staff=False
                )
                logger.info(f"New user account created with username: {username} (Staff ID)")
            
            # ============================================
            # CREATE OR UPDATE USER PROFILE
            # ============================================
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.password_changed = True
            profile.first_login = False
            profile.is_verified = True
            profile.verified_at = timezone.now()
            profile.verified_by = request.user
            profile.save()
            
            # ============================================
            # CREATE OR UPDATE STAFF PROFILE
            # ============================================
            staff_profile, created = Staff.objects.get_or_create(
                user=user,
                defaults={
                    'staff_id': staff_id,
                    'id_number': application.id_number,
                    'position': 'pending',
                    'is_identity_verified': True,
                    'verified_at': timezone.now(),
                    'verified_by': request.user,
                    'verification_notes': f"Auto-verified during application approval. Original notes: {notes}",
                    'passport_photo': application.passport_photo,
                    'id_front': application.id_front,
                    'id_back': application.id_back,
                }
            )
            
            if not created:
                # Update existing staff profile
                staff_profile.staff_id = staff_id
                staff_profile.id_number = application.id_number
                staff_profile.is_identity_verified = True
                staff_profile.verified_at = timezone.now()
                staff_profile.verified_by = request.user
                staff_profile.verification_notes = f"Auto-verified during application approval. Original notes: {notes}"
                if application.passport_photo:
                    staff_profile.passport_photo = application.passport_photo
                if application.id_front:
                    staff_profile.id_front = application.id_front
                if application.id_back:
                    staff_profile.id_back = application.id_back
                staff_profile.save()
            
            # Assign shop if provided
            if shop_id:
                try:
                    from shops.models import ShopBranch
                    shop = ShopBranch.objects.get(id=shop_id)
                    staff_profile.assigned_shop = shop
                    staff_profile.save()
                    logger.info(f"Staff {username} assigned to shop: {shop.name}")
                except Exception as e:
                    logger.error(f"Error assigning shop: {str(e)}")
            
            # ============================================
            # ASSIGN TO GROUP
            # ============================================
            group_name = None
            if group_id:
                try:
                    group = Group.objects.get(id=group_id)
                    user.groups.clear()  # Clear existing groups
                    user.groups.add(group)
                    group_name = group.name
                except Group.DoesNotExist:
                    logger.warning(f"Group with id {group_id} does not exist")
            
            # ============================================
            # UPDATE APPLICATION STATUS
            # ============================================
            application.status = 'approved'
            application.reviewed_by = request.user
            application.review_date = timezone.now()
            application.review_notes = notes
            application.created_user = user
            application.save()
            
            # Clean up session
            if f'pending_password_{application.id_number}' in request.session:
                del request.session[f'pending_password_{application.id_number}']
            
            # ============================================
            # SEND APPROVAL EMAIL
            # ============================================
            try:
                subject = "✅ Your FieldMax Application Has Been Approved!"
                html_message = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <style>
                        body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
                        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                        .header {{ background: linear-gradient(135deg, #28a745 0%, #1e7e34 100%); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                        .content {{ background: #f8f9fa; padding: 30px; border: 1px solid #dee2e6; }}
                        .credentials {{ background: white; padding: 20px; border-radius: 10px; margin: 20px 0; border-left: 4px solid #28a745; }}
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>🎉 Welcome to FieldMax, {application.first_name}!</h2>
                        </div>
                        <div class="content">
                            <p>Dear <strong>{application.first_name} {application.last_name}</strong>,</p>
                            <p>Congratulations! Your application has been <strong>approved</strong>.</p>
                            <div class="credentials">
                                <h3>Your Login Credentials:</h3>
                                <ul>
                                    <li><strong>Username:</strong> {staff_id}</li>
                                    <li><strong>Password:</strong> The password you chose during registration</li>
                                    <li><strong>Staff ID:</strong> {staff_id}</li>
                                    <li><strong>Role:</strong> {group_name if group_name else "Staff Member"}</li>
                                </ul>
                            </div>
                            <p><strong>Important:</strong> Your username is your <strong>Staff ID: {staff_id}</strong></p>
                            <p>Click here to login: <a href="{request.build_absolute_uri('/staff/login/')}">Login to Dashboard</a></p>
                        </div>
                    </div>
                </body>
                </html>
                """
                queue_email(subject, "Your application has been approved", [application.email], html_message)
            except Exception as e:
                logger.error(f"Failed to send approval email: {str(e)}")
            
            messages.success(
                request, 
                f'✅ Application approved! Username: {staff_id}, Password: User\'s chosen password'
            )
            return redirect('staff:application_detail', pk=application.pk)
            
        except Exception as e:
            logger.error(f"Error approving application: {str(e)}", exc_info=True)
            messages.error(request, f'Error approving application: {str(e)}')
            return redirect('staff:application_detail', pk=application.pk)
    
    # GET request - show approval form
    groups = Group.objects.all().order_by('name')
    from shops.models import ShopBranch
    shops = ShopBranch.objects.filter(is_active=True).order_by('name')
    
    # Calculate next staff ID for preview
    from staff.models import Staff
    import re
    last_staff = Staff.objects.order_by('-id').first()
    if last_staff and last_staff.staff_id:
        numbers = re.findall(r'\d+', last_staff.staff_id)
        if numbers:
            last_num = int(numbers[0])
            next_num = last_num + 1
            next_staff_id = f"FM{next_num:03d}"
        else:
            next_staff_id = "FM001"
    else:
        next_staff_id = "FM001"
    
    context = {
        'application': application,
        'extra_data': extra_data,
        'groups': groups,
        'shops': shops,
        'next_staff_id': next_staff_id,
    }
    return render(request, 'staff/approve.html', context)




@staff_member_required
def application_revert_to_pending(request, pk):
    """Revert an approved application back to pending status and delete associated user account"""
    application = get_object_or_404(StaffApplication, pk=pk)
    
    # Check if application is approved
    if application.status == 'approved':
        user_deleted = False
        username = None
        user_email = application.email
        
        # Try to find and delete the associated user account
        try:
            # First check if there's a direct reference
            if hasattr(application, 'created_user') and application.created_user:
                user = application.created_user
                username = user.username
                
                # Check if this is a superuser (prevent deleting admins)
                if user.is_superuser:
                    messages.error(
                        request, 
                        f'Cannot revert application #{application.id} - associated user "{username}" is a superuser. '
                        f'Please delete manually from admin.'
                    )
                    return redirect('staff:application_list')
                
                # Delete the user
                user.delete()
                user_deleted = True
                
            else:
                # Try to find user by email
                try:
                    user = User.objects.get(email=application.email)
                    username = user.username
                    
                    # Check if this is a superuser
                    if user.is_superuser:
                        messages.error(
                            request, 
                            f'Cannot revert application #{application.id} - user with email "{application.email}" is a superuser. '
                            f'Please delete manually from admin.'
                        )
                        return redirect('staff:application_list')
                    
                    # Delete the user
                    user.delete()
                    user_deleted = True
                    
                except User.DoesNotExist:
                    # No user found - that's fine
                    pass
                    
        except Exception as e:
            logger.error(f"Error deleting user for application #{application.id}: {str(e)}")
            messages.warning(
                request, 
                f'Application will be reverted but there was an error deleting the user account: {str(e)}'
            )
        
        # Store old values for logging/notification
        old_status = application.status
        old_reviewed_by = application.reviewed_by
        old_review_date = application.review_date
        
        # Revert the application status
        application.status = 'pending'
        application.reviewed_by = None
        application.review_date = None
        application.review_notes = None
        if hasattr(application, 'created_user'):
            application.created_user = None
        application.save()
        
        # Log the action
        logger.info(
            f"Application #{application.id} reverted from {old_status} to pending by {request.user.username}. "
            f"User deleted: {user_deleted} (Username: {username})"
        )
        
        # Send email notification to applicant (optional)
#        try:
#            send_revert_notification(application, user_deleted, username)
#        except Exception as e:
#            logger.error(f"Failed to send revert notification email: {str(e)}")
        
        # Success message
        if user_deleted:
            messages.success(
                request, 
                f'✅ Application #{application.id} for {application.full_name} has been reverted to pending.<br>'
                f'👤 User account "<strong>{username}</strong>" has been deleted.'
            )
        else:
            messages.success(
                request, 
                f'✅ Application #{application.id} for {application.full_name} has been reverted to pending.<br>'
                f'ℹ️ No associated user account was found.'
            )
    else:
        messages.warning(
            request, 
            f'⚠️ Application #{application.id} is not approved (current status: {application.get_status_display()}) and cannot be reverted.'
        )
    
    return redirect('staff:application_list')

@login_required
def application_reject(request, pk):
    """Reject an application"""
    application = get_object_or_404(StaffApplication, pk=pk)
    
    if request.method == 'POST':
        try:
            reason = request.POST.get('review_notes', '')
            if not reason:
                messages.error(request, 'Please provide a reason for rejection.')
                return render(request, 'staff/reject.html', {'application': application})
            
            application.status = 'rejected'
            application.reviewed_by = request.user
            application.review_date = timezone.now()
            application.review_notes = reason
            application.save()
            
            
            messages.success(
                request, 
                f'Application for {application.full_name()} has been rejected.'
            )
            return redirect('staff:application_detail', pk=application.pk)
            
        except Exception as e:
            logger.error(f"Error rejecting application: {str(e)}")
            messages.error(request, f'Error rejecting application: {str(e)}')
            return redirect('staff:application_detail', pk=application.pk)
    
    context = {
        'application': application,
    }
    return render(request, 'staff/reject.html', context)

@login_required
def view_documents(request, pk):
    """View all application documents"""
    application = get_object_or_404(StaffApplication, pk=pk)
    
    context = {
        'application': application,
    }
    return render(request, 'staff/documents.html', context)





from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required

@login_required
def password_change(request):
    """Force password change on first login"""
    
    # Check if user has already changed password
    try:
        if request.user.profile.password_changed:
            # If already changed, redirect to dashboard
            return redirect('staff:staff_dashboard')
    except:
        pass
    
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            
            # Update session to prevent logout
            update_session_auth_hash(request, user)
            
            # Mark password as changed
            try:
                profile = request.user.profile
                profile.password_changed = True
                profile.first_login = False
                profile.save()
            except:
                pass
            
            messages.success(request, 'Your password was successfully updated!')
            return redirect('staff:staff_dashboard')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = PasswordChangeForm(request.user)
    
    context = {
        'form': form,
        'first_login': True,
    }
    return render(request, 'staff/password_change.html', context)

# ============================================
# ENSURE WORKER THREAD STARTS ON RENDER
# ============================================
# This must be at the very bottom of the file

import time

def ensure_worker_running():
    """Ensure email worker thread is running"""
    global worker_thread, worker_running, email_queue
    
    # Give Django a moment to fully initialize
    time.sleep(2)
    
    if worker_thread is None or not worker_thread.is_alive():
        worker_running = True
        worker_thread = threading.Thread(target=email_worker, daemon=True)
        worker_thread.start()
        logger.info("🚀 Email worker thread started (from ensure_worker_running)")
        print("🚀 Email worker thread started on Render")
    else:
        logger.info(f"✅ Email worker already running. Alive: {worker_thread.is_alive()}")
        print(f"✅ Email worker already running. Alive: {worker_thread.is_alive()}")

# Run the check in a separate thread to not block startup
threading.Thread(target=ensure_worker_running, daemon=True).start()



@login_required
def diagnostic_email(request):
    """Diagnostic endpoint to check email system"""
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    # Test queue an email
    test_id = f"test-{random.randint(1000, 9999)}"
    queue_email(
        subject=f"Diagnostic Test {test_id}",
        message="This is a diagnostic test email",
        recipient_list=[request.user.email],
        html_message="<h1>Diagnostic Test</h1><p>If you see this, email is working!</p>"
    )
    
    return JsonResponse({
        'worker_alive': worker_thread.is_alive() if worker_thread else False,
        'worker_running': worker_running,
        'queue_size': email_queue.qsize(),
        'on_render': os.environ.get('RENDER', False),
        'test_id': test_id,
        'sendgrid_key_exists': bool(settings.SENDGRID_API_KEY),
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_edit(request, pk):
    """Edit user details including staff profile information"""
    from shops.models import ShopBranch
    
    user_to_edit = get_object_or_404(User, pk=pk)
    
    # Get or create user profile
    try:
        profile = user_to_edit.profile
    except:
        profile = UserProfile.objects.create(user=user_to_edit)
    
    # Get or create staff profile
    try:
        staff_profile = user_to_edit.staff_profile
    except:
        staff_profile = None
    
    # Get all active shops
    shops = ShopBranch.objects.filter(is_active=True).order_by('name')
    
    if request.method == 'POST':
        # ... rest of your POST handling code ...
        pass
    
    context = {
        'user': user_to_edit,
        'profile': profile,
        'staff_profile': staff_profile,
        'groups': Group.objects.all().order_by('name'),
        'selected_groups': user_to_edit.groups.values_list('id', flat=True),
        'shops': shops,  # Make sure this is passed
        'selected_shop': staff_profile.assigned_shop.id if staff_profile and staff_profile.assigned_shop else None,
        'title': f'Edit User: {user_to_edit.username}'
    }
    return render(request, 'staff/users/edit.html', context)



@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_deactivate(request, pk):
    """Deactivate a user account"""
    user_to_deactivate = get_object_or_404(User, pk=pk)
    
    # Prevent deactivating yourself
    if user_to_deactivate == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect('staff:user_detail', pk=pk)
    
    # Check if already inactive
    if not user_to_deactivate.is_active:
        messages.warning(request, f"User {user_to_deactivate.username} is already inactive.")
        return redirect('staff:user_detail', pk=pk)
    
    # Deactivate the user
    user_to_deactivate.is_active = False
    user_to_deactivate.save()
    
    logger.info(f"User {user_to_deactivate.username} deactivated by {request.user.username}")
    messages.success(request, f"User {user_to_deactivate.username} has been deactivated successfully.")
    
    return redirect('staff:user_detail', pk=pk)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_activate(request, pk):
    """Activate a user account"""
    user_to_activate = get_object_or_404(User, pk=pk)
    
    # Prevent activating yourself (though you should already be active)
    if user_to_activate == request.user:
        messages.error(request, "You are already active.")
        return redirect('staff:user_detail', pk=pk)
    
    # Check if already active
    if user_to_activate.is_active:
        messages.warning(request, f"User {user_to_activate.username} is already active.")
        return redirect('staff:user_detail', pk=pk)
    
    # Activate the user
    user_to_activate.is_active = True
    user_to_activate.save()
    
    logger.info(f"User {user_to_activate.username} activated by {request.user.username}")
    messages.success(request, f"User {user_to_activate.username} has been activated successfully.")
    
    return redirect('staff:user_detail', pk=pk)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_delete(request, pk):
    """Delete a user account permanently"""
    user_to_delete = get_object_or_404(User, pk=pk)
    
    # Prevent deleting yourself
    if user_to_delete == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect('staff:user_list')
    
    # Store username for message
    username = user_to_delete.username
    full_name = user_to_delete.get_full_name() or username
    
    try:
        # Delete related staff profile first (if exists)
        if hasattr(user_to_delete, 'staff_profile'):
            user_to_delete.staff_profile.delete()
        
        # Delete related user profile (if exists)
        if hasattr(user_to_delete, 'profile'):
            user_to_delete.profile.delete()
        
        # Delete the user
        user_to_delete.delete()
        
        logger.info(f"User {username} deleted by {request.user.username}")
        messages.success(request, f"User {full_name} has been deleted successfully.")
        
    except Exception as e:
        logger.error(f"Error deleting user {username}: {str(e)}")
        messages.error(request, f"Error deleting user: {str(e)}")
    
    return redirect('staff:user_list')

# Optional: AJAX endpoints for smoother UX
@login_required
@user_passes_test(lambda u: u.is_superuser)
@csrf_exempt
def user_toggle_status(request, pk):
    """Toggle user active status via AJAX"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        user_to_toggle = get_object_or_404(User, pk=pk)
        
        # Prevent toggling yourself
        if user_to_toggle == request.user:
            return JsonResponse({'error': 'Cannot toggle your own status'}, status=400)
        
        # Toggle status
        user_to_toggle.is_active = not user_to_toggle.is_active
        user_to_toggle.save()
        
        status = 'activated' if user_to_toggle.is_active else 'deactivated'
        logger.info(f"User {user_to_toggle.username} {status} by {request.user.username}")
        
        return JsonResponse({
            'success': True,
            'message': f'User {user_to_toggle.username} has been {status}',
            'is_active': user_to_toggle.is_active,
            'status': status
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@user_passes_test(lambda u: u.is_superuser)
@csrf_exempt
def user_delete_ajax(request, pk):
    """Delete user via AJAX"""
    if request.method != 'DELETE':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        user_to_delete = get_object_or_404(User, pk=pk)
        
        # Prevent deleting yourself
        if user_to_delete == request.user:
            return JsonResponse({'error': 'Cannot delete your own account'}, status=400)
        
        username = user_to_delete.username
        
        # Delete related profiles
        if hasattr(user_to_delete, 'staff_profile'):
            user_to_delete.staff_profile.delete()
        if hasattr(user_to_delete, 'profile'):
            user_to_delete.profile.delete()
        
        # Delete the user
        user_to_delete.delete()
        
        logger.info(f"User {username} deleted by {request.user.username}")
        
        return JsonResponse({
            'success': True,
            'message': f'User {username} has been deleted successfully'
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_delete_confirm(request, pk):
    """Show delete confirmation page"""
    user_to_delete = get_object_or_404(User, pk=pk)
    
    # Prevent deleting yourself
    if user_to_delete == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect('staff:user_list')
    
    context = {
        'user': user_to_delete,
    }
    return render(request, 'staff/users/delete_confirm.html', context)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_deactivate_confirm(request, pk):
    """Show deactivate confirmation page"""
    user_to_deactivate = get_object_or_404(User, pk=pk)
    
    # Prevent deactivating yourself
    if user_to_deactivate == request.user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect('staff:user_detail', pk=pk)
    
    # Check if already inactive
    if not user_to_deactivate.is_active:
        messages.warning(request, f"User {user_to_deactivate.username} is already inactive.")
        return redirect('staff:user_detail', pk=pk)
    
    context = {
        'user': user_to_deactivate,
    }
    return render(request, 'staff/users/deactivate_confirm.html', context)

@login_required
@user_passes_test(lambda u: u.is_superuser)
def user_activate_confirm(request, pk):
    """Show activate confirmation page"""
    user_to_activate = get_object_or_404(User, pk=pk)
    
    # Check if already active
    if user_to_activate.is_active:
        messages.warning(request, f"User {user_to_activate.username} is already active.")
        return redirect('staff:user_detail', pk=pk)
    
    context = {
        'user': user_to_activate,
    }
    return render(request, 'staff/users/activate_confirm.html', context)



from .utils.user_status import UserStatusManager


def is_superuser(user):
    """Check if user is superuser"""
    return user.is_superuser

# ============================================
# Lock User Views
# ============================================

@login_required
@user_passes_test(is_superuser)
def user_lock_confirm(request, pk):  # Changed from user_id to pk
    """Confirm lock user page"""
    target_user = get_object_or_404(User, id=pk)
    
    # Prevent locking self
    if target_user == request.user:
        messages.error(request, "You cannot lock your own account.")
        return redirect('staff:user_detail', pk=pk)  # Changed to pk
    
    # Check if already locked
    if hasattr(target_user, 'status') and target_user.status.is_locked:
        messages.warning(request, f"User {target_user.username} is already locked.")
        return redirect('staff:user_detail', pk=pk)  # Changed to pk
    
    context = {
        'user': target_user,  # Changed to 'user' to match template
        'target_user': target_user,
        'action': 'lock',
        'action_title': 'Lock User Account',
        'action_icon': 'fas fa-lock',
        'action_color': 'warning',
        'warning_message': 'The user will not be able to login until unlocked by an admin.',
        'reason_required': True,
        'reason_options': [
            ('admin', 'Admin Lock'),
            ('suspicious', 'Suspicious Activity'),
        ]
    }
    
    return render(request, 'staff/users/lock_confirm.html', context)  # Changed template name

@login_required
@user_passes_test(is_superuser)
def user_lock_process(request, pk):  # Changed from user_id to pk
    """Process lock user action"""
    if request.method != 'POST':
        return redirect('staff:user_list')
    
    target_user = get_object_or_404(User, id=pk)
    
    # Prevent locking self
    if target_user == request.user:
        messages.error(request, "You cannot lock your own account.")
        return redirect('staff:user_detail', pk=pk)  # Changed to pk
    
    reason = request.POST.get('reason', 'admin')
    
    # Lock the user
    UserStatusManager.lock_user(target_user, reason, request)
    
    messages.success(request, f"User {target_user.username} has been locked successfully.")
    return redirect('staff:user_detail', pk=pk)  # Changed to pk

@login_required
@user_passes_test(is_superuser)
def user_unlock_confirm(request, pk):  # Changed from user_id to pk
    """Confirm unlock user page"""
    target_user = get_object_or_404(User, id=pk)
    
    # Check if not locked
    if not hasattr(target_user, 'status') or not target_user.status.is_locked:
        messages.warning(request, f"User {target_user.username} is not locked.")
        return redirect('staff:user_detail', pk=pk)  # Changed to pk
    
    context = {
        'user': target_user,  # Changed to 'user' to match template
        'target_user': target_user,
        'action': 'unlock',
        'action_title': 'Unlock User Account',
        'action_icon': 'fas fa-unlock-alt',
        'action_color': 'success',
        'warning_message': 'The user will be able to login again after unlocking.',
        'reason_required': False,
    }
    
    return render(request, 'staff/users/unlock_confirm.html', context)  # Changed template name

@login_required
@user_passes_test(is_superuser)
def user_unlock_process(request, pk):  # Changed from user_id to pk
    """Process unlock user action"""
    if request.method != 'POST':
        return redirect('staff:user_list')
    
    target_user = get_object_or_404(User, id=pk)
    
    # Unlock the user
    UserStatusManager.unlock_user(target_user, request)
    
    messages.success(request, f"User {target_user.username} has been unlocked successfully.")
    return redirect('staff:user_detail', pk=pk)  # Changed to pk


# ============================================
# Suspend User Views
# ============================================

@login_required
@user_passes_test(is_superuser)
def user_suspend_confirm(request, pk):  # Changed from user_id to pk
    """Confirm suspend user page"""
    target_user = get_object_or_404(User, id=pk)
    
    # Prevent suspending self
    if target_user == request.user:
        messages.error(request, "You cannot suspend your own account.")
        return redirect('staff:user_detail', pk=pk)  # Changed to pk
    
    # Check if already suspended
    if hasattr(target_user, 'status') and target_user.status.is_suspended:
        messages.warning(request, f"User {target_user.username} is already suspended.")
        return redirect('staff:user_detail', pk=pk)  # Changed to pk
    
    context = {
        'user': target_user,  # Changed to 'user' to match template
        'target_user': target_user,
        'action': 'suspend',
        'action_title': 'Suspend User Account',
        'action_icon': 'fas fa-pause-circle',
        'action_color': 'warning',
        'warning_message': 'The user will not be able to login until the suspension period ends.',
        'reason_required': True,
        'show_duration': True,
        'duration_options': [
            (7, '7 days'),
            (14, '14 days'),
            (30, '30 days'),
            (60, '60 days'),
            (90, '90 days'),
        ]
    }
    
    return render(request, 'staff/users/suspend_confirm.html', context)


@login_required
@user_passes_test(is_superuser)
def user_suspend_process(request, pk):  # Changed from user_id to pk
    """Process suspend user action"""
    if request.method != 'POST':
        return redirect('staff:user_list')
    
    target_user = get_object_or_404(User, id=pk)
    
    # Prevent suspending self
    if target_user == request.user:
        messages.error(request, "You cannot suspend your own account.")
        return redirect('staff:user_detail', pk=pk)  # Changed to pk
    
    reason = request.POST.get('reason', '').strip()
    days = int(request.POST.get('days', 30))
    
    if not reason:
        messages.error(request, "Please provide a reason for suspension.")
        return redirect('staff:user_suspend_confirm', pk=pk)  # Changed to pk
    
    # Suspend the user
    UserStatusManager.suspend_user(target_user, reason, request.user, days, request)
    
    messages.success(request, f"User {target_user.username} has been suspended for {days} days.")
    return redirect('staff:user_detail', pk=pk)  # Changed to pk


@login_required
@user_passes_test(is_superuser)
def user_unsuspend_confirm(request, pk):  # Changed from user_id to pk
    """Confirm unsuspend user page"""
    target_user = get_object_or_404(User, id=pk)
    
    # Check if not suspended
    if not hasattr(target_user, 'status') or not target_user.status.is_suspended:
        messages.warning(request, f"User {target_user.username} is not suspended.")
        return redirect('staff:user_detail', pk=pk)  # Changed to pk
    
    context = {
        'user': target_user,  # Changed to 'user' to match template
        'target_user': target_user,
        'action': 'unsuspend',
        'action_title': 'Unsuspend User Account',
        'action_icon': 'fas fa-play',
        'action_color': 'success',
        'warning_message': 'The user will be able to login again after unsuspending.',
        'reason_required': False,
    }
    
    return render(request, 'staff/users/unsuspend_confirm.html', context)


@login_required
@user_passes_test(is_superuser)
def user_unsuspend_process(request, pk):  # Changed from user_id to pk
    """Process unsuspend user action"""
    if request.method != 'POST':
        return redirect('staff:user_list')
    
    target_user = get_object_or_404(User, id=pk)
    
    # Unsuspend the user
    UserStatusManager.unsuspend_user(target_user, request)
    
    messages.success(request, f"User {target_user.username} has been unsuspended successfully.")
    return redirect('staff:user_detail', pk=pk)  # Changed to pk



# ============================================
# POWERED BY PAGE
# ============================================
def powered_by_page(request):
    """Page showing information about FieldMax"""
    return render(request, 'staff/powered_by.html')