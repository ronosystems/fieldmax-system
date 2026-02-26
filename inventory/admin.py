from django.contrib import admin
from django import forms
from .models import Supplier, Category, Product, ProductImage, StockEntry, StockAlert, ProductReview
from django.utils.html import format_html
from django.db.models import Count, Sum
from decimal import Decimal
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User


from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html





# ====================================
# CUSTOM USER ADMIN - SAFE VERSION
# ====================================

class CustomUserAdmin(UserAdmin):
    # SIMPLE list_display - no custom methods first
    list_display = ['username', 'email', 'first_name', 'last_name', 'is_staff', 'is_superuser', 'is_active']
    list_filter = ['is_staff', 'is_superuser', 'is_active']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    list_per_page = 25
    list_display_links = ['username']
    
    # Fieldsets for user detail page
    fieldsets = (
        ('📋 BASIC INFORMATION', {
            'fields': ('username', 'password', 'email')
        }),
        ('👤 PERSONAL INFO', {
            'fields': ('first_name', 'last_name')
        }),
        ('🔑 PERMISSIONS', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ('wide',),
        }),
        ('📅 IMPORTANT DATES', {
            'fields': ('last_login', 'date_joined'),
            'classes': ('collapse',),
        }),
    )
    
    # Actions
    actions = ['make_active', 'make_inactive', 'make_staff', 'remove_staff']
    actions_on_top = True
    actions_on_bottom = False
    
    def make_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} users activated.')
    make_active.short_description = "Activate selected users"
    
    def make_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} users deactivated.')
    make_inactive.short_description = "Deactivate selected users"
    
    def make_staff(self, request, queryset):
        updated = queryset.update(is_staff=True)
        self.message_user(request, f'{updated} users granted staff access.')
    make_staff.short_description = "Grant staff access"
    
    def remove_staff(self, request, queryset):
        updated = queryset.update(is_staff=False)
        self.message_user(request, f'{updated} users removed from staff.')
    remove_staff.short_description = "Remove staff access"

# Unregister the default User admin and register our custom one
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)







# ====================================
# CUSTOM FORMS
# ====================================

class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'
    
    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category')
        sku_value = cleaned_data.get('sku_value')
        quantity = cleaned_data.get('quantity')
        brand = cleaned_data.get('brand')
        model = cleaned_data.get('model')
        
        if category:
            if category.is_single_item:
                if not sku_value:
                    self.add_error('sku_value', 'SKU value (IMEI/Serial) is required for single items')
                if quantity != 1:
                    self.add_error('quantity', 'Single items must have quantity = 1')
                if not brand or not model:
                    if not brand:
                        self.add_error('brand', 'Brand is required for single items')
                    if not model:
                        self.add_error('model', 'Model is required for single items')
            
            if category.is_bulk_item:
                if quantity and quantity < 0:
                    self.add_error('quantity', 'Quantity cannot be negative')
        
        return cleaned_data

# ====================================
# INLINE CLASSES
# ====================================

class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ['image', 'is_primary', 'order']
    classes = ['collapse']

