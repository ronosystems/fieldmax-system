# shops/templatetags/custom_filters.py
from django import template

register = template.Library()

@register.filter
def abs_value(value):
    """Return absolute value of a number"""
    try:
        return abs(float(value))
    except (ValueError, TypeError):
        return value
    

@register.filter
def divide(value, arg):
    """Divide the value by the argument"""
    try:
        return float(value) / float(arg)
    except (ValueError, TypeError, ZeroDivisionError):
        return 0

@register.filter
def multiply(value, arg):
    """Multiply the value by the argument"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0