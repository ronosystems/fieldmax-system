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
from functools import wraps
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import UserProfile




logger = logging.getLogger(__name__)
User = get_user_model()

# Create a global queue and worker thread
email_queue = queue.Queue()
worker_running = True
worker_thread = None

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





import sys

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

# ============================================
# Start the worker thread
# ============================================
worker_thread = threading.Thread(target=email_worker, daemon=True)
worker_thread.start()
logger.info(f"✅ Worker thread started. Alive: {worker_thread.is_alive()}")






def custom_logout(request):
    """Custom logout view that handles POST requests"""
    logout(request)
    messages.success(request, "You have been successfully logged out.")
    return redirect('website:home') 





# ============================================
# CORRECT AUTOREDIRECT DASHBOARD
# ============================================
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





# ============================================
# Identity Verification View
# ============================================
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







# ============================================
# Resend Verification Code
# ============================================
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


# ============================================
# Send admin notification
# ============================================
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






# ============================================
# Send verification result email to staff
# ============================================
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




#==========================================
# ADMIN DASHBOARD - COMPREHENSIVE STATISTICS
#==========================================
@login_required
@dashboard_for_role('Administrator')
def admin_dashboard(request):
    """Admin dashboard with full system overview - includes active sales, returns, and reversals"""
    from django.contrib.auth import get_user_model
    from inventory.models import Product, Category, StockAlert, ReturnRequest
    from sales.models import Sale, SaleItem
    from credit.models import CreditTransaction, CreditCustomer, CreditCompany
    from django.db.models import Sum, Count, Q, F, Avg, DecimalField
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
    # GET RETURNED SALE IDs (to exclude from active sales)
    # ============================================
    returned_sale_ids = ReturnRequest.objects.filter(
        ~Q(status='rejected')  # Exclude rejected returns
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
    # CURRENT MONTH'S SALES
    # ============================================
    current_month_sales = active_sales.filter(
        sale_date__year=current_year,
        sale_date__month=current_month
    )
    
    current_month_sales_value = current_month_sales.aggregate(
        total=Sum('total_amount')
    )['total'] or 0
    
    current_month_sales_count = current_month_sales.count()
    current_month_items_sold = SaleItem.objects.filter(
        sale__in=current_month_sales
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    # Get month name
    month_name = timezone.now().strftime('%B')
    
    # Calculate previous month's sales for comparison
    if current_month == 1:
        prev_month = 12
        prev_year = current_year - 1
    else:
        prev_month = current_month - 1
        prev_year = current_year
    
    previous_month_sales = active_sales.filter(
        sale_date__year=prev_year,
        sale_date__month=prev_month
    ).aggregate(total=Sum('total_amount'))['total'] or 0
    
    # Calculate percentage change
    if previous_month_sales > 0:
        monthly_percentage_change = ((current_month_sales_value - previous_month_sales) / previous_month_sales) * 100
    else:
        monthly_percentage_change = 100 if current_month_sales_value > 0 else 0
    
    # ============================================
    # SYSTEM OVERVIEW
    # ============================================
    total_users = User.objects.count()
    active_users = User.objects.filter(is_active=True).count()
    total_staff = User.objects.filter(is_staff=True).count()
    total_products = Product.objects.count()
    total_categories = Category.objects.count()
    
    # ============================================
    # PRODUCT STATS
    # ============================================
    # Total items count (sum of all product quantities)
    total_item_count = Product.objects.aggregate(
        total=Sum('quantity')
    )['total'] or 0
    
    # Total inventory value (selling price × quantity)
    total_inventory_value = Product.objects.filter(
        is_active=True
    ).aggregate(
        total_value=Sum(F('selling_price') * F('quantity'), output_field=DecimalField())
    )['total_value'] or Decimal('0')
    
    # Total inventory cost (buying price × quantity)
    total_inventory_cost = Product.objects.filter(
        is_active=True
    ).aggregate(
        total_cost=Sum(F('buying_price') * F('quantity'), output_field=DecimalField())
    )['total_cost'] or Decimal('0')
    
    # Calculate potential profit
    potential_profit = total_inventory_value - total_inventory_cost
    
    # Calculate profit margin percentage
    if total_inventory_value > 0:
        profit_margin_percentage = (potential_profit / total_inventory_value) * 100
    else:
        profit_margin_percentage = 0
    
    # Products added this month
    products_added_this_month = Product.objects.filter(
        created_at__year=current_year,
        created_at__month=current_month
    ).count()
    
    # Products with zero stock
    zero_stock_products = Product.objects.filter(
        quantity=0
    ).count()
    
    # Active products vs inactive
    active_products = Product.objects.filter(is_active=True).count()
    inactive_products = Product.objects.filter(is_active=False).count()
    
    # Products by type (single vs bulk)
    single_items = Product.objects.filter(
        category__item_type='single'
    ).count()
    bulk_items = Product.objects.filter(
        category__item_type='bulk'
    ).count()
    
    # ============================================
    # TODAY'S STATS
    # ============================================
    today_sales = active_sales.filter(sale_date__date=today).aggregate(
        total=Sum('total_amount')
    )['total'] or 0
    today_sales_count = active_sales.filter(sale_date__date=today).count()
    today_items_sold = SaleItem.objects.filter(
        sale__in=active_sales.filter(sale_date__date=today)
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    # ============================================
    # OVERALL SALES STATS
    # ============================================
    total_sales_value = active_sales.aggregate(
        total=Sum('total_amount')
    )['total'] or 0
    total_sales_count = active_sales.count()
    total_items_sold = SaleItem.objects.filter(
        sale__in=active_sales
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    # Average transaction value
    avg_transaction_value = total_sales_value / total_sales_count if total_sales_count > 0 else 0
    
    # ============================================
    # REVERSAL STATS
    # ============================================
    reversed_sales = Sale.objects.filter(is_reversed=True)
    reversed_count = reversed_sales.count()
    reversed_amount = reversed_sales.aggregate(total=Sum('total_amount'))['total'] or 0
    
    # ============================================
    # RETURN STATS
    # ============================================
    all_returns = ReturnRequest.objects.all()
    total_returns = all_returns.count()
    total_refund_amount = all_returns.aggregate(total=Sum('refund_amount'))['total'] or 0
    
    # Returns by status
    pending_returns = all_returns.filter(status__in=['submitted', 'verified']).count()
    approved_returns = all_returns.filter(status='approved').count()
    processed_returns = all_returns.filter(status='processed').count()
    rejected_returns = all_returns.filter(status='rejected').count()
    damaged_returns = all_returns.filter(status='damaged_loss').count()
    
    # Damaged returns loss value
    damaged_loss = all_returns.filter(status='damaged_loss').aggregate(
        total=Sum('loss_amount')
    )['total'] or 0
    
    # ============================================
    # CREDIT STATS (UPDATED WITH PENDING VALUE LOGIC)
    # ============================================
    # Total credit value (all transactions)
    total_credit = CreditTransaction.objects.aggregate(
        total=Sum('ceiling_price')
    )['total'] or 0
    
    # Total pending credit value (unpaid)
    total_pending_credit_value = CreditTransaction.objects.filter(
        payment_status='pending'
    ).aggregate(
        total=Sum('ceiling_price')
    )['total'] or 0
    
    # Total paid credit value
    total_paid_credit_value = CreditTransaction.objects.filter(
        payment_status='paid'
    ).aggregate(
        total=Sum('ceiling_price')
    )['total'] or 0
    
    # Count statistics
    pending_credit = CreditTransaction.objects.filter(payment_status='pending').count()
    paid_credit = CreditTransaction.objects.filter(payment_status='paid').count()
    overdue_credit = CreditTransaction.objects.filter(
        payment_status='pending',
        transaction_date__date__lte=month_ago
    ).count()
    
    # Calculate payment completion percentage
    if total_credit > 0:
        payment_completion_percentage = (total_paid_credit_value / total_credit) * 100
    else:
        payment_completion_percentage = 0
    
    # Calculate overdue amount
    overdue_credit_amount = CreditTransaction.objects.filter(
        payment_status='pending',
        transaction_date__date__lte=month_ago
    ).aggregate(
        total=Sum('ceiling_price')
    )['total'] or 0
    
    # ============================================
    # CUSTOMER STATS
    # ============================================
    total_customers = CreditCustomer.objects.count()
    active_customers = CreditCustomer.objects.filter(is_active=True).count()
    new_customers_today = CreditCustomer.objects.filter(
        created_at__date=today
    ).count()
    
    # ============================================
    # INVENTORY STATS
    # ============================================
    low_stock_products = Product.objects.filter(
        Q(category__item_type='bulk') & 
        Q(quantity__gt=0) & 
        Q(quantity__lte=F('reorder_level'))
    ).count()
    
    out_of_stock = Product.objects.filter(
        Q(category__item_type='bulk', quantity=0) |
        Q(category__item_type='single', status='sold')
    ).count()
    
    # Stock alerts
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
    # STAFF BY POSITION
    # ============================================
    from staff.models import Staff
    staff_by_position = Staff.objects.values('position').annotate(
        count=Count('id')
    ).order_by('position')
    
    # Total staff count from Staff model
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
        
        # Daily active sales
        day_sales = active_sales.filter(sale_date__date=date).aggregate(
            total=Sum('total_amount')
        )['total'] or 0
        sales_data.append(float(day_sales))
        
        # Daily credit transactions
        day_credit = CreditTransaction.objects.filter(
            transaction_date__date=date
        ).aggregate(
            total=Sum('ceiling_price')
        )['total'] or 0
        credit_data.append(float(day_credit))
        
        # Daily returns
        day_returns = ReturnRequest.objects.filter(
            requested_at__date=date
        ).aggregate(
            total=Sum('refund_amount')
        )['total'] or 0
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
        amount = method_sales.aggregate(total=Sum('total_amount'))['total'] or 0
        percentage = (amount / total_sales_value * 100) if total_sales_value > 0 else 0
        
        payment_methods.append({
            'name': method,
            'count': count,
            'amount': amount,
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
        
        # Product Stats
        'total_item_count': total_item_count,
        'total_inventory_value': total_inventory_value,
        'total_inventory_cost': total_inventory_cost,
        'potential_profit': potential_profit,
        'profit_margin_percentage': profit_margin_percentage,
        'products_added_this_month': products_added_this_month,
        'zero_stock_products': zero_stock_products,
        'active_products': active_products,
        'inactive_products': inactive_products,
        'single_items': single_items,
        'bulk_items': bulk_items,
        
        # Today's Stats
        'today_sales': today_sales,
        'today_sales_count': today_sales_count,
        'today_items_sold': today_items_sold,
        
        # Current Month's Stats
        'current_month_sales_value': current_month_sales_value,
        'current_month_sales_count': current_month_sales_count,
        'current_month_items_sold': current_month_items_sold,
        'month_name': month_name,
        'monthly_percentage_change': monthly_percentage_change,
        'previous_month_sales': previous_month_sales,
        
        # Sales Overview
        'total_sales_value': total_sales_value,
        'total_sales_count': total_sales_count,
        'total_items_sold': total_items_sold,
        'avg_transaction_value': avg_transaction_value,
        
        # Reversal Stats
        'reversed_count': reversed_count,
        'reversed_amount': reversed_amount,
        'reversal_percentage': (reversed_count / (total_sales_count + reversed_count) * 100) if (total_sales_count + reversed_count) > 0 else 0,
        
        # Return Stats
        'total_returns': total_returns,
        'total_refund_amount': total_refund_amount,
        'pending_returns': pending_returns,
        'approved_returns': approved_returns,
        'processed_returns': processed_returns,
        'rejected_returns': rejected_returns,
        'damaged_returns': damaged_returns,
        'damaged_loss': damaged_loss,
        
        # Credit Stats (UPDATED)
        'total_credit': total_credit,
        'total_pending_credit_value': total_pending_credit_value,
        'total_paid_credit_value': total_paid_credit_value,
        'pending_credit': pending_credit,
        'paid_credit': paid_credit,
        'overdue_credit': overdue_credit,
        'overdue_credit_amount': overdue_credit_amount,
        'payment_completion_percentage': payment_completion_percentage,
        
        # Customer Stats
        'total_customers': total_customers,
        'active_customers': active_customers,
        'new_customers_today': new_customers_today,
        
        # Inventory Stats
        'low_stock_products': low_stock_products,
        'out_of_stock': out_of_stock,
        'active_alerts': active_alerts,
        'critical_alerts': critical_alerts,
        
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
    from inventory.models import Product, Category, StockAlert, StockEntry
    from sales.models import SaleItem
    from django.db.models import Sum, Count, Q, F
    from django.contrib import messages
    from django.utils import timezone
    from datetime import timedelta
    
    prepare_dashboard_messages(request, 'Store Manager')

    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    
    # ============================================
    # INVENTORY OVERVIEW
    # ============================================
    total_products = Product.objects.count()
    total_categories = Category.objects.count()
    
    # Stock value calculation
    products = Product.objects.all()
    total_stock_value = 0
    for product in products:
        if hasattr(product, 'buying_price') and product.buying_price and product.quantity:
            total_stock_value += product.buying_price * product.quantity
    
    # ============================================
    # STOCK ALERTS - USING STOCKALERT MODEL
    # ============================================
    # Get active alerts that are not dismissed
    active_alerts = StockAlert.objects.filter(
        is_active=True,
        is_dismissed=False
    ).select_related('product').order_by(
        '-severity',  # Critical first
        '-last_alerted'
    )
    
    # Count alerts by type for the badge
    low_stock_alerts_count = active_alerts.filter(alert_type='lowstock').count()
    needs_reorder_count = active_alerts.filter(alert_type='needs_reorder').count()
    out_of_stock_count = active_alerts.filter(alert_type='outofstock').count()
    damaged_count = active_alerts.filter(alert_type='damaged').count()
    
    # Get low stock alerts for display (limit to 10)
    low_stock_alerts = active_alerts[:10]
    
    # ============================================
    # PRODUCT STATUS COUNTS (using actual status field)
    # ============================================
    available_products = Product.objects.filter(status='available').count()
    low_stock_products = Product.objects.filter(status='lowstock').count()
    out_of_stock = Product.objects.filter(status='outofstock').count()
    sold_products = Product.objects.filter(status='sold').count()
    damaged_products = Product.objects.filter(status='damaged').count()
    reserved_products = Product.objects.filter(status='reserved').count()
    
    # Alternative low stock count using quantity threshold
    low_stock_by_quantity = Product.objects.filter(
        quantity__gt=0,
        quantity__lte=F('reorder_level')
    ).count()
    
    # ============================================
    # RECENT STOCK MOVEMENTS
    # ============================================
    recent_movements = StockEntry.objects.select_related(
        'product', 'created_by'
    ).order_by('-created_at')[:10]
    
    # ============================================
    # CATEGORY-WISE STOCK
    # ============================================
    stock_by_category = []
    for category in Category.objects.all():
        category_products = category.products.all()
        product_count = category_products.count()
        total_stock = category_products.aggregate(Sum('quantity'))['quantity__sum'] or 0
        stock_by_category.append({
            'name': category.name,
            'product_count': product_count,
            'total_stock': total_stock
        })
    # Sort by total_stock descending
    stock_by_category = sorted(stock_by_category, key=lambda x: x['total_stock'], reverse=True)[:10]
    
    # ============================================
    # TOP SELLING PRODUCTS
    # ============================================
    try:
        top_selling = SaleItem.objects.values(
            'product_name', 'product_code'
        ).annotate(
            total_sold=Sum('quantity'),
            total_revenue=Sum('total_price')
        ).order_by('-total_sold')[:10]
    except:
        top_selling = []
    
    # ============================================
    # RECENT PRODUCTS & NEW THIS WEEK
    # ============================================
    new_products_week = Product.objects.filter(created_at__date__gte=week_ago).count()
    recent_products = Product.objects.select_related('category').order_by('-created_at')[:10]
    
    # ============================================
    # PENDING RETURNS
    # ============================================
    try:
        from inventory.models import ReturnRequest
        pending_returns = ReturnRequest.objects.filter(
            status__in=['submitted', 'verified']
        ).order_by('-requested_at')[:8]
        pending_returns_count = ReturnRequest.objects.filter(
            status__in=['submitted', 'verified']
        ).count()
        verified_returns_count = ReturnRequest.objects.filter(status='verified').count()
    except:
        pending_returns = []
        pending_returns_count = 0
        verified_returns_count = 0
    
    # ============================================
    # OVERSTOCK (products with quantity > 100)
    # ============================================
    overstock = Product.objects.filter(quantity__gt=100).count()
    
    context = {
        # Basic counts
        'total_products': total_products,
        'total_categories': total_categories,
        'total_stock_value': total_stock_value,
        
        # Stock alerts - FIXED: These are what the template expects
        'low_stock_alerts': low_stock_alerts,  # This will now show actual alerts
        'low_stock_alerts_count': low_stock_alerts_count,
        'needs_reorder_count': needs_reorder_count,
        'out_of_stock_count': out_of_stock_count,
        'damaged_count': damaged_count,
        
        # Product status counts
        'low_stock_products': low_stock_products,
        'out_of_stock': out_of_stock,
        'available_products': available_products,
        'sold_products': sold_products,
        'damaged_products': damaged_products,
        'reserved_products': reserved_products,
        'overstock': overstock,
        'low_stock_by_quantity': low_stock_by_quantity,
        
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
# SALES AGENT DASHBOARD - WITH PRODUCT LOOKUP
# ============================================
@login_required
@dashboard_for_role('Sales Agent')
def sales_agent_dashboard(request):
    """Dashboard for sales agents with product price lookup"""
    from sales.models import Sale, SaleItem
    from inventory.models import Product, Category
    from django.db.models import Sum, Count, Q
    from django.utils import timezone
    from datetime import timedelta
    from django.http import JsonResponse
    import json
    
    # Check if this is an AJAX lookup request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.GET.get('action') == 'lookup':
        return product_lookup_api(request)
    
    prepare_dashboard_messages(request, 'Sales Agent')
    
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # My Sales Performance
    my_sales_today = Sale.objects.filter(
        seller=request.user,
        sale_date__date=today
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('sale_id')
    )
    
    my_sales_week = Sale.objects.filter(
        seller=request.user,
        sale_date__date__gte=week_ago
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('sale_id')
    )
    
    my_sales_month = Sale.objects.filter(
        seller=request.user,
        sale_date__date__gte=month_ago
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('sale_id')
    )
    
    # Recent Sales
    recent_sales = Sale.objects.filter(
        seller=request.user
    ).order_by('-sale_date')[:10]
    
    # Top Products I Sold
    top_products = SaleItem.objects.filter(
        sale__seller=request.user
    ).values('product_name').annotate(
        total_qty=Sum('quantity'),
        total_value=Sum('total_price')
    ).order_by('-total_qty')[:5]
    
    # Get all categories for filter dropdown
    categories = Category.objects.filter(is_active=True)
    
    # Daily targets
    daily_target = 50000  # KSH 50,000
    target_achievement = (my_sales_today['total'] or 0) / daily_target * 100 if daily_target > 0 else 0
    
    context = {
        'my_sales_today': my_sales_today,
        'my_sales_week': my_sales_week,
        'my_sales_month': my_sales_month,
        'recent_sales': recent_sales,
        'top_products': top_products,
        'daily_target': daily_target,
        'target_achievement': target_achievement,
        'categories': categories,
    }
    return render(request, 'staff/dashboards/sales_agent_dashboard.html', context)


# ============================================
# PRODUCT LOOKUP API - FOR SALES AGENT DASHBOARD
# ============================================
def product_lookup_api(request):
    """
    API endpoint for product lookup dashboard.
    Searches across all product fields: product_code, sku_value, barcode, name, brand, model
    """
    search_term = request.GET.get('q', '').strip()
    
    if not search_term or len(search_term) < 2:
        return JsonResponse({
            'success': False,
            'message': 'Please enter at least 2 characters'
        })
    
    try:
        # Build search query across multiple fields
        products = Product.objects.filter(
            Q(product_code__icontains=search_term) |
            Q(sku_value__icontains=search_term) |
            Q(barcode__icontains=search_term) |
            Q(name__icontains=search_term) |
            Q(brand__icontains=search_term) |
            Q(model__icontains=search_term) |
            Q(description__icontains=search_term)
        ).select_related('category').filter(is_active=True)[:20]  # Limit to 20 results
        
        if not products.exists():
            return JsonResponse({
                'success': False,
                'message': 'No products found matching your search'
            })
        
        # If multiple products found, return all for grid display
        products_list = []
        for product in products:
            # Format specifications for display
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
                'product_code': product.product_code,
                'name': product.name,
                'display_name': product.display_name,
                'selling_price': float(product.selling_price) if product.selling_price else 0,
                'buying_price': float(product.buying_price) if product.buying_price else 0,
                'best_price': float(product.best_price) if product.best_price else None,
                'sku_value': product.sku_value,
                'barcode': product.barcode,
                'brand': product.brand,
                'model': product.model,
                'quantity': product.quantity,
                'category': product.category.name if product.category else None,
                'category_id': product.category.id if product.category else None,
                'status': product.status,
                'stock_status': product.stock_status,
                'stock_status_badge': product.stock_status_badge,
                'stock_status_icon': product.stock_status_icon,
                'condition': product.get_condition_display() if product.condition else 'New',
                'warranty_months': product.warranty_months,
                'specifications': specs,
                'is_featured': product.is_featured,
                'is_single_item': product.category.is_single_item if product.category else False,
                'created_at': product.created_at.isoformat() if product.created_at else None,
                'updated_at': product.updated_at.isoformat() if product.updated_at else None,
            })
        
        response_data = {
            'success': True,
            'products': products_list,
            'total_matches': products.count(),
            'message': f'Found {products.count()} product(s)'
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Product lookup error: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': f'Error searching for products: {str(e)}'
        }, status=500)


# ============================================
# PRODUCT LOOKUP API - WITH DEBUGGING
# ============================================
def product_lookup_api(request):
    """
    API endpoint for product lookup dashboard.
    Searches across all product fields: product_code, sku_value, barcode, name, brand, model
    """
    import logging
    logger = logging.getLogger(__name__)
    
    search_term = request.GET.get('q', '').strip()
    
    # Log the request
    logger.info(f"🔍 Product lookup request - Search term: '{search_term}'")
    logger.info(f"🔍 Request headers: {dict(request.headers)}")
    logger.info(f"🔍 GET params: {dict(request.GET)}")
    
    if not search_term or len(search_term) < 2:
        return JsonResponse({
            'success': False,
            'message': 'Please enter at least 2 characters',
            'debug': {'search_term': search_term}
        })
    
    try:
        # Build search query across multiple fields
        products = Product.objects.filter(
            Q(product_code__icontains=search_term) |
            Q(sku_value__icontains=search_term) |
            Q(barcode__icontains=search_term) |
            Q(name__icontains=search_term) |
            Q(brand__icontains=search_term) |
            Q(model__icontains=search_term) |
            Q(description__icontains=search_term)
        ).select_related('category').filter(is_active=True)[:20]
        
        # Log the query and count
        logger.info(f"🔍 SQL Query: {products.query}")
        logger.info(f"🔍 Products found: {products.count()}")
        
        # Debug: Check if there are any products at all
        total_products = Product.objects.count()
        logger.info(f"🔍 Total products in database: {total_products}")
        
        if total_products == 0:
            return JsonResponse({
                'success': False,
                'message': 'No products in database',
                'debug': {'total_products': 0}
            })
        
        if not products.exists():
            return JsonResponse({
                'success': False,
                'message': 'No products found matching your search',
                'debug': {
                    'search_term': search_term,
                    'total_products': total_products
                }
            })
        
        # Build products list
        products_list = []
        for product in products:
            # Log each product found
            logger.info(f"🔍 Found product: {product.product_code} - {product.display_name}")
            
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
                'product_code': product.product_code or '',
                'name': product.name or '',
                'display_name': product.display_name or '',
                'selling_price': float(product.selling_price) if product.selling_price else 0,
                'buying_price': float(product.buying_price) if product.buying_price else 0,
                'best_price': float(product.best_price) if product.best_price else None,
                'sku_value': product.sku_value or '',
                'barcode': product.barcode or '',
                'brand': product.brand or '',
                'model': product.model or '',
                'quantity': product.quantity or 0,
                'category': product.category.name if product.category else '',
                'category_id': product.category.id if product.category else None,
                'status': product.status or '',
                'stock_status': product.stock_status,
                'condition': product.get_condition_display() if product.condition else 'New',
                'warranty_months': product.warranty_months or 12,
                'specifications': specs,
                'is_featured': product.is_featured,
                'is_single_item': product.category.is_single_item if product.category else False,
            })
        
        response_data = {
            'success': True,
            'products': products_list,
            'total_matches': len(products_list),
            'message': f'Found {len(products_list)} product(s)',
            'debug': {
                'search_term': search_term,
                'total_products': total_products
            }
        }
        
        # Log the response
        logger.info(f"🔍 Sending response with {len(products_list)} products")
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"🔍 Product lookup error: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'Error searching for products: {str(e)}',
            'debug': {'error': str(e)}
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
# ============================================
# TECHNICIAN MY JOBS - ONLY OWN JOBS
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
# SALES MANAGER DASHBOARD - CORRECTED VERSION
# ============================================
@login_required
@dashboard_for_role('Sales Manager')
def sales_manager_dashboard(request):
    """Dashboard for sales manager - oversees all sales team"""
    from sales.models import Sale, SaleItem
    from django.contrib.auth import get_user_model
    from django.db.models import Sum, Count
    from django.utils import timezone
    from datetime import timedelta
    
    User = get_user_model()

    prepare_dashboard_messages(request, 'Sales Manager')
    
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # Team Overview - FIXED: Added import for StaffApplication
    try:
        from staff.models import StaffApplication
        sales_team = StaffApplication.objects.filter(
            status='approved',
            position__in=['sales_agent', 'cashier']
        ).count()
    except:
        # Fallback if StaffApplication doesn't exist
        sales_team = User.objects.filter(
            groups__name__in=['Sales Agent', 'Cashier']
        ).count()
    
    # Team Performance Today - FIXED: Changed Count('id') to Count('sale_id')
    team_sales_today = Sale.objects.filter(
        sale_date__date=today
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('sale_id')  # FIXED: Use sale_id instead of id
    )
    
    # Team Performance This Week
    team_sales_week = Sale.objects.filter(
        sale_date__date__gte=week_ago
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('sale_id')
    )
    
    # Team Performance This Month
    team_sales_month = Sale.objects.filter(
        sale_date__date__gte=month_ago
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('sale_id')
    )
    
    # Sales by team member (today) - FIXED: Use correct field names
    sales_by_member_today = Sale.objects.filter(
        sale_date__date=today
    ).values('seller__username', 'seller__first_name', 'seller__last_name').annotate(
        total_sales=Sum('total_amount'),
        transaction_count=Count('sale_id'),  # FIXED: Use sale_id
        avg_ticket=Sum('total_amount') / Count('sale_id')
    ).order_by('-total_sales')[:10]
    
    # Sales by team member (this week)
    sales_by_member_week = Sale.objects.filter(
        sale_date__date__gte=week_ago
    ).values('seller__username').annotate(
        total_sales=Sum('total_amount'),
        transaction_count=Count('sale_id')
    ).order_by('-total_sales')[:10]
    
    # Payment method distribution (today)
    payment_methods_today = Sale.objects.filter(
        sale_date__date=today
    ).values('payment_method').annotate(
        count=Count('sale_id'),
        total=Sum('total_amount')
    )
    
    # Top selling products company-wide (today) - FIXED: Use correct field names
    top_products_today = SaleItem.objects.filter(
        sale__sale_date__date=today
    ).values('product_name', 'product_code').annotate(
        total_qty=Sum('quantity'),
        total_value=Sum('total_price'),
        transaction_count=Count('sale__sale_id')  # FIXED: Use sale__sale_id
    ).order_by('-total_qty')[:10]
    
    # Top selling products (this week)
    top_products_week = SaleItem.objects.filter(
        sale__sale_date__date__gte=week_ago
    ).values('product_name').annotate(
        total_qty=Sum('quantity'),
        total_value=Sum('total_price')
    ).order_by('-total_qty')[:10]
    
    # Recent sales (last 10)
    recent_sales = Sale.objects.select_related('seller').order_by('-sale_date')[:10]
    
    # Credit sales today
    credit_sales_today = Sale.objects.filter(
        sale_date__date=today,
        is_credit=True
    ).aggregate(
        count=Count('sale_id'),
        total=Sum('total_amount')
    )
    
    # Cash sales today
    cash_sales_today = Sale.objects.filter(
        sale_date__date=today,
        is_credit=False
    ).aggregate(
        count=Count('sale_id'),
        total=Sum('total_amount')
    )
    
    # ============================================
    # HOURLY SALES DATA - FIXED VARIABLE NAMES
    # ============================================
    hourly_labels = []
    hourly_data = []
    
    # Create hour labels from 7 AM to 10 PM (14 hours)
    for hour in range(7, 22):  # 7 AM to 9 PM
        hourly_labels.append(f"{hour:02d}:00")
        
        # Get sales for this hour
        hour_sales = Sale.objects.filter(
            sale_date__date=today,
            sale_date__hour=hour
        ).aggregate(
            total=Sum('total_amount'),
            count=Count('sale_id')
        )
        
        hourly_data.append(float(hour_sales['total'] or 0))
    
    # Optional: Create hourly_sales list for detailed info (if needed)
    hourly_sales = []
    for i, hour in enumerate(range(7, 22)):
        hourly_sales.append({
            'hour': hour,
            'amount': hourly_data[i],
            'count': Sale.objects.filter(
                sale_date__date=today,
                sale_date__hour=hour
            ).count(),
            'percentage': (hourly_data[i] / float(team_sales_today['total'] or 1)) * 100 if team_sales_today['total'] else 0
        })
    
    # Top performing team member
    top_performer = sales_by_member_today[0] if sales_by_member_today else None
    
    context = {
        'today': today,
        
        # Team stats
        'sales_team': sales_team,
        'team_sales_today': team_sales_today,
        'team_sales_week': team_sales_week,
        'team_sales_month': team_sales_month,
        
        # Sales by member
        'sales_by_member_today': sales_by_member_today,
        'sales_by_member_week': sales_by_member_week,
        
        # Payment methods
        'payment_methods_today': payment_methods_today,
        
        # Top products
        'top_products_today': top_products_today,
        'top_products_week': top_products_week,
        
        # Recent sales
        'recent_sales': recent_sales,
        
        # Credit/Cash stats
        'credit_sales_today': credit_sales_today,
        'cash_sales_today': cash_sales_today,
        
        # Chart data - FIXED: Use correct variable names for template
        'hourly_labels': hourly_labels,   # ← FIXED: Changed from chart_labels
        'hourly_data': hourly_data,       # ← FIXED: Changed from chart_data
        'hourly_sales': hourly_sales,
        
        # Top performer
        'top_performer': top_performer,
        
        # Averages
        'avg_ticket_today': team_sales_today['total'] / team_sales_today['count'] if team_sales_today['count'] else 0,
    }
    
    return render(request, 'staff/dashboards/sales_manager_dashboard.html', context)

    




# ============================================
# CASHIER DASHBOARD
# ============================================
@login_required
@dashboard_for_role('Cashier')
def cashier_dashboard(request):
    """Dashboard for cashier desk"""
    from sales.models import Sale
    from django.db.models import F, Count, Sum, Q
    from staff.models import Staff
    from shops.models import ShopBranch

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
    
    # Today's Transactions
    today_transactions = Sale.objects.filter(
        sale_date__date=today
    ).aggregate(
        count=Count('sale_id'),
        cash_total=Sum('total_amount', filter=Q(payment_method='Cash')),
        mpesa_total=Sum('total_amount', filter=Q(payment_method='M-Pesa')),
        card_total=Sum('total_amount', filter=Q(payment_method='Card')),
        points_total=Sum('total_amount', filter=Q(payment_method='Points'))
    )
    
    # Recent Transactions
    recent_transactions = Sale.objects.filter(
        sale_date__date=today
    ).order_by('-sale_date')[:20]
    
    context = {
        # Add cart data to context
        'cart': cart,
        'subtotal': subtotal,
        'cart_count': len(cart),
        
        # Add shop to context
        'current_shop': current_shop,
        
        # Keep existing context
        'today_transactions': today_transactions,
        'recent_transactions': recent_transactions,
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
# CREDIT OFFICER DASHBOARD
# ============================================
@login_required
@dashboard_for_role('Credit Officer')
def credit_officer_dashboard(request):
    """Dashboard for credit officer showing only their assigned products and transactions"""
    from credit.models import CreditTransaction, CreditCustomer, CreditCompany, CreditTransactionLog
    from inventory.models import Product
    from sales.models import Sale
    from django.db.models import Sum, Count, Q
    from django.utils import timezone
    from datetime import timedelta
    import json
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
    # Get IDs of products that already have ANY credit transaction (SOLD)
    # ============================================
    products_with_credit = CreditTransaction.objects.values_list('product_id', flat=True).distinct()
    
    # ============================================
    # PRODUCTS FOR SEARCH FUNCTIONALITY
    # Only show products owned by this user that are:
    # - Not sold (status='available')
    # - Have stock > 0
    # - Have no existing credit transaction
    # ============================================
    products = Product.objects.filter(
        owner=current_user,
        is_active=True,
        quantity__gt=0,
        status='available',  # Only available items
        category__item_type='single'  # Only single items for credit
    ).exclude(
        id__in=products_with_credit  # Exclude items already used for credit
    ).select_related('category')[:50]
    
    # ============================================
    # CONVERT PRODUCTS TO JSON FOR JAVASCRIPT
    # ============================================
    products_json = json.dumps([
        {
            'id': p.id,
            'code': p.product_code,
            'name': p.display_name,
            'price': float(p.selling_price),
            'stock': p.quantity,
            'sku': p.sku_value or '',
        } for p in products
    ], cls=DjangoJSONEncoder)
    
    # ============================================
    # COMPANIES FOR DROPDOWN
    # All active companies (this is system-wide)
    # ============================================
    companies = CreditCompany.objects.filter(is_active=True)
    
    # ============================================
    # CUSTOMERS FOR DROPDOWN - FIXED: Only customers with NO credit transactions
    # Customers this user has created/dealt with but haven't taken any credit
    # ============================================
    # Get IDs of customers who already have ANY credit transaction
    customers_with_credit = CreditTransaction.objects.values_list('customer_id', flat=True).distinct()
    
    # Show customers who:
    # 1. Were created by this user (transactions__dealer=current_user) OR
    # 2. Are active
    # 3. Have NO credit transactions (exclude customers_with_credit)
    customers = CreditCustomer.objects.filter(
        Q(transactions__dealer=current_user) | Q(created_by=current_user),  # Customers this user has dealt with or created
        is_active=True
    ).exclude(
        id__in=customers_with_credit  # Exclude customers who already have credit
    ).distinct().order_by('-created_at')[:100]
    
    # ============================================
    # STATS CARD 1: My Available Stock Count
    # Products owned by this user that are available for credit
    # ============================================
    total_products = products.count()
    
    # ============================================
    # STATS CARD 2: My Daily Sales Count
    # Sales made by this user today
    # ============================================
    daily_sales = CreditTransaction.objects.filter(
        dealer=current_user,
        transaction_date__date=today
    ).count()
    
    # ============================================
    # STATS CARD 3: My Monthly Sales Count
    # Sales made by this user in last 30 days
    # ============================================
    monthly_sales = CreditTransaction.objects.filter(
        dealer=current_user,
        transaction_date__date__gte=thirty_days_ago
    ).count()
    
    # ============================================
    # STATS CARD 4: My Customers
    # Customers this user has dealt with
    # ============================================
    total_customers = CreditCustomer.objects.filter(
        transactions__dealer=current_user,
        is_active=True
    ).distinct().count()
    
    # ============================================
    # CREDIT OVERVIEW STATS
    # Only transactions created by this user
    # ============================================
    total_credit = CreditTransaction.objects.filter(
        dealer=current_user
    ).aggregate(
        total=Sum('ceiling_price')
    )['total'] or 0
    
    total_paid = CreditTransaction.objects.filter(
        dealer=current_user,
        payment_status='paid'
    ).aggregate(total=Sum('ceiling_price'))['total'] or 0
    
    total_pending = CreditTransaction.objects.filter(
        dealer=current_user,
        payment_status='pending'
    ).aggregate(total=Sum('ceiling_price'))['total'] or 0
    
    total_partial = CreditTransaction.objects.filter(
        dealer=current_user,
        payment_status='partial'
    ).aggregate(total=Sum('ceiling_price'))['total'] or 0
    
    # ============================================
    # CUSTOMER STATS
    # Customers with active credit from this user
    # ============================================
    active_credit_customers = CreditCustomer.objects.filter(
        transactions__dealer=current_user,
        transactions__payment_status='pending'
    ).distinct().count()
    
    # ============================================
    # TODAY'S CREDIT TRANSACTIONS
    # Transactions by this user today
    # ============================================
    today_credit = CreditTransaction.objects.filter(
        dealer=current_user,
        transaction_date__date=today
    ).aggregate(
        total=Sum('ceiling_price'),
        count=Count('id')
    )
    
    # ============================================
    # MONTHLY CREDIT TRANSACTIONS
    # Transactions by this user in last 30 days
    # ============================================
    month_credit = CreditTransaction.objects.filter(
        dealer=current_user,
        transaction_date__date__gte=thirty_days_ago
    ).aggregate(
        total=Sum('ceiling_price'),
        count=Count('id')
    )
    
    # ============================================
    # RECENT CREDIT TRANSACTIONS
    # Recent transactions by this user
    # ============================================
    recent_credits = CreditTransaction.objects.filter(
        dealer=current_user
    ).select_related(
        'customer', 'credit_company'
    ).order_by('-transaction_date')[:15]
    
    # ============================================
    # CREDIT BY COMPANY
    # Only companies this user has transacted with
    # ============================================
    credit_by_company = CreditCompany.objects.filter(
        transactions__dealer=current_user
    ).annotate(
        total_credit=Sum('transactions__ceiling_price', filter=Q(transactions__dealer=current_user)),
        active_transactions=Count('transactions', filter=Q(transactions__dealer=current_user, transactions__payment_status='pending')),
        paid_transactions=Count('transactions', filter=Q(transactions__dealer=current_user, transactions__payment_status='paid')),
        total_customers=Count('transactions__customer', filter=Q(transactions__dealer=current_user), distinct=True)
    ).order_by('-total_credit')[:5]
    
    # ============================================
    # CREDIT TRANSACTIONS BY STATUS
    # Only transactions by this user
    # ============================================
    status_counts = CreditTransaction.objects.filter(
        dealer=current_user
    ).values('payment_status').annotate(
        count=Count('id'),
        total=Sum('ceiling_price')
    ).order_by('payment_status')
    
    # ============================================
    # TOP CUSTOMERS BY CREDIT AMOUNT
    # Only customers this user has dealt with
    # ============================================
    top_customers = CreditCustomer.objects.filter(
        transactions__dealer=current_user
    ).annotate(
        total_credit=Sum('transactions__ceiling_price', filter=Q(transactions__dealer=current_user)),
        transaction_count=Count('transactions', filter=Q(transactions__dealer=current_user)),
        pending_balance=Sum('transactions__ceiling_price', 
                           filter=Q(transactions__dealer=current_user, 
                                   transactions__payment_status='pending'))
    ).filter(transaction_count__gt=0).order_by('-total_credit')[:10]
    
    # ============================================
    # PRODUCTS AVAILABLE FOR CREDIT
    # Only products owned by this user that are available
    # ============================================
    available_products = products.count()
    
    context = {
        # Stats Card Values - All filtered by current user
        'total_products': total_products,
        'daily_sales': daily_sales,
        'monthly_sales': monthly_sales,
        'total_customers': total_customers,
        
        # Credit Overview - All filtered by current user
        'total_credit': total_credit,
        'total_paid': total_paid,
        'total_pending': total_pending,
        'total_partial': total_partial,
        'active_credit_customers': active_credit_customers,
        'available_products': available_products,
        
        # Credit Transactions - All filtered by current user
        'today_credit': today_credit,
        'month_credit': month_credit,
        'recent_credits': recent_credits,
        
        # Analytics - All filtered by current user
        'credit_by_company': credit_by_company,
        'status_counts': status_counts,
        'top_customers': top_customers,
        
        # Form Data - Filtered appropriately
        'products': products,
        'products_json': products_json,
        'companies': companies,
        'customers': customers,
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
# M-PESA AGENT DASHBOARD
# ============================================
# ============================================
# M-PESA AGENT DASHBOARD
# ============================================
@login_required
@dashboard_for_role('M-Pesa Agent')
def mpesa_agent_dashboard(request):
    """Dashboard for M-Pesa Agent - role-based view"""
    from shops.models import DailyShopReport, ShopBranch
    from django.db.models import Sum
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
    
    # For superusers - show ALL data across ALL shops
    if request.user.is_superuser:
        # Get all reports (no shop filter)
        all_reports = DailyShopReport.objects.all()
        
        # Weekly transactions (all shops)
        weekly_transactions = all_reports.filter(
            report_date__gte=week_ago,
            report_date__lte=today
        ).aggregate(total=Sum('shop_sales'))['total'] or 0
        
        # Monthly transactions (all shops)
        monthly_transactions = all_reports.filter(
            report_date__gte=month_ago,
            report_date__lte=today
        ).aggregate(total=Sum('shop_sales'))['total'] or 0
        
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
        ).aggregate(total=Sum('shop_sales'))['total'] or 0
        
    else:
        # For regular users - show only their assigned shop data
        if assigned_shop:
            reports = DailyShopReport.objects.filter(shop=assigned_shop)
            
            # Weekly transactions
            weekly_transactions = reports.filter(
                report_date__gte=week_ago,
                report_date__lte=today,
                submitted_by=request.user
            ).aggregate(total=Sum('shop_sales'))['total'] or 0
            
            # Monthly transactions
            monthly_transactions = reports.filter(
                report_date__gte=month_ago,
                report_date__lte=today,
                submitted_by=request.user
            ).aggregate(total=Sum('shop_sales'))['total'] or 0
            
            # Monthly expenses
            monthly_expenses = reports.filter(
                report_date__gte=month_ago,
                report_date__lte=today,
                submitted_by=request.user
            ).aggregate(total=Sum('total_expenses'))['total'] or 0
            
            # Total reports
            total_reports = reports.filter(submitted_by=request.user).count()
    
    context = {
        # Common data
        'assigned_shop': assigned_shop,
        'today': today,
        'weekly_transactions': int(weekly_transactions),
        'monthly_transactions': int(monthly_transactions),
        'monthly_expenses': float(monthly_expenses),
        'total_reports': total_reports,
        
        # Superuser specific data
        'total_shops': total_shops,
        'reports_today': reports_today,
        'total_transactions_today': int(total_transactions_today),
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









@staff_member_required
def user_list(request):
    """View to list all users in the system"""
    users = User.objects.all().order_by('-date_joined')
    return render(request, 'staff/users/list.html', {
        'users': users,
        'total_users': users.count(),
        'active_users': users.filter(is_active=True).count(),
        'staff_users': users.filter(is_staff=True).count(),
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









# ====================================
# PUBLIC APPLICATION FORM
# ====================================
def application_form(request):
    """Public form for staff applications"""
    if request.method == 'POST':
        try:
            # Check if this is an AJAX request
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            
            # Get form data
            first_name = request.POST.get('first_name')
            last_name = request.POST.get('last_name')
            email = request.POST.get('email')
            phone = request.POST.get('phone')
            id_number = request.POST.get('id_number')
            address = request.POST.get('address', '')
            position = request.POST.get('position')
            experience = request.POST.get('experience', '')
            terms_accepted = request.POST.get('terms_accepted') == 'on'
            privacy_accepted = request.POST.get('privacy_accepted') == 'on'
            
            # Validate required fields
            if not all([first_name, last_name, email, phone, id_number, position]):
                error_msg = 'Please fill in all required fields.'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_msg})
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            if not terms_accepted or not privacy_accepted:
                error_msg = 'You must accept the terms and privacy policy.'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_msg})
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            # ============================================
            # CHECK 1: EMAIL ALREADY EXISTS IN USER TABLE (ALREADY APPROVED STAFF)
            # ============================================
            if User.objects.filter(email=email).exists():
                existing_user = User.objects.get(email=email)
                error_msg = f'❌ An account with email {email} already exists in the system.\n'
                error_msg += f'This email is registered to: {existing_user.get_full_name() or existing_user.username}\n'
                error_msg += 'Please use a different email address or contact the administrator if this is an error.'
                
                if is_ajax:
                    return JsonResponse({
                        'success': False, 
                        'error': error_msg,
                        'existing_user': True,
                        'existing_name': existing_user.get_full_name() or existing_user.username,
                        'error_type': 'user_exists'
                    })
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            # ============================================
            # CHECK 2: PHONE NUMBER ALREADY EXISTS IN USER TABLE
            # ============================================
            # Clean phone number (remove non-digits)
            import re
            clean_phone = re.sub(r'\D', '', phone)
            
            if User.objects.filter(username=clean_phone).exists():
                existing_user = User.objects.get(username=clean_phone)
                error_msg = f'❌ Phone number {phone} is already registered in the system.\n'
                error_msg += f'Registered to: {existing_user.get_full_name() or existing_user.username}\n'
                error_msg += 'Please use a different phone number or contact the administrator.'
                
                if is_ajax:
                    return JsonResponse({
                        'success': False, 
                        'error': error_msg,
                        'error_type': 'phone_exists'
                    })
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            # ============================================
            # CHECK 3: ID NUMBER ALREADY EXISTS IN USER TABLE (via Staff profile)
            # ============================================
            if Staff.objects.filter(id_number=id_number).exists():
                existing_staff = Staff.objects.get(id_number=id_number)
                error_msg = f'❌ ID Number {id_number} is already registered in the system.\n'
                error_msg += f'Registered to: {existing_staff.user.get_full_name() or existing_staff.user.username}\n'
                error_msg += 'Please use your correct ID number or contact the administrator.'
                
                if is_ajax:
                    return JsonResponse({
                        'success': False, 
                        'error': error_msg,
                        'error_type': 'id_exists'
                    })
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            # ============================================
            # CHECK 4: EMAIL ALREADY EXISTS IN PENDING/UNDER_REVIEW APPLICATIONS
            # ============================================
            pending_app = StaffApplication.objects.filter(
                email=email, 
                status__in=['pending', 'under_review']
            ).first()
            
            if pending_app:
                error_msg = f'❌ An application with email {email} is already pending review.\n'
                error_msg += f'Submitted on: {pending_app.application_date.strftime("%Y-%m-%d")}\n'
                error_msg += 'Please wait for review or contact the administrator.'
                
                if is_ajax:
                    return JsonResponse({
                        'success': False, 
                        'error': error_msg,
                        'pending': True,
                        'submission_date': pending_app.application_date.strftime("%Y-%m-%d"),
                        'error_type': 'pending_application'
                    })
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            # ============================================
            # CHECK 5: EMAIL ALREADY EXISTS IN REJECTED APPLICATIONS
            # ============================================
            rejected_app = StaffApplication.objects.filter(
                email=email, 
                status='rejected'
            ).first()
            
            if rejected_app:
                error_msg = f'❌ An application with email {email} was previously rejected.\n'
                error_msg += f'Rejection date: {rejected_app.review_date.strftime("%Y-%m-%d") if rejected_app.review_date else "Unknown"}\n'
                if rejected_app.review_notes:
                    error_msg += f'Reason: {rejected_app.review_notes}\n'
                error_msg += 'If you believe this is an error, please contact the administrator.'
                
                if is_ajax:
                    return JsonResponse({
                        'success': False, 
                        'error': error_msg,
                        'rejected': True,
                        'rejection_date': rejected_app.review_date.strftime("%Y-%m-%d") if rejected_app.review_date else None,
                        'rejection_reason': rejected_app.review_notes,
                        'error_type': 'rejected_application'
                    })
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            # ============================================
            # CHECK 6: ID NUMBER ALREADY EXISTS IN APPLICATIONS
            # ============================================
            existing_id_app = StaffApplication.objects.filter(id_number=id_number).first()
            if existing_id_app:
                status_msg = {
                    'pending': 'pending review',
                    'under_review': 'under review',
                    'approved': 'already approved',
                    'rejected': 'previously rejected'
                }.get(existing_id_app.status, 'exists')
                
                error_msg = f'❌ An application with ID number {id_number} already exists.\n'
                error_msg += f'Status: {status_msg}\n'
                error_msg += f'Submitted on: {existing_id_app.application_date.strftime("%Y-%m-%d")}\n'
                error_msg += 'Please contact the administrator for assistance.'
                
                if is_ajax:
                    return JsonResponse({
                        'success': False, 
                        'error': error_msg,
                        'existing': True,
                        'existing_name': existing_id_app.full_name(),
                        'status': existing_id_app.status,
                        'error_type': 'id_in_application'
                    })
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            # ============================================
            # CHECK 7: PHONE NUMBER ALREADY EXISTS IN PENDING APPLICATIONS
            # ============================================
            pending_phone = StaffApplication.objects.filter(
                phone=phone, 
                status__in=['pending', 'under_review']
            ).first()
            
            if pending_phone:
                error_msg = f'❌ Phone number {phone} already has a pending application.\n'
                error_msg += f'Submitted on: {pending_phone.application_date.strftime("%Y-%m-%d")}\n'
                error_msg += 'Please wait for review or contact the administrator.'
                
                if is_ajax:
                    return JsonResponse({
                        'success': False, 
                        'error': error_msg,
                        'error_type': 'phone_pending'
                    })
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            # ============================================
            # CHECK 8: PHONE NUMBER ALREADY EXISTS IN REJECTED APPLICATIONS
            # ============================================
            rejected_phone = StaffApplication.objects.filter(
                phone=phone, 
                status='rejected'
            ).first()
            
            if rejected_phone:
                error_msg = f'❌ Phone number {phone} was used in a previously rejected application.\n'
                error_msg += f'Rejection date: {rejected_phone.review_date.strftime("%Y-%m-%d") if rejected_phone.review_date else "Unknown"}\n'
                error_msg += 'Please contact the administrator if you believe this is an error.'
                
                if is_ajax:
                    return JsonResponse({
                        'success': False, 
                        'error': error_msg,
                        'error_type': 'phone_rejected'
                    })
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            # ============================================
            # HANDLE FILE UPLOADS
            # ============================================
            passport_photo = request.FILES.get('passport_photo')
            id_front = request.FILES.get('id_front')
            id_back = request.FILES.get('id_back')
            
            if not all([passport_photo, id_front, id_back]):
                error_msg = 'Please upload all required documents.'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_msg})
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            # Get client IP and user agent
            ip_address = request.META.get('REMOTE_ADDR')
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            
            # Create application
            application = StaffApplication.objects.create(
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone,
                id_number=id_number,
                address=address,
                position=position,
                experience=experience,
                passport_photo=passport_photo,
                id_front=id_front,
                id_back=id_back,
                terms_accepted=terms_accepted,
                privacy_accepted=privacy_accepted,
                ip_address=ip_address,
                user_agent=user_agent,
                status='pending'
            )
            
            logger.info(f"New staff application created: {application.full_name()} (ID: {application.id})")
            
            # ============================================
            # SEND ADMIN NOTIFICATION (commented out)
            # ============================================
            """
            try:
                from utils.notifications import AdminNotifier
                AdminNotifier.notify_new_application(application)
                logger.info(f"Admin notification sent for application #{application.id}")
            except ImportError:
                logger.warning("AdminNotifier not available - skipping notification")
            except Exception as e:
                logger.error(f"Failed to send admin notification: {str(e)}")
                # Don't fail the application if notification fails
            """
            
            # Return response based on request type
            if is_ajax:
                return JsonResponse({
                    'success': True,
                    'message': 'Your application has been submitted successfully!',
                    'application_id': application.id,
                    'data': {
                        'name': application.full_name(),
                        'position': application.get_position_display(),
                        'application_date': application.application_date.strftime('%Y-%m-%d %H:%M')
                    }
                })
            else:
                messages.success(request, 'Your application has been submitted successfully!')
                return redirect('staff:application_success')
            
        except Exception as e:
            logger.error(f"Error creating staff application: {str(e)}")
            error_msg = f'Error submitting application: {str(e)}'
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_msg})
            
            messages.error(request, error_msg)
            return render(request, 'staff/apply.html', {
                'positions': StaffApplication.POSITION_CHOICES
            })
    
    # GET request - show form
    context = {
        'positions': StaffApplication.POSITION_CHOICES,
    }
    return render(request, 'staff/apply.html', context)







