# Create file: finance/management/commands/cleanup_mpesa.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from finance.models import MpesaTransaction

class Command(BaseCommand):
    help = 'Clean up stuck M-Pesa transactions'

    def handle(self, *args, **options):
        threshold = timezone.now() - timedelta(minutes=10)
        stuck = MpesaTransaction.objects.filter(
            status='pending',
            created_at__lt=threshold
        )
        
        count = stuck.count()
        stuck.update(status='failed')
        
        self.stdout.write(f"Cleaned up {count} stuck M-Pesa transactions")