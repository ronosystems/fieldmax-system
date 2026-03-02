import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def send_email_via_api(to_email, subject, html_content, plain_text=None):
    """Send email using SendGrid Web API (port 443) instead of SMTP"""
    
    if not settings.SENDGRID_API_KEY:
        logger.error("❌ SENDGRID_API_KEY not set in environment")
        return False
    
    message = Mail(
        from_email=settings.DEFAULT_FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        html_content=html_content,
        plain_text_content=plain_text
    )
    
    try:
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        
        if response.status_code in [200, 202]:
            logger.info(f"✅ Email sent via API to {to_email}")
            return True
        else:
            logger.error(f"❌ API error: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"❌ SendGrid API failed: {str(e)}")
        return False
