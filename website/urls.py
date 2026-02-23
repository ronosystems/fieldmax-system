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
    # PENDING ORDERS SYSTEM
    # ============================================
    # Customer submits order
    path('order-success/', views.order_success, name='order-success'),
    path('api/public/create-order/', views.public_create_order, name='public-create-order'),
    path('api/pending-orders-count/', pending_orders_count, name='pending_orders_count'),
    path('api/pending-orders/<str:order_id>/', views.get_order_details_notification, name='api-single-order-details'),
    
    # Staff views and actions
    path('staff/pending-orders/', views.pending_orders_list, name='pending-orders-list'),
    path('staff/approve-order/<str:order_id>/', views.approve_order, name='approve-order'),
    path('staff/reject-order/<str:order_id>/', views.reject_order, name='reject-order'),
    
    # API for badge count
    path('api/pending-orders/count/', views.pending_orders_count, name='pending-orders-count'),
    path('api/pending-orders/', views.api_get_all_orders, name='api-all-orders'),




    path('home-stats/', views.home_stats, name='home_stats'),
    path('featured-products/', views.featured_products, name='featured_products'),
    path('trending-stats/', views.trending_stats, name='trending_stats'),
    
    # Product interactions
    path('products/<int:product_id>/view/', views.increment_product_view, name='increment_view'),

    # ============================================
    # ENHANCED CATEGORIES API
    # ============================================
    path('categories/', views.categories_list_public, name='categories-public'),
    path('api/categories/', views.api_get_categories, name='api-get-categories'),
    path('api/categories/<int:category_id>/', views.api_category_details, name='api-category-details'),
    path('categories/', RedirectView.as_view(url='/shop/', permanent=False), name='categories-redirect'),

]    