# staff/context_processors.py
from .models import Staff, StaffApplication
from inventory.models import StockAlert, ReturnRequest

def pending_counts(request):
    """Add pending counts to all templates"""
    counts = {
        'staff_verification_pending': 0,
        'staff_onboarding_pending': 0,
    }
    
    if request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff):
        # Pending verifications count
        counts['staff_verification_pending'] = Staff.objects.filter(
            verification_submitted_at__isnull=False,
            is_identity_verified=False
        ).count()
        
        # Pending applications count
        counts['staff_onboarding_pending'] = StaffApplication.objects.filter(
            status='pending'
        ).count()
    
    return counts


def notification_count(request):  # This must be named 'notification_count'
    """Get notification count for the current user"""
    if not request.user.is_authenticated:
        return {'notification_count': 0}
    
    from inventory.models import StockAlert, ReturnRequest
    
    # Count active stock alerts
    stock_alert_count = StockAlert.objects.filter(
        is_active=True,
        is_dismissed=False
    ).count()
    
    # Count pending returns (different for staff vs regular users)
    if request.user.is_staff or request.user.is_superuser:
        pending_returns = ReturnRequest.objects.filter(status='submitted').count()
    else:
        pending_returns = ReturnRequest.objects.filter(
            requested_by=request.user,
            status='submitted'
        ).count()
    
    return {'notification_count': stock_alert_count + pending_returns}