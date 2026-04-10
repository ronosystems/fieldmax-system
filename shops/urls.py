from django.urls import path
from . import views

app_name = 'shops'  # Changed from 'shop' to 'shops'

urlpatterns = [
    # Dashboard & Reports
    path('', views.shop_dashboard, name='dashboard'),
    path('reports/', views.reports_list, name='reports_list'),
    path('report/create/', views.create_daily_report, name='create_report'),
    path('report/<int:report_id>/', views.report_detail, name='report_detail'),
    path('report/<int:report_id>/edit/', views.edit_daily_report, name='edit_report'),
    path('report/<int:report_id>/finalize/', views.finalize_report, name='finalize_report'),
    path('report/<int:report_id>/mpesa-summary/', views.mpesa_daily_summary, name='mpesa_summary'),
    
    # Shop Management
    path('branches/', views.shop_branches, name='branches'),
    path('branches/add/', views.add_branch, name='add_branch'),
    path('branches/<int:shop_id>/edit/', views.edit_shop_branch, name='edit_branch'),
    
    # Bank Accounts
    path('bank-accounts/', views.bank_accounts, name='bank_accounts'),
    path('bank-accounts/add/', views.add_bank_account, name='add_bank_account'),
    path('bank-accounts/<int:account_id>/edit/', views.edit_bank_account, name='edit_bank_account'),
    
    # M-Pesa Accounts
    path('mpesa-accounts/', views.mpesa_accounts, name='mpesa_accounts'),
    path('mpesa-accounts/add/', views.add_mpesa_account, name='add_mpesa_account'),
    path('mpesa-accounts/<int:account_id>/edit/', views.edit_mpesa_account, name='edit_mpesa_account'),
    
    # Dynamic Choices Management
    path('choices/', views.manage_choices, name='manage_choices'),
    path('choices/delete/<int:choice_id>/', views.delete_choice, name='delete_choice'),
    
    # Statistics
    path('statistics/', views.shop_statistics, name='shop_statistics'),
    
    # Export
    path('export/csv/', views.export_reports_csv, name='export_csv'),
    
    # AJAX Endpoints
    path('api/shop/<int:shop_id>/banks/', views.get_shop_banks, name='get_shop_banks'),
    path('api/shop/<int:shop_id>/mpesa-accounts/', views.get_shop_mpesa_accounts, name='get_shop_mpesa'),
    path('api/weekly-sales/', views.weekly_sales_data, name='weekly_sales_data'),
    path('api/weekly-transactions/', views.weekly_transactions_data, name='weekly_transactions_data'),
    path('api/report/<int:report_id>/summary/', views.get_report_summary, name='get_report_summary'),
    path('api/expense-distribution/', views.expense_distribution, name='expense_distribution'),
]