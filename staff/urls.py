from django.urls import path
from . import views
from .views import (
    diagnostic_email,
)

app_name = 'staff'

urlpatterns = [
    # ============================================
    # MAIN DASHBOARD (redirects based on role)
    # ============================================
    path('otp-verify/', views.otp_verify, name='otp_verify'),
    path('otp-resend/', views.otp_resend, name='otp_resend'),
    path('', views.staff_dashboard, name='staff_dashboard'),
    path('stats-dashboard/', views.staff_stats_dashboard, name='staff_stats_dashboard'),
    path('logout/', views.custom_logout, name='logout'),  # Keep only one logout
    path('password-change/', views.password_change, name='password_change'),
    
    # ============================================
    # ITP VERIFICATION URLS - ADD THESE LINES
    # ============================================
    path('verify/<int:staff_id>/', views.verify_identity, name='verify_identity'),
    path('resend-verification/', views.resend_verification, name='resend_verification'),
    path('email-status/', views.email_queue_status, name='email_queue_status'),
    path('admin-verify/', views.admin_verify_list, name='admin_verify_list'),
    path('admin-verify/<int:staff_id>/', views.admin_verify_staff, name='admin_verify_staff'),
    
    # ============================================
    # ROLE-SPECIFIC DASHBOARDS
    # ============================================
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('sales-officer-dashboard/', views.sales_officer_dashboard, name='sales_officer_dashboard'),
    path('sales-manager-dashboard/', views.sales_manager_dashboard, name='sales_manager_dashboard'),
    path('cashier-dashboard/', views.cashier_dashboard, name='cashier_dashboard'),
    path('store-manager-dashboard/', views.store_manager_dashboard, name='store_manager_dashboard'),
    path('credit-manager-dashboard/', views.credit_manager_dashboard, name='credit_manager_dashboard'),
    path('credit-officer-dashboard/', views.credit_officer_dashboard, name='credit_officer_dashboard'),
    path('customer-service-dashboard/', views.customer_service_dashboard, name='customer_service_dashboard'),
    path('supervisor-dashboard/', views.supervisor_dashboard, name='supervisor_dashboard'),
    path('security-dashboard/', views.security_dashboard, name='security_dashboard'),
    path('cleaner-dashboard/', views.cleaner_dashboard, name='cleaner_dashboard'),
    
    # ============================================
    # USER MANAGEMENT
    # ============================================
    path('users/', views.user_list, name='user_list'),
    path('users/<int:pk>/', views.user_detail, name='user_detail'),
    path('diagnostic-email/', diagnostic_email, name='diagnostic_email'),
    
    # ============================================
    # APPLICATION MANAGEMENT
    # ============================================
    path('applications/', views.application_list, name='application_list'),
    path('applications/<int:pk>/', views.application_detail, name='application_detail'),
    path('applications/<int:pk>/edit/', views.application_edit, name='application_edit'),
    path('applications/<int:pk>/delete/', views.application_delete, name='application_delete'),
    path('applications/<int:pk>/approve/', views.application_approve, name='application_approve'),
    path('applications/<int:pk>/reject/', views.application_reject, name='application_reject'),
    path('applications/<int:pk>/documents/', views.view_documents, name='view_documents'),
    path('applications/<int:pk>/revert-to-pending/', views.application_revert_to_pending, name='application_revert_to_pending'),
    
    # ============================================
    # PUBLIC APPLICATION FORMS
    # ============================================
    path('apply/', views.application_form, name='apply'),
    path('apply/success/', views.application_success, name='application_success'),
    path('notifications/', views.notifications_page, name='notifications_page'),
]