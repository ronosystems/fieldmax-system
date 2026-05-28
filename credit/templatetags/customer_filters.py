# credit/templatetags/customer_filters.py
from django import template
from credit.models import CreditTransaction

register = template.Library()

@register.filter
def has_active_credit(customer):
    """Check if customer has an active credit device"""
    if not customer or not customer.id:
        return False
    return CreditTransaction.objects.filter(
        customer=customer,
        payment_status__in=['pending', 'partially_paid']
    ).exists()

@register.filter
def is_eligible_customer(customer):
    """Check if customer is eligible for new credit (no active credit)"""
    return not has_active_credit(customer)