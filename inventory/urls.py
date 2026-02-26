from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
    # Products
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.product_add, name='product_add'),
    path('products/bulk-add/', views.product_bulk_add, name='product_bulk_add'),
    path('products/<int:pk>/', views.product_detail, name='product_detail'),
    path('products/<int:pk>/edit/', views.product_edit, name='product_edit'),
    path('products/<int:pk>/delete/', views.product_delete, name='product_delete'),
    path('api/search-users/', views.search_users, name='search_users'),
    path('product-transfer/', views.product_transfer, name='product_transfer'),

    # Restocking
    path('restock/search/', views.search_product_for_restock, name='restock-search'),
    path('restock/process/', views.process_restock, name='restock-process'),
    path('restock/', views.ProductRestockView.as_view(), name='product_restock'),
    
    # Categories
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('categories/', views.category_list, name='category_list'),
    path('categories/add/', views.category_add, name='category_add'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    
    # Suppliers
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/<int:pk>/edit/', views.supplier_edit, name='supplier_edit'),
    path('suppliers/add/', views.supplier_add, name='supplier_add'),
    path('suppliers/<int:pk>/delete/', views.supplier_delete, name='supplier_delete'),

    # Returns
    path('returns/', views.return_list, name='return_list'),
    path('returns/search/', views.return_product, name='return_product'),
    path('returns/submit/', views.return_submit, name='return_submit'),
    path('returns/<int:pk>/', views.return_detail, name='return_detail'),
    path('returns/<int:pk>/verify/', views.return_verify, name='return_verify'),
    path('returns/<int:pk>/approve/', views.return_approve, name='return_approve'),
    path('returns/<int:pk>/reject/', views.return_reject, name='return_reject'),
    path('returns/<int:pk>/process/', views.return_process, name='return_process'),
    path('api/return-search/', views.return_search_api, name='return_search_api'),
    
    # Stock Movements
    path('stock/', views.stock_movements, name='stock_movements'),
    path('stock/add/<int:product_id>/', views.stock_entry_add, name='stock_entry_add'),
    path('stock/<int:pk>/reverse/', views.reverse_entry, name='reverse_entry'),
    
    
    # Stock Alerts
    path('alerts/', views.stock_alerts, name='stock_alerts'),
    path('alerts/<int:pk>/restock/', views.restock_product, name='restock_product'),
    path('alerts/<int:pk>/dismiss/', views.dismiss_alert, name='dismiss_alert'),

    # Stock Alert URLs
    path('stock-alerts/', views.stock_alerts, name='stock_alerts'),
    path('stock-alerts/<int:pk>/', views.alert_detail, name='alert_detail'),
    path('stock-alerts/<int:pk>/dismiss/', views.dismiss_alert, name='dismiss_alert'),
    path('stock-alerts/<int:pk>/reactivate/', views.reactivate_alert, name='reactivate_alert'),
    path('stock-alerts/<int:pk>/restock/', views.restock_from_alert, name='restock_from_alert'),
    path('stock-alerts/export/', views.export_alerts, name='export_alerts'),
    path('stock-alerts/bulk-dismiss/', views.bulk_dismiss_alerts, name='bulk_dismiss_alerts'),
    
    # Reviews
    path('reviews/', views.product_reviews, name='product_reviews'),
]