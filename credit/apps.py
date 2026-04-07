from django.apps import AppConfig

class CreditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'credit'
    
    def ready(self):
        # Signals are now handled by finance app
        # import credit.signals  # DISABLED - causes duplicates
        pass