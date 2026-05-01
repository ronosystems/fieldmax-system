# staff/context_processors.py
from .models import Staff, StaffApplication
from inventory.models import StockAlert, ReturnRequest
from django.contrib.auth.models import Group

def user_groups(request):
    """Add user group info to all templates"""
    if request.user.is_authenticated:
        user_groups = request.user.groups.all()
        user_group_names = [group.name for group in user_groups]
        
        # Determine role display
        role_display = 'Staff Member'
        if hasattr(request.user, 'staff_profile') and request.user.staff_profile.position:
            role_display = request.user.staff_profile.get_position_display()
        elif 'Administrator' in user_group_names:
            role_display = 'Administrator'
        elif 'Cashier' in user_group_names:
            role_display = 'Cashier'
        elif 'Sales Agent' in user_group_names:
            role_display = 'Sales Agent'
        # Add more roles as needed
        
        return {
            'is_administrator': 'Administrator' in user_group_names,
            'user_groups': user_groups,
            'user_group_names': user_group_names,
            'user_role_display': role_display,
        }
    return {
        'is_administrator': False,
        'user_groups': [],
        'user_group_names': [],
        'user_role_display': 'Guest',
    }

def get_user_role_display(user, group_names):
    """Helper to get readable role name"""
    # Check Staff model first
    if hasattr(user, 'staff_profile') and user.staff_profile.position:
        return user.staff_profile.get_position_display()
    
    # Fallback to groups
    role_map = {
        'Administrator': 'Administrator',
        'Cashier': 'Cashier',
        'Sales Agent': 'Sales Agent',
        'Sales Manager': 'Sales Manager',
        'Store Manager': 'Store Manager',
        'Credit Manager': 'Credit Manager',
        'Credit Officer': 'Credit Officer',
        'Finance Manager': 'Finance Manager',
        'Customer Service': 'Customer Service',
        'M-Pesa Agent': 'M-Pesa Agent',
        'Security Officer': 'Security Officer',
        'Cleaner': 'Cleaner',
    }
    
    for group in group_names:
        if group in role_map:
            return role_map[group]
    
    return 'Staff Member'

def pending_counts(request):
    """Add pending counts to all templates"""
    counts = {
        'staff_verification_pending': 0,
        'staff_onboarding_pending': 0,
    }
    
    if request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff):
        counts['staff_verification_pending'] = Staff.objects.filter(
            verification_submitted_at__isnull=False,
            is_identity_verified=False
        ).count()
        
        counts['staff_onboarding_pending'] = StaffApplication.objects.filter(
            status='pending'
        ).count()
    
    return counts

def notification_count(request):
    """Get notification count for the current user"""
    if not request.user.is_authenticated:
        return {'notification_count': 0}
    
    stock_alert_count = StockAlert.objects.filter(
        is_active=True,
        is_dismissed=False
    ).count()
    
    if request.user.is_staff or request.user.is_superuser:
        pending_returns = ReturnRequest.objects.filter(status='submitted').count()
    else:
        pending_returns = ReturnRequest.objects.filter(
            requested_by=request.user,
            status='submitted'
        ).count()
    
    return {'notification_count': stock_alert_count + pending_returns}