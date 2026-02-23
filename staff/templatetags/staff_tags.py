from django import template
from django.template.defaultfilters import stringfilter
from ..models import StaffApplication

register = template.Library()

@register.filter
def has_role(user, roles):
    """Check if user has any of the specified roles"""
    if user.is_superuser:
        return True
        
    try:
        staff_app = StaffApplication.objects.get(
            created_user=user,
            status='approved'
        )
        role_list = [role.strip() for role in roles.split(',')]
        return staff_app.position in role_list
    except StaffApplication.DoesNotExist:
        return False

@register.simple_tag
def get_dashboard_name(user):
    """Get appropriate dashboard name for user"""
    if user.is_superuser:
        return "Admin Dashboard"
        
    try:
        staff_app = StaffApplication.objects.get(
            created_user=user,
            status='approved'
        )
        
        dashboard_names = {
            'sales_agent': 'Sales Officer Dashboard',
            'cashier': 'Cashier Dashboard',
            'store_manager': 'Store Manager Dashboard',
            'sales_manager': 'Sales Manager Dashboard',
            'credit_manager': 'Credit Manager Dashboard',
            'customer_service': 'Customer Service Dashboard',
            'supervisor': 'Supervisor Dashboard',
            'security': 'Security Dashboard',
            'cleaner': 'Cleaner Dashboard',
        }
        
        return dashboard_names.get(staff_app.position, 'Staff Dashboard')
        
    except StaffApplication.DoesNotExist:
        return "Staff Dashboard"

@register.simple_tag
def get_user_position(user):
    """Get user's position from StaffApplication"""
    if user.is_superuser:
        return None
        
    try:
        staff_app = StaffApplication.objects.get(
            created_user=user,
            status='approved'
        )
        return staff_app.position
    except StaffApplication.DoesNotExist:
        return None

@register.filter
@stringfilter
def replace(value, arg):
    """Replace all occurrences of a string with another string"""
    try:
        old, new = arg.split(',')
        return value.replace(old, new)
    except (ValueError, AttributeError):
        return value

@register.filter
def position_display(position_code):
    """Convert position code to display name"""
    position_display = {
        'sales_agent': 'Sales Officer',
        'cashier': 'Cashier Desk',
        'store_manager': 'Store Manager',
        'sales_manager': 'Sales Manager',
        'credit_manager': 'Credit Manager',
        'customer_service': 'Customer Care Service',
        'supervisor': 'Supervisor',
        'security': 'Security Officer',
        'cleaner': 'Office Cleaner',
    }
    return position_display.get(position_code, position_code)