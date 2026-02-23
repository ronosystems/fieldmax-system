from django import template

register = template.Library()

@register.filter
def subtract(value, arg):
    """Subtract the arg from the value"""
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def length_unique_products(cart):
    """Return the number of unique products in cart"""
    unique_products = set()
    for item in cart:
        unique_products.add(item.get('product_code'))
    return len(unique_products)

@register.filter
def price_points_count(cart):
    """Return the number of unique price points"""
    price_points = set()
    for item in cart:
        price_points.add(f"{item.get('product_code')}_{item.get('price')}")
    return len(price_points)