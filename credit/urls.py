from django.urls import path
from . import views

app_name = 'credit'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
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
    
    # API for Sales integration
    path('api/sale-to-credit/<str:sale_id>/', views.convert_sale_to_credit, name='convert_sale_to_credit'),
]