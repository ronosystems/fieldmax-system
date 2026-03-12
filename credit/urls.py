from django.urls import path
from . import views

app_name = 'credit'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    path('statistics/', views.credit_statistics, name='credit_statistics'),
    
    # Companies
    path('companies/', views.company_list, name='company_list'),
    path('companies/add/', views.company_add, name='company_add'),
    path('companies/<int:pk>/', views.company_detail, name='company_detail'),
    path('companies/<int:pk>/edit/', views.company_edit, name='company_edit'),
    
    # Customers
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/add/', views.customer_add, name='customer_add'),
    path('customers/<int:pk>/', views.customer_detail, name='customer_detail'),
    path('customers/<int:pk>/edit/', views.customer_edit, name='customer_edit'),
    
    # Transactions
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transactions/create/', views.transaction_create, name='transaction_create'),
    path('transactions/<int:pk>/', views.transaction_detail, name='transaction_detail'),
    path('transactions/<int:pk>/pay/', views.transaction_pay, name='transaction_pay'),
    path('transactions/<int:pk>/cancel/', views.transaction_cancel, name='transaction_cancel'),
    path('transactions/<int:pk>/reverse/', views.transaction_reverse, name='transaction_reverse'), 
    path('transactions/<int:pk>/receipt/', views.transaction_receipt, name='transaction_receipt'),
    
    # Payments
    path('payments/', views.payment_list, name='payment_list'),
    path('payments/add/', views.payment_add, name='payment_add'),
    path('payments/<int:pk>/', views.payment_detail, name='payment_detail'),

    # ===== COMMISSION URLS (5 buttons) =====
    
    # 1. Commission Dashboard
    path('commissions/dashboard/', views.commission_dashboard, name='commission_dashboard'),
    path('commissions/<int:pk>/', views.commission_detail, name='commission_detail'),
    
    # 2. Request Commissions - List eligible transactions
    path('commissions/request/', views.request_commission_list, name='request_commission'),
    
    # 3. Approve Commissions - List requested commissions
    path('commissions/approve/', views.approve_commission_list, name='approve_commission'),
    
    # 4. Pay Commissions - List approved commissions
    path('commissions/pay/', views.pay_commission_list, name='pay_commission'),
    
    # 5. Commissions Report - All commissions report
    path('commissions/report/', views.commission_report, name='commission_report'),
    
    # ===== AJAX endpoints for actions =====
    path('commissions/request/<int:pk>/submit/', views.request_commission_submit, name='request_commission_submit'),
    path('commissions/approve/<int:pk>/submit/', views.approve_commission_submit, name='approve_commission_submit'),
    path('commissions/pay/<int:pk>/submit/', views.pay_commission_submit, name='pay_commission_submit'),
    path('commissions/bulk-pay/', views.bulk_pay_commission, name='bulk_pay_commission'),
    
    # API for Sales integration
    path('api/search-seller-commission/', views.search_seller_commission_status, name='search_seller_commission'),
    path('api/sale-to-credit/<str:sale_id>/', views.convert_sale_to_credit, name='convert_sale_to_credit'),  
    path('api/search-transaction/', views.search_transaction, name='search_transaction'),  

    path('commissions/report/', views.commission_report, name='commission_report'),
    path('commissions/report/export/', views.export_commission_report, name='export_commission_report'),
]