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
    path('api/sale/create/', views.sale_create_api, name='sale_create_api'),
    
    # ===== SOLD ITEMS =====
    path('sold-items/', views.sold_items_list, name='sold_items_list'),
    path('sold-items/export/', views.export_sold_items, name='export_sold_items'),
    
    # ===== CUSTOMER LOYALTY URLS =====
    path('customer/register/', views.customer_register, name='customer_register'),
    path('customers/', views.customer_list, name='customer_list'),
    path('customer/search/', views.customer_search, name='customer_search'),
    path('customer/<int:pk>/', views.customer_detail, name='customer_detail'),
    path('customer/<int:pk>/edit/', views.customer_edit, name='customer_edit'),
    path('customer/<int:pk>/delete/', views.customer_delete, name='customer_delete'),
    path('customer/<int:pk>/transactions/', views.customer_transactions, name='customer_transactions'),
    
    # ===== PERIOD DETAILS =====
    path('period-details/', views.period_details, name='period_details'),
    
    # ============================================
    # API endpoints for cart management (AJAX)
    # ============================================
    path('api/get-cart/', views.get_cart, name='get_cart'),
    path('api/get-product/<str:product_code>/', views.get_product_details, name='get_product_details'),
    path('api/add-to-cart/', views.add_to_cart, name='add_to_cart'),
    path('api/update-cart/', views.update_cart, name='update_cart'),
    path('api/update-cart-price/', views.update_cart_price, name='update_cart_price'),
    path('api/remove-from-cart/', views.remove_from_cart, name='remove_from_cart'),
    path('api/clear-cart/', views.clear_cart, name='clear_cart'),
    path('api/search-products/', views.search_products, name='search_products'),
    
    # API endpoints for period details
    path('api/items-by-date/', views.items_by_date_api, name='items_by_date_api'),
    path('api/items-by-week/', views.items_by_week_api, name='items_by_week_api'),
    path('api/items-by-month/', views.items_by_month_api, name='items_by_month_api'),
    path('api/sale-details/<int:sale_id>/', views.sale_details_api, name='sale_details_api'),
    
    # M-PESA PAYMENT API
    path('api/check-payment/<str:sale_id>/', views.check_payment_status, name='check_payment_status'),
    path('api/check-payment-by-phone/', views.check_payment_by_phone, name='check_payment_by_phone'),
    path('api/send-otp/', views.send_otp, name='send_otp'),
    path('api/verify-otp/', views.verify_otp, name='verify_otp'),
    
    # SALE MANAGEMENT (with payment endpoints)
    path('sale/<str:sale_id>/mpesa-pay/', views.initiate_mpesa_payment, name='mpesa_pay'),
    path('sale/<str:sale_id>/update-payment/', views.update_sale_payment, name='update_sale_payment'),
    path('sale/<str:sale_id>/record-direct-payment/', views.record_direct_payment, name='record_direct_payment'),
    path('sale/<str:sale_id>/complete-payment/', views.complete_sale_payment, name='complete_sale_payment'),
    path('sale/<str:sale_id>/delete-pending/', views.delete_pending_sale, name='delete_pending_sale'),
    path('sale/<str:sale_id>/award-points/', views.award_points_to_sale, name='award_points_to_sale'),
    
    # ============================================
    # SALE DETAILS (specific sale_id patterns)
    # These use the same pattern but are more specific
    # ============================================
    path('sale/<str:sale_id>/receipt/', views.sale_receipt, name='sale_receipt'),
    path('sale/<str:sale_id>/print/', views.sale_receipt, name='sale_print'),
    path('sale/<str:sale_id>/reverse/', views.sale_reverse, name='sale_reverse'),
    
    # ============================================
    # CATCH-ALL - MUST BE ABSOLUTELY LAST!
    # This will match sale_id like "SALE-123"
    # ============================================
    path('<str:sale_id>/', views.sale_detail, name='sale_detail'),
]