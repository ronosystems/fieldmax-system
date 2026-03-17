from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    # Dashboard
    path('', views.sales_dashboard, name='sales_dashboard'),
    path('statistics/', views.sales_statistics, name='sales_statistics'),
    
    # Sales list and create
    path('sales/', views.sale_list, name='sale_list'),
    path('create/', views.sale_create, name='sale_create'),
    
    # ===== SOLD ITEMS =====
    path('sold-items/', views.sold_items_list, name='sold_items_list'),
    path('sold-items/export/', views.export_sold_items, name='export_sold_items'),
    
    # ===== CUSTOMER LOYALTY URLS - MUST COME BEFORE CATCH-ALL =====
    path('customer/register/', views.customer_register, name='customer_register'),
    path('customers/', views.customer_list, name='customer_list'),
    path('customer/search/', views.customer_search, name='customer_search'),
    path('customer/<int:pk>/', views.customer_detail, name='customer_detail'),
    path('customer/<int:pk>/transactions/', views.customer_transactions, name='customer_transactions'),
    
    # ===== API endpoints for cart management (AJAX) =====
    path('api/get-cart/', views.get_cart, name='get_cart'),
    path('api/get-product/<str:product_code>/', views.get_product_details, name='get_product_details'),
    path('api/add-to-cart/', views.add_to_cart, name='add_to_cart'),
    path('api/update-cart/', views.update_cart, name='update_cart'),
    path('api/update-cart-price/', views.update_cart_price, name='update_cart_price'),
    path('api/remove-from-cart/', views.remove_from_cart, name='remove_from_cart'),
    path('api/clear-cart/', views.clear_cart, name='clear_cart'),
    path('api/search-products/', views.search_products, name='search_products'),
    
    # ===== CATCH-ALL PATTERNS - MUST BE LAST =====
    path('<str:sale_id>/', views.sale_detail, name='sale_detail'),
    path('<str:sale_id>/receipt/', views.sale_receipt, name='sale_receipt'),
    path('<str:sale_id>/print/', views.sale_receipt, name='sale_print'),
    path('<str:sale_id>/reverse/', views.sale_reverse, name='sale_reverse'),
]