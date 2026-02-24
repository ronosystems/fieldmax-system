from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from datetime import datetime
from .models import OTPVerification
import logging


year = datetime.now().year

logger = logging.getLogger(__name__)




def send_otp_email(user, otp_code):
    """Send OTP code via email"""
    subject = f'FieldMax - Your Dashboard Access Code'
    
    # Get user name safely
    user_name = user.get_full_name() or user.username
    
    message = f"""
    Dear {user_name},
    
    Your One-Time Password (OTP) for dashboard access is: {otp_code}
    
    This code will expire in 5 minutes.
    
    If you did not request this code, please contact your system administrator immediately.
    
    Regards,
    FieldMax Security Team
    """
    
    html_message = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f9f9f9; padding: 30px; border: 1px solid #ddd; }}
            .otp-code {{ font-size: 32px; font-weight: bold; color: #667eea; text-align: center; padding: 20px; background: white; border-radius: 10px; margin: 20px 0; letter-spacing: 5px; }}
            .footer {{ background: #f1f1f1; padding: 15px; text-align: center; font-size: 12px; border-radius: 0 0 10px 10px; }}
            .warning {{ color: #dc3545; font-size: 14px; margin-top: 20px; }}
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
                <div class="otp-code">{otp_code}</div>
                <p>This code will expire in <strong>5 minutes</strong>.</p>
                <div class="warning">
                    <strong>⚠️ Security Notice:</strong> If you did not request this code, 
                    please contact your system administrator immediately.
                </div>
            </div>
            <div class="footer">
                <p>This is an automated message from FieldMax System. Please do not reply.</p>
                <p>&copy; {year} FieldMax. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """.format(
        user_name=user_name,
        otp_code=otp_code,
        year=timezone.now().year
    )
    
    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"OTP email sent to {user.email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send OTP email to {user.email}: {str(e)}")
        return False






def get_user_role(user):
    """Get the highest role for a user"""
    if user.is_superuser:
        return 'Administrator'
    
    user_groups = user.groups.values_list('name', flat=True)
    
    # Define role hierarchy (highest to lowest)
    role_hierarchy = [
        'Administrator',
        'Supervisor',
        'Sales Manager',
        'Store Manager',
        'Credit Officer',
        'Assistant Manager',
        'Credit Manager',
        'Customer Service',
        'Security Officer',
        'Sales Agent',
        'Cashier',
        'Cleaner',
    ]
    
    for role in role_hierarchy:
        if role in user_groups:
            return role
    
    return None

def requires_otp(user):
    """Check if user requires OTP for dashboard access"""
    if user.is_superuser:
        return True
    
    # Groups that require OTP
    otp_required_groups = [
        'Administrator',
        'Supervisor',
        'Sales Manager',
        'Store Manager',
        'Assistant Manager',
        'Credit Manager',
    ]
    
    user_groups = user.groups.values_list('name', flat=True)
    return any(group in otp_required_groups for group in user_groups)