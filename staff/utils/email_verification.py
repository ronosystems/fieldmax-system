# staff/utils/email_verification.py
import random
import string
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.urls import reverse
import logging

logger = logging.getLogger(__name__)

def generate_verification_code(length=6):
    """Generate a random verification code"""
    return ''.join(random.choices(string.digits, k=length))

def send_itp_verification_email(staff_member, request=None):
    """
    Send ITP verification email to staff member
    """
    try:
        # Generate verification code if not exists
        if not staff_member.verification_code:
            staff_member.verification_code = generate_verification_code()
            staff_member.save(update_fields=['verification_code'])
        
        # Build verification link
        if request:
            verification_link = request.build_absolute_uri(
                reverse('staff:verify_identity', args=[staff_member.id])
            )
        else:
            verification_link = f"{settings.SITE_URL}/staff/verify/{staff_member.id}/"
        
        # Context for email template
        context = {
            'staff_name': staff_member.user.get_full_name(),
            'staff_id': staff_member.staff_id,
            'staff_email': staff_member.user.email,
            'department': staff_member.department.name if hasattr(staff_member, 'department') and staff_member.department else 'N/A',
            'position': staff_member.position,
            'verification_code': staff_member.verification_code,
            'verification_link': verification_link,
            'site_url': settings.SITE_URL,
        }
        
        # You'll need to create these templates
        try:
            html_message = render_to_string('staff/email/verification_email.html', context)
            plain_message = render_to_string('staff/email/verification_email.txt', context)
        except:
            # Fallback if templates don't exist
            html_message = f"""
            <html>
            <body>
                <h2>Identity Verification Required</h2>
                <p>Hello {staff_member.user.get_full_name()},</p>
                <p>Your verification code is: <strong>{staff_member.verification_code}</strong></p>
                <p>Click here to verify: <a href="{verification_link}">{verification_link}</a></p>
                <p>This code expires in 24 hours.</p>
            </body>
            </html>
            """
            plain_message = f"""
            Identity Verification Required
            
            Hello {staff_member.user.get_full_name()},
            
            Your verification code is: {staff_member.verification_code}
            
            Click here to verify: {verification_link}
            
            This code expires in 24 hours.
            """
        
        # Send email
        send_mail(
            subject='🔐 Identity Verification Required - FieldMax Staff Portal',
            message=strip_tags(plain_message),
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[staff_member.user.email],
            fail_silently=False,
        )
        
        logger.info(f"ITP verification email sent to {staff_member.user.email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send ITP verification email: {str(e)}")
        return False