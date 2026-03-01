# staff/context_processors.py
from .models import Staff, StaffApplication

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