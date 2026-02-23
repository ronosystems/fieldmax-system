from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.cache import cache_page
from django.utils.timesince import timesince
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.contrib.auth.views import LoginView
from django.views.generic import TemplateView, ListView
from django.contrib.auth.models import User
from sales.models import Sale, SaleItem
from django.utils import timezone
from django.db.models import Sum, Q, F, DecimalField, Count
from inventory.models import Product, Category, StockEntry
from decimal import Decimal
import logging
from django.http import JsonResponse
import json
from django.db import transaction
from .models import PendingOrder, PendingOrderItem, Order, Customer
from django.conf import settings

from datetime import timedelta 
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.utils import timezone

from django.db.models import Q
from difflib import SequenceMatcher






logger = logging.getLogger(__name__)





# ============================================
#  CATEGORIES LIST PUBLIC
# ============================================
@require_GET
def categories_list_public(request):
    """
    Public endpoint for categories list
    URL: /categories/
    
    Returns JSON for public consumption.
    """
    try:
        categories = Category.objects.all().order_by('name')
        
        category_list = []
        for category in categories:
            # Count only available products
            available_count = category.products.filter(
                is_active=True
            ).filter(
                Q(status='available') | Q(status='lowstock')
            ).count()
            
            total_count = category.products.filter(is_active=True).count()
            
            category_list.append({
                'id': category.id,
                'name': category.name,
                'category_code': category.category_code,
                'item_type': category.get_item_type_display(),
                'is_single_item': category.is_single_item,
                'product_count': total_count,
                'available_count': available_count,
                'url': f'/shop/?category={category.id}'
            })
        
        return JsonResponse({
            'success': True,
            'categories': category_list,
            'count': len(category_list)
        })
    
    except Exception as e:
        logger.error(f"Error in categories_list_public: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e),
            'categories': []
        }, status=500)







# ============================================
# API GET CATEGORIES
# ============================================
@require_GET
@cache_page(60 * 5)  # Cache for 5 minutes
def api_get_categories(request):
    """
    Enhanced API endpoint to get all categories with metadata
    URL: /api/categories/
    """
    try:
        categories = Category.objects.all().order_by('name')
        
        category_list = []
        
        for category in categories:
            # Count products by status
            products = category.products.filter(is_active=True)
            
            available_count = products.filter(
                Q(status='available') | Q(status='lowstock')
            ).count()
            
            total_count = products.count()
            
            # Determine icon based on item type
            if category.is_single_item:
                if 'phone' in category.name.lower():
                    icon = 'bi-phone'
                elif 'tablet' in category.name.lower():
                    icon = 'bi-tablet'
                elif 'laptop' in category.name.lower():
                    icon = 'bi-laptop'
                elif 'watch' in category.name.lower():
                    icon = 'bi-smartwatch'
                else:
                    icon = 'bi-phone'
            else:
                if 'cable' in category.name.lower() or 'charger' in category.name.lower():
                    icon = 'bi-lightning-charge'
                elif 'case' in category.name.lower() or 'cover' in category.name.lower():
                    icon = 'bi-box'
                elif 'headphone' in category.name.lower() or 'earphone' in category.name.lower():
                    icon = 'bi-headphones'
                elif 'accessory' in category.name.lower():
                    icon = 'bi-bag'
                else:
                    icon = 'bi-box-seam'
            
            category_data = {
                'id': category.id,
                'name': category.name,
                'category_code': category.category_code,
                'item_type': category.get_item_type_display(),
                'item_type_key': category.item_type,
                'sku_type': category.get_sku_type_display(),
                'is_single_item': category.is_single_item,
                'icon': icon,
                'product_count': total_count,
                'available_count': available_count,
                'url': f'/shop/?category={category.id}'
            }
            
            category_list.append(category_data)
        
        return JsonResponse({
            'success': True,
            'categories': category_list,
            'total': len(category_list)
        })
    
    except Exception as e:
        logger.error(f"Error in api_get_categories: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e),
            'categories': []
        }, status=500)






