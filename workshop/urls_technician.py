from django.urls import path
from . import views_technician

app_name = 'workshop_technician'

urlpatterns = [
    # Main dashboard
    path('dashboard/', views_technician.technician_dashboard, name='technician_dashboard'),
    
    # Jobs
    path('jobs/', views_technician.technician_jobs, name='technician_jobs'),
    path('jobs/<int:job_id>/', views_technician.technician_job_detail, name='technician_job_detail'),
    path('jobs/<int:job_id>/update-status/', views_technician.technician_update_status, name='technician_update_status'),
    path('jobs/<int:job_id>/add-expense/', views_technician.technician_add_expense, name='technician_add_expense'),
    path('jobs/<int:job_id>/take/', views_technician.technician_take_job, name='technician_take_job'),
    
    # Performance
    path('performance/', views_technician.technician_my_performance, name='technician_performance'),
    
    # AJAX endpoints
    path('search-customer/', views_technician.technician_search_customer, name='technician_search_customer'),
]