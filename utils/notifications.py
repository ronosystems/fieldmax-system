# utils/notifications.py
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

class AdminNotifier:
    """Send email notifications to admin for various system events"""
    
    ADMIN_EMAIL = 'fieldmaxdevteam@gmail.com'  # Your admin email
    
    @classmethod
    def send_notification(cls, subject, message, html_message=None):
        """Send email to admin"""
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[cls.ADMIN_EMAIL],
                html_message=html_message,
                fail_silently=False,
            )
            logger.info(f"Admin notification sent: {subject}")
            return True
        except Exception as e:
            logger.error(f"Failed to send admin notification: {str(e)}")
            return False
    
    # ============================================
    # SALES NOTIFICATIONS
    # ============================================
    
    @classmethod
    def notify_sale_completed(cls, sale, items_count):
        """Notify admin when a sale is completed"""
        subject = f'💰 Sale Completed - {sale.sale_id}'
        
        context = {
            'sale': sale,
            'items_count': items_count,
            'cashier': sale.seller.get_full_name() or sale.seller.username,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'is_credit': sale.is_credit,
        }
        
        html_message = render_to_string('notifications/email/sale_completed.html', context)
        plain_message = f"""
        Sale Completed: {sale.sale_id}
        Amount: KSH {sale.total_amount}
        Cashier: {sale.seller.username}
        Date: {sale.sale_date}
        Items: {items_count}
        Payment: {sale.payment_method}
        """
        
        return cls.send_notification(subject, plain_message, html_message)
    
    @classmethod
    def notify_sale_reversed(cls, sale, reversed_by, reason):
        """Notify admin when a sale is reversed"""
        subject = f'↩️ Sale Reversed - {sale.sale_id}'
        
        context = {
            'sale': sale,
            'reversed_by': reversed_by.get_full_name() or reversed_by.username,
            'reason': reason,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        html_message = render_to_string('notifications/email/sale_reversed.html', context)
        plain_message = f"""
        Sale Reversed: {sale.sale_id}
        Original Amount: KSH {sale.total_amount}
        Reversed By: {reversed_by.username}
        Reason: {reason}
        Date: {timezone.now()}
        """
        
        return cls.send_notification(subject, plain_message, html_message)
    
    # ============================================
    # INVENTORY NOTIFICATIONS
    # ============================================
    
    @classmethod
    def notify_stock_added(cls, product, quantity, entry_type, added_by):
        """Notify admin when stock is added"""
        subject = f'📦 Stock Added - {product.product_code}'
        
        context = {
            'product': product,
            'quantity': quantity,
            'entry_type': entry_type,
            'added_by': added_by.get_full_name() or added_by.username,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'new_stock': product.quantity,
        }
        
        html_message = render_to_string('notifications/email/stock_added.html', context)
        plain_message = f"""
        Stock Added: {product.name} ({product.product_code})
        Quantity: {quantity}
        Type: {entry_type}
        Added By: {added_by.username}
        New Stock Level: {product.quantity}
        """
        
        return cls.send_notification(subject, plain_message, html_message)
    
    @classmethod
    def notify_low_stock(cls, product):
        """Notify admin when product reaches low stock"""
        subject = f'⚠️ Low Stock Alert - {product.product_code}'
        
        context = {
            'product': product,
            'current_stock': product.quantity,
            'reorder_level': product.reorder_level,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        html_message = render_to_string('notifications/email/low_stock.html', context)
        plain_message = f"""
        LOW STOCK ALERT!
        Product: {product.name} ({product.product_code})
        Current Stock: {product.quantity}
        Reorder Level: {product.reorder_level}
        Please reorder immediately.
        """
        
        return cls.send_notification(subject, plain_message, html_message)
    
    @classmethod
    def notify_out_of_stock(cls, product):
        """Notify admin when product is out of stock"""
        subject = f'❌ Out of Stock - {product.product_code}'
        
        context = {
            'product': product,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        html_message = render_to_string('notifications/email/out_of_stock.html', context)
        plain_message = f"""
        OUT OF STOCK!
        Product: {product.name} ({product.product_code})
        This product is now out of stock. Please restock.
        """
        
        return cls.send_notification(subject, plain_message, html_message)
    
    # ============================================
    # PRODUCT NOTIFICATIONS
    # ============================================
    
    @classmethod
    def notify_product_added(cls, product, added_by):
        """Notify admin when new product is added"""
        subject = f'🆕 New Product Added - {product.product_code}'
        
        context = {
            'product': product,
            'added_by': added_by.get_full_name() or added_by.username,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'is_single': product.category.is_single_item,
        }
        
        html_message = render_to_string('notifications/email/product_added.html', context)
        plain_message = f"""
        New Product Added!
        Name: {product.name}
        Code: {product.product_code}
        Category: {product.category.name}
        Price: KSH {product.selling_price}
        Added By: {added_by.username}
        """
        
        return cls.send_notification(subject, plain_message, html_message)
    
    @classmethod
    def notify_products_transferred(cls, products, from_user, to_user, transferred_by):
        """Notify admin when products are transferred between users"""
        subject = f'🔄 Products Transferred - {len(products)} items'
        
        product_list = "\n".join([f"  • {p.product_code} - {p.name}" for p in products])
        
        context = {
            'products': products,
            'count': len(products),
            'from_user': from_user.get_full_name() or from_user.username,
            'to_user': to_user.get_full_name() or to_user.username,
            'transferred_by': transferred_by.get_full_name() or transferred_by.username,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'product_list': product_list,
        }
        
        html_message = render_to_string('notifications/email/products_transferred.html', context)
        plain_message = f"""
        Products Transferred!
        Count: {len(products)} items
        From: {from_user.username}
        To: {to_user.username}
        By: {transferred_by.username}
        
        Products:
        {product_list}
        """
        
        return cls.send_notification(subject, plain_message, html_message)
    
    # ============================================
    # CREDIT NOTIFICATIONS
    # ============================================
    
    @classmethod
    def notify_credit_created(cls, transaction):
        """Notify admin when credit transaction is created"""
        subject = f'💳 Credit Created - {transaction.transaction_id}'
        
        context = {
            'transaction': transaction,
            'customer': transaction.customer,
            'company': transaction.credit_company,
            'dealer': transaction.dealer,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        html_message = render_to_string('notifications/email/credit_created.html', context)
        plain_message = f"""
        Credit Transaction Created!
        ID: {transaction.transaction_id}
        Customer: {transaction.customer.full_name}
        Amount: KSH {transaction.ceiling_price}
        Company: {transaction.credit_company.name}
        Dealer: {transaction.dealer.username}
        """
        
        return cls.send_notification(subject, plain_message, html_message)
    
    @classmethod
    def notify_credit_paid(cls, transaction):
        """Notify admin when credit is paid"""
        subject = f'✅ Credit Paid - {transaction.transaction_id}'
        
        context = {
            'transaction': transaction,
            'customer': transaction.customer,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        html_message = render_to_string('notifications/email/credit_paid.html', context)
        plain_message = f"""
        Credit Payment Received!
        Transaction: {transaction.transaction_id}
        Customer: {transaction.customer.full_name}
        Amount: KSH {transaction.ceiling_price}
        Status: {transaction.payment_status}
        """
        
        return cls.send_notification(subject, plain_message, html_message)





    
    # ============================================
    # STAFF APPLICATION NOTIFICATIONS
    # ============================================
    
    @classmethod
    def notify_new_application(cls, application):
        """Notify admin when a new staff application is submitted"""
        subject = f'📝 New Staff Application - {application.full_name()}'
        
        context = {
            'application': application,
            'full_name': application.full_name(),
            'position': application.get_position_display(),
            'email': application.email,
            'phone': application.phone,
            'id_number': application.id_number,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'application_id': application.id,
            'site_url': getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000'),
        }
        
        try:
            html_message = render_to_string('notifications/email/new_application.html', context)
        except Exception:
            html_message = None
        
        plain_message = f"""
        NEW STAFF APPLICATION SUBMITTED
        ─────────────────────────────────
        Name: {application.full_name()}
        Position: {application.get_position_display()}
        Email: {application.email}
        Phone: {application.phone}
        ID Number: {application.id_number}
        Date: {application.application_date.strftime('%Y-%m-%d %H:%M')}
        
        View application: {getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')}/staff/applications/{application.id}/
        """
        
        return cls.send_notification(subject, plain_message, html_message)
    
    @classmethod
    def notify_application_processed(cls, application, action, processed_by):
        """Notify admin when an application is approved or rejected"""
        action_emoji = '✅' if action == 'approved' else '❌'
        subject = f'{action_emoji} Application {action.title()} - {application.full_name()}'
        
        context = {
            'application': application,
            'full_name': application.full_name(),
            'position': application.get_position_display(),
            'action': action,
            'processed_by': processed_by.get_full_name() or processed_by.username,
            'date': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'application_id': application.id,
            'site_url': getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000'),
        }
        
        try:
            html_message = render_to_string('notifications/email/application_processed.html', context)
        except Exception:
            html_message = None
        
        plain_message = f"""
        APPLICATION {action.upper()}
        ─────────────────────────────────
        Name: {application.full_name()}
        Position: {application.get_position_display()}
        Action: {action}
        Processed By: {processed_by.username}
        Date: {context['date']}
        
        View application: {getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')}/staff/applications/{application.id}/
        """
        
        return cls.send_notification(subject, plain_message, html_message)