# ====================================
# SUPPLIER ADMIN
# ====================================

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['name', 'contact_person', 'phone', 'email', 'product_count', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'contact_person', 'email', 'phone', 'tax_id']
    readonly_fields = ['product_count', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Company Information', {
            'fields': ('name', 'contact_person', 'phone', 'email', 'address')
        }),
        ('Business Details', {
            'fields': ('tax_id', 'payment_terms', 'is_active')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

# ====================================
# CATEGORY ADMIN
# ====================================

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'category_code', 'item_type', 'sku_type', 'product_count', 'is_active']
    list_filter = ['item_type', 'sku_type', 'is_active']
    search_fields = ['name', 'category_code']
    readonly_fields = ['category_code', 'product_count', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Category Information', {
            'fields': ('name', 'category_code')
        }),
        ('Type Settings', {
            'fields': ('item_type', 'sku_type'),
            'description': 'These settings determine how products in this category behave'
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )











# ====================================
# PRODUCT ADMIN - MAIN
# ====================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    
    # ====================================
    # LIST DISPLAY - ALL COLUMNS
    # ====================================
    list_display = [
        'product_code',           # Product Code
        'display_name',            # Product Name
        'category_name',           # Category
        'buying_price_display',    # Cost Price
        'selling_price_display',   # Selling Price
        'best_price_display',      # Best Price
        'sku_display',             # SKU
        'barcode_display',         # Barcode
        'stock_display',           # Stock
        'status_display',          # Status
        'condition_display',       # Condition
    ]
    
    list_display_links = ['product_code', 'display_name']
    
    # ====================================
    # SEARCH CONFIGURATION
    # ====================================
    search_fields = [
        'product_code', 
        'name', 
        'brand', 
        'model', 
        'sku_value', 
        'barcode',
        'description',
    ]
    search_help_text = "Search by product code, name, brand, model, SKU, or barcode"
    
    # ====================================
    # READONLY FIELDS
    # ====================================
    readonly_fields = [
        'product_code', 
        'created_at', 
        'updated_at', 
        'view_count', 
        'sales_count',
        'profit_calculation',
    ]
    
    # ====================================
    # INLINES
    # ====================================
    inlines = [ProductImageInline]
    
    # ====================================
    # LAYOUT OPTIONS
    # ====================================
    save_on_top = True
    list_per_page = 25
    show_full_result_count = True
    
    # ====================================
    # FIELDSETS - FORM LAYOUT
    # ====================================
    fieldsets = (
        ('📋 BASIC INFORMATION', {
            'fields': (
                ('product_code', 'name'),
                ('category', 'owner'),
            ),
            'classes': ('wide',),
        }),
        
        ('💰 PRICING DETAILS', {
            'fields': (
                ('buying_price', 'selling_price', 'best_price'),
                'profit_calculation',
            ),
            'classes': ('wide', 'collapse'),
        }),
        
        ('📦 INVENTORY TRACKING', {
            'fields': (
                ('sku_value', 'barcode'),
                ('quantity', 'reorder_level'),
                'last_restocked',
            ),
            'classes': ('wide',),
        }),
        
        ('📱 PRODUCT SPECIFICATIONS', {
            'fields': (
                ('brand', 'model'),
                ('condition', 'warranty_months'),
                'specifications',
                'description',
            ),
            'classes': ('wide', 'collapse'),
        }),
        
        ('🏭 SUPPLIER INFORMATION', {
            'fields': ('supplier',),
            'classes': ('wide', 'collapse'),
        }),
        
        ('🖼️ MEDIA', {
            'fields': ('image',),
            'classes': ('wide', 'collapse'),
        }),
        
        ('📊 STATUS & TRACKING', {
            'fields': (
                ('status', 'is_featured'),
                'is_active',
                ('view_count', 'sales_count'),
            ),
            'classes': ('wide', 'collapse'),
        }),
        
        ('📅 SYSTEM METADATA', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('wide', 'collapse'),
        }),
    )
    
    # ====================================
    # ACTIONS
    # ====================================
    actions = ['mark_as_available', 'mark_as_sold', 'mark_as_featured']
    actions_on_top = True
    actions_on_bottom = False
    
    # ====================================
    # CUSTOM METHODS FOR DISPLAY
    # ====================================
    
    def get_queryset(self, request):
        """Optimize queryset"""
        return super().get_queryset(request).select_related('category', 'supplier', 'owner')
    
    # Product Name
    def display_name(self, obj):
        try:
            if obj.brand and obj.model:
                return f"{obj.brand} {obj.model}"
            return obj.name or obj.product_code or "Unnamed"
        except:
            return "Error"
    display_name.short_description = 'Product'
    display_name.admin_order_field = 'name'
    
    # Category
    def category_name(self, obj):
        try:
            if not obj.category:
                return "-"
            if obj.category.is_single_item:
                return f"📱 {obj.category.name}"
            else:
                return f"📦 {obj.category.name}"
        except:
            return "-"
    category_name.short_description = 'Category'
    category_name.admin_order_field = 'category__name'
    
    # Buying Price - UPDATED TO KSH
    def buying_price_display(self, obj):
        try:
            if obj.buying_price:
                return f"KSH {obj.buying_price:,.0f}"
            return "-"
        except:
            return "-"
    buying_price_display.short_description = 'Cost (KSH)'
    buying_price_display.admin_order_field = 'buying_price'
    
    # Selling Price - UPDATED TO KSH
    def selling_price_display(self, obj):
        try:
            if obj.selling_price:
                return f"KSH {obj.selling_price:,.0f}"
            return "-"
        except:
            return "-"
    selling_price_display.short_description = 'Sell (KSH)'
    selling_price_display.admin_order_field = 'selling_price'
    
    # Best Price - UPDATED TO KSH
    def best_price_display(self, obj):
        try:
            if obj.best_price:
                return f"KSH {obj.best_price:,.0f}"
            return "-"
        except:
            return "-"
    best_price_display.short_description = 'Best (KSH)'
    best_price_display.admin_order_field = 'best_price'
    
    # SKU
    def sku_display(self, obj):
        try:
            if obj.sku_value:
                sku = str(obj.sku_value)
                if len(sku) > 15:
                    sku = sku[:12] + "..."
                return sku
            return "-"
        except:
            return "-"
    sku_display.short_description = 'SKU'
    sku_display.admin_order_field = 'sku_value'
    
    # Barcode
    def barcode_display(self, obj):
        try:
            if obj.barcode:
                barcode = str(obj.barcode)
                if len(barcode) > 15:
                    barcode = barcode[:12] + "..."
                return barcode
            return "-"
        except:
            return "-"
    barcode_display.short_description = 'Barcode'
    barcode_display.admin_order_field = 'barcode'
    
    # Stock
    def stock_display(self, obj):
        try:
            qty = obj.quantity or 0
            
            if obj.category and obj.category.is_single_item:
                return "✓" if qty > 0 else "✗"
            else:
                if obj.reorder_level and qty <= obj.reorder_level and qty > 0:
                    return f"{qty} ⚠️"
                elif qty == 0:
                    return "0 ❌"
                return str(qty)
        except:
            return "0"
    stock_display.short_description = 'Stock'
    stock_display.admin_order_field = 'quantity'
    
    # Status
    def status_display(self, obj):
        try:
            status_map = {
                'available': '✓ Available',
                'sold': '✗ Sold',
                'reserved': '⏳ Reserved',
                'damaged': '⚠️ Damaged',
                'lowstock': '⚠️ Low Stock',
                'outofstock': '❌ Out of Stock',
            }
            return status_map.get(obj.status, obj.get_status_display() or 'Unknown')
        except:
            return 'Unknown'
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'
    
    # Condition
    def condition_display(self, obj):
        try:
            return obj.get_condition_display() or 'Unknown'
        except:
            return 'Unknown'
    condition_display.short_description = 'Condition'
    condition_display.admin_order_field = 'condition'
    
    # Profit Calculation - UPDATED TO KSH
    def profit_calculation(self, obj):
        try:
            if obj.buying_price and obj.selling_price:
                profit = obj.selling_price - obj.buying_price
                margin = (profit / obj.buying_price * 100) if obj.buying_price > 0 else 0
                
                return (f"Profit: KSH {profit:,.0f} | Margin: {margin:.1f}%")
            return "Set buying and selling prices to see profit"
        except:
            return "Error calculating profit"
    profit_calculation.short_description = 'Profit Analysis'
    
    # ====================================
    # ACTIONS
    # ====================================
    
    def mark_as_available(self, request, queryset):
        updated = queryset.update(status='available')
        self.message_user(request, f'{updated} products marked as available.')
    mark_as_available.short_description = "Mark selected as Available"
    
    def mark_as_sold(self, request, queryset):
        updated = queryset.update(status='sold')
        self.message_user(request, f'{updated} products marked as sold.')
    mark_as_sold.short_description = "Mark selected as Sold"
    
    def mark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(request, f'{updated} products marked as featured.')
    mark_as_featured.short_description = "Mark selected as Featured"