# ============================================
# API CATEGORY DETAILS
# ============================================
@require_GET
def api_category_details(request, category_id):
    """
    Get detailed information about a specific category
    URL: /api/categories/<id>/
    """
    try:
        category = Category.objects.get(id=category_id)
        
        # Get product statistics
        products = category.products.filter(is_active=True)
        
        stats = {
            'total': products.count(),
            'available': products.filter(status='available').count(),
            'lowstock': products.filter(status='lowstock').count(),
            'outofstock': products.filter(status='outofstock').count(),
            'sold': products.filter(status='sold').count() if category.is_single_item else 0
        }
        
        # Get recent products
        recent_products = []
        for product in products.order_by('-created_at')[:5]:
            recent_products.append({
                'id': product.id,
                'name': product.name,
                'product_code': product.product_code,
                'price': float(product.selling_price),
                'status': product.get_status_display(),
                'image_url': product.image.url if product.image else None
            })
        
        return JsonResponse({
            'success': True,
            'category': {
                'id': category.id,
                'name': category.name,
                'category_code': category.category_code,
                'item_type': category.get_item_type_display(),
                'sku_type': category.get_sku_type_display(),
                'is_single_item': category.is_single_item,
                'stats': stats,
                'recent_products': recent_products
            }
        })
    
    except Category.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Category not found'
        }, status=404)
    
    except Exception as e:
        logger.error(f"Error getting category details: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)
    





@require_http_methods(["GET"])
def search_products(request):
    """
    Search products and display full details if found, 
    or suggest related products if not found
    """
    query = request.GET.get('q', '').strip()
    
    context = {
        'page_title': 'Search Results',
        'search_query': query,
        'categories': Category.objects.all(),
    }
    
    if not query:
        context['message'] = 'Please enter a search term'
        return render(request, 'website/search_results.html', context)
    
    # Search for exact or close matches
    exact_matches = Product.objects.filter(
        Q(name__iexact=query) |
        Q(product_code__iexact=query) |
        Q(sku_value__iexact=query),
        is_active=True,
        category__isnull=False
    ).select_related('category', 'owner')
    
    if exact_matches.exists():
        # Exact match found - show full details
        context['exact_match'] = exact_matches.first()
        context['match_type'] = 'exact'
        
        # Also get related products from same category
        if context['exact_match'].category:
            context['related_products'] = Product.objects.filter(
                category=context['exact_match'].category,
                is_active=True,
                category__isnull=False
            ).exclude(
                id=context['exact_match'].id
            ).order_by('-created_at')[:6]
        
        return render(request, 'website/search_results.html', context)
    
    # No exact match - search for partial matches
    partial_matches = Product.objects.filter(
        Q(name__icontains=query) |
        Q(product_code__icontains=query) |
        Q(sku_value__icontains=query) |
        Q(category__name__icontains=query),
        is_active=True,
        category__isnull=False
    ).select_related('category', 'owner').order_by('-created_at')
    
    if partial_matches.exists():
        context['products'] = partial_matches
        context['match_type'] = 'partial'
        context['message'] = f'Found {partial_matches.count()} product(s) matching "{query}"'
        return render(request, 'website/search_results.html', context)
    
    # No matches found - suggest related products based on query keywords
    query_words = query.lower().split()
    
    # Try to find products with any of the query words
    suggested_products = Product.objects.filter(
        is_active=True,
        category__isnull=False
    ).select_related('category', 'owner')
    
    for word in query_words:
        if len(word) > 2:  # Only use words longer than 2 characters
            suggested_products = suggested_products.filter(
                Q(name__icontains=word) |
                Q(category__name__icontains=word)
            )
    
    suggested_products = suggested_products.distinct().order_by('-created_at')[:12]
    
    if suggested_products.exists():
        context['products'] = suggested_products
        context['match_type'] = 'suggested'
        context['message'] = f'No exact match for "{query}". Here are some suggestions:'
    else:
        # Fallback to popular/recent products
        context['products'] = Product.objects.filter(
            is_active=True,
            category__isnull=False,
            status__in=['available', 'lowstock']
        ).select_related('category', 'owner').order_by('-created_at')[:12]
        
        context['match_type'] = 'fallback'
        context['message'] = f'No products found for "{query}". Browse our latest products:'
    
    return render(request, 'website/search_results.html', context)





# ============================================
# BEST PRICE HELPER FUNCTIONS
# ============================================

def calculate_best_price(product):
    """
    Helper function to calculate best price for a product
    
    Formula: Buying Price + 50% of Profit Margin
    
    Args:
        product: Product instance
        
    Returns:
        Decimal: Best price rounded to 2 decimal places
    """
    try:
        buying_price = Decimal(str(product.buying_price)) if product.buying_price else Decimal('0.00')
        selling_price = Decimal(str(product.selling_price)) if product.selling_price else Decimal('0.00')
        
        profit_margin = selling_price - buying_price
        best_price = buying_price + (profit_margin * Decimal('0.5'))
        
        return round(best_price, 2)
    except Exception as e:
        print(f"Error calculating best price: {e}")
        return Decimal('0.00')








# ============================================
# HOME VIEW
# ============================================

def home(request):
    """
    Home page with top 12 most frequently sold products
    """
    # Get top 12 best-selling items - with category safety check
    best_sellers = []
    
    try:
        # Filter out products without categories first
        best_sellers = Product.objects.filter(
            sale_items__isnull=False,
            category__isnull=False,  # Only products with categories
            is_active=True
        ).annotate(
            times_ordered=Count('sale_items__id', distinct=True)
        ).filter(
            Q(status='available') | Q(status='lowstock')
        ).order_by('-times_ordered')[:12]
        
    except Exception as e:
        # Fallback: Show newest available products with categories
        best_sellers = Product.objects.filter(
            Q(status='available') | Q(status='lowstock'),
            category__isnull=False,
            is_active=True
        ).order_by('-created_at')[:12]
    
    # If less than 12 products, fill with newest
    try:
        count = best_sellers.count() if hasattr(best_sellers, 'count') else len(best_sellers)
        
        if count < 12:
            if hasattr(best_sellers, 'values_list'):
                best_seller_ids = list(best_sellers.values_list('id', flat=True))
            else:
                best_seller_ids = [p.id for p in best_sellers]
            
            remaining_count = 12 - count
            
            newest_products = Product.objects.filter(
                Q(status='available') | Q(status='lowstock'),
                category__isnull=False,
                is_active=True
            ).exclude(
                id__in=best_seller_ids
            ).order_by('-created_at')[:remaining_count]
            
            from itertools import chain
            best_sellers = list(chain(best_sellers, newest_products))
        else:
            best_sellers = list(best_sellers) if not isinstance(best_sellers, list) else best_sellers
            
    except Exception as e:
        best_sellers = Product.objects.filter(
            Q(status='available') | Q(status='lowstock'),
            category__isnull=False,
            is_active=True
        ).order_by('-created_at')[:12]
    
    # Get all active categories that have products for filtering
    try:
        categories = Category.objects.filter(
            products__is_active=True,
            products__isnull=False
        ).filter(
            Q(products__status='available') | Q(products__status='lowstock')
        ).distinct().order_by('name')
        
    except Exception as e:
        # Fallback: Get all categories
        categories = Category.objects.all().order_by('name')
    
    context = {
        'page_title': 'Fieldmax',
        'featured_products': best_sellers,
        'categories': categories,
    }
    
    return render(request, 'website/home.html', context)










# ============================================
# HOME STATS
# ============================================
@require_http_methods(["GET"])
def home_stats(request):
    """
    API endpoint to fetch homepage statistics
    """
    try:
        # Get total products (only available and low stock)
        total_products = Product.objects.filter(
            Q(status='available') | Q(status='lowstock'),
            category__isnull=False,  # Only products with categories
            is_active=True
        ).count()
        
        # Get total customers
        total_customers = Customer.objects.filter(is_active=True).count()
        
        # Calculate satisfaction rate from completed orders
        completed_orders = Order.objects.filter(status='completed')
        if completed_orders.exists():
            total_orders = Order.objects.count()
            successful_orders = completed_orders.count()
            satisfaction = round((successful_orders / total_orders) * 100) if total_orders > 0 else 98
        else:
            satisfaction = 98
        
        return JsonResponse({
            'success': True,
            'stats': {
                'total_products': total_products,
                'total_customers': total_customers,
                'satisfaction': satisfaction
            }
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
            'stats': {
                'total_products': 0,
                'total_customers': 0,
                'satisfaction': 0
            }
        }, status=500)






# ============================================
# FEATURED PRODUCTS
# ============================================

@require_http_methods(["GET"])
def featured_products(request):
    """
    API endpoint to fetch featured/best-selling products
    """
    try:
        products = Product.objects.filter(
            Q(status='available') | Q(status='lowstock'),
            category__isnull=False,  # Only products with categories
            is_active=True,
            is_featured=True
        ).order_by('-created_at')[:8]
        
        product_list = []
        for product in products:
            # Determine badge based on status
            badge = None
            if product.status == 'lowstock':
                badge = 'LOW STOCK'
            elif product.status == 'available' and product.quantity < 5:
                badge = 'HURRY UP!'
            
            # Get emoji based on category or product type
            emoji = get_product_emoji(product)
            
            product_list.append({
                'id': product.id,
                'name': product.name,
                'price': float(product.selling_price),
                'code': product.product_code,
                'emoji': emoji,
                'badge': badge,
                'is_single_item': product.category.is_single_item if product.category else False,
                'quantity': product.quantity,
                'image_url': product.image.url if product.image else None
            })
        
        return JsonResponse({
            'success': True,
            'products': product_list,
            'count': len(product_list)
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
            'products': []
        }, status=500)






# ============================================
# PRODUCT EMOJI HELPER
# ============================================
def get_product_emoji(product):
    """
    Helper function to return emoji based on product category or type
    """
    emoji_map = {
        'phone': '📱',
        'smartphone': '📱',
        'laptop': '💻',
        'tablet': '📲',
        'headphone': '🎧',
        'earphone': '🎧',
        'speaker': '🔊',
        'smartwatch': '⌚',
        'watch': '⌚',
        'camera': '📷',
        'charger': '🔌',
        'cable': '🔌',
        'case': '📦',
        'cover': '📦',
        'protector': '🛡️',
        'power bank': '🔋',
        'battery': '🔋',
        'mouse': '🖱️',
        'keyboard': '⌨️',
        'gaming': '🎮',
        'console': '🎮',
    }
    
    # Check product name first
    product_name = product.name.lower()
    for keyword, emoji in emoji_map.items():
        if keyword in product_name:
            return emoji
    
    # Check category if available
    if product.category:
        category_name = product.category.name.lower()
        for keyword, emoji in emoji_map.items():
            if keyword in category_name:
                return emoji
    
    return '📦'




def product_detail(request, pk):
    """Product detail page"""
    product = get_object_or_404(Product, pk=pk, is_active=True)
    
    # Increment view count
    product.view_count += 1
    product.save(update_fields=['view_count'])
    
    # Get related products (same category)
    related_products = Product.objects.filter(
        category=product.category,
        is_active=True
    ).exclude(id=product.id)[:4]
    
    context = {
        'product': product,
        'related_products': related_products,
    }
    
    return render(request, 'website/product_detail.html', context)






# ============================================
# TRENDING STATS
# ============================================
@require_http_methods(["GET"])
def trending_stats(request):
    """
    API endpoint to get trending products and recent activity stats
    """
    try:
        # Get recent orders (last 7 days)
        week_ago = timezone.now() - timedelta(days=7)
        recent_orders = Order.objects.filter(
            created_at__gte=week_ago
        ).count()
        
        # Get trending products - only those with categories
        trending = Product.objects.filter(
            Q(status='available') | Q(status='lowstock'),
            category__isnull=False,
            is_active=True
        ).order_by('-view_count')[:5]
        
        trending_list = []
        for p in trending:
            trending_list.append({
                'id': p.id,
                'name': p.name,
                'price': float(p.selling_price),
                'views': getattr(p, 'view_count', 0)
            })
        
        return JsonResponse({
            'success': True,
            'data': {
                'recent_orders': recent_orders,
                'trending_products': trending_list
            }
        })
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)









# ============================================
# PRODUCT VIEW INCREMENT
# ============================================
@require_http_methods(["POST"])
@csrf_exempt
def increment_product_view(request, product_id):
    """
    Increment view count when a product is viewed
    """
    try:
        product = Product.objects.get(id=product_id)
        if hasattr(product, 'view_count'):
            product.view_count += 1
            product.save(update_fields=['view_count'])
        
        return JsonResponse({
            'success': True,
            'view_count': getattr(product, 'view_count', 0)
        })
    
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Product not found'
        }, status=404)
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)








# ============================================
# DASHBOARD URL CONTEXT PROCESSOR
# ============================================

def dashboard_url(request):
    """Make dashboard URL available globally in all templates"""
    url = '#'  # Default fallback
    
    if request.user.is_authenticated:
        user = request.user
        print(f"[DEBUG] User authenticated: {user.username}")
        print(f"[DEBUG] User has profile: {hasattr(user, 'profile')}")
        
        if hasattr(user, 'profile') and user.profile:
            profile = user.profile
            print(f"[DEBUG] Profile exists, role: {getattr(profile, 'role', None)}")
            
            if profile.role:
                role_name = profile.role.name.lower()
                print(f"[DEBUG] Role name: {role_name}")
                
                # Map role names to dashboard URLs
                role_urls = {
                    'admin': '/admin-dashboard/',
                    'manager': '/manager-dashboard/',
                    'agent': '/agent-dashboard/',
                    'cashier': '/cashier-dashboard/',
                    'seller': '/seller-dashboard/',
                }
                
                url = role_urls.get(role_name, '#')
            else:
                print(f"[DEBUG] Profile exists but no role assigned")
        elif user.is_superuser:
            print(f"[DEBUG] User is superuser")
            url = '/admin-dashboard/'
        else:
            print(f"[DEBUG] User authenticated but no profile or superuser")
    
    print(f"[DEBUG] Final dashboard_url: {url}")
    return {'dashboard_url': url}









