# staff/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Count, Sum
from django.contrib import messages
from django.utils import timezone 
from .models import (
    PendingOrder, 
    PendingOrderItem, 
    Customer, 
    Order, 
    OrderItem, 
    Cart, 
    CartItem
)


# ============================================
# PENDING ORDER ADMIN
# ============================================

class PendingOrderItemInline(admin.TabularInline):
    """Inline for pending order items"""
    model = PendingOrderItem
    extra = 0
    readonly_fields = ('product_name', 'quantity', 'unit_price', 'total_price')
    fields = ('product_name', 'quantity', 'unit_price', 'total_price')
    can_delete = False
    
    def total_price(self, obj):
        return f"KES {obj.total_price:,.2f}"
    total_price.short_description = 'Total'


@admin.register(PendingOrder)
class PendingOrderAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'buyer_name', 'buyer_phone', 'total_amount_display', 
                   'item_count', 'status_badge', 'created_at', 'action_buttons')
    list_filter = ('status', 'payment_method', 'created_at')
    search_fields = ('order_id', 'buyer_name', 'buyer_phone', 'buyer_email')
    readonly_fields = ('order_id', 'created_at', 'updated_at', 'cart_items_display')
    inlines = [PendingOrderItemInline]
    fieldsets = (
        ('Order Information', {
            'fields': ('order_id', 'status', 'created_at', 'updated_at')
        }),
        ('Customer Details', {
            'fields': ('buyer_name', 'buyer_phone', 'buyer_email', 'buyer_id_number')
        }),
        ('Order Details', {
            'fields': ('total_amount', 'item_count', 'payment_method', 'notes', 'cart_items_display')
        }),
        ('Staff Actions', {
            'fields': ('reviewed_by', 'reviewed_at', 'rejection_reason', 
                      'approved_by', 'approved_date', 'rejected_by', 'rejected_date')
        }),
    )
    
    def total_amount_display(self, obj):
        return format_html('<span class="font-weight-bold">KES {:,}</span>', obj.total_amount)
    total_amount_display.short_description = 'Total Amount'
    
    def status_badge(self, obj):
        colors = {
            'pending': 'warning',
            'completed': 'success',
            'rejected': 'danger',
        }
        color = colors.get(obj.status, 'secondary')
        icons = {
            'pending': 'fa-clock',
            'completed': 'fa-check-circle',
            'rejected': 'fa-times-circle',
        }
        icon = icons.get(obj.status, 'fa-question-circle')
        return format_html(
            '<span class="badge bg-{}"><i class="fas {} me-1"></i>{}</span>',
            color, icon, obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def cart_items_display(self, obj):
        items = obj.cart_items
        if not items:
            return "No items"
        
        html = '<div style="max-height: 200px; overflow-y: auto;">'
        for item in items:
            html += f'<div style="padding: 5px; border-bottom: 1px solid #eee;">'
            html += f'<strong>{item.get("name", "Unknown")}</strong><br>'
            html += f'Qty: {item.get("quantity", 0)} x KES {item.get("price", 0):,.2f}<br>'
            html += f'Total: KES {item.get("total", 0):,.2f}'
            html += '</div>'
        html += '</div>'
        return format_html(html)
    cart_items_display.short_description = 'Cart Items'
    
    def action_buttons(self, obj):
        buttons = []
        if obj.status == 'pending':
            approve_url = reverse('admin:pendingorder_approve', args=[obj.id])
            reject_url = reverse('admin:pendingorder_reject', args=[obj.id])
            buttons.append(f'<a href="{approve_url}" class="button" style="background: #28a745; color: white; padding: 3px 8px; border-radius: 3px; text-decoration: none; margin-right: 5px;">✓ Approve</a>')
            buttons.append(f'<a href="{reject_url}" class="button" style="background: #dc3545; color: white; padding: 3px 8px; border-radius: 3px; text-decoration: none;">✗ Reject</a>')
        return format_html(''.join(buttons))
    action_buttons.short_description = 'Actions'
    action_buttons.allow_tags = True
    
    actions = ['approve_selected', 'reject_selected']
    
    def approve_selected(self, request, queryset):
        count = 0
        for order in queryset.filter(status='pending'):
            # Approve logic here (you'll need to implement)
            order.status = 'completed'
            order.reviewed_by = request.user
            order.reviewed_at = timezone.now()
            order.save()
            count += 1
        self.message_user(request, f'{count} order(s) approved successfully.', messages.SUCCESS)
    approve_selected.short_description = "Approve selected orders"
    
    def reject_selected(self, request, queryset):
        count = 0
        for order in queryset.filter(status='pending'):
            order.status = 'rejected'
            order.reviewed_by = request.user
            order.reviewed_at = timezone.now()
            order.save()
            count += 1
        self.message_user(request, f'{count} order(s) rejected.', messages.SUCCESS)
    reject_selected.short_description = "Reject selected orders"
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('reviewed_by')


# ============================================
# CUSTOMER ADMIN
# ============================================

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'email', 'phone', 'city', 'is_active', 'order_count', 'total_spent', 'created_at')
    list_filter = ('is_active', 'city', 'created_at')
    search_fields = ('full_name', 'email', 'phone')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Personal Information', {
            'fields': ('user', 'full_name', 'email', 'phone')
        }),
        ('Address Information', {
            'fields': ('address', 'city', 'postal_code')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def order_count(self, obj):
        count = obj.orders.count()
        return format_html('<span class="badge bg-info">{}</span>', count)
    order_count.short_description = 'Orders'
    
    def total_spent(self, obj):
        total = obj.orders.aggregate(total=Sum('total_amount'))['total'] or 0
        return format_html('KES {:,}', total)
    total_spent.short_description = 'Total Spent'
    
    actions = ['activate_customers', 'deactivate_customers']
    
    def activate_customers(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} customer(s) activated.')
    activate_customers.short_description = "Activate selected customers"
    
    def deactivate_customers(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} customer(s) deactivated.')
    deactivate_customers.short_description = "Deactivate selected customers"


# ============================================
# ORDER ADMIN
# ============================================

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product_code', 'product_name', 'product_price', 'quantity', 'subtotal')
    fields = ('product_code', 'product_name', 'product_price', 'quantity', 'subtotal')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'customer_link', 'total_amount_display', 'status_badge', 
                   'payment_status_badge', 'item_count', 'created_at')
    list_filter = ('status', 'payment_status', 'created_at')
    search_fields = ('order_number', 'customer_name', 'customer_email', 'customer_phone')
    readonly_fields = ('order_number', 'created_at', 'updated_at', 'completed_at')
    inlines = [OrderItemInline]
    fieldsets = (
        ('Order Information', {
            'fields': ('order_number', 'status', 'payment_status', 'created_at', 'updated_at', 'completed_at')
        }),
        ('Customer Information', {
            'fields': ('customer', 'customer_name', 'customer_email', 'customer_phone')
        }),
        ('Delivery Details', {
            'fields': ('delivery_address', 'delivery_city', 'delivery_postal_code')
        }),
        ('Pricing', {
            'fields': ('subtotal', 'delivery_fee', 'total_amount')
        }),
        ('Additional', {
            'fields': ('notes',)
        }),
    )
    
    def customer_link(self, obj):
        if obj.customer:
            url = reverse('admin:staff_customer_change', args=[obj.customer.id])
            return format_html('<a href="{}">{}</a>', url, obj.customer_name)
        return obj.customer_name
    customer_link.short_description = 'Customer'
    
    def total_amount_display(self, obj):
        return format_html('<strong>KES {:,}</strong>', obj.total_amount)
    total_amount_display.short_description = 'Total'
    
    def status_badge(self, obj):
        colors = {
            'pending': 'secondary',
            'confirmed': 'info',
            'processing': 'primary',
            'shipped': 'warning',
            'delivered': 'success',
            'completed': 'success',
            'cancelled': 'danger',
        }
        color = colors.get(obj.status, 'secondary')
        return format_html('<span class="badge bg-{}">{}</span>', color, obj.get_status_display())
    status_badge.short_description = 'Status'
    
    def payment_status_badge(self, obj):
        colors = {
            'pending': 'warning',
            'paid': 'success',
            'failed': 'danger',
            'refunded': 'info',
        }
        color = colors.get(obj.payment_status, 'secondary')
        icons = {
            'pending': 'fa-clock',
            'paid': 'fa-check',
            'failed': 'fa-times',
            'refunded': 'fa-undo',
        }
        icon = icons.get(obj.payment_status, 'fa-question')
        return format_html(
            '<span class="badge bg-{}"><i class="fas {} me-1"></i>{}</span>',
            color, icon, obj.get_payment_status_display()
        )
    payment_status_badge.short_description = 'Payment'
    
    def item_count(self, obj):
        count = obj.items.count()
        return format_html('<span class="badge bg-info">{}</span>', count)
    item_count.short_description = 'Items'
    
    actions = ['mark_as_confirmed', 'mark_as_processing', 'mark_as_shipped', 'mark_as_delivered', 'mark_as_completed', 'cancel_orders']
    
    def mark_as_confirmed(self, request, queryset):
        updated = queryset.update(status='confirmed')
        self.message_user(request, f'{updated} order(s) marked as confirmed.')
    mark_as_confirmed.short_description = "Mark as confirmed"
    
    def mark_as_processing(self, request, queryset):
        updated = queryset.update(status='processing')
        self.message_user(request, f'{updated} order(s) marked as processing.')
    mark_as_processing.short_description = "Mark as processing"
    
    def mark_as_shipped(self, request, queryset):
        updated = queryset.update(status='shipped')
        self.message_user(request, f'{updated} order(s) marked as shipped.')
    mark_as_shipped.short_description = "Mark as shipped"
    
    def mark_as_delivered(self, request, queryset):
        updated = queryset.update(status='delivered')
        self.message_user(request, f'{updated} order(s) marked as delivered.')
    mark_as_delivered.short_description = "Mark as delivered"
    
    def mark_as_completed(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(status='completed', completed_at=timezone.now())
        self.message_user(request, f'{updated} order(s) marked as completed.')
    mark_as_completed.short_description = "Mark as completed"
    
    def cancel_orders(self, request, queryset):
        updated = queryset.update(status='cancelled')
        self.message_user(request, f'{updated} order(s) cancelled.')
    cancel_orders.short_description = "Cancel orders"
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('customer').prefetch_related('items')


# ============================================
# CART ADMIN
# ============================================

class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ('product', 'quantity', 'subtotal')
    fields = ('product', 'quantity', 'subtotal')
    can_delete = False
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer_link', 'session_key', 'item_count', 'total_display', 'created_at', 'updated_at')
    list_filter = ('created_at',)
    search_fields = ('session_key', 'customer__full_name', 'customer__email')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [CartItemInline]
    
    def customer_link(self, obj):
        if obj.customer:
            url = reverse('admin:staff_customer_change', args=[obj.customer.id])
            return format_html('<a href="{}">{}</a>', url, obj.customer.full_name)
        return '-'
    customer_link.short_description = 'Customer'
    
    def item_count(self, obj):
        count = obj.items.count()
        return format_html('<span class="badge bg-info">{}</span>', count)
    item_count.short_description = 'Items'
    
    def total_display(self, obj):
        total = obj.get_total()
        return format_html('<strong>KES {:,}</strong>', total)
    total_display.short_description = 'Total'


# ============================================
# DASHBOARD STATISTICS
# ============================================

class StaffDashboardAdmin(admin.AdminSite):
    """Custom admin site with dashboard statistics"""
    site_header = 'FieldMax Staff Portal'
    site_title = 'FieldMax Admin'
    index_title = 'Staff Dashboard'
    
    def get_app_list(self, request):
        app_list = super().get_app_list(request)
        
        # Add custom statistics
        if request.user.is_superuser:
            from django.utils import timezone
            today = timezone.now().date()
            
            # Get stats
            pending_orders = PendingOrder.objects.filter(status='pending').count()
            new_customers = Customer.objects.filter(created_at__date=today).count()
            today_orders = Order.objects.filter(created_at__date=today).count()
            
            # Add to app list (you can customize this)
            for app in app_list:
                if app['app_label'] == 'staff':
                    app['models'].append({
                        'name': 'dashboard_stats',
                        'object_name': 'DashboardStats',
                        'admin_url': '#',
                        'view_only': True,
                        'perms': {'change': False, 'add': False, 'delete': False},
                    })
        return app_list

# Optional: Create a custom admin site
# admin_site = StaffDashboardAdmin(name='staffadmin')