# main urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from staff.forms import CustomAuthenticationForm  # Import the custom form

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('website.urls')),
    path('inventory/', include('inventory.urls')),
    path('sales/', include('sales.urls')),
    path('store/', include('store.urls')),
    path('staff/', include('staff.urls')),
    path('credit/', include('credit.urls')),
    path('profiles/', include('profiles.urls')),
    
    # Authentication URLs - Use custom form
    path('login/', auth_views.LoginView.as_view(
        template_name='registration/login.html',
        authentication_form=CustomAuthenticationForm
    ), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)