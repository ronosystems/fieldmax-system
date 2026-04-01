from django import template

register = template.Library()

@register.filter
def sum_commission(transactions):
    """Sum commission amounts for a queryset of transactions"""
    if not transactions:
        return 0
    return sum(t.commission_amount for t in transactions)