from django_cron import CronJobBase, Schedule
from django.core.management import call_command
from inventory.models import StockAlert
from inventory.utils import send_stock_alert_email
import logging

logger = logging.getLogger(__name__)

class StockAlertCronJob(CronJobBase):
    RUN_EVERY_MINS = 24 * 60  # Run once per day
    
    schedule = Schedule(run_every_mins=RUN_EVERY_MINS)
    code = 'inventory.stock_alert_cron'

    def do(self):
        try:
            # Run the check command
            call_command('check_stock_alerts', '--fix', '--email')
            logger.info("Daily stock alert check completed")
        except Exception as e:
            logger.error(f"Stock alert cron failed: {str(e)}")