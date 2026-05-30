from django.urls import path
from . import views

app_name = 'workshop'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    
    # Job Management
    path('jobs/', views.job_list, name='job_list'),
    path('jobs/create/', views.job_create, name='job_create'),
    path('jobs/<int:job_id>/', views.job_detail, name='job_detail'),
    path('jobs/<int:job_id>/edit/', views.job_edit, name='job_edit'),
    path('jobs/<int:job_id>/delete/', views.job_delete, name='job_delete'),
    path('jobs/<int:job_id>/add-payment/', views.add_payment, name='add_payment'),
    path('jobs/<int:job_id>/receipt/', views.job_receipt, name='job_receipt'),
    
    # Technician Views
    path('technician/dashboard/', views.technician_dashboard, name='technician_dashboard'),
    path('technician/jobs/', views.technician_jobs, name='technician_jobs'),
    path('technician/jobs/<int:job_id>/update-status/', views.technician_update_job_status, name='technician_update_job_status'),
    path('technician/performance/', views.technician_performance, name='technician_performance'),
    
    # Pickup Views
    path('pickup/', views.pickup_page, name='pickup_page'),
    path('pickup/search/', views.search_job_for_pickup, name='search_job_for_pickup'),
    path('pickup/process/<int:job_id>/', views.process_pickup, name='process_pickup'),
    
    # Reports
    path('reports/', views.reports, name='reports'),
    
    # Helpers
    path('get-technicians-by-shop/', views.get_technicians_by_shop, name='get_technicians_by_shop'),
]