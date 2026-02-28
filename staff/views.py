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
import logging
import os
from decimal import Decimal
from .models import Staff 
from .utils.email_verification import send_itp_verification_email, generate_verification_code 
import threading






logger = logging.getLogger(__name__)



User = get_user_model()






# ============================================
# Async Email Helper
# ============================================
def send_email_async(subject, message, recipient_list, html_message=None):
    """Send email in background thread to prevent timeout"""
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipient_list,
            html_message=html_message,
            fail_silently=True,
        )
        logger.info(f"Background email sent to {recipient_list}")
    except Exception as e:
        logger.error(f"Background email error: {e}")






@login_required
def otp_verify(request):
    """OTP verification page"""
    # If user doesn't require OTP, redirect to dashboard
    if not requires_otp(request.user):
        return redirect('staff:staff_dashboard')
    
    # Get intended dashboard URL from session
    intended_url = request.session.get('intended_dashboard_url', 'staff:staff_dashboard')
    
    if request.method == 'POST':
        otp_code = request.POST.get('otp_code', '').strip()
        
        # Verify OTP
        success, message = OTPVerification.verify_otp(
            request.user, 
            otp_code, 
            purpose='dashboard_access'
        )
        
        if success:
            # Clear the OTP requirement from session
            request.session['otp_verified'] = True
            request.session['otp_verified_at'] = timezone.now().isoformat()
            
            messages.success(request, message)
            return redirect(intended_url)
        else:
            messages.error(request, message)
    
    # Generate new OTP if needed - WITH ASYNC EMAIL
    if request.method == 'GET' or 'resend' in request.GET:
        otp = OTPVerification.generate_otp(request.user, purpose='dashboard_access')
        
        # Prepare email content
        user_name = request.user.get_full_name() or request.user.username
        subject = 'FieldMax - Your Dashboard Access Code'
        message = f"""
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
                    <p><small>If you did not request this code, please contact your system administrator.</small></p>
                </div>
                <div class="footer">
                    <p>&copy; {timezone.now().year} FieldMax. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Send email in background thread
        thread = threading.Thread(
            target=send_email_async,
            args=(subject, message, [request.user.email]),
            kwargs={'html_message': html_message}
        )
        thread.daemon = True
        thread.start()
        
        messages.info(request, f'A 6-digit OTP has been sent to your email: {request.user.email}')
    
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
        subject = 'FieldMax - Your Dashboard Access Code'
        message = f"""
        Dear {user_name},
        
        Your One-Time Password (OTP) for dashboard access is: {otp.otp_code}
        
        This code will expire in 5 minutes.
        
        Regards,
        FieldMax Security Team
        """
        
        # Send email in background thread (NON-BLOCKING)
        thread = threading.Thread(
            target=send_email_async,
            args=(subject, message, [request.user.email])
        )
        thread.daemon = True
        thread.start()
        
        return JsonResponse({'success': True, 'message': 'OTP resent successfully'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})










def custom_logout(request):
    """Custom logout view that handles POST requests"""
    logout(request)
    messages.success(request, "You have been successfully logged out.")
    return redirect('home') 



# ============================================
# MAIN DASHBOARD REDIRECT (Based on Groups)
# ============================================
@login_required
def staff_dashboard(request):
    """Main dashboard that redirects to role-specific dashboard"""
    
    # ============================================
    # STEP 1: Check if user has staff profile
    # ============================================
    try:
        staff_profile = request.user.staff_profile
    except AttributeError:
        # User doesn't have a staff profile
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
            # Documents submitted, pending admin approval
            messages.info(request, "Your identity verification is pending admin approval. You'll be notified once verified.")
            return render(request, 'staff/pending_approval.html', {
                'staff_profile': staff_profile,
                'message': 'Your documents are under review. This usually takes 24-48 hours.'
            })
        
        # Check if verification code exists and is not expired (24 hours)
        from django.utils import timezone
        from datetime import timedelta
        
        if staff_profile.verification_code and staff_profile.verification_sent_at:
            # Check if verification is expired (24 hours)
            time_diff = timezone.now() - staff_profile.verification_sent_at
            is_expired = time_diff > timedelta(hours=24)
            
            if is_expired:
                # Generate new verification code
                staff_profile.verification_code = generate_verification_code()
                staff_profile.verification_sent_at = timezone.now()
                staff_profile.verification_attempts = 0
                staff_profile.save(update_fields=['verification_code', 'verification_sent_at', 'verification_attempts'])
                
                # Send new verification email
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
            # First time - generate and send verification code
            from .utils.email_verification import send_itp_verification_email
            from django.utils import timezone
            
            staff_profile.verification_code = generate_verification_code()
            staff_profile.verification_sent_at = timezone.now()
            staff_profile.verification_attempts = 0
            staff_profile.save(update_fields=['verification_code', 'verification_sent_at', 'verification_attempts'])
            
            # Send verification email
            send_itp_verification_email(staff_profile, request)
            messages.info(request, "Welcome! Please verify your identity to access the dashboard. A 6-digit verification code has been sent to your email.")
        
        # Store intended URL and redirect to verification page
        request.session['intended_dashboard_url'] = request.path
        return redirect('staff:verify_identity', staff_id=staff_profile.id)
    
    # ============================================
    # STEP 4: Superuser goes to admin dashboard
    # ============================================
    if request.user.is_superuser:
        intended_url = 'staff:admin_dashboard'
    else:
        # Get user's groups
        user_groups = request.user.groups.values_list('name', flat=True)
        
        # Define group to dashboard mapping
        dashboard_routes = {
            'Administrator': 'staff:admin_dashboard',
            'Sales Manager': 'staff:sales_manager_dashboard',
            'Sales Agent': 'staff:sales_officer_dashboard',
            'Cashier': 'staff:cashier_dashboard',
            'Store Manager': 'staff:store_manager_dashboard',
            'Credit Manager': 'staff:credit_manager_dashboard',
            'Credit Officer': 'staff:credit_officer_dashboard',
            'Customer Service': 'staff:customer_service_dashboard',
            'Supervisor': 'staff:supervisor_dashboard',
            'Security Officer': 'staff:security_dashboard',
            'Cleaner': 'staff:cleaner_dashboard',
            'Assistant Manager': 'staff:supervisor_dashboard',
            'Inventory Manager': 'staff:store_manager_dashboard',
        }
        
        # Find matching dashboard
        intended_url = 'staff:staff_stats_dashboard'  # Default
        for group_name, dashboard_url in dashboard_routes.items():
            if group_name in user_groups:
                intended_url = dashboard_url
                break
    
    # ============================================
    # STEP 5: Check if user requires OTP
    # ============================================
    if requires_otp(request.user):
        # Check if already verified in this session
        if not request.session.get('otp_verified'):
            # Store intended URL and redirect to OTP page
            request.session['intended_dashboard_url'] = intended_url
            return redirect('staff:otp_verify')
    
    # ============================================
    # STEP 6: If all checks passed, redirect directly
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
        
        # Send admin notification
        send_verification_admin_notification(staff, request)
        
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
            
            # Send email
            from .utils.email_verification import send_itp_verification_email
            if send_itp_verification_email(staff, request):
                messages.success(request, "✅ New 6-digit verification code sent to your email!")
                return JsonResponse({
                    'success': True,
                    'message': 'Verification code resent successfully'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': 'Failed to send verification email. Please try again.'
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


# ============================================
# Admin verification approval view
# ============================================
@staff_member_required
def admin_verify_staff(request, staff_id):
    """Admin view to verify staff identity"""
    staff = get_object_or_404(Staff, id=staff_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        notes = request.POST.get('notes', '')
        
        if action == 'approve':
            staff.is_identity_verified = True
            staff.verified_at = timezone.now()
            staff.verified_by = request.user
            staff.verification_notes = notes
            staff.save()
            
            # Send approval email to staff
            send_verification_result_email(staff, approved=True, notes=notes)
            
            messages.success(request, f"✅ {staff.user.get_full_name()} has been verified successfully!")
            
        elif action == 'reject':
            staff.is_identity_verified = False
            staff.verified_at = None
            staff.verified_by = request.user
            staff.verification_notes = notes
            staff.verification_submitted_at = None  # Allow resubmission
            staff.save()
            
            # Send rejection email to staff
            send_verification_result_email(staff, approved=False, notes=notes)
            
            messages.warning(request, f"⚠️ Verification rejected for {staff.user.get_full_name()}. Notes: {notes}")
        
        return redirect('admin:staff_staff_changelist')
    
    context = {
        'staff': staff,
    }
    return render(request, 'staff/admin_verify.html', context)


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







#==========================================
# ADMIN DASHBOARD
#==========================================
@login_required
def admin_dashboard(request):
    """Admin dashboard with full system overview"""
    from django.contrib.auth import get_user_model
    from inventory.models import Product, Category
    from sales.models import Sale
    from credit.models import CreditTransaction, CreditCustomer, CreditCompany
    
    User = get_user_model()
    
    # System Overview
    total_users = User.objects.count()
    total_staff = User.objects.filter(is_staff=True).count()
    total_products = Product.objects.count()
    total_categories = Category.objects.count()
    
    # Today's stats
    today = timezone.now().date()
    today_sales = Sale.objects.filter(sale_date__date=today).aggregate(
        total=Sum('total_amount')
    )['total'] or 0
    today_sales_count = Sale.objects.filter(sale_date__date=today).count()
    
    # Overall stats
    total_sales = Sale.objects.aggregate(total=Sum('total_amount'))['total'] or 0
    
    # Credit stats
    total_credit = CreditTransaction.objects.aggregate(
        total=Sum('ceiling_price')
    )['total'] or 0
    
    pending_credit = CreditTransaction.objects.filter(payment_status='pending').count()
    
    # Customer stats
    total_customers = CreditCustomer.objects.count()
    
    # Staff by Position
    staff_by_position = StaffApplication.objects.filter(
        status='approved'
    ).values('position').annotate(
        count=Count('id')
    ).order_by('position')
    
    # Recent Activities
    recent_sales = Sale.objects.order_by('-sale_date')[:10]
    recent_credits = CreditTransaction.objects.select_related('customer').order_by('-transaction_date')[:10]
    recent_users = User.objects.order_by('-date_joined')[:10]
    
    # Chart data (last 7 days)
    labels = []
    sales_data = []
    credit_data = []
    
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        labels.append(date.strftime('%d %b'))
        
        day_sales = Sale.objects.filter(sale_date__date=date).aggregate(
            total=Sum('total_amount')
        )['total'] or 0
        sales_data.append(float(day_sales))
        
        day_credit = CreditTransaction.objects.filter(
            transaction_date__date=date
        ).aggregate(
            total=Sum('ceiling_price')
        )['total'] or 0
        credit_data.append(float(day_credit))
    
    context = {
        'total_users': total_users,
        'total_staff': total_staff,
        'total_products': total_products,
        'total_categories': total_categories,
        'today_sales': today_sales,
        'today_sales_count': today_sales_count,
        'total_sales': total_sales,
        'total_credit': total_credit,
        'pending_credit': pending_credit,
        'total_customers': total_customers,
        'staff_by_position': staff_by_position,
        'recent_sales': recent_sales,
        'recent_credits': recent_credits,
        'recent_users': recent_users,
        'chart_labels': labels,
        'sales_data': sales_data,
        'credit_data': credit_data,
    }
    return render(request, 'staff/dashboards/admin_dashboard.html', context)







# ============================================
# STORE MANAGER DASHBOARD - FIXED WITH STOCK ALERTS
# ============================================
@login_required
def store_manager_dashboard(request):
    """Dashboard for store manager"""
    from inventory.models import Product, Category, StockAlert, StockEntry
    from sales.models import SaleItem
    from django.db.models import Sum, Count, Q, F
    from django.contrib import messages
    from django.utils import timezone
    from datetime import timedelta
    
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
# SALES OFFICER DASHBOARD
# ============================================
@login_required
def sales_officer_dashboard(request):
    """Dashboard for sales officers"""
    from sales.models import Sale, SaleItem
    
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    
    # My Sales Performance
    my_sales_today = Sale.objects.filter(
        seller=request.user,
        sale_date__date=today
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('id')
    )
    
    my_sales_week = Sale.objects.filter(
        seller=request.user,
        sale_date__date__gte=week_ago
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('id')
    )
    
    my_sales_month = Sale.objects.filter(
        seller=request.user,
        sale_date__date__gte=month_ago
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('id')
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
    
    # Daily targets (example)
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
    }
    return render(request, 'staff/dashboards/sales_officer_dashboard.html', context)







# ============================================
# SALES MANAGER DASHBOARD - CORRECTED VERSION
# ============================================
@login_required
def sales_manager_dashboard(request):
    """Dashboard for sales manager - oversees all sales team"""
    from sales.models import Sale, SaleItem
    from django.contrib.auth import get_user_model
    from django.db.models import Sum, Count
    from django.utils import timezone
    from datetime import timedelta
    
    User = get_user_model()
    
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
    
    # Hourly sales data for chart
    hourly_sales = []
    for hour in range(8, 21):  # 8 AM to 8 PM
        hour_sales = Sale.objects.filter(
            sale_date__date=today,
            sale_date__hour=hour
        ).aggregate(
            total=Sum('total_amount'),
            count=Count('sale_id')
        )
        hourly_sales.append({
            'hour': hour,
            'amount': float(hour_sales['total'] or 0),
            'count': hour_sales['count'] or 0,
            'percentage': (float(hour_sales['total'] or 0) / float(team_sales_today['total'] or 1)) * 100
        })
    
    # Chart labels and data
    chart_labels = [f"{h}:00" for h in range(8, 21)]
    chart_data = [s['amount'] for s in hourly_sales]
    
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
        
        # Chart data
        'chart_labels': chart_labels,
        'chart_data': chart_data,
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
def cashier_dashboard(request):
    """Dashboard for cashier desk"""
    from sales.models import Sale
    from django.db.models import F, Count, Sum, Q
    
    today = timezone.now().date()
    
    # Get cart from session - ADD THIS
    cart = request.session.get('sales_cart', [])
    subtotal = sum(item.get('total', 0) for item in cart)
    
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
        
        # Keep existing context
        'today_transactions': today_transactions,
        'recent_transactions': recent_transactions,
    }
    return render(request, 'staff/dashboards/cashier_dashboard.html', context)








# ============================================
# CREDIT MANAGER DASHBOARD
# ============================================

@login_required
def credit_manager_dashboard(request):
    """Dashboard for Credit Manager - oversees all credit operations"""
    
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
def customer_service_dashboard(request):
    """Dashboard for customer service"""
    from credit.models import CreditCustomer, CreditTransaction
    from django.db.models import Count, Q
    
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
# SUPERVISOR DASHBOARD
# ============================================
@login_required
def supervisor_dashboard(request):
    """Dashboard for supervisor - overview of all departments"""
    from sales.models import Sale
    from credit.models import CreditTransaction, CreditCustomer
    from inventory.models import Product
    from django.contrib.auth import get_user_model
    from django.db.models import Sum, Count, Q
    
    User = get_user_model()
    today = timezone.now().date()
    
    # Team Overview
    team_members = StaffApplication.objects.filter(
        status='approved'
    ).count()
    
    team_by_position = StaffApplication.objects.filter(
        status='approved'
    ).values('position').annotate(
        count=Count('id')
    ).order_by('position')
    
    # Today's Performance
    today_sales = Sale.objects.filter(sale_date__date=today).aggregate(
        total=Sum('total_amount'),
        count=Count('sale_id')
    )
    
    today_credit = CreditTransaction.objects.filter(
        transaction_date__date=today
    ).aggregate(
        total=Sum('ceiling_price'),
        count=Count('id')
    )
    
    # Alerts
    low_stock_alerts = Product.objects.filter(quantity__lt=10).count()
    pending_credit = CreditTransaction.objects.filter(payment_status='pending').count()
    
    # Customer stats
    total_customers = CreditCustomer.objects.count()
    new_customers_today = CreditCustomer.objects.filter(
        created_at__date=today
    ).count()
    
    # Recent activities across departments
    recent_sales = Sale.objects.order_by('-sale_date')[:5]
    recent_credits = CreditTransaction.objects.select_related('customer').order_by('-transaction_date')[:5]
    
    context = {
        'team_members': team_members,
        'team_by_position': team_by_position,
        'today_sales': today_sales,
        'today_credit': today_credit,
        'low_stock_alerts': low_stock_alerts,
        'pending_credit': pending_credit,
        'total_customers': total_customers,
        'new_customers_today': new_customers_today,
        'recent_sales': recent_sales,
        'recent_credits': recent_credits,
    }
    return render(request, 'staff/dashboards/supervisor_dashboard.html', context)




# ============================================
# SECURITY OFFICER DASHBOARD
# ============================================
@login_required
def security_dashboard(request):
    """Dashboard for security officer"""
    from inventory.models import Product
    from sales.models import Sale
    
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
# CLEANER DASHBOARD
# ============================================
@login_required
def cleaner_dashboard(request):
    """Dashboard for office cleaner"""
    # Simple dashboard with cleaning schedule, tasks, etc.
    
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
            
            # Check if ID number already exists
            if StaffApplication.objects.filter(id_number=id_number).exists():
                existing_app = StaffApplication.objects.filter(id_number=id_number).first()
                error_msg = f'An application with ID number {id_number} already exists. Please contact support if this is your ID.'
                
                if is_ajax:
                    return JsonResponse({
                        'success': False, 
                        'error': error_msg,
                        'existing': True,
                        'existing_name': existing_app.full_name() if existing_app else None
                    })
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            # Check if email already exists
            if StaffApplication.objects.filter(email=email).exists():
                error_msg = f'An application with email {email} already exists. Please use a different email or contact support.'
                
                if is_ajax:
                    return JsonResponse({'success': False, 'error': error_msg})
                messages.error(request, error_msg)
                return render(request, 'staff/apply.html', {
                    'positions': StaffApplication.POSITION_CHOICES
                })
            
            # Handle file uploads
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
            # SEND ADMIN NOTIFICATION
            # ============================================
            try:
                from utils.notifications import AdminNotifier
                AdminNotifier.notify_new_application(application)
                logger.info(f"Admin notification sent for application #{application.id}")
            except ImportError:
                logger.warning("AdminNotifier not available - skipping notification")
            except Exception as e:
                logger.error(f"Failed to send admin notification: {str(e)}")
                # Don't fail the application if notification fails
            
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






# ====================================
# APPROVE VIEW
# ====================================
from django.contrib.auth.models import User, Group
from django.contrib.auth.hashers import make_password
from staff.models import UserProfile  # Add this import
import random
import string


@login_required
def application_approve(request, pk):
    """Approve an application and create user account with proper group"""
    application = get_object_or_404(StaffApplication, pk=pk)
    
    if request.method == 'POST':
        try:
            # Get role/group from form
            group_id = request.POST.get('group')
            notes = request.POST.get('review_notes', '')
            
            # Use email as username
            username = application.email
            
            # Check if username exists, if so add suffix
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                if '@' in base_username:
                    local_part, domain = base_username.split('@')
                    username = f"{local_part}{counter}@{domain}"
                else:
                    username = f"{base_username}{counter}"
                counter += 1
            
            # Default password
            password = "Fsl@12345"
            
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
            
            # Assign to selected group
            if group_id:
                try:
                    group = Group.objects.get(id=group_id)
                    user.groups.add(group)
                    
                    # Also add to department group based on the selected role
                    department_map = {
                        'Sales Agent': 'Sales Department',
                        'Sales Manager': 'Sales Department',
                        'Cashier': 'Sales Department',
                        'Store Manager': 'Inventory Department',
                        'Credit Officer': 'Credit Department',
                        'Customer Service': 'Credit Department',
                    }
                    
                    # Add to department group if exists
                    if group.name in department_map:
                        dept_group, _ = Group.objects.get_or_create(name=department_map[group.name])
                        user.groups.add(dept_group)
                        
                except Group.DoesNotExist:
                    pass
            
            # Update application status
            application.status = 'approved'
            application.reviewed_by = request.user
            application.review_date = timezone.now()
            application.review_notes = notes
            application.created_user = user
            application.save()
            
            # Send email to applicant
            send_login_credentials(application, user, password)
            
            # ============================================
            # SEND ADMIN NOTIFICATION
            # ============================================
            try:
                from utils.notifications import AdminNotifier
                # Notify admin about approval
                AdminNotifier.notify_application_processed(
                    application=application,
                    action='approved',
                    processed_by=request.user
                )
                logger.info(f"Admin notification sent for approved application #{application.id}")
            except ImportError:
                logger.warning("AdminNotifier not available - skipping notification")
            except Exception as e:
                logger.error(f"Failed to send admin notification: {str(e)}")
                # Don't fail the approval if notification fails
            
            messages.success(
                request, 
                f'✅ Application for {application.full_name()} has been approved.<br>'
                f'👤 User account created with group: <strong>{group.name if group_id else "No group"}</strong><br>'
                f'📧 Username: <strong>{username}</strong><br>'
                f'🔑 Password: <strong>{password}</strong><br>'
                f'⚠️ <span class="text-warning">User will be required to change password on first login.</span>'
            )
            return redirect('staff:application_detail', pk=application.pk)
            
        except Exception as e:
            logger.error(f"Error approving application: {str(e)}")
            messages.error(request, f'Error approving application: {str(e)}')
            return redirect('staff:application_detail', pk=application.pk)
    
    # GET request - show approval form with group selection
    groups = Group.objects.all().order_by('name')
    
    context = {
        'application': application,
        'groups': groups,
        'first_login_note': True,  # Add note to template about first login
    }
    return render(request, 'staff/approve.html', context)







def send_login_credentials(application, user, password):
    """Send login credentials to approved staff"""
    try:
        subject = f'🎉 Welcome to FieldMax - Your Staff Account has been Created'
        
        context = {
            'name': application.full_name(),
            'username': user.username,
            'email': application.email,
            'password': password,
            'is_staff': user.is_staff,
            'groups': ', '.join([group.name for group in user.groups.all()]),
        }
        
        html_message = render_to_string('staff/email/welcome_email.html', context)
        plain_message = f"""
        Dear {application.full_name()},
        
        🎉 Congratulations! Your staff application has been approved.
        
        Your staff account has been created with the following credentials:
        ─────────────────────────────────
        Username: {user.username}
        Email: {application.email}
        Password: {password}
        Staff Access: {'Enabled' if user.is_staff else 'Standard'}
        Role: {', '.join([group.name for group in user.groups.all()]) or 'No specific role'}
        ─────────────────────────────────
        
        ⚠️ IMPORTANT: Please change your password after first login for security.
        
        Welcome to the team!
        
        Regards,
        FieldMax HR Team
        """
        
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [application.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        logger.info(f"Welcome email sent to {application.email} with username: {user.username}")
        
    except Exception as e:
        logger.error(f"Failed to send welcome email to {application.email}: {str(e)}")






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
        try:
            send_revert_notification(application, user_deleted, username)
        except Exception as e:
            logger.error(f"Failed to send revert notification email: {str(e)}")
        
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


def send_revert_notification(application, user_deleted, username):
    """Send notification email when application is reverted"""
    try:
        subject = f'FieldMax - Your Staff Application Status Update'
        
        context = {
            'name': application.full_name(),
            'application_id': application.id,
            'position': application.get_position_display(),
            'user_deleted': user_deleted,
            'username': username,
            'reverted_date': timezone.now().strftime('%Y-%m-%d %H:%M'),
            'support_email': settings.DEFAULT_FROM_EMAIL,
        }
        
        html_message = render_to_string('staff/email/revert_notification.html', context)
        plain_message = f"""
        Dear {application.full_name()},
        
        Your staff application (#{application.id}) status has been updated.
        
        Status: PENDING (Reverted from Approved)
        Position: {application.get_position_display()}
        Date: {timezone.now().strftime('%Y-%m-%d %H:%M')}
        
        {'Your user account access has been removed.' if user_deleted else ''}
        
        If you have any questions, please contact the HR department.
        
        Regards,
        FieldMax HR Team
        """
        
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [application.email],
            html_message=html_message,
            fail_silently=True,
        )
        
    except Exception as e:
        logger.error(f"Failed to send revert notification email to {application.email}: {str(e)}")





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