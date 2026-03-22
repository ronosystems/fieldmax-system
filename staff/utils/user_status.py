# staff/utils/user_status.py
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages

class UserStatusManager:
    """Manage user account statuses"""
    
    @staticmethod
    def lock_user(user, reason='admin', request=None):
        """Lock a user account"""
        user.is_locked = True
        user.locked_at = timezone.now()
        user.lock_reason = reason
        user.save()
        
        message = f"User {user.username} has been locked."
        if request:
            messages.success(request, message)
        return message
    
    @staticmethod
    def unlock_user(user, request=None):
        """Unlock a user account"""
        user.is_locked = False
        user.locked_at = None
        user.lock_reason = ''
        user.failed_login_attempts = 0
        user.save()
        
        message = f"User {user.username} has been unlocked."
        if request:
            messages.success(request, message)
        return message
    
    @staticmethod
    def suspend_user(user, reason, suspended_by, days=30, request=None):
        """Suspend a user account"""
        user.is_suspended = True
        user.suspended_at = timezone.now()
        user.suspended_until = timezone.now() + timedelta(days=days)
        user.suspension_reason = reason
        user.suspended_by = suspended_by
        user.save()
        
        message = f"User {user.username} has been suspended until {user.suspended_until.strftime('%Y-%m-%d')}."
        if request:
            messages.success(request, message)
        return message
    
    @staticmethod
    def unsuspend_user(user, request=None):
        """Unsuspend a user account"""
        user.is_suspended = False
        user.suspended_until = None
        user.save()
        
        message = f"User {user.username} has been unsuspended."
        if request:
            messages.success(request, message)
        return message
    
    @staticmethod
    def deactivate_user(user, reason, deactivated_by, request=None):
        """Permanently deactivate a user account"""
        user.is_active = False
        user.deactivated_at = timezone.now()
        user.deactivated_reason = reason
        user.deactivated_by = deactivated_by
        user.save()
        
        message = f"User {user.username} has been deactivated."
        if request:
            messages.success(request, message)
        return message
    
    @staticmethod
    def activate_user(user, request=None):
        """Reactivate a user account"""
        user.is_active = True
        user.deactivated_at = None
        user.deactivated_reason = ''
        user.deactivated_by = None
        user.save()
        
        message = f"User {user.username} has been activated."
        if request:
            messages.success(request, message)
        return message
    
    @staticmethod
    def get_user_status(user):
        """Get detailed user status"""
        status = {
            'username': user.username,
            'full_name': user.get_full_name(),
            'email': user.email,
            'can_login': True,
            'restrictions': []
        }
        
        if not user.is_active:
            status['can_login'] = False
            status['restrictions'].append({
                'type': 'deactivated',
                'message': 'Account deactivated',
                'date': user.deactivated_at,
                'reason': user.deactivated_reason
            })
        
        if user.is_locked:
            status['can_login'] = False
            status['restrictions'].append({
                'type': 'locked',
                'message': 'Account locked',
                'date': user.locked_at,
                'reason': user.lock_reason
            })
        
        if user.is_suspended:
            status['can_login'] = False
            status['restrictions'].append({
                'type': 'suspended',
                'message': 'Account suspended',
                'date': user.suspended_at,
                'until': user.suspended_until,
                'reason': user.suspension_reason
            })
        
        return status
    



    # staff/utils/user_status.py
from django.utils import timezone
from datetime import timedelta
from django.contrib import messages
from staff.models import UserStatus

class UserStatusManager:
    """Manage user account statuses"""
    
    @staticmethod
    def get_user_status(user):
        """Get or create user status"""
        status, created = UserStatus.objects.get_or_create(user=user)
        return status
    
    @staticmethod
    def lock_user(user, reason='admin', request=None):
        """Lock a user account"""
        status = UserStatusManager.get_user_status(user)
        status.is_locked = True
        status.locked_at = timezone.now()
        status.lock_reason = reason
        status.save()
        
        message = f"User {user.username} has been locked."
        if request:
            messages.success(request, message)
        return message
    
    @staticmethod
    def unlock_user(user, request=None):
        """Unlock a user account"""
        status = UserStatusManager.get_user_status(user)
        status.is_locked = False
        status.locked_at = None
        status.lock_reason = ''
        status.failed_login_attempts = 0
        status.save()
        
        message = f"User {user.username} has been unlocked."
        if request:
            messages.success(request, message)
        return message
    
    @staticmethod
    def suspend_user(user, reason, suspended_by, days=30, request=None):
        """Suspend a user account"""
        status = UserStatusManager.get_user_status(user)
        status.is_suspended = True
        status.suspended_at = timezone.now()
        status.suspended_until = timezone.now() + timedelta(days=days)
        status.suspension_reason = reason
        status.suspended_by = suspended_by
        status.save()
        
        message = f"User {user.username} has been suspended until {status.suspended_until.strftime('%Y-%m-%d')}."
        if request:
            messages.success(request, message)
        return message
    
    @staticmethod
    def unsuspend_user(user, request=None):
        """Unsuspend a user account"""
        status = UserStatusManager.get_user_status(user)
        status.is_suspended = False
        status.suspended_until = None
        status.save()
        
        message = f"User {user.username} has been unsuspended."
        if request:
            messages.success(request, message)
        return message
    
    @staticmethod
    def deactivate_user(user, reason, deactivated_by, request=None):
        """Permanently deactivate a user account"""
        user.is_active = False
        user.save()
        
        status = UserStatusManager.get_user_status(user)
        status.deactivated_at = timezone.now()
        status.deactivated_reason = reason
        status.deactivated_by = deactivated_by
        status.save()
        
        message = f"User {user.username} has been deactivated."
        if request:
            messages.success(request, message)
        return message
    
    @staticmethod
    def activate_user(user, request=None):
        """Reactivate a user account"""
        user.is_active = True
        user.save()
        
        status = UserStatusManager.get_user_status(user)
        status.deactivated_at = None
        status.deactivated_reason = ''
        status.deactivated_by = None
        status.save()
        
        message = f"User {user.username} has been activated."
        if request:
            messages.success(request, message)
        return message
    
    @staticmethod
    def record_failed_login(user):
        """Record failed login attempt"""
        status = UserStatusManager.get_user_status(user)
        status.failed_login_attempts += 1
        status.last_failed_login = timezone.now()
        
        # Auto-lock after 5 failed attempts
        if status.failed_login_attempts >= 5:
            status.is_locked = True
            status.locked_at = timezone.now()
            status.lock_reason = 'failed_login'
        
        status.save()
        return status.failed_login_attempts
    
    @staticmethod
    def reset_failed_attempts(user):
        """Reset failed login attempts"""
        status = UserStatusManager.get_user_status(user)
        status.failed_login_attempts = 0
        status.last_failed_login = None
        status.save()