# ====================================
# STOCK ENTRY ADMIN
# ====================================

@admin.register(StockEntry)
class StockEntryAdmin(admin.ModelAdmin):
    list_display = [
        'id', 
        'product_name', 
        'entry_type_colored', 
        'quantity_colored', 
        'unit_price_ksh', 
        'total_amount_ksh', 
        'reference_id', 
        'created_by', 
        'created_at_colored'
    ]
    search_fields = ['product__product_code', 'product__name', 'reference_id', 'notes']
    readonly_fields = ['total_amount', 'created_at', 'stock_before', 'stock_after']
    raw_id_fields = ['product', 'created_by']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('product', 'entry_type', 'quantity')
        }),
        ('Financial Information', {
            'fields': (('unit_price', 'total_amount'),)
        }),
        ('Stock Impact', {
            'fields': ('stock_before', 'stock_after'),
            'classes': ('wide',),
        }),
        ('Reference Information', {
            'fields': ('reference_id', 'notes', 'created_by')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def product_name(self, obj):
        try:
            return obj.product.display_name if obj.product else "-"
        except:
            return "-"
    product_name.short_description = 'Product'
    product_name.admin_order_field = 'product__name'
    
    def entry_type_colored(self, obj):
        colors = {
            'purchase': '#27ae60',  # Green
            'sale': '#e74c3c',       # Red
            'reversal': '#f39c12',    # Orange
            'adjustment': '#3498db',  # Blue
        }
        color = colors.get(obj.entry_type, '#95a5a6')
        return format_html(
            '<span style="color: {}; font-weight: bold;">⬤ {}</span>',
            color, obj.get_entry_type_display()
        )
    entry_type_colored.short_description = 'Type'
    
    def quantity_colored(self, obj):
        if obj.quantity > 0:
            return format_html('<span style="color: #27ae60; font-weight: bold;">+{}</span>', obj.quantity)
        elif obj.quantity < 0:
            return format_html('<span style="color: #e74c3c; font-weight: bold;">{}</span>', obj.quantity)
        return str(obj.quantity)
    quantity_colored.short_description = 'Qty'
    
    def unit_price_ksh(self, obj):
        try:
            return f"KSH {obj.unit_price:,.0f}" if obj.unit_price else "-"
        except:
            return "-"
    unit_price_ksh.short_description = 'Unit Price'
    
    def total_amount_ksh(self, obj):
        try:
            return f"KSH {obj.total_amount:,.0f}" if obj.total_amount else "-"
        except:
            return "-"
    total_amount_ksh.short_description = 'Total'
    
    def created_at_colored(self, obj):
        if obj.created_at:
            return format_html(
                '<span title="{}">{}</span>',
                obj.created_at,
                obj.created_at.strftime('%Y-%m-%d %H:%M')
            )
        return "-"
    created_at_colored.short_description = 'Created'
    
    def stock_before(self, obj):
        """Calculate stock before this entry"""
        try:
            # Sum all entries before this one
            entries_before = StockEntry.objects.filter(
                product=obj.product,
                created_at__lt=obj.created_at
            ).aggregate(total=Sum('quantity'))['total'] or 0
            
            # Add initial product quantity? This depends on your logic
            # For now, just show entries sum
            return entries_before
        except:
            return "N/A"
    stock_before.short_description = 'Stock Before'
    
    def stock_after(self, obj):
        """Calculate stock after this entry"""
        try:
            entries_total = StockEntry.objects.filter(
                product=obj.product,
                created_at__lte=obj.created_at
            ).aggregate(total=Sum('quantity'))['total'] or 0
            return entries_total
        except:
            return "N/A"
    stock_after.short_description = 'Stock After'
    
    actions = ['revert_entry']
    
    def revert_entry(self, request, queryset):
        """Create reversal entries for selected entries"""
        count = 0
        for entry in queryset:
            try:
                # Create reversal entry
                StockEntry.objects.create(
                    product=entry.product,
                    quantity=-entry.quantity,  # Reverse the quantity
                    entry_type='reversal',
                    unit_price=entry.unit_price,
                    total_amount=entry.total_amount,
                    reference_id=f"REV-{entry.id}",
                    notes=f"Reversal of entry #{entry.id}",
                    created_by=request.user
                )
                count += 1
            except Exception as e:
                self.message_user(request, f"Error reverting entry #{entry.id}: {str(e)}", level='ERROR')
        
        self.message_user(request, f'Created {count} reversal entries.')
    revert_entry.short_description = "Reverse selected entries"











# ====================================
# STOCK ALERT ADMIN
# ====================================

@admin.register(StockAlert)
class StockAlertAdmin(admin.ModelAdmin):
    list_display = [
        'product', 
        'alert_type', 
        'severity', 
        'current_stock', 
        'threshold', 
        'is_active', 
        'is_dismissed',
        'last_alerted'
    ]
    list_filter = [
        'alert_type', 
        'severity', 
        'is_active', 
        'is_dismissed'
    ]
    search_fields = [
        'product__name', 
        'product__product_code',
        'product__sku_value'
    ]
    readonly_fields = [
        'current_stock', 
        'alert_count', 
        'created_at', 
        'updated_at', 
        'last_alerted'
    ]
    list_editable = ['is_active']
    
    fieldsets = (
        ('Product Information', {
            'fields': ('product', 'alert_type', 'severity')
        }),
        ('Stock Levels', {
            'fields': ('current_stock', 'threshold', 'reorder_level')
        }),
        ('Alert Status', {
            'fields': ('is_active', 'is_dismissed', 'dismissed_by', 'dismissed_at', 'dismissed_reason')
        }),
        ('Tracking', {
            'fields': ('alert_count', 'last_alerted', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('product', 'dismissed_by')
    
    def has_delete_permission(self, request, obj=None):
        # Allow deletion for superusers only
        return request.user.is_superuser






# ====================================
# PRODUCT REVIEW ADMIN
# ====================================

@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ['product_name', 'customer_name', 'rating', 'comment_preview', 'created_at', 'is_verified']
    list_filter = ['rating', 'is_verified', 'is_active', 'created_at']
    search_fields = ['product__name', 'customer_name', 'comment']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Review Information', {
            'fields': ('product', 'customer_name', 'rating', 'comment')
        }),
        ('Status', {
            'fields': ('is_verified', 'is_active')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def product_name(self, obj):
        try:
            return obj.product.display_name if obj.product else "-"
        except:
            return "-"
    product_name.short_description = 'Product'
    
    def comment_preview(self, obj):
        try:
            if obj.comment and len(obj.comment) > 50:
                return obj.comment[:50] + '...'
            return obj.comment or "-"
        except:
            return "-"
    comment_preview.short_description = 'Comment'