# ====================================
# APPLICATION SUCCESS VIEW
# ====================================
def application_success(request):
    """Application success page"""
    return render(request, 'staff/success.html')





# ====================================
# ADMIN LIST VIEW
# ====================================
@login_required
def application_list(request):
    """List all staff applications"""
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
    
    context = {
        'applications': page_obj,
        'status_choices': StaffApplication.STATUS_CHOICES,
        'position_choices': StaffApplication.POSITION_CHOICES,
    }
    return render(request, 'staff/list.html', context)


# ====================================
# DETAIL VIEW
# ====================================
@login_required
def application_detail(request, pk):
    """View application details"""
    application = get_object_or_404(StaffApplication, pk=pk)
    
    context = {
        'application': application,
    }
    return render(request, 'staff/detail.html', context)


# ====================================
# EDIT VIEW
# ====================================
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


# ====================================
# DELETE VIEW
# ====================================
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
    """Approve an application and create user account with proper group"""
    application = get_object_or_404(StaffApplication, pk=pk)
    
    if request.method == 'POST':
        try:
            # Get role/group from form
            group_id = request.POST.get('group')
            notes = request.POST.get('review_notes', '')
            
            # ============================================
            # USE PHONE NUMBER AS USERNAME
            # ============================================
            username = application.phone
            
            # Remove any non-digit characters from phone (keep only numbers)
            import re
            username = re.sub(r'\D', '', username)
            
            # Ensure username is not empty
            if not username:
                # Fallback to email if phone is empty
                username = application.email.split('@')[0]
            
            # Check if username exists, if so add suffix
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
            
            # ============================================
            # USE ID NUMBER AS PASSWORD
            # ============================================
            password = application.id_number
            
            # Remove any spaces from password
            password = password.strip() if password else "Fsl@12345"
            
            # Ensure password meets minimum requirements (at least 8 chars)
            if len(password) < 8:
                # Pad with zeros or add default if too short
                password = password.zfill(8)  # Pads with zeros to make 8 chars
            
            # Create user account
            user = User.objects.create_user(
                username=username,
                email=application.email,
                password=password,
                first_name=application.first_name,
                last_name=application.last_name,
                is_active=True,
                is_staff=True  # Give staff access
            )
            
            # ============================================
            # CREATE USER PROFILE FOR PASSWORD TRACKING
            # ============================================
            # Create profile with password_changed=False (first login)
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.password_changed = False
            profile.first_login = True
            profile.save()
            
            logger.info(f"User profile created for {user.username} - First login tracking enabled")
            
            # ============================================
            # CREATE/UPDATE STAFF PROFILE WITH AUTO-VERIFICATION
            # ============================================
            from staff.models import Staff
            
            # USE APPLICANT'S ID NUMBER AS STAFF ID
            staff_id = application.id_number
            
            # Remove any spaces or special characters
            staff_id = staff_id.strip().replace(' ', '')
            
            # Check if staff_id already exists, if so add suffix
            original_staff_id = staff_id
            counter = 1
            while Staff.objects.filter(staff_id=staff_id).exists():
                staff_id = f"{original_staff_id}_{counter}"
                counter += 1
            
            # Get position value
            position = application.position
            
            # Check if staff profile already exists (created by signal)
            try:
                staff_profile = Staff.objects.get(user=user)
                # If exists, update it with auto-verification
                staff_profile.staff_id = staff_id
                staff_profile.position = position
                staff_profile.is_identity_verified = True
                staff_profile.verified_at = timezone.now()
                staff_profile.verified_by = request.user
                staff_profile.verification_notes = f"Auto-verified during application approval. Original notes: {notes}"
                staff_profile.passport_photo = application.passport_photo
                staff_profile.id_front = application.id_front
                staff_profile.id_back = application.id_back
                staff_profile.save()
                
                logger.info(f"Existing staff profile updated for {user.username} with staff ID: {staff_id}")
                
            except Staff.DoesNotExist:
                # Create new staff profile
                staff_profile = Staff.objects.create(
                    user=user,
                    staff_id=staff_id,
                    id_number=application.id_number, 
                    position=position,
                    is_identity_verified=True,  # AUTO-VERIFY!
                    verified_at=timezone.now(),
                    verified_by=request.user,
                    verification_notes=f"Auto-verified during application approval. Original notes: {notes}",
                    # Copy documents from application to staff profile
                    passport_photo=application.passport_photo,
                    id_front=application.id_front,
                    id_back=application.id_back,
                )
                
                logger.info(f"New staff profile created for {user.username} with staff ID: {staff_id}")
            
            # ============================================
            # ASSIGN TO GROUP
            # ============================================
            group_name = None
            
            # Assign to selected group
            if group_id:
                try:
                    group = Group.objects.get(id=group_id)
                    user.groups.add(group)
                    group_name = group.name
                        
                except Group.DoesNotExist:
                    logger.warning(f"Group with id {group_id} does not exist")
            
            # Update application status
            application.status = 'approved'
            application.reviewed_by = request.user
            application.review_date = timezone.now()
            application.review_notes = notes
            application.created_user = user
            application.save()
            
            messages.success(
                request, 
                f'✅ Application for {application.full_name()} has been approved.<br>'
                f'👤 User account created with group: <strong>{group_name if group_name else "No group"}</strong><br>'
                f'📧 Username: <strong>{username}</strong> (Phone number)<br>'
                f'🔑 Password: <strong>{password}</strong> (ID number)<br>'
                f'🆔 Staff ID: <strong>{staff_id}</strong> (Using ID number from application)<br>'
                f'✅ Staff profile auto-verified! User can login and access dashboard immediately.<br>'
                f'⚠️ <span class="text-warning">User will be required to change password on first login.</span>'
            )
            return redirect('staff:application_detail', pk=application.pk)
            
        except Exception as e:
            logger.error(f"Error approving application: {str(e)}", exc_info=True)
            messages.error(request, f'Error approving application: {str(e)}')
            return redirect('staff:application_detail', pk=application.pk)
    
    # GET request - show approval form with group selection
    groups = Group.objects.all().order_by('name')
    
    context = {
        'application': application,
        'groups': groups,
        'first_login_note': True,
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


#def send_revert_notification(application, user_deleted, username):
#    """Send notification email when application is reverted"""
#    try:
#        subject = f'FieldMax - Your Staff Application Status Update'
        
#        context = {
#            'name': application.full_name(),
#            'application_id': application.id,
#            'position': application.get_position_display(),
#            'user_deleted': user_deleted,
#            'username': username,
#            'reverted_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
#            'support_email': settings.DEFAULT_FROM_EMAIL,
#        }
#        
#        html_message = render_to_string('staff/email/revert_notification.html', context)
#        plain_message = f"""
#        Dear {application.full_name()},
#        
#        Your staff application (#{application.id}) status has been updated.
#        
#        Status: PENDING (Reverted from Approved)
#        Position: {application.get_position_display()}
#        Date: {timezone.now().strftime('%Y-%m-%d %H:%M')}
#        
#        {'Your user account access has been removed.' if user_deleted else ''}
#        
#        If you have any questions, please contact the HR department.
#        
#        Regards,
#        FieldMax HR Team
#        """
#        
#        send_mail(
#            subject,
#            plain_message,
#            settings.DEFAULT_FROM_EMAIL,
#            [application.email],
#            html_message=html_message,
#            fail_silently=True,
#        )
        
#    except Exception as e:
#        logger.error(f"Failed to send revert notification email to {application.email}: {str(e)}")





# ====================================
# REJECT VIEW
# ====================================
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
            







            # ============================================
            # SEND ADMIN NOTIFICATION
            # ============================================
            """
            try:
                from utils.notifications import AdminNotifier
                # Notify admin about rejection
                AdminNotifier.notify_application_processed(
                    application=application,
                    action='rejected',
                    processed_by=request.user
                )
                logger.info(f"Admin notification sent for rejected application #{application.id}")
            except ImportError:
                logger.warning("AdminNotifier not available - skipping notification")
            except Exception as e:
                logger.error(f"Failed to send admin notification: {str(e)}")
            """




            
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









# ====================================
# DOCUMENTS VIEW
# ====================================
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












@login_required
def notifications_page(request):
    """Display all notifications for the user"""
    
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
    # RECENT ACTIVITY
    # ============================================
    from inventory.models import StockEntry
    
    recent_activity = StockEntry.objects.select_related(
        'product', 'created_by'
    ).filter(
        created_at__gte=last_week
    ).order_by('-created_at')[:20]
    
    # ============================================
    # LOW STOCK PRODUCTS
    # ============================================
    low_stock_products = Product.objects.filter(
        Q(category__item_type='bulk', quantity__lte=5, quantity__gt=0) |
        Q(status='lowstock')
    ).select_related('category')[:10]
    
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
        
        # Pending staff applications - FIXED: Use correct field names
        pending_applications = StaffApplication.objects.filter(
            status='pending'
        ).order_by('-application_date')[:10]  # Using application_date field
    
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
        'pending_verifications': pending_verifications.count(),
        'pending_applications': pending_applications.count(),
    }
    
    context = {
        'stock_alerts': stock_alerts,
        'pending_returns': pending_returns,
        'verified_returns': verified_returns,
        'recent_activity': recent_activity,
        'low_stock_products': low_stock_products,
        'pending_verifications': pending_verifications,
        'pending_applications': pending_applications,
        'notification_counts': notification_counts,
        'now': now,
        'last_24h': last_24h,
        'last_week': last_week,
    }
    
    return render(request, 'staff/notifications_page.html', context)








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
    """Edit user details"""
    user_to_edit = get_object_or_404(User, pk=pk)
    
    # Get or create user profile
    try:
        profile = user_to_edit.profile
    except:
        profile = UserProfile.objects.create(user=user_to_edit)
    
    if request.method == 'POST':
        try:
            # Update basic user fields
            user_to_edit.first_name = request.POST.get('first_name', '').strip()
            user_to_edit.last_name = request.POST.get('last_name', '').strip()
            user_to_edit.email = request.POST.get('email', '').strip()
            
            # Update username if provided and changed
            new_username = request.POST.get('username', '').strip()
            if new_username and new_username != user_to_edit.username:
                # Check if username already exists
                if User.objects.filter(username=new_username).exclude(id=user_to_edit.id).exists():
                    messages.error(request, f'Username "{new_username}" is already taken.')
                    return render(request, 'staff/users/edit.html', {
                        'user': user_to_edit,
                        'profile': profile,
                        'groups': Group.objects.all().order_by('name'),
                        'selected_groups': user_to_edit.groups.values_list('id', flat=True)
                    })
                user_to_edit.username = new_username
            
            # Update user type
            is_staff = request.POST.get('is_staff') == 'on'
            is_superuser = request.POST.get('is_superuser') == 'on'
            
            # Prevent removing superuser status from last superuser
            if user_to_edit.is_superuser and not is_superuser:
                superuser_count = User.objects.filter(is_superuser=True).count()
                if superuser_count <= 1:
                    messages.error(request, 'Cannot remove superuser status from the last superuser.')
                    return render(request, 'staff/users/edit.html', {
                        'user': user_to_edit,
                        'profile': profile,
                        'groups': Group.objects.all().order_by('name'),
                        'selected_groups': user_to_edit.groups.values_list('id', flat=True)
                    })
            
            user_to_edit.is_staff = is_staff
            user_to_edit.is_superuser = is_superuser
            user_to_edit.is_active = request.POST.get('is_active') == 'on'
            
            # Update profile fields
            profile.phone_number = request.POST.get('phone_number', '').strip()
            profile.address = request.POST.get('address', '').strip()
            profile.city = request.POST.get('city', '').strip()
            profile.country = request.POST.get('country', '').strip()
            
            # Save user and profile
            user_to_edit.save()
            profile.save()
            
            # Update groups
            selected_groups = request.POST.getlist('groups')
            user_to_edit.groups.clear()
            for group_id in selected_groups:
                try:
                    group = Group.objects.get(id=group_id)
                    user_to_edit.groups.add(group)
                except Group.DoesNotExist:
                    pass
            
            logger.info(f"User {user_to_edit.username} edited by {request.user.username}")
            messages.success(request, f'User {user_to_edit.username} has been updated successfully.')
            
            return redirect('staff:user_detail', pk=user_to_edit.id)
            
        except Exception as e:
            logger.error(f"Error editing user {user_to_edit.username}: {str(e)}")
            messages.error(request, f'Error updating user: {str(e)}')
            return render(request, 'staff/users/edit.html', {
                'user': user_to_edit,
                'profile': profile,
                'groups': Group.objects.all().order_by('name'),
                'selected_groups': user_to_edit.groups.values_list('id', flat=True)
            })
    
    # GET request - show edit form
    context = {
        'user': user_to_edit,
        'profile': profile,
        'groups': Group.objects.all().order_by('name'),
        'selected_groups': user_to_edit.groups.values_list('id', flat=True),
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




def powered_by_page(request):
    """Page showing information about FieldMax"""
    return render(request, 'staff/powered_by.html')