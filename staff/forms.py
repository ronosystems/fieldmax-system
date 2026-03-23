# staff/forms.py
from django.contrib.auth.forms import AuthenticationForm
from django import forms
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

class CustomAuthenticationForm(AuthenticationForm):
    """
    Custom authentication form that shows specific error messages
    for all account statuses: deactivated, suspended, locked
    """
    
    def clean(self):
        """
        Override clean method to check account status before password validation
        """
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        
        if username and password:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            try:
                # Try to find user by username or email
                user = None
                try:
                    user = User.objects.get(username=username)
                except User.DoesNotExist:
                    try:
                        user = User.objects.get(email=username)
                    except User.DoesNotExist:
                        pass
                
                if user:
                    # Log user found
                    logger.info(f"Login attempt for user: {user.username}, Active: {user.is_active}")
                    
                    # ============================================
                    # 1. CHECK DEACTIVATED (is_active = False)
                    # ============================================
                    if not user.is_active:
                        # Check if there's additional info in status
                        error_msg = 'Account Inactive.'
                        if hasattr(user, 'status') and user.status.deactivated_reason:
                            error_msg += f''
                        error_msg += ''
                        
                        raise forms.ValidationError(
                            error_msg,
                            code='deactivated'
                        )
                    
                    # ============================================
                    # 2. CHECK SUSPENDED
                    # ============================================
                    if hasattr(user, 'status') and user.status.is_suspended:
                        if user.status.suspended_until:
                            if user.status.suspended_until > timezone.now():
                                # Currently suspended
                                error_msg = f'account suspended.'
                                if user.status.suspension_reason:
                                    error_msg += f''
                                error_msg += ''
                                raise forms.ValidationError(error_msg, code='suspended')
                            else:
                                # Suspension expired - auto unsuspend
                                from .utils.user_status import UserStatusManager
                                UserStatusManager.unsuspend_user(user)
                                logger.info(f"Auto-unsuspended user: {user.username}")
                        else:
                            # Suspended without end date
                            error_msg = 'Account Suspended.'
                            if user.status.suspension_reason:
                                error_msg += f''
                            error_msg += ''
                            raise forms.ValidationError(error_msg, code='suspended')
                    
                    # ============================================
                    # 3. CHECK LOCKED
                    # ============================================
                    if hasattr(user, 'status') and user.status.is_locked:
                        if user.status.locked_at:
                            lock_expiry = user.status.locked_at + timedelta(minutes=30)
                            if lock_expiry > timezone.now():
                                # Currently locked
                                remaining = lock_expiry - timezone.now()
                                minutes_left = int(remaining.total_seconds() / 60)
                                seconds_left = int(remaining.total_seconds() % 60)
                                
                                if minutes_left > 0:
                                    error_msg = f'Account locked.'
                                else:
                                    error_msg = f'Account locked'
                                
                                if user.status.lock_reason:
                                    error_msg += f''
                                
                                raise forms.ValidationError(error_msg, code='locked')
                            else:
                                # Lock expired - auto unlock
                                from .utils.user_status import UserStatusManager
                                UserStatusManager.unlock_user(user)
                                logger.info(f"Auto-unlocked user: {user.username}")
                        else:
                            # Locked without timestamp
                            error_msg = 'Account locked.'
                            if user.status.lock_reason:
                                error_msg += f''
                            error_msg += ''
                            raise forms.ValidationError(error_msg, code='locked')
                    
                    # ============================================
                    # 4. ACCOUNT IS ACTIVE - PROCEED WITH PASSWORD CHECK
                    # ============================================
                    logger.info(f"Account is active for user: {user.username}")
                    
            except Exception as e:
                logger.error(f"Error checking user status: {e}")
                raise
        
        # Now do normal authentication
        return super().clean()
    
    def confirm_login_allowed(self, user):
        """
        Override to add custom validation for account status
        """
        # ============================================
        # 1. CHECK DEACTIVATED
        # ============================================
        if not user.is_active:
            error_msg = 'Account Inactive.'
            if hasattr(user, 'status') and user.status.deactivated_reason:
                error_msg += f''
            error_msg += ''
            raise forms.ValidationError(error_msg, code='deactivated')
        
        # ============================================
        # 2. CHECK SUSPENDED
        # ============================================
        if hasattr(user, 'status') and user.status.is_suspended:
            if user.status.suspended_until and user.status.suspended_until > timezone.now():
                error_msg = f'Account Suspended.'
                if user.status.suspension_reason:
                    error_msg += f''
                error_msg += ''
                raise forms.ValidationError(error_msg, code='suspended')
            elif user.status.suspended_until and user.status.suspended_until <= timezone.now():
                # Auto-unsuspend if expired
                from .utils.user_status import UserStatusManager
                UserStatusManager.unsuspend_user(user)
            else:
                error_msg = 'Account Suspended.'
                if user.status.suspension_reason:
                    error_msg += f''
                error_msg += ''
                raise forms.ValidationError(error_msg, code='suspended')
        
        # ============================================
        # 3. CHECK LOCKED
        # ============================================
        if hasattr(user, 'status') and user.status.is_locked:
            if user.status.locked_at:
                lock_expiry = user.status.locked_at + timedelta(minutes=30)
                if lock_expiry > timezone.now():
                    remaining = lock_expiry - timezone.now()
                    minutes_left = int(remaining.total_seconds() / 60)
                    error_msg = f'Account locked'
                    if user.status.lock_reason:
                        error_msg += f''
                    raise forms.ValidationError(error_msg, code='locked')
                else:
                    # Auto-unlock if expired
                    from .utils.user_status import UserStatusManager
                    UserStatusManager.unlock_user(user)
            else:
                error_msg = 'Account locked.'
                if user.status.lock_reason:
                    error_msg += f''
                error_msg += ''
                raise forms.ValidationError(error_msg, code='locked')
        
        # Call parent method for other validations
        super().confirm_login_allowed(user)