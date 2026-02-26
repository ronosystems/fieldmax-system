from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from inventory.models import Product, StockAlert
from inventory.utils import send_stock_alert_email, get_stock_alert_recipients
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Check all products and update stock alerts'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Actually create/update alerts (otherwise just dry run)',
        )
        parser.add_argument(
            '--product-id',
            type=int,
            help='Check only a specific product by ID',
        )
        parser.add_argument(
            '--category',
            type=str,
            help='Check only products in a specific category',
        )
        parser.add_argument(
            '--email',
            action='store_true',
            help='Send email report after checking',
        )
        parser.add_argument(
            '--force-email',
            action='store_true',
            help='Send email even if no alerts (for testing)',
        )

    def handle(self, *args, **options):
        fix = options['fix']
        send_email = options.get('email', False)
        force_email = options.get('force_email', False)
        product_id = options.get('product_id')
        category_name = options.get('category')
        
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("STOCK ALERT CHECKER"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        
        # Show email recipients if sending email
        if send_email:
            recipients = get_stock_alert_recipients()
            self.stdout.write(f"Email will be sent to: {', '.join(recipients) if recipients else 'No recipients'}")
            self.stdout.write("-" * 60)
        
        # Build query
        products = Product.objects.filter(is_active=True)
        
        if product_id:
            products = products.filter(id=product_id)
            self.stdout.write(f"Checking specific product ID: {product_id}")
        
        if category_name:
            products = products.filter(category__name__icontains=category_name)
            self.stdout.write(f"Checking category: {category_name}")
        
        total_products = products.count()
        self.stdout.write(f"Total products to check: {total_products}")
        self.stdout.write("-" * 60)
        
        alert_counts = {
            'lowstock': 0,
            'needs_reorder': 0,
            'outofstock': 0,
            'damaged': 0,
            'available': 0,
            'total_alerts': 0
        }
        
        created_alerts = 0
        updated_alerts = 0
        alerts_created = []  # Store created alerts for email
        
        for product in products:
            status = product.stock_status
            self.stdout.write(f"\n📦 {product.product_code}: {product.display_name}")
            self.stdout.write(f"   Category: {product.category.name if product.category else 'No Category'}")
            self.stdout.write(f"   Quantity: {product.quantity}")
            self.stdout.write(f"   Status: {status}")
            
            if status in ['lowstock', 'needs_reorder', 'outofstock', 'damaged']:
                alert_counts[status] += 1
                alert_counts['total_alerts'] += 1
                
                if fix:
                    # Determine threshold based on status
                    threshold = 5
                    if status == 'needs_reorder' and product.reorder_level:
                        threshold = product.reorder_level
                    
                    # Determine severity
                    severity = 'warning'
                    if status == 'needs_reorder':
                        severity = 'danger'
                    elif status == 'outofstock':
                        severity = 'critical'
                    elif status == 'damaged':
                        severity = 'danger'
                    
                    # Create or update alert
                    alert, created = StockAlert.objects.update_or_create(
                        product=product,
                        is_dismissed=False,
                        defaults={
                            'alert_type': status,
                            'severity': severity,
                            'current_stock': product.quantity,
                            'threshold': threshold,
                            'reorder_level': product.reorder_level,
                            'is_active': True,
                            'last_alerted': timezone.now(),
                        }
                    )
                    
                    if created:
                        created_alerts += 1
                        alerts_created.append(alert)
                        self.stdout.write(self.style.SUCCESS(f"   ✅ Created {status} alert"))
                    else:
                        updated_alerts += 1
                        alerts_created.append(alert)
                        self.stdout.write(self.style.SUCCESS(f"   ✅ Updated {status} alert"))
                else:
                    self.stdout.write(self.style.WARNING(f"   ⚠️ Would create alert (dry run)"))
                    
                # Show details
                if product.reorder_level:
                    self.stdout.write(f"   Reorder Level: {product.reorder_level}")
                
            else:
                alert_counts['available'] += 1
                self.stdout.write(self.style.SUCCESS(f"   ✅ Stock is healthy"))
                
                # Deactivate any existing alerts for this product
                if fix:
                    deactivated = StockAlert.objects.filter(
                        product=product, 
                        is_active=True
                    ).update(is_active=False, is_dismissed=True)
                    if deactivated:
                        self.stdout.write(f"   🔕 Deactivated existing alerts")
        
        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Total products checked: {total_products}")
        self.stdout.write(f"Products with healthy stock: {alert_counts['available']}")
        self.stdout.write(f"Products needing attention: {alert_counts['total_alerts']}")
        self.stdout.write(f"  - Low Stock: {alert_counts['lowstock']}")
        self.stdout.write(f"  - Needs Reorder: {alert_counts['needs_reorder']}")
        self.stdout.write(f"  - Out of Stock: {alert_counts['outofstock']}")
        self.stdout.write(f"  - Damaged: {alert_counts['damaged']}")
        
        if fix:
            self.stdout.write("\n" + "-" * 60)
            self.stdout.write(f"Alerts created: {created_alerts}")
            self.stdout.write(f"Alerts updated: {updated_alerts}")
            self.stdout.write(self.style.SUCCESS("✅ Database updated with alerts"))
            
            # Send email if requested
            if send_email and (alert_counts['total_alerts'] > 0 or force_email):
                self.stdout.write("\n" + "-" * 60)
                self.stdout.write("📧 Sending email report...")
                
                # Get all active alerts
                active_alerts = StockAlert.objects.filter(
                    is_active=True, 
                    is_dismissed=False
                ).select_related('product', 'product__category')
                
                if active_alerts.exists() or force_email:
                    email_sent = send_stock_alert_email(active_alerts)
                    if email_sent:
                        self.stdout.write(self.style.SUCCESS("✅ Email sent successfully"))
                    else:
                        self.stdout.write(self.style.ERROR("❌ Failed to send email"))
                else:
                    self.stdout.write("ℹ️ No active alerts to email")
            elif send_email and alert_counts['total_alerts'] == 0 and not force_email:
                self.stdout.write("\nℹ️ No alerts to email (use --force-email to send anyway)")
        else:
            self.stdout.write("\n" + "!" * 60)
            self.stdout.write(self.style.WARNING("This was a DRY RUN. No changes were made."))
            self.stdout.write(self.style.WARNING("Use --fix to actually create alerts:"))
            self.stdout.write(self.style.WARNING("  python manage.py check_stock_alerts --fix"))