# ============================================
# PRODUCTS PAGE
# ============================================
@require_http_methods(["GET"])
def products_page(request):
    """
    Products listing page
    """
    products = Product.objects.filter(
        is_active=True,
        status__in=['available', 'lowstock'],
        category__isnull=False  # Only show products with categories
    ).select_related('category').order_by('-created_at')
    
    context = {
        'page_title': 'Shop - Fieldmax',
        'products': products
    }
    
    return render(request, 'website/products.html', context)








# ============================================
# API FEATURED PRODUCTS
# ============================================
@require_http_methods(["GET"])
def api_featured_products(request):
    """
    API endpoint to get featured/best-selling products for home page
    URL: /api/featured-products/
    """
    try:
        products = Product.objects.filter(
            is_active=True,
            status__in=['available', 'lowstock'],
            category__isnull=False  # Only products with categories
        ).select_related('category').annotate(
            sales_count=Count('sale_items')
        ).order_by('-sales_count', '-created_at')[:8]
        
        product_list = []
        
        for product in products:
            badge = 'HOT' if getattr(product, 'sales_count', 0) > 5 else 'NEW'
            if product.status == 'lowstock':
                badge = 'SALE'
            
            # Get product emoji based on category
            emoji = '📱'  # Default
            if product.category:
                category_name = product.category.name.lower()
                if 'phone' in category_name or 'mobile' in category_name:
                    emoji = '📱'
                elif 'headphone' in category_name or 'earphone' in category_name:
                    emoji = '🎧'
                elif 'watch' in category_name:
                    emoji = '⌚'
                elif 'accessory' in category_name or 'cable' in category_name:
                    emoji = '🔌'
                elif 'screen' in category_name or 'protector' in category_name:
                    emoji = '🛡️'
            
            product_data = {
                'id': product.id,
                'name': product.name,
                'product_code': product.product_code,
                'price': float(product.selling_price or 0),
                'category': product.category.name if product.category else 'Uncategorized',
                'status': product.status,
                'quantity': product.quantity or 0,
                'is_single_item': product.category.is_single_item if product.category else False,
                'badge': badge,
                'emoji': emoji,
                'image': None
            }
            
            product_list.append(product_data)
        
        logger.info(f"[API] Returned {len(product_list)} featured products")
        
        return JsonResponse({
            'success': True,
            'products': product_list,
            'count': len(product_list)
        })
        
    except Exception as e:
        logger.error(f"[API ERROR] Featured products: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e),
            'products': []
        }, status=500)








# ============================================
# API HOME STATS
# ============================================
@require_http_methods(["GET"])
def api_home_stats(request):
    """
    API endpoint for homepage statistics
    URL: /api/home-stats/
    """
    try:
        # Total products in stock with categories
        total_products = Product.objects.filter(
            is_active=True,
            quantity__gt=0,
            category__isnull=False
        ).count()
        
        # Total customers (unique buyers)
        total_customers = Sale.objects.filter(
            buyer_name__isnull=False
        ).values('buyer_phone').distinct().count()
        
        # Calculate satisfaction
        total_sales = Sale.objects.filter(is_reversed=False).count()
        total_returns = Sale.objects.filter(is_reversed=True).count()
        
        if total_sales > 0:
            satisfaction = int(((total_sales - total_returns) / total_sales) * 100)
        else:
            satisfaction = 98
        
        stats = {
            'total_products': total_products,
            'total_customers': min(total_customers * 1000, 100000),
            'satisfaction': satisfaction,
            'support': '24/7'
        }
        
        return JsonResponse({
            'success': True,
            'stats': stats
        })
        
    except Exception as e:
        logger.error(f"[API ERROR] Home stats: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e),
            'stats': {
                'total_products': 1000,
                'total_customers': 50000,
                'satisfaction': 98,
                'support': '24/7'
            }
        })







# ============================================
# API PRODUCTS BY CATEGORY
# ============================================

@require_http_methods(["GET"])
def api_product_categories(request):
    """
    Get all active categories with product counts
    URL: /api/categories/
    """
    try:
        categories = Category.objects.filter(
            products__is_active=True
        ).distinct()
        
        category_list = []
        for cat in categories:
            # Calculate count manually
            product_count = cat.products.filter(is_active=True).count()
            category_list.append({
                'id': cat.id,
                'name': cat.name,
                'code': cat.category_code,
                'item_type': cat.get_item_type_display(),
                'product_count': product_count
            })
        
        return JsonResponse({
            'success': True,
            'categories': category_list
        })
        
    except Exception as e:
        logger.error(f"[API ERROR] Categories: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e),
            'categories': []
        }, status=500)






# ============================================
# API QUICK SEARCH
# ============================================
@require_http_methods(["POST"])
def api_quick_search(request):
    """
    Quick product search for home page search bar
    URL: /api/quick-search/
    """
    try:
        data = json.loads(request.body)
        search_term = data.get('search', '').strip()
        
        if not search_term or len(search_term) < 2:
            return JsonResponse({
                'success': False,
                'message': 'Search term too short',
                'products': []
            })
        
        products = Product.objects.filter(
            Q(name__icontains=search_term) |
            Q(product_code__icontains=search_term) |
            Q(sku_value__icontains=search_term),
            is_active=True,
            category__isnull=False  # Only products with categories
        ).select_related('category')[:10]
        
        results = []
        for product in products:
            results.append({
                'id': product.id,
                'name': product.name,
                'product_code': product.product_code,
                'price': float(product.selling_price or 0),
                'category': product.category.name if product.category else 'Other',
                'status': product.status,
                'url': f'/products/{product.id}/'
            })
        
        return JsonResponse({
            'success': True,
            'products': results,
            'count': len(results)
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON',
            'products': []
        }, status=400)
    except Exception as e:
        logger.error(f"[API ERROR] Quick search: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e),
            'products': []
        }, status=500)



# ============================================
# ORDER SEARCH - PUBLIC
# ============================================
from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
@require_http_methods(["POST", "GET"])
def search_order(request):
    """
    Public endpoint to search for an order by order ID or phone number
    URL: /search-order/
    """
    if request.method == "GET":
        return render(request, 'website/search_order.html', {
            'page_title': 'Track Your Order - Fieldmax'
        })
    
    try:
        data = json.loads(request.body) if request.body else request.POST
        search_term = data.get('search_term', '').strip()
        
        if not search_term:
            return JsonResponse({
                'success': False,
                'message': 'Please enter an order ID or phone number'
            })
        
        # Search by order ID first
        order = None
        try:
            order = PendingOrder.objects.filter(
                Q(order_id__icontains=search_term) |
                Q(buyer_phone__icontains=search_term) |
                Q(buyer_name__icontains=search_term)
            ).first()
        except:
            pass
        
        if not order:
            # Try Sale model as fallback
            try:
                from sales.models import Sale
                sale = Sale.objects.filter(
                    Q(sale_id__icontains=search_term) |
                    Q(buyer_phone__icontains=search_term) |
                    Q(buyer_name__icontains=search_term)
                ).first()
                
                if sale:
                    return JsonResponse({
                        'success': True,
                        'order_type': 'sale',
                        'order': {
                            'order_id': sale.sale_id,
                            'buyer_name': sale.buyer_name,
                            'buyer_phone': sale.buyer_phone,
                            'total_amount': float(sale.total_amount),
                            'status': 'completed',
                            'created_at': sale.sale_date.isoformat() if sale.sale_date else None,
                            'payment_method': sale.payment_method,
                            'receipt_url': f'/sales/receipt/{sale.sale_id}/'
                        }
                    })
            except:
                pass
            
            return JsonResponse({
                'success': False,
                'message': f'No order found matching "{search_term}"'
            })
        
        # Parse cart items
        try:
            cart_items = json.loads(order.cart_data) if order.cart_data else []
        except:
            cart_items = []
        
        # Get status display
        status_display = {
            'pending': 'Pending Review',
            'approved': 'Approved',
            'completed': 'Completed',
            'rejected': 'Rejected',
            'cancelled': 'Cancelled'
        }.get(order.status, order.status.title())
        
        # Determine status color
        status_color = {
            'pending': 'warning',
            'approved': 'info',
            'completed': 'success',
            'rejected': 'danger',
            'cancelled': 'secondary'
        }.get(order.status, 'secondary')
        
        order_data = {
            'order_id': order.order_id,
            'buyer_name': order.buyer_name,
            'buyer_phone': order.buyer_phone,
            'buyer_email': order.buyer_email or '',
            'total_amount': float(order.total_amount),
            'status': order.status,
            'status_display': status_display,
            'status_color': status_color,
            'payment_method': order.payment_method,
            'created_at': order.created_at.isoformat() if order.created_at else None,
            'notes': order.notes or '',
            'item_count': len(cart_items),
            'items': cart_items,
            'sale_id': order.sale_id
        }
        
        return JsonResponse({
            'success': True,
            'order_type': 'pending',
            'order': order_data
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid request data'
        }, status=400)
    except Exception as e:
        logger.error(f"[ORDER SEARCH ERROR] {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'Search failed: {str(e)}'
        }, status=500)


