# finance/apps.py
from django.apps import AppConfig

class FinanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'finance'
    
    def ready(self):
        try:
            import finance.signals
        except ImportError:
            pass  # signals.py doesn't exist yet
