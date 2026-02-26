from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.contrib.auth.models import User, Group
from django.conf import settings
import logging
from datetime import timedelta
from django.utils import timezone



logger = logging.getLogger(__name__)

def get_stock_alert_recipients():
    """Get list of admin and store manager emails"""
    emails = []
    
    # Get all superusers (admins)
    admins = User.objects.filter(is_superuser=True, is_active=True)
    emails.extend([admin.email for admin in admins if admin.email])
    
    # Get store managers group (create this group if it doesn't exist)
    try:
        store_managers_group = Group.objects.get(name='Store Managers')
        store_managers = store_managers_group.user_set.filter(is_active=True)
        emails.extend([manager.email for manager in store_managers if manager.email])
    except Group.DoesNotExist:
        logger.warning("Store Managers group does not exist. Create it in admin panel.")
    
    # Remove duplicates and empty emails
    emails = list(set([email for email in emails if email]))
    
    return emails

def send_stock_alert_email(alerts_data):
    """Send stock alert email to admins and store managers"""
    
    recipients = get_stock_alert_recipients()
    
    if not recipients:
        logger.warning("No recipients found for stock alerts")
        return False
    
    # Prepare email content
    subject = f"🚨 Stock Alert Report - {timezone.now().strftime('%B %d, %Y')}"
    
    # Count alerts by type
    alert_counts = {
        'lowstock': alerts_data.filter(alert_type='lowstock').count(),
        'needs_reorder': alerts_data.filter(alert_type='needs_reorder').count(),
        'outofstock': alerts_data.filter(alert_type='outofstock').count(),
        'damaged': alerts_data.filter(alert_type='damaged').count(),
        'total': alerts_data.count()
    }
    
    # Render HTML email

    html_message = render_to_string('inventory/stock/alerts.html', { 
        'alerts': alerts_data,
        'alert_counts': alert_counts,
        'date': timezone.now(),
        'site_url': settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'http://127.0.0.1:8000'
    })
    
    # Plain text version
    text_message = f"""
    STOCK ALERT REPORT - {timezone.now().strftime('%B %d, %Y')}
    ============================================
    
    Summary:
    - Total Alerts: {alert_counts['total']}
    - Low Stock: {alert_counts['lowstock']}
    - Needs Reorder: {alert_counts['needs_reorder']}
    - Out of Stock: {alert_counts['outofstock']}
    - Damaged: {alert_counts['damaged']}
    
    Please log in to the system to view details and take action.
    {settings.SITE_URL if hasattr(settings, 'SITE_URL') else 'http://127.0.0.1:8000'}/inventory/stock-alerts/
    """
    
    try:
        send_mail(
            subject=subject,
            message=text_message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )
        logger.info(f"Stock alert email sent to {len(recipients)} recipients")
        return True
    except Exception as e:
        logger.error(f"Failed to send stock alert email: {str(e)}")
        return False