# ============================================
# ORDER SEARCH PAGE - PUBLIC
# ============================================
def order_search_page(request):
    """
    Render the order search page
    URL: /orders/search/
    """
    return render(request, 'website/search_order.html', {
        'page_title': 'Track Your Order - Fieldmax'
    })



# ============================================
# SHOPPING CART
# ============================================
def shopping_cart(request):
    """Display shopping cart page"""
    return render(request, 'website/cart.html', {
        'page_title': 'Shopping Cart - Fieldmax'
    })








# ============================================
# VALIDATE CART
# ============================================
@require_http_methods(["POST"])
def validate_cart(request):
    """
    Validate cart items against current database inventory
    Returns updated prices and availability
    """
    try:
        data = json.loads(request.body)
        cart_items = data.get('cart', [])
        
        validated_items = []
        total = 0
        errors = []
        
        for item in cart_items:
            product_id = item.get('id')
            quantity = item.get('quantity', 1)
            
            try:
                product = Product.objects.get(id=product_id, is_active=True)
                
                # Check if product has category
                if not product.category:
                    errors.append(f"{product.name} has no category assigned and cannot be purchased")
                    continue
                
                # Check availability
                if product.status == 'sold':
                    errors.append(f"{product.name} has been sold")
                    continue
                
                if product.category.is_single_item and quantity > 1:
                    errors.append(f"{product.name} is a single item (quantity must be 1)")
                    quantity = 1
                
                if not product.category.is_single_item and product.quantity < quantity:
                    errors.append(f"Only {product.quantity} units of {product.name} available")
                    quantity = product.quantity
                
                # Validate price hasn't changed
                current_price = float(product.selling_price or 0)
                cart_price = float(item.get('price', 0))
                
                price_changed = abs(current_price - cart_price) > 0.01
                
                validated_item = {
                    'id': product.id,
                    'name': product.name,
                    'product_code': product.product_code,
                    'price': current_price,
                    'old_price': cart_price if price_changed else None,
                    'quantity': quantity,
                    'max_quantity': product.quantity if not product.category.is_single_item else 1,
                    'is_single_item': product.category.is_single_item,
                    'subtotal': current_price * quantity,
                    'available': True
                }
                
                validated_items.append(validated_item)
                total += validated_item['subtotal']
                
            except Product.DoesNotExist:
                errors.append(f"Product ID {product_id} not found")
        
        return JsonResponse({
            'success': True,
            'items': validated_items,
            'total': total,
            'errors': errors,
            'item_count': len(validated_items)
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Cart validation error: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)






# ============================================
# CHECKOUT
# ============================================
@require_http_methods(["POST"])
def checkout(request):
    """
    Process checkout - create sales for cart items
    """
    try:
        data = json.loads(request.body)
        cart_items = data.get('cart', [])
        buyer_name = data.get('buyer_name', '').strip()
        buyer_phone = data.get('buyer_phone', '').strip()
        buyer_id = data.get('buyer_id', '').strip()
        
        if not cart_items:
            return JsonResponse({
                'success': False,
                'message': 'Cart is empty'
            }, status=400)
        
        if not buyer_name or not buyer_phone:
            return JsonResponse({
                'success': False,
                'message': 'Customer name and phone are required'
            }, status=400)
        
        # Redirect to sales system for actual checkout
        request.session['checkout_cart'] = cart_items
        request.session['checkout_buyer'] = {
            'name': buyer_name,
            'phone': buyer_phone,
            'id_number': buyer_id
        }
        
        return JsonResponse({
            'success': True,
            'message': 'Redirecting to checkout...',
            'redirect_url': '/sales/checkout/'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid request data'
        }, status=400)
    except Exception as e:
        logger.error(f"Checkout error: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'Checkout failed: {str(e)}'
        }, status=500)








# ============================================
# CREATE PENDING ORDER
# ============================================
@csrf_exempt
@require_http_methods(["POST"])
def public_create_order(request):
    """
    DEFINITELY public endpoint for customer orders
    """
    try:
        data = json.loads(request.body)
        
        cart_items = data.get('cart', [])
        buyer_name = data.get('buyer_name', '').strip()
        buyer_phone = data.get('buyer_phone', '').strip()
        
        if not cart_items:
            return JsonResponse({
                'success': False,
                'message': 'Cart is empty'
            }, status=400)
        
        if not buyer_name or not buyer_phone:
            return JsonResponse({
                'success': False,
                'message': 'Buyer name and phone are required'
            }, status=400)
        
        # Calculate totals
        item_count = sum(item.get('quantity', 1) for item in cart_items)
        total_amount = sum(
            float(item.get('price', 0)) * item.get('quantity', 1) 
            for item in cart_items
        )
        
        # Create PendingOrder
        with transaction.atomic():
            order = PendingOrder.objects.create(
                buyer_name=buyer_name,
                buyer_phone=buyer_phone,
                buyer_email=data.get('buyer_email', ''),
                buyer_id_number=data.get('buyer_id', ''),
                payment_method=data.get('payment_method', 'cash'),
                notes=data.get('notes', ''),
                cart_data=json.dumps(cart_items),
                total_amount=total_amount,
                item_count=item_count,
                status='pending'
            )
            
            # Create individual order items
            for item in cart_items:
                PendingOrderItem.objects.create(
                    order=order,
                    product_name=item.get('name', 'Unknown'),
                    quantity=item.get('quantity', 1),
                    unit_price=item.get('price', 0)
                )
        
        logger.info(
            f"[PUBLIC ORDER CREATED] {order.order_id} | "
            f"Buyer: {buyer_name} | Items: {item_count} | "
            f"Total: KSh {total_amount}"
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Order submitted successfully!',
            'order_id': order.order_id,
            'redirect_url': '/order-success/'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"[PUBLIC ORDER ERROR] {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'Failed to create order: {str(e)}'
        }, status=500)







# ============================================
# CHECKOUT PAGE
# ============================================
@require_http_methods(["GET"])
def checkout_page(request):
    """
    Render checkout page
    URL: /checkout/
    """
    return render(request, 'website/checkout.html', {
        'page_title': 'Checkout - Fieldmax'
    })






# ============================================
# API: GET PENDING ORDERS WITH APPROVER INFO
# ============================================
def api_pending_orders(request):
    """
    API endpoint to get all pending orders with approver info
    URL: /api/pending-orders/
    """
    try:
        orders = PendingOrder.objects.all().order_by('-created_at')
        
        # Use the serializer if available, otherwise build manually
        try:
            from .serializers import PendingOrderSerializer
            serializer = PendingOrderSerializer(orders, many=True)
            orders_data = serializer.data
        except ImportError:
            # Fallback to manual serialization
            orders_data = []
            for order in orders:
                orders_data.append({
                    'order_id': order.order_id,
                    'buyer_name': order.buyer_name,
                    'buyer_phone': order.buyer_phone,
                    'buyer_id_number': order.buyer_id_number or '',
                    'buyer_email': order.buyer_email or '',
                    'total_amount': float(order.total_amount),
                    'status': order.status,
                    'created_at': order.created_at.isoformat(),
                    'approved_by': order.approved_by.get_full_name() if order.approved_by else None,
                    'rejected_by': order.rejected_by.get_full_name() if order.rejected_by else None,
                    'approved_at': order.approved_at.isoformat() if order.approved_at else None,
                    'rejected_at': order.rejected_at.isoformat() if order.rejected_at else None,
                    'rejection_reason': order.rejection_reason
                })
        
        return JsonResponse({
            'success': True,
            'orders': orders_data
        })
        
    except Exception as e:
        logger.error(f"[API PENDING ORDERS ERROR] {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e),
            'orders': []
        }, status=500)







# ============================================
# STAFF VIEW: LIST PENDING ORDERS
# ============================================
@login_required
@require_http_methods(["GET"])
def pending_orders_list(request):
    """
    Staff view to see all pending orders
    URL: /staff/pending-orders/
    """
    pending_orders = PendingOrder.objects.filter(
        status__iexact='pending'
    ).prefetch_related('items').order_by('-created_at')

    context = {
        'page_title': 'Pending Orders - Fieldmax',
        'pending_orders': pending_orders,
        'pending_count': pending_orders.count()
    }

    return render(request, 'website/pending_orders.html', context)







# ============================================
# API: GET PENDING ORDERS COUNT
# ============================================
@login_required
@require_http_methods(["GET"])
def pending_orders_count(request):
    """
    API endpoint to get count of pending orders (for staff badge)
    URL: /api/pending-orders/count/
    """
    try:
        count = PendingOrder.objects.filter(status='pending').count()
        return JsonResponse({
            'success': True,
            'count': count
        })
    except Exception as e:
        logger.error(f"[PENDING COUNT ERROR] {str(e)}")
        return JsonResponse({
            'success': False,
            'count': 0,
            'error': str(e)
        })
    





