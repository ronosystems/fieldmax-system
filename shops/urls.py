# shops/urls.py
from django.urls import path
from . import views

app_name = 'shops'

urlpatterns = [
    # ==================== DASHBOARD & HOME ====================
    path('', views.shop_dashboard, name='dashboard'),
    path('dashboard/', views.shop_dashboard, name='shop_dashboard'),
    
    # ==================== STATISTICS ====================
    path('statistics/', views.shop_statistics, name='shop_statistics'),
    path('statistics/<int:shop_id>/', views.shop_detail_statistics, name='shop_detail_stats'),
    
    # ==================== DAILY REPORTS ====================
    path('reports/', views.reports_list, name='reports_list'),
    path('reports/create/', views.create_daily_report, name='create_report'),
    path('reports/<int:report_id>/', views.report_detail, name='report_detail'),
    path('reports/<int:report_id>/edit/', views.edit_daily_report, name='edit_report'),
    path('reports/<int:report_id>/finalize/', views.finalize_report, name='finalize_report'),
    path('reports/<int:report_id>/unfinalize/', views.unfinalize_report, name='unfinalize_report'),
    
    # ==================== SHOP BRANCHES ====================
    path('branches/', views.shop_branches, name='branches'), 
    path('branches/add/', views.add_branch, name='add_branch'),
    path('branches/<int:shop_id>/edit/', views.edit_shop_branch, name='edit_branch'),
    
    # ==================== MPESA ACCOUNTS ====================
    path('mpesa-accounts/', views.mpesa_accounts, name='mpesa_accounts'),
    path('mpesa-accounts/add/', views.add_mpesa_account, name='add_mpesa_account'),
    path('mpesa-accounts/<int:account_id>/edit/', views.edit_mpesa_account, name='edit_mpesa_account'),
    path('mpesa-accounts/<int:account_id>/', views.mpesa_accounts_detail, name='mpesa_accounts_detail'),
    path('mpesa-accounts/<int:account_id>/delete/', views.delete_mpesa_account, name='delete_mpesa_account'),
    
    # ==================== BANK ACCOUNTS ====================
    path('bank-accounts/', views.bank_accounts, name='bank_accounts'),
    path('bank-accounts/add/', views.add_bank_account, name='add_bank_account'),
    path('bank-accounts/<int:account_id>/edit/', views.edit_bank_account, name='edit_bank_account'),
    
    # ==================== CASH ACCOUNTS ====================
    path('cash-accounts/', views.cash_accounts, name='cash_accounts'),
    path('cash-accounts/add/', views.add_cash_account, name='add_cash_account'),
    path('cash-accounts/<int:account_id>/edit/', views.edit_cash_account, name='edit_cash_account'),
    
    # ==================== DYNAMIC CHOICES ====================
    path('choices/', views.manage_choices, name='manage_choices'),
    path('choices/delete/<int:choice_id>/', views.delete_choice, name='delete_choice'),
    
    # ==================== EXPORT ====================
    path('export/csv/', views.export_reports_csv, name='export_csv'),
    
    # =================== AJAX ENDPOINTS ====================
    path('api/shop/<int:shop_id>/banks/', views.get_shop_banks, name='get_shop_banks'),
    path('api/shop/<int:shop_id>/mpesa-accounts/', views.get_shop_mpesa_accounts, name='get_shop_mpesa_accounts'),
    path('api/shop/<int:shop_id>/cash-accounts/', views.get_shop_cash_accounts, name='get_shop_cash_accounts'),
    path('api/shop/<int:shop_id>/users/', views.get_shop_users, name='get_shop_users'),
    path('api/previous-closing/', views.get_previous_closing_balance, name='previous_closing'),
    path('api/weekly-sales/', views.weekly_sales_data, name='weekly_sales_data'),
    path('api/weekly-transactions/', views.weekly_transactions_data, name='weekly_transactions_data'),
    path('api/expense-distribution/', views.expense_distribution, name='expense_distribution'),
    path('api/shop/<int:shop_id>/accounts/', views.get_shop_accounts, name='get_shop_accounts'),

    # ==================== ALIASES ====================
    path('branches-list/', views.shop_branches, name='branches_list'),
    path('reports-list/', views.reports_list, name='reports_list_alias'),
]