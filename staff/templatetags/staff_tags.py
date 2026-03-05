from django import template
from django.template.defaultfilters import stringfilter
from ..models import StaffApplication

register = template.Library()

@register.filter
def has_role(user, roles):
    """Check if user has any of the specified roles"""
    if not user or not user.is_authenticated:
        return False
        
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
    if not user or not user.is_authenticated:
        return "Staff Dashboard"
        
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
            'credit_officer': 'Credit Officer Dashboard',
            'customer_service': 'Customer Service Dashboard',
            'supervisor': 'Supervisor Dashboard',
            'security_officer': 'Security Dashboard',
            'cleaner': 'Cleaner Dashboard',
            'inventory_manager': 'Inventory Manager Dashboard',
            'assistant_manager': 'Assistant Manager Dashboard',
        }
        
        return dashboard_names.get(staff_app.position, 'Staff Dashboard')
        
    except StaffApplication.DoesNotExist:
        return "Staff Dashboard"

@register.filter
def get_user_position(user):
    """Get user's position from StaffApplication - NOW AS A FILTER"""
    if not user or not user.is_authenticated:
        return None
        
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
    if not position_code:
        return ''
        
    position_display = {
        'sales_agent': 'Sales Officer',
        'cashier': 'Cashier',
        'store_manager': 'Store Manager',
        'sales_manager': 'Sales Manager',
        'credit_manager': 'Credit Manager',
        'credit_officer': 'Credit Officer',
        'customer_service': 'Customer Service',
        'supervisor': 'Supervisor',
        'security_officer': 'Security Officer',
        'cleaner': 'Cleaner',
        'inventory_manager': 'Inventory Manager',
        'assistant_manager': 'Assistant Manager',
        'administrator': 'Administrator',
    }
    return position_display.get(position_code, position_code.replace('_', ' ').title())