@login_required
@require_http_methods(["GET"])
def api_get_all_orders(request):
    """Get all pending orders for admin view"""
    try:
        orders = PendingOrder.objects.all().order_by('-created_at')
        
        orders_list = []
        for order in orders:
            orders_list.append({
                'order_id': order.order_id,
                'buyer_name': order.buyer_name,
                'buyer_phone': order.buyer_phone,
                'buyer_id_number': order.buyer_id_number or '',
                'buyer_email': order.buyer_email or '',
                'total_amount': float(order.total_amount),
                'status': order.status,
                'created_at': order.created_at.isoformat(),
            })
        
        return JsonResponse({
            'success': True,
            'orders': orders_list
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)





# ============================================
# APPROVE ORDER WITH ETR GENERATION
# ============================================
@login_required
@require_http_methods(["POST"])
def approve_order(request, order_id):
    """
    Staff approves order → Creates actual Sale with ETR number
    URL: /staff/approve-order/<order_id>/
    """
    try:
        # Get pending order
        pending_order = PendingOrder.objects.get(
            order_id=order_id,
            status='pending'
        )
        
        with transaction.atomic():
            # Lock the pending order
            pending_order = PendingOrder.objects.select_for_update().get(
                pk=pending_order.pk
            )
            
            # Parse cart items
            cart_items = pending_order.cart_items
            
            # STEP 1: CREATE THE SALE
            sale = Sale.objects.create(
                seller=request.user,
                buyer_name=pending_order.buyer_name,
                buyer_phone=pending_order.buyer_phone,
                buyer_id_number=pending_order.buyer_id_number,
                payment_method=pending_order.payment_method,
                etr_status='pending'
            )
            
            logger.info(f"[ORDER APPROVAL] Created Sale {sale.sale_id} from pending order {order_id}")
            
            # STEP 2: ADD ITEMS TO SALE
            created_items = []
            errors = []
            
            for item in cart_items:
                try:
                    # Get product from database with lock
                    product = Product.objects.select_for_update().get(
                        id=item['id'],
                        is_active=True
                    )
                    
                    # Check if product has category
                    if not product.category:
                        errors.append(f"{product.name} has no category assigned and cannot be sold")
                        continue
                    
                    quantity = item['quantity']
                    
                    # Validate availability
                    if product.status == 'sold' and product.category.is_single_item:
                        errors.append(f"{product.name} is no longer available")
                        continue
                    
                    if not product.category.is_single_item and product.quantity < quantity:
                        errors.append(f"Only {product.quantity} units of {product.name} available")
                        continue
                    
                    # Create SaleItem
                    sale_item = SaleItem.objects.create(
                        sale=sale,
                        product=product,
                        product_code=product.product_code,
                        product_name=product.name,
                        sku_value=product.sku_value,
                        quantity=quantity,
                        unit_price=product.selling_price,
                    )
                    
                    # Process sale (deduct stock)
                    sale_item.process_sale()
                    created_items.append(sale_item)
                    
                except Product.DoesNotExist:
                    errors.append(f"Product ID {item['id']} not found")
                    continue
                except Exception as e:
                    logger.error(f"[APPROVAL ITEM ERROR] {str(e)}", exc_info=True)
                    errors.append(f"Error: {str(e)}")
                    continue
            
            if not created_items:
                raise Exception("No items could be processed: " + "; ".join(errors))
            
            # Refresh sale to get calculated totals
            sale.refresh_from_db()
            
            # STEP 3: GENERATE ETR NUMBER FROM SALE ID
            etr_number = generate_etr_from_sale_id(sale.sale_id)
            
            sale.etr_receipt_number = etr_number
            sale.etr_status = 'generated'
            sale.etr_processed_at = timezone.now()
            
            if hasattr(sale, 'fiscal_receipt_number'):
                sale.fiscal_receipt_number = etr_number
            
            sale.save(update_fields=[
                'etr_receipt_number',
                'fiscal_receipt_number',
                'etr_status',
                'etr_processed_at'
            ])
            
            logger.info(
                f"[ETR GENERATED] Sale: {sale.sale_id} | "
                f"ETR: {etr_number} | "
                f"From pending order: {order_id}"
            )
            
            # STEP 4: UPDATE PENDING ORDER WITH APPROVER INFO
            pending_order.status = 'completed'
            pending_order.sale_id = sale.sale_id
            pending_order.approved_by = request.user  # NEW: Track who approved
            pending_order.approved_at = timezone.now()  # NEW: Track when
            pending_order.reviewed_by = request.user
            pending_order.reviewed_at = timezone.now()
            pending_order.save()
            
            logger.info(
                f"[ORDER APPROVED] {pending_order.order_id} → Sale {sale.sale_id} | "
                f"Approved by: {request.user.username} | "
                f"Items: {len(created_items)}/{len(cart_items)} | "
                f"ETR: {etr_number}"
            )
            
            return JsonResponse({
                'success': True,
                'message': f'Order approved! Sale {sale.sale_id} created with {len(created_items)} items.',
                'sale_id': sale.sale_id,
                'etr_receipt_number': etr_number,
                'fiscal_receipt_number': etr_number,
                'items_processed': len(created_items),
                'total_items': len(cart_items),
                'total_amount': float(sale.total_amount),
                'receipt_url': f'/sales/receipt/{sale.sale_id}/',
                'errors': errors if errors else None
            })
            
    except PendingOrder.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Order not found or already processed'
        }, status=404)
    except Exception as e:
        logger.error(f"[ORDER APPROVAL ERROR] {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'Failed to approve order: {str(e)}'
        }, status=500)






# ============================================
# ETR GENERATION HELPER
# ============================================
def generate_etr_from_sale_id(sale_id):
    """
    Generate ETR number from Sale ID
    Extracts numeric portion from sale_id
    """
    try:
        if '-' in str(sale_id):
            numeric_part = str(sale_id).split('-')[-1]
        else:
            numeric_part = str(sale_id).replace('#', '').replace('SALE', '')
        
        numeric_part = numeric_part.strip()
        
        if not numeric_part.isdigit():
            logger.warning(f"[ETR WARNING] Non-numeric sale_id: {sale_id}, using fallback")
            return "0000"
        
        logger.info(f"[ETR GENERATION] Sale ID: {sale_id} → ETR: {numeric_part}")
        
        return numeric_part
    
    except Exception as e:
        logger.error(f"[ETR ERROR] Failed to extract from {sale_id}: {e}")
        return "0000"






# ============================================
# STAFF ACTION: REJECT ORDER
# ============================================
@login_required
@require_http_methods(["POST"])
def reject_order(request, order_id):
    """
    Staff rejects order
    URL: /staff/reject-order/<order_id>/
    """
    try:
        data = json.loads(request.body)
        reason = data.get('reason', 'No reason provided')
        
        pending_order = PendingOrder.objects.get(
            order_id=order_id,
            status='pending'
        )
        
        # Update with rejection info
        pending_order.status = 'rejected'
        pending_order.rejection_reason = reason
        pending_order.rejected_by = request.user  # NEW: Track who rejected
        pending_order.rejected_at = timezone.now()  # NEW: Track when
        pending_order.reviewed_by = request.user
        pending_order.reviewed_at = timezone.now()
        pending_order.save()
        
        logger.info(
            f"[ORDER REJECTED] {pending_order.order_id} | "
            f"Rejected by: {request.user.username} | "
            f"Reason: {reason}"
        )
        
        return JsonResponse({
            'success': True,
            'message': 'Order rejected successfully'
        })
        
    except PendingOrder.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Order not found'
        }, status=404)
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid request data'
        }, status=400)
    except Exception as e:
        logger.error(f"[ORDER REJECTION ERROR] {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'Failed to reject order: {str(e)}'
        }, status=500)





