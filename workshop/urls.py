# workshop/urls.py
from django.urls import path, include
from . import views

app_name = 'workshop'

urlpatterns = [
    # Existing URLs
    path('', views.dashboard, name='dashboard'),
    path('jobs/', views.job_list, name='job_list'),
    path('jobs/create/', views.job_create, name='job_create'),
    path('jobs/<int:job_id>/', views.job_detail, name='job_detail'),
    path('jobs/<int:job_id>/edit/', views.job_edit, name='job_edit'),
    path('jobs/<int:job_id>/delete/', views.job_delete, name='job_delete'),
    path('jobs/<int:job_id>/add-payment/', views.add_payment, name='add_payment'),
    path('reports/', views.reports, name='reports'),
    path('shops/<int:shop_id>/jobs/', views.shop_jobs, name='shop_jobs'),
    path('job-receipt/<int:job_id>/', views.job_receipt, name='job_receipt'),
    
    # Include technician URLs (no namespace)
    path('technician/', include('workshop.urls_technician')),
    
    # Helper URLs
    path('get-technicians-by-shop/', views.get_technicians_by_shop, name='get_technicians_by_shop'),
    path('technician-update-job-status/<int:job_id>/', views.technician_update_job_status, name='technician_update_job_status'),

    # Pickup URLs
    path('pickup/', views.pickup_page, name='pickup_page'),
    path('search-job-for-pickup/', views.search_job_for_pickup, name='search_job_for_pickup'),
    path('process-pickup/<int:job_id>/', views.process_pickup, name='process_pickup'),
]