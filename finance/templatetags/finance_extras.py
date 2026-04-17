from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key"""
    if dictionary is None:
        return None
    return dictionary.get(key)

@register.filter
def splitlines(value):
    """Split a string by newlines and return a list of lines"""
    if value:
        return value.splitlines()
    return []