# ============================================
# PROCESS ORDER
# ============================================
@require_http_methods(["POST"])
def process_order(request):
    """
    Process order with new Sale/SaleItem structure
    """
    try:
        data = json.loads(request.body)
        
        cart_items = data.get('cart', [])
        buyer_name = data.get('buyer_name', '').strip()
        buyer_phone = data.get('buyer_phone', '').strip()
        buyer_email = data.get('buyer_email', '').strip()
        buyer_id = data.get('buyer_id', '').strip()
        payment_method = data.get('payment_method', 'cash')
        notes = data.get('notes', '').strip()
        
        if not cart_items:
            return JsonResponse({
                'success': False,
                'message': 'Cart is empty'
            }, status=400)
        
        if not buyer_name or not buyer_phone:
            return JsonResponse({
                'success': False,
                'message': 'Buyer name and phone are required'
            }, status=400)
        
        with transaction.atomic():
            # STEP 1: CREATE THE SALE
            seller = request.user if request.user.is_authenticated else User.objects.filter(is_superuser=True).first()
            
            sale = Sale.objects.create(
                seller=seller,
                buyer_name=buyer_name,
                buyer_phone=buyer_phone,
                buyer_id_number=buyer_id,
                payment_method=payment_method,
            )
            
            logger.info(f"[WEB ORDER] Created Sale {sale.sale_id} for {buyer_name}")
            
            # STEP 2: ADD ITEMS TO THE SALE
            created_items = []
            errors = []
            
            for item in cart_items:
                try:
                    product = Product.objects.select_for_update().get(
                        id=item['id'],
                        is_active=True
                    )
                    
                    # Check if product has category
                    if not product.category:
                        errors.append(f"{product.name} has no category assigned and cannot be sold")
                        continue
                    
                    quantity = item['quantity']
                    
                    # Validate product availability
                    if product.status == 'sold' and product.category.is_single_item:
                        errors.append(f"{product.name} is no longer available (already sold)")
                        continue
                    
                    if not product.category.is_single_item and product.quantity < quantity:
                        errors.append(f"Only {product.quantity} units of {product.name} available")
                        continue
                    
                    # CREATE SALE ITEM
                    sale_item = SaleItem.objects.create(
                        sale=sale,
                        product=product,
                        product_code=product.product_code,
                        product_name=product.name,
                        sku_value=product.sku_value,
                        quantity=quantity,
                        unit_price=product.selling_price,
                    )
                    
                    # PROCESS THE SALE (DEDUCT STOCK)
                    sale_item.process_sale()
                    
                    created_items.append(sale_item)
                    
                    logger.info(
                        f"[WEB ORDER ITEM] Sale: {sale.sale_id} | "
                        f"Product: {product.product_code} | "
                        f"Qty: {quantity} | "
                        f"Price: KSh {sale_item.total_price}"
                    )
                    
                except Product.DoesNotExist:
                    errors.append(f"Product ID {item['id']} not found")
                    continue
                except Exception as e:
                    logger.error(f"Error processing item {item['id']}: {str(e)}", exc_info=True)
                    errors.append(f"Error processing {item.get('name', 'item')}: {str(e)}")
                    continue
            
            # STEP 3: VALIDATE RESULTS
            if not created_items:
                raise Exception("No items could be processed. " + "; ".join(errors))
            
            sale.refresh_from_db()
            
            # STEP 4: PREPARE RESPONSE
            success_count = len(created_items)
            total_count = len(cart_items)
            
            response_data = {
                'success': True,
                'message': f'Order placed successfully! {success_count} of {total_count} items processed.',
                'order_count': success_count,
                'sale_id': sale.sale_id,
                'total_amount': float(sale.total_amount),
                'items': [
                    {
                        'product_name': item.product_name,
                        'quantity': item.quantity,
                        'amount': float(item.total_price)
                    }
                    for item in created_items
                ],
                'redirect_url': '/order-success/',
                'errors': errors if errors else None
            }
            
            # Store order info in session for success page
            request.session['last_order'] = {
                'sale_id': sale.sale_id,
                'buyer_name': buyer_name,
                'buyer_phone': buyer_phone,
                'total_amount': float(sale.total_amount),
                'item_count': success_count,
                'payment_method': payment_method,
                'items': [
                    {
                        'name': item.product_name,
                        'quantity': item.quantity,
                        'total': float(item.total_price)
                    }
                    for item in created_items
                ]
            }
            
            logger.info(
                f"[WEB ORDER COMPLETE] Sale: {sale.sale_id} | "
                f"Items: {success_count} | "
                f"Total: KSh {sale.total_amount} | "
                f"Buyer: {buyer_name}"
            )
            
            return JsonResponse(response_data)
            
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Order processing error: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'Failed to process order: {str(e)}'
        }, status=500)




# ============================================
# API: GET SINGLE ORDER DETAILS
# ============================================
@login_required
@require_http_methods(["GET"])
def api_single_order_details(request, order_id):
    """
    API endpoint to get detailed information about a specific order
    URL: /api/pending-orders/<order_id>/
    """
    try:
        order = PendingOrder.objects.get(order_id=order_id)
        
        # Parse cart data
        try:
            cart_items = json.loads(order.cart_data) if order.cart_data else []
        except:
            cart_items = []
        
        # Get user display names
        approved_by_name = None
        rejected_by_name = None
        reviewed_by_name = None
        
        if order.approved_by:
            approved_by_name = order.approved_by.get_full_name() or order.approved_by.username
        if order.rejected_by:
            rejected_by_name = order.rejected_by.get_full_name() or order.rejected_by.username
        if order.reviewed_by:
            reviewed_by_name = order.reviewed_by.get_full_name() or order.reviewed_by.username
        
        order_data = {
            'order_id': order.order_id,
            'buyer_name': order.buyer_name,
            'buyer_phone': order.buyer_phone,
            'buyer_email': order.buyer_email or '',
            'buyer_id_number': order.buyer_id_number or '',
            'total_amount': float(order.total_amount),
            'payment_method': order.payment_method,
            'notes': order.notes or '',
            'status': order.status,
            'cart_items': cart_items,
            'created_at': order.created_at.isoformat() if order.created_at else None,
            'updated_at': order.updated_at.isoformat() if order.updated_at else None,
            'approved_date': order.approved_date.isoformat() if order.approved_date else None,
            'rejected_date': order.rejected_date.isoformat() if order.rejected_date else None,
            'reviewed_at': order.reviewed_at.isoformat() if order.reviewed_at else None,
            'approved_by': approved_by_name,
            'rejected_by': rejected_by_name,
            'reviewed_by': reviewed_by_name,
            'rejection_reason': order.rejection_reason,
            'sale_id': order.sale_id
        }
        
        return JsonResponse({
            'success': True,
            'order': order_data
        })
        
    except PendingOrder.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Order not found'
        }, status=404)
    except Exception as e:
        import traceback
        logger.error(f"[ORDER DETAILS ERROR] {str(e)}\n{traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)





# ============================================
# API: GET SINGLE ORDER DETAILS FOR NOTIFICATIONS
# ============================================
# Add this NEW function to views.py (replace the old one)
@login_required
@require_http_methods(["GET"])
def get_order_details_notification(request, order_id):
    """
    Get detailed information about a specific order
    URL: /api/pending-orders/<order_id>/
    """
    try:
        order = PendingOrder.objects.get(order_id=order_id)
        
        # Parse cart data
        try:
            cart_items = json.loads(order.cart_data) if order.cart_data else []
        except:
            cart_items = []
        
        # Get user display names safely
        approved_by_name = None
        rejected_by_name = None
        reviewed_by_name = None
        
        if order.approved_by:
            approved_by_name = order.approved_by.get_full_name() or order.approved_by.username
        if order.rejected_by:
            rejected_by_name = order.rejected_by.get_full_name() or order.rejected_by.username
        if order.reviewed_by:
            reviewed_by_name = order.reviewed_by.get_full_name() or order.reviewed_by.username
        
        order_data = {
            'order_id': order.order_id,
            'buyer_name': order.buyer_name,
            'buyer_phone': order.buyer_phone,
            'buyer_email': order.buyer_email or '',
            'buyer_id_number': order.buyer_id_number or '',
            'total_amount': float(order.total_amount),
            'payment_method': order.payment_method,
            'notes': order.notes or '',
            'status': order.status,
            'cart_items': cart_items,
            'created_at': order.created_at.isoformat() if order.created_at else None,
            'updated_at': order.updated_at.isoformat() if order.updated_at else None,
            'approved_date': order.approved_date.isoformat() if order.approved_date else None,  # CORRECT FIELD NAME
            'rejected_date': order.rejected_date.isoformat() if order.rejected_date else None,  # CORRECT FIELD NAME
            'reviewed_at': order.reviewed_at.isoformat() if order.reviewed_at else None,
            'approved_by': approved_by_name,
            'rejected_by': rejected_by_name,
            'reviewed_by': reviewed_by_name,
            'rejection_reason': order.rejection_reason,
            'sale_id': order.sale_id
        }
        
        return JsonResponse({
            'success': True,
            'order': order_data
        })
        
    except PendingOrder.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Order not found'
        }, status=404)
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"[ORDER DETAILS ERROR] {str(e)}\n{error_trace}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)






# ============================================
# NOTIFICATION SYSTEM - ADD THESE FUNCTIONS
# ============================================

