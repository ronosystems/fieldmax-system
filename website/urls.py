# website/urls.py
from django.urls import path
from .views import (
    home,
    shopping_cart,
    validate_cart,
    pending_orders_count,
)
from . import views
from django.contrib.auth.views import LogoutView
from django.views.generic import RedirectView
from .views import check_session_status


app_name = 'website'

urlpatterns = [
    # ============================================
    # HOME & PRODUCTS
    # ============================================
    path('', home, name='home'),
    path('products/', views.products_page, name='products_page'),
    path('product/<int:pk>/', views.product_detail, name='product_detail'),
    path('search/', views.search_products, name='search'),
    path('api/check-session/', check_session_status, name='check-session'),

    # ============================================
    # API ENDPOINTS FOR HOME PAGE
    # ============================================
    path('api/featured-products/', views.api_featured_products, name='api-featured-products'),
    path('api/home-stats/', views.api_home_stats, name='api-home-stats'),
    path('api/categories/', views.api_product_categories, name='api-categories'),
    path('api/quick-search/', views.api_quick_search, name='api-quick-search'),
    
    # ============================================
    # SHOPPING CART & CHECKOUT
    # ============================================
    path('shop/', views.shop_view, name='shop'),
    path('cart/', shopping_cart, name='shopping-cart'),
    path('api/validate-cart/', validate_cart, name='validate-cart'),
    path('checkout/', views.checkout_page, name='checkout'),
    path('api/cart/add/', views.api_add_to_cart, name='api-add-to-cart'),

    # ============================================
    # ORDER SEARCH & RECEIPT
    # ============================================
    path('search-order/', views.search_order, name='search_order'),
    path('orders/search/', views.order_search_page, name='order_search_page'),
    path('api/search-order/', views.search_order, name='api_search_order'),
    path('api/notifications/', views.get_notifications, name='api-notifications'),
    path('api/notifications/<str:notification_id>/read/', views.mark_notification_read, name='api-notification-read'),
    path('api/pending-orders/<str:order_id>/', views.get_order_details_notification, name='api-order-details'),
    path('api/pending-orders/', views.api_pending_orders, name='api_pending_orders'),
    path('api/pending-orders/<str:order_id>/', views.get_order_details_notification, name='order_detail_api'),
    path('api/order/<str:order_id>/receipt/', views.api_order_receipt, name='api_order_receipt'),
    path('order/<str:order_id>/receipt/', views.pending_order_receipt, name='order_receipt'),

    # ============================================
    # PENDING ORDERS SYSTEM - CUSTOMER
    # ============================================

    path('customers/', views.customer_list, name='customer-list'),
    path('customers/create/', views.customer_create, name='customer-create'),
    path('order-success/', views.order_success, name='order-success'),
    path('api/public/create-order/', views.public_create_order, name='public-create-order'),
    path('api/pending-orders-count/', pending_orders_count, name='pending_orders_count'),
    path('api/pending-orders/<str:order_id>/', views.get_order_details_notification, name='api-single-order-details'),
    
    # ============================================
    # PENDING ORDERS SYSTEM - STAFF
    # ============================================
    # Staff views (HTML pages)
    path('orders/', views.pending_orders_list, name='order-list'),
    path('staff/pending-orders/', views.pending_orders_list, name='pending-orders-list'),
    path('staff/pending-orders/<str:order_id>/', views.pending_order_detail, name='pending-order-detail'),
    
    # Staff actions (POST endpoints)
    path('staff/approve-order/<str:order_id>/', views.approve_order, name='approve-order'),
    path('staff/reject-order/<str:order_id>/', views.reject_order, name='reject-order'),
    
    # URL aliases for order management
    path('orders/list/', views.pending_orders_list, name='order-list'),
    path('orders/create/', views.shop_view, name='order-create'),
    path('orders/pending/', views.pending_orders_list, name='pending-orders'),
    path('orders/completed/', views.completed_orders, name='completed-orders'),
    path('orders/search/', views.order_search_page, name='order-search'),
    path('orders/track/', views.order_search_page, name='order-track'),
    
    # ============================================
    # PENDING ORDERS SYSTEM - API ENDPOINTS
    # ============================================
    # Count endpoints
    path('api/pending-orders/count/', views.pending_orders_count, name='pending-orders-count'),
    path('api/pending-orders/all/', views.api_get_all_orders, name='api-all-orders'),
    
    # Order management APIs
    path('api/pending-orders/<str:order_id>/approve/', views.approve_pending_order_notification, name='api-approve-order'),
    path('api/pending-orders/<str:order_id>/reject/', views.reject_pending_order_notification, name='api-reject-order'),


    # ============================================
    # REPORT VIEWS
    # ============================================
    path('reports/orders/', views.order_report, name='order-report'),
    path('reports/sales/', views.sales_report, name='sales-report'),
    path('reports/performance/', views.performance_report, name='performance-report'),

    # ============================================
    # STATISTICS & ANALYTICS
    # ============================================
    path('home-stats/', views.home_stats, name='home_stats'),
    path('featured-products/', views.featured_products, name='featured_products'),
    path('trending-stats/', views.trending_stats, name='trending_stats'),
    path('api/sales-chart-data/', views.get_sales_chart_data, name='sales-chart-data'),
    
    # ============================================
    # PRODUCT INTERACTIONS
    # ============================================
    path('products/<int:product_id>/view/', views.increment_product_view, name='increment_view'),

    # ============================================
    # ENHANCED CATEGORIES API
    # ============================================
    path('categories/', views.categories_list_public, name='categories-public'),
    path('api/categories/', views.api_get_categories, name='api-get-categories'),
    path('api/categories/<int:category_id>/', views.api_category_details, name='api-category-details'),
    path('categories/', RedirectView.as_view(url='/shop/', permanent=False), name='categories-redirect'),

    # ============================================
    # SHOPPING CART & CHECKOUT
    # ============================================
    path('cart/', shopping_cart, name='shopping-cart'),
    path('shop/', views.shop_view, name='shop'),
    path('checkout/', views.checkout_page, name='checkout'),

    # ============================================
    # MISSING URLS ADDED HERE
    # ============================================
    
    # Product search and details
    path('api/search/products/', views.search_products, name='api-search-products'),
    path('api/product/<int:product_id>/', views.product_detail, name='api-product-detail'),
    
    # Order tracking public page
    path('track-order/', views.order_search_page, name='track-order'),
    path('track-order/<str:order_id>/', views.search_order, name='track-order-detail'),
    
    # Checkout process
    path('api/checkout/process/', views.checkout, name='api-checkout-process'),
    path('api/checkout/validate/', views.validate_cart, name='api-checkout-validate'),
    
    # Order success page with order data
    path('order-success/<str:order_id>/', views.order_success, name='order-success-detail'),
    
    # Staff dashboard integration
    path('staff/orders/', views.pending_orders_list, name='staff-orders'),
    path('staff/orders/completed/', views.completed_orders, name='staff-completed-orders'),
    
    # Notification actions
    path('api/notifications/mark-all-read/', views.mark_notification_read, name='api-notifications-mark-all'),
    path('api/cart/count/', views.api_cart_count, name='api-cart-count'),
    
    # Debug endpoints (only in debug mode)
    path('debug/product/<str:product_code>/', views.debug_product_status, name='debug-product-status'),

    # profile and settings
    path('profile/', views.profile, name='profile'),
    path('settings/', views.settings, name='settings'),
]

# ============================================
# ADDITIONAL URLS FOR COMPLETENESS
# ============================================

# These are additional patterns that might be needed based on your views.py
# If you have these views, uncomment them:

"""
    # Customer management
    path('api/customers/', views.api_customers, name='api-customers'),
    path('api/customers/<int:customer_id>/', views.api_customer_detail, name='api-customer-detail'),
    
    # Bulk operations
    path('api/orders/bulk-approve/', views.bulk_approve_orders, name='api-bulk-approve'),
    path('api/orders/bulk-reject/', views.bulk_reject_orders, name='api-bulk-reject'),
    
    # Export functionality
    path('staff/orders/export/', views.export_orders_csv, name='export-orders'),
    path('staff/orders/export/<str:format>/', views.export_orders, name='export-orders-format'),
    
    # Order statistics
    path('api/orders/statistics/', views.order_statistics, name='api-order-statistics'),
    path('api/orders/daily-stats/', views.daily_order_stats, name='api-daily-order-stats'),
"""