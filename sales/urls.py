from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    # Dashboard
    path('', views.sales_dashboard, name='sales_dashboard'),
    
    # Sales list and create
    path('sales/', views.sale_list, name='sale_list'),
    path('create/', views.sale_create, name='sale_create'),
    path('<str:sale_id>/', views.sale_detail, name='sale_detail'),
    path('<str:sale_id>/receipt/', views.sale_receipt, name='sale_receipt'),
    path('<str:sale_id>/reverse/', views.sale_reverse, name='sale_reverse'),
    
    # API endpoints for cart management (AJAX)
    path('api/get-cart/', views.get_cart, name='get_cart'),
    path('api/get-product/<str:product_code>/', views.get_product_details, name='get_product_details'),
    path('api/add-to-cart/', views.add_to_cart, name='add_to_cart'),
    path('api/update-cart/', views.update_cart, name='update_cart'),              # ADD THIS
    path('api/update-cart-price/', views.update_cart_price, name='update_cart_price'),  # ADD THIS
    path('api/remove-from-cart/', views.remove_from_cart, name='remove_from_cart'),
    path('api/clear-cart/', views.clear_cart, name='clear_cart'),                  # ADD THIS (optional)

    # API endpoint for product search (AJAX)
    path('api/search-products/', views.search_products, name='search_products'),
]