@login_required
@require_http_methods(["GET"])
def get_notifications(request):
    """
    Get all notifications (pending orders and recent activity)
    URL: /api/notifications/
    """
    try:
        # Get pending orders
        pending_orders = PendingOrder.objects.filter(
            status='pending'
        ).order_by('-created_at')[:20]
        
        # Get completed/rejected orders from last 24 hours
        yesterday = timezone.now() - timezone.timedelta(days=1)
        recent_orders = PendingOrder.objects.filter(
            status__in=['completed', 'rejected'],
            updated_at__gte=yesterday
        ).order_by('-updated_at')[:10]
        
        notifications = []
        
        # Add pending order notifications
        for order in pending_orders:
            try:
                cart_items = json.loads(order.cart_data) if order.cart_data else []
            except:
                cart_items = []
            
            item_count = len(cart_items)
            
            notifications.append({
                'id': f'pending_{order.id}',
                'order_id': order.order_id,
                'type': 'pending_order',
                'status': 'pending',
                'title': 'New Order Pending Review',
                'message': f'Order #{order.order_id} for Ksh {order.total_amount:,.0f} from {order.buyer_name}',
                'buyer_name': order.buyer_name,
                'buyer_phone': order.buyer_phone,
                'total_amount': float(order.total_amount),
                'item_count': item_count,
                'created_at': order.created_at.isoformat(),
                'read': False
            })
        
        # Add recent activity notifications
        for order in recent_orders:
            if order.status == 'completed':
                notifications.append({
                    'id': f'completed_{order.id}',
                    'order_id': order.order_id,
                    'type': 'order_completed',
                    'status': 'completed',
                    'title': 'Order Completed',
                    'message': f'Order #{order.order_id} from {order.buyer_name} was approved and processed',
                    'created_at': order.updated_at.isoformat(),
                    'read': True
                })
            elif order.status == 'rejected':
                notifications.append({
                    'id': f'rejected_{order.id}',
                    'order_id': order.order_id,
                    'type': 'order_rejected',
                    'status': 'rejected',
                    'title': 'Order Rejected',
                    'message': f'Order #{order.order_id} from {order.buyer_name} was rejected',
                    'created_at': order.updated_at.isoformat(),
                    'read': True
                })
        
        return JsonResponse({
            'success': True,
            'notifications': notifications,
            'unread_count': len([n for n in notifications if not n.get('read', False)])
        })
        
    except Exception as e:
        logger.error(f"[NOTIFICATIONS ERROR] {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e),
            'notifications': []
        }, status=500)







# ============================================
# MARK NOTIFICATION AS READ
# ============================================
@login_required
@require_http_methods(["POST"])
def mark_notification_read(request, notification_id):
    """
    Mark a notification as read
    URL: /api/notifications/<notification_id>/read/
    """
    # In a real implementation, you'd store read status in database
    # For now, we just return success
    return JsonResponse({
        'success': True,
        'message': 'Notification marked as read'
    })





# ============================================
# APPROVE PENDING ORDER FROM NOTIFICATION
# ============================================
@login_required
@require_http_methods(["POST"])
def approve_pending_order_notification(request, order_id):
    """
    Approve a pending order from notification panel
    URL: /api/pending-orders/<order_id>/approve/
    
    This is a wrapper around your existing approve_order function
    """
    try:
        # Call your existing approve_order function
        return approve_order(request, order_id)
        
    except Exception as e:
        logger.error(f"[APPROVE FROM NOTIFICATION ERROR] {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)





# ============================================
# REJECT PENDING ORDER FROM NOTIFICATION
# ============================================
@login_required
@require_http_methods(["POST"])
def reject_pending_order_notification(request, order_id):
    """
    Reject a pending order from notification panel
    URL: /api/pending-orders/<order_id>/reject/
    
    This is a wrapper around your existing reject_order function
    """
    try:
        # Call your existing reject_order function
        return reject_order(request, order_id)
        
    except Exception as e:
        logger.error(f"[REJECT FROM NOTIFICATION ERROR] {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)







# ============================================
# ORDER SUCCESS
# ============================================

@require_http_methods(["GET"])
def order_success(request):
    """
    Order success page
    """
    return render(request, 'website/order_success.html', {
        'page_title': 'Order Successful - Fieldmax',
    })






# ============================================
# API ADD TO CART
# ============================================
@csrf_exempt
@require_POST
def api_add_to_cart(request):
    try:
        data = json.loads(request.body)
        product_id = data.get('product_id')
        quantity = int(data.get('quantity', 1))
        
        product = Product.objects.filter(id=product_id, is_active=True).first()
        if not product:
            return JsonResponse({'status': 'error', 'message': 'Product not found'}, status=404)
        
        # Check if product has category
        if not product.category:
            return JsonResponse({'status': 'error', 'message': 'Product has no category assigned'}, status=400)
        
        cart = request.session.get('cart', {})
        
        product_key = str(product_id)
        if product_key in cart:
            cart[product_key]['quantity'] += quantity
            max_quantity = product.quantity if not product.category.is_single_item else 1
            if cart[product_key]['quantity'] > max_quantity:
                cart[product_key]['quantity'] = max_quantity
        else:
            max_quantity = product.quantity if not product.category.is_single_item else 1
            if quantity > max_quantity:
                quantity = max_quantity
            
            cart[product_key] = {
                'name': product.name,
                'product_code': product.product_code,
                'price': float(product.selling_price),
                'quantity': quantity,
            }
        
        request.session['cart'] = cart
        request.session.modified = True
        
        return JsonResponse({'status': 'success', 'message': 'Product added to cart'})
    
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)







# ============================================
# SHOP VIEW
# ============================================
def shop_view(request):
    """
    Display all products organized by category
    """
    category_id = request.GET.get('category')
    selected_category = None
    
    all_categories = Category.objects.all()
    
    if category_id:
        try:
            selected_category = Category.objects.get(id=category_id)
            categories = [selected_category]
        except Category.DoesNotExist:
            categories = all_categories
    else:
        categories = all_categories
    
    categories_with_products = []
    for category in categories:
        # Only include products that have categories
        active_products = category.products.filter(is_active=True, category__isnull=False).order_by('-created_at')
        category.filtered_products = active_products
        if active_products.exists():
            categories_with_products.append(category)
    
    context = {
        'categories': categories_with_products,
        'all_categories': all_categories,
        'selected_category': selected_category,
        'debug': settings.DEBUG,
    }
    
    return render(request, 'website/shop.html', context)





# ============================================
# SHOP LIST VIEW (CLASS-BASED)
# ============================================
class ShopListView(ListView):
    """
    Class-based view for shop page with category filtering
    """
    model = Category
    template_name = 'website/shop.html'
    context_object_name = 'categories'
    
    def get_queryset(self):
        category_id = self.request.GET.get('category')
        
        if category_id:
            try:
                selected_category = Category.objects.get(id=category_id)
                categories = [selected_category]
            except Category.DoesNotExist:
                categories = Category.objects.all()
        else:
            categories = Category.objects.all()
        
        filtered_categories = []
        for category in categories:
            # Only include products that have categories
            active_products = category.products.filter(is_active=True, category__isnull=False).order_by('-created_at')
            category.filtered_products = active_products
            if active_products.exists():
                filtered_categories.append(category)
        
        return filtered_categories
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        category_id = self.request.GET.get('category')
        if category_id:
            try:
                context['selected_category'] = Category.objects.get(id=category_id)
            except Category.DoesNotExist:
                context['selected_category'] = None
        else:
            context['selected_category'] = None
        
        context['all_categories'] = Category.objects.all()
        context['debug'] = settings.DEBUG
        
        return context







# ============================================
# SALES CHART DATA - FIXED VERSION
# ============================================
def get_sales_chart_data(request):
    """
    Generate REAL data for sales statistics charts
    Fixed to handle products without categories
    """
    today = timezone.now().date()
    last_7_days = []
    sales_count_7days = []
    revenue_7days = []
    
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        last_7_days.append(date.strftime('%a'))
        
        daily_sales = Sale.objects.filter(
            sale_date__date=date,
            is_reversed=False
        )
        
        sales_count = daily_sales.count()
        sales_count_7days.append(sales_count)
        
        daily_revenue = daily_sales.aggregate(
            total=Sum('total_amount')
        )['total'] or 0
        revenue_7days.append(float(daily_revenue))
    
    # DONUT CHART DATA - Sales by Category
    thirty_days_ago = today - timedelta(days=30)
    
    # Get sales items with products that have categories
    category_sales = SaleItem.objects.filter(
        sale__sale_date__date__gte=thirty_days_ago,
        sale__is_reversed=False,
        product__category__isnull=False  # Only include products with categories
    ).values(
        'product__category__name'
    ).annotate(
        count=Count('id'),
        revenue=Sum('total_price')
    ).order_by('-count')
    
    category_labels = []
    category_counts = []
    category_colors = [
        'rgba(59, 130, 246, 0.8)',
        'rgba(16, 185, 129, 0.8)',
        'rgba(245, 158, 11, 0.8)',
        'rgba(139, 92, 246, 0.8)',
        'rgba(239, 68, 68, 0.8)',
        'rgba(236, 72, 153, 0.8)',
        'rgba(20, 184, 166, 0.8)',
        'rgba(251, 146, 60, 0.8)',
    ]
    
    for idx, item in enumerate(category_sales):
        category_name = item['product__category__name'] or 'Uncategorized'
        category_labels.append(category_name)
        category_counts.append(item['count'])
    
    # Count sales without categories
    no_category_sales = SaleItem.objects.filter(
        sale__sale_date__date__gte=thirty_days_ago,
        sale__is_reversed=False,
        product__category__isnull=True  # Products without categories
    ).count()
    
    if no_category_sales > 0:
        category_labels.append('No Category')
        category_counts.append(no_category_sales)
    
    if len(category_labels) > 8:
        others_count = sum(category_counts[8:])
        category_labels = category_labels[:8] + ['Others']
        category_counts = category_counts[:8] + [others_count]
    
    if not category_labels:
        category_labels = ['No Sales Yet']
        category_counts = [0]
    
    return {
        'chart_data': {
            'bar_chart': {
                'labels': json.dumps(last_7_days),
                'sales_count': json.dumps(sales_count_7days),
                'revenue': json.dumps(revenue_7days)
            },
            'donut_chart': {
                'labels': json.dumps(category_labels),
                'counts': json.dumps(category_counts),
                'colors': json.dumps(category_colors[:len(category_labels)])
            }
        }
    }






def is_staff_subdomain(request):
    """Check if request is coming from staff subdomain"""
    host = request.get_host()
    return 'staff.fieldmaxstore' in host




def get_client_ip(request):
    """Get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip







# ============================================
# FIX PRODUCT STATUSES
# ============================================
def fix_product_statuses():
    """
    Management command to fix inconsistent product statuses.
    Only fix products that have categories
    """
    fixed_count = 0
    
    # Fix single items
    single_items = Product.objects.filter(
        category__item_type='single',
        category__isnull=False,  # Only products with categories
        is_active=True
    )
    
    for product in single_items:
        old_status = product.status
        
        has_active_sale = Sale.objects.filter(
            product=product,
            is_reversed=False
        ).exists()
        
        if has_active_sale:
            correct_status = 'sold'
            correct_quantity = 0
        else:
            correct_status = 'available'
            correct_quantity = 1
        
        if product.status != correct_status or product.quantity != correct_quantity:
            logger.info(
                f"Fixing {product.product_code}: "
                f"Status {old_status} → {correct_status}, "
                f"Quantity {product.quantity} → {correct_quantity}"
            )
            
            product.status = correct_status
            product.quantity = correct_quantity
            product.save(update_fields=['status', 'quantity'])
            fixed_count += 1
    
    # Fix bulk items
    bulk_items = Product.objects.filter(
        category__item_type='bulk',
        category__isnull=False,  # Only products with categories
        is_active=True
    )
    
    for product in bulk_items:
        old_status = product.status
        quantity = product.quantity or 0
        
        if quantity > 5:
            correct_status = 'available'
        elif quantity > 0:
            correct_status = 'lowstock'
        else:
            correct_status = 'outofstock'
        
        if product.status != correct_status:
            logger.info(
                f"Fixing bulk item {product.product_code}: "
                f"Status {old_status} → {correct_status}"
            )
            
            product.status = correct_status
            product.save(update_fields=['status'])
            fixed_count += 1
    
    logger.info(f"✅ Fixed {fixed_count} products with inconsistent statuses")
    return fixed_count

# ============================================
# DEBUG PRODUCT STATUS
# ============================================
@login_required
def debug_product_status(request, product_code):
    """
    Debug endpoint to check product status consistency.
    """
    try:
        product = Product.objects.get(product_code=product_code)
    except Product.DoesNotExist:
        return render(request, "debug.html", {
            "error": f"Product {product_code} not found"
        })
    
    active_sales = Sale.objects.filter(
        product=product,
        is_reversed=False
    )
    
    stock_entries = StockEntry.objects.filter(
        product=product
    ).order_by('-created_at')[:10]
    
    if product.category:
        if product.category.is_single_item:
            expected_status = 'sold' if active_sales.exists() else 'available'
            expected_quantity = 0 if active_sales.exists() else 1
        else:
            quantity = product.quantity or 0
            if quantity > 5:
                expected_status = 'available'
            elif quantity > 0:
                expected_status = 'lowstock'
            else:
                expected_status = 'outofstock'
            expected_quantity = quantity
    else:
        expected_status = 'unknown'
        expected_quantity = product.quantity
    
    debug_info = {
        "product": product,
        "actual_status": product.status,
        "expected_status": expected_status,
        "actual_quantity": product.quantity,
        "expected_quantity": expected_quantity,
        "is_consistent": (
            product.status == expected_status and 
            product.quantity == expected_quantity
        ),
        "active_sales": active_sales,
        "stock_entries": stock_entries,
        "has_category": bool(product.category),
    }
    
    return render(request, "debug_product.html", debug_info)








# ============================================
# SESSION CHECK API
# ============================================
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils import timezone

@login_required
@require_http_methods(["GET"])
def check_session_status(request):
    """
    API endpoint to check session status and time remaining
    URL: /api/check-session/
    
    Returns:
    - authenticated: bool
    - minutes_remaining: int
    - session_expires_soon: bool (true if < 5 minutes remaining)
    """
    try:
        last_activity = request.session.get('last_activity')
        
        if not last_activity:
            # No activity tracked yet - session is fresh
            return JsonResponse({
                'authenticated': True,
                'minutes_remaining': 30,
                'session_expires_soon': False,
                'message': 'Session active'
            })
        
        # Calculate time remaining
        last_activity_time = timezone.datetime.fromisoformat(last_activity)
        time_since_activity = timezone.now() - last_activity_time
        
        # Session timeout is 30 minutes (1800 seconds)
        timeout_seconds = 1800
        elapsed_seconds = time_since_activity.total_seconds()
        remaining_seconds = max(0, timeout_seconds - elapsed_seconds)
        minutes_remaining = int(remaining_seconds / 60)
        
        # Warn if less than 5 minutes remaining
        session_expires_soon = minutes_remaining < 5
        
        return JsonResponse({
            'authenticated': True,
            'minutes_remaining': minutes_remaining,
            'seconds_remaining': int(remaining_seconds),
            'session_expires_soon': session_expires_soon,
            'message': f'Session expires in {minutes_remaining} minutes' if session_expires_soon else 'Session active'
        })
        
    except Exception as e:
        logger.error(f"Session check error: {str(e)}")
        return JsonResponse({
            'authenticated': True,
            'minutes_remaining': 30,
            'session_expires_soon': False,
            'error': str(e)
        })
    




    # ============================================
# PENDING ORDER RECEIPT
# ============================================
@require_http_methods(["GET"])
def pending_order_receipt(request, order_id):
    """
    Generate a receipt for a pending order
    URL: /api/order/<order_id>/receipt/
    """
    try:
        order = PendingOrder.objects.get(order_id=order_id)
        
        # Parse cart items
        try:
            cart_items = json.loads(order.cart_data) if order.cart_data else []
        except:
            cart_items = []
        
        # Format items for display
        items = []
        for item in cart_items:
            items.append({
                'name': item.get('name', 'Unknown Item'),
                'quantity': item.get('quantity', 1),
                'price': float(item.get('price', 0)),
                'total': float(item.get('price', 0)) * item.get('quantity', 1)
            })
        
        context = {
            'order': order,
            'items': items,
            'total_amount': float(order.total_amount),
            'created_at': order.created_at,
            'status_display': order.get_status_display(),
            'page_title': f'Order Receipt #{order.order_id}'
        }
        
        return render(request, 'website/order_receipt.html', context)
        
    except PendingOrder.DoesNotExist:
        return render(request, '404.html', {
            'message': f'Order {order_id} not found'
        }, status=404)
    except Exception as e:
        logger.error(f"[RECEIPT ERROR] {str(e)}", exc_info=True)
        return render(request, '500.html', {
            'message': f'Error generating receipt: {str(e)}'
        }, status=500)


# ============================================
# API: GET ORDER RECEIPT DATA
# ============================================
@require_http_methods(["GET"])
def api_order_receipt(request, order_id):
    """
    API endpoint to get receipt data for an order
    URL: /api/order/<order_id>/receipt/
    """
    try:
        order = PendingOrder.objects.get(order_id=order_id)
        
        # Parse cart items
        try:
            cart_items = json.loads(order.cart_data) if order.cart_data else []
        except:
            cart_items = []
        
        # Format items for JSON response
        items = []
        for item in cart_items:
            items.append({
                'name': item.get('name', 'Unknown Item'),
                'quantity': item.get('quantity', 1),
                'price': float(item.get('price', 0)),
                'total': float(item.get('price', 0)) * item.get('quantity', 1)
            })
        
        receipt_data = {
            'order_id': order.order_id,
            'buyer_name': order.buyer_name,
            'buyer_phone': order.buyer_phone,
            'buyer_email': order.buyer_email or '',
            'total_amount': float(order.total_amount),
            'status': order.status,
            'status_display': order.get_status_display(),
            'created_at': order.created_at.isoformat() if order.created_at else None,
            'payment_method': order.payment_method,
            'items': items,
            'item_count': len(items),
            'notes': order.notes or ''
        }
        
        return JsonResponse({
            'success': True,
            'receipt': receipt_data
        })
        
    except PendingOrder.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': f'Order {order_id} not found'
        }, status=404)
    except Exception as e:
        logger.error(f"[API RECEIPT ERROR] {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': str(e)
        }, status=500)