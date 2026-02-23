
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages
from .models import UserProfile

class PasswordChangeMiddleware:
    """Middleware to force password change on first login"""
    
    def __init__(self, get_response):
        self.get_response = get_response
        
    def __call__(self, request):
        # Skip for unauthenticated users
        if not request.user.is_authenticated:
            return self.get_response(request)
        
        # Skip for staff password change URL and logout
        if request.path in [reverse('staff:password_change'), reverse('staff:logout'), reverse('admin:logout')]:
            return self.get_response(request)
        
        # Check if user needs to change password
        try:
            # Try to get or create profile
            profile, created = UserProfile.objects.get_or_create(user=request.user)
            
            # If password hasn't been changed yet (first login)
            if not profile.password_changed:
                messages.warning(request, 'Please change your password to continue.')
                return redirect('staff:password_change')
                
        except Exception as e:
            # Log the error but don't block access completely
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in PasswordChangeMiddleware: {str(e)}")
            
            # Create profile if it doesn't exist
            UserProfile.objects.get_or_create(user=request.user)
        
        return self.get_response(request)