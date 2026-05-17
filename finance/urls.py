from django.urls import path
from . import views
from finance.kopokopo_service import kopokopo_webhook

app_name = 'finance'

urlpatterns = [
    # ============================================
    # FINANCE DASHBOARD
    # ============================================
    path('', views.finance_dashboard, name='dashboard'),
    
    # ============================================
    # SALARY MANAGEMENT
    # ============================================
    path('salaries/', views.salary_list, name='salary_list'),
    path('salaries/create/', views.salary_create, name='salary_create'),
    path('salaries/<int:pk>/', views.salary_detail, name='salary_detail'),
    path('salaries/<int:pk>/approve/', views.salary_approve, name='salary_approve'),
    path('salaries/<int:pk>/pay/', views.salary_pay, name='salary_pay'),
    path('salaries/<int:pk>/receipt/', views.salary_receipt, name='salary_receipt'),
    path('salaries/approve/list/', views.salary_approve_list, name='salary_approve_list'),
    path('salaries/pay/list/', views.salary_pay_list, name='salary_pay_list'),
    path('salaries/history/', views.salary_history, name='salary_history'),
    
    # ============================================
    # COMMISSION MANAGEMENT
    # ============================================
    # Request Commissions (for sellers)
    path('commissions/request/', views.commission_request_list, name='commission_request_list'),
    path('commissions/search/', views.commission_transaction_search, name='commission_transaction_search'),
    path('commissions/request/<int:pk>/submit/', views.commission_request_submit, name='commission_request_submit'),
    
    # All Commissions
    path('commissions/all/', views.commission_list, name='commission_list'),
    
    # Approve Commissions (for finance)
    path('commissions/approve-list/', views.commission_approve_list, name='commission_approve_list'),
    path('commissions/approve-seller/<int:seller_id>/', views.commission_approve_seller, name='commission_approve_seller'),
    path('commissions/<int:pk>/approve/', views.commission_approve_page, name='commission_approve'),
    
    # Pay Commissions (for finance)
    path('commissions/pay-list/', views.commission_pay_list, name='commission_pay_list'),
    path('commissions/pay-seller/<int:seller_id>/', views.commission_pay_seller, name='commission_pay_seller'),
    path('commissions/<int:pk>/pay/', views.commission_pay_page, name='commission_pay'),
    
    # Reject Commission
    path('commissions/<int:pk>/reject/', views.commission_reject_page, name='commission_reject'),
    
    # Commission History & Details
    path('commissions/history/', views.commission_history, name='commission_history'),
    path('commissions/<int:pk>/', views.commission_detail, name='commission_detail'),
    
    # Reports & Export
    path('commissions/summary/', views.commission_summary, name='commission_summary'),
    path('commissions/export/', views.commission_export, name='commission_export'),
    
    # ============================================
    # FINANCIAL TRANSACTIONS
    # ============================================
    path('transactions/', views.financial_transactions, name='financial_transactions'),
    path('transactions/', views.financial_transactions, name='transactions'),  # Alias for backward compatibility
    
    # ============================================
    # INCOME AND EXPENSE
    # ============================================
    path('income/', views.financial_income, name='financial_income'),
    path('income/<str:transaction_id>/', views.income_detail, name='income_detail'),
    path('expenses/', views.financial_expenses, name='financial_expenses'),
    path('expenses/<str:transaction_id>/', views.expenses_detail, name='expenses_detail'),
    path('sales-income/', views.sales_income_page, name='sales_income'),
    path('inventory-expenses/', views.inventory_expenses_page, name='inventory_expenses'),
    
    # ============================================
    # FINANCE ACCOUNTS
    # ============================================
    path('accounts/cash/', views.cash_account, name='cash_account'),
    path('accounts/bank/', views.bank_account, name='bank_account'),
    path('accounts/credit/', views.credit_account, name='credit_account'),
    path('accounts/add-transaction/', views.add_account_transaction, name='add_account_transaction'),
    
    # ============================================
    # CREDIT COMPANY PAYMENTS
    # ============================================
    path('credit-company-payments/', views.credit_company_payments_dashboard, name='credit_company_payments'),
    path('credit-company-payment/<int:company_id>/', views.credit_company_payment, name='credit_company_payment'),

    # ============================================
    # STOCK PURCHASE EXPENSES
    # ============================================
    path('stock-purchases/', views.stock_purchase_expenses, name='stock_purchase_expenses'),

    # ============================================
    # M-PESA PAYMENTS
    # ============================================
    path('mpesa/stk-push/', views.stk_push_only, name='stk_push_only'),
    path('mpesa/store-cart/', views.store_mpesa_cart, name='store_mpesa_cart'),  # NEW
    path('mpesa/get-cart/<str:checkout_id>/', views.get_mpesa_cart, name='get_mpesa_cart'),  # NEW
    path('mpesa-callback/', views.mpesa_callback, name='mpesa_callback'),
    path('mpesa-status/<str:checkout_request_id>/', views.mpesa_status_check, name='mpesa_status_check'),
    path('webhook/kopokopo/', kopokopo_webhook, name='kopokopo_webhook'),

    #==============================================
    # MONEY TRANSFERS
    #==============================================
    path('transfers/', views.money_transfer_list, name='money_transfer_list'),
    path('transfers/create/', views.money_transfer_create, name='money_transfer_create'),
    path('transfers/<int:pk>/', views.money_transfer_detail, name='money_transfer_detail'),
    path('transfers/<int:pk>/cancel/', views.money_transfer_cancel, name='money_transfer_cancel'),

    #==============================================
    # CAPITAL INJECTIONS & LOAN REPAYMENTS
    #==============================================
    path('capital-injections/', views.capital_injection_list, name='capital_injection_list'),
    path('capital-injections/create/', views.capital_injection_create, name='capital_injection_create'),
    path('capital-injections/<str:injection_id>/', views.capital_injection_detail, name='capital_injection_detail'),
    path('capital-injections/<str:injection_id>/repay/', views.loan_repayment_create, name='loan_repayment_create'),
]