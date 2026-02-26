from django import template

register = template.Library()

@register.filter
def multiply(value, arg):
    """Multiply two numbers"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0

@register.filter
def div(value, arg):
    """Divide two numbers"""
    try:
        if float(arg) == 0:
            return 0
        return float(value) / float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0

@register.filter
def floatformat(value, arg):
    """Format float to specified decimal places"""
    try:
        return f"{float(value):.{arg}f}"
    except (ValueError, TypeError):
        return value

@register.filter
def filter_by_type(alerts, alert_type):
    """Filter alerts by type"""
    if alerts is None:
        return []
    return [alert for alert in alerts if alert.alert_type == alert_type]