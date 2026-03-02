# utils/email_utils.py
from django.core.mail import send_mail, send_mass_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class EmailService:
    """Service class for handling all email operations"""
    
    @staticmethod
    def send_html_email(subject, template_name, context, recipient_list, from_email=None):
        """
        Send HTML email using Django templates
        
        Args:
            subject: Email subject
            template_name: Path to HTML template (e.g., 'emails/welcome.html')
            context: Dictionary of context variables for template
            recipient_list: List of recipient email addresses
            from_email: Sender email (defaults to DEFAULT_FROM_EMAIL)
        
        Returns:
            int: Number of successfully sent emails
        """
        try:
            # Render HTML content
            html_content = render_to_string(template_name, context)
            # Create plain text version
            text_content = strip_tags(html_content)
            
            # Create email message
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=from_email or settings.DEFAULT_FROM_EMAIL,
                to=recipient_list if isinstance(recipient_list, list) else [recipient_list]
            )
            email.attach_alternative(html_content, "text/html")
            
            # Send email
            result = email.send(fail_silently=False)
            logger.info(f"Email sent to {recipient_list}: {subject}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to send email to {recipient_list}: {str(e)}")
            raise
    
    @staticmethod
    def send_simple_email(subject, message, recipient_list, from_email=None):
        """Send simple plain text email"""
        try:
            result = send_mail(
                subject=subject,
                message=message,
                from_email=from_email or settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipient_list if isinstance(recipient_list, list) else [recipient_list],
                fail_silently=False,
            )
            logger.info(f"Simple email sent to {recipient_list}")
            return result
        except Exception as e:
            logger.error(f"Failed to send simple email: {str(e)}")
            raise
    
    @staticmethod
    def send_template_email(email_type, context, recipient_list):
        """
        Send predefined template-based emails
        """
        templates = {
            'welcome': {
                'subject': 'Welcome to Fieldmax!',
                'template': 'emails/welcome.html'
            },
            'password_reset': {
                'subject': 'Password Reset Request',
                'template': 'emails/password_reset.html'
            },
            'invoice': {
                'subject': f"Invoice #{context.get('invoice_number', '')}",
                'template': 'emails/invoice.html'
            },
            'credit_alert': {
                'subject': 'Credit Limit Alert',
                'template': 'emails/credit_alert.html'
            },
            'sale_confirmation': {
                'subject': 'Sale Confirmation',
                'template': 'emails/sale_confirmation.html'
            },
        }
        
        if email_type not in templates:
            raise ValueError(f"Unknown email type: {email_type}")
        
        template_info = templates[email_type]
        return EmailService.send_html_email(
            subject=template_info['subject'],
            template_name=template_info['template'],
            context=context,
            recipient_list=recipient_list
        )