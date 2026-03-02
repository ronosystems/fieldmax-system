import os
from sendgrid import SendGridAPIClient
from django.conf import settings
import logging
import sendgrid

logger = logging.getLogger(__name__)

def send_email_via_api(to_email, subject, html_content, plain_text=None):
    """Send email using SendGrid Web API - works with any version"""
    
    if not settings.SENDGRID_API_KEY:
        logger.error("❌ SENDGRID_API_KEY not set in environment")
        return False
    
    # Check sendgrid version
    sendgrid_version = sendgrid.__version__
    logger.info(f"📧 Using SendGrid version: {sendgrid_version}")
    
    try:
        if sendgrid_version.startswith('3.'):
            # Version 3.x syntax
            import sendgrid
            from sendgrid.helpers.mail import Email, Content, Mail
            
            sg = sendgrid.SendGridAPIClient(api_key=settings.SENDGRID_API_KEY)
            from_email = Email(settings.DEFAULT_FROM_EMAIL)
            to_email_obj = Email(to_email)
            subject_line = subject
            content = Content("text/plain", plain_text or "")
            
            mail = Mail(from_email, subject_line, to_email_obj, content)
            
            # Add HTML content if provided
            if html_content:
                mail.add_content(Content("text/html", html_content))
            
            response = sg.client.mail.send.post(request_body=mail.get())
            
        else:
            # Version 6+ syntax
            from sendgrid.helpers.mail import Mail
            
            sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
            mail = Mail(
                from_email=settings.DEFAULT_FROM_EMAIL,
                to_emails=to_email,
                subject=subject,
                plain_text_content=plain_text or "",
                html_content=html_content
            )
            response = sg.send(mail)
        
        if response.status_code in [200, 202]:
            logger.info(f"✅ Email sent via API to {to_email}")
            return True
        else:
            logger.error(f"❌ API error: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"❌ SendGrid API failed: {str(e)}")
        return False