from django.contrib import admin
from django import forms
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.db.models import Count, Sum
from decimal import Decimal

from .models import Supplier, Category, Product, ProductImage, StockEntry, StockAlert, ProductReview


# ====================================
# CUSTOM USER ADMIN - SAFE VERSION
# ====================================

class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'is_staff', 'is_superuser', 'is_active']
    list_filter = ['is_staff', 'is_superuser', 'is_active']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    list_per_page = 25
    list_display_links = ['username']
    
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
    
    list_display = [
        'product_code',
        'display_name',
        'category_name',
        'buying_price_display',
        'selling_price_display',
        'best_price_display',
        'sku_display',
        'barcode_display',
        'stock_display',
        'status_display',
        'condition_display',
    ]
    
    list_display_links = ['product_code', 'display_name']
    
    search_fields = [
        'product_code', 
        'name', 
        'brand', 
        'model', 
        'sku_value', 
        'barcode',
        'serial_number',
        'imei_number',
        'description',
    ]
    search_help_text = "Search by product code, name, brand, model, SKU, serial, IMEI, or barcode"
    
    # ✅ FIXED: Removed 'view_count' and 'sales_count' (they don't exist in your model)
    readonly_fields = [
        'product_code', 
        'barcode',
        'created_at', 
        'updated_at', 
        'profit_calculation',
    ]
    
    inlines = [ProductImageInline]
    save_on_top = True
    list_per_page = 25
    show_full_result_count = True
    
    fieldsets = (
        ('📋 BASIC INFORMATION', {
            'fields': (
                ('product_code', 'barcode'),
                ('name', 'category'),
                ('owner',),
            ),
            'classes': ('wide',),
        }),
        
        ('🔢 UNIQUE IDENTIFIERS', {
            'fields': (
                ('serial_number', 'imei_number'),
                'sku_value',
            ),
            'classes': ('wide',),
            'description': 'For single items: provide either Serial Number OR IMEI Number (for phones)',
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
                ('quantity', 'reserved_quantity'),
                ('reorder_level', 'last_restocked'),
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
                'status',
                'is_active',
            ),
            'classes': ('wide', 'collapse'),
        }),
        
        ('⚠️ LOSS TRACKING', {
            'fields': (
                ('is_stolen_or_lost', 'loss_type'),
                ('loss_reported_date', 'loss_reported_by'),
                'loss_notes',
                ('police_report_number', 'police_station'),
                ('insurance_claim_filed', 'insurance_claim_number', 'insurance_claim_amount'),
                ('insurance_payout_amount', 'insurance_payout_date'),
                ('recovered_date', 'recovered_by'),
                'recovery_notes',
            ),
            'classes': ('wide', 'collapse'),
        }),
        
        ('📅 SYSTEM METADATA', {
            'fields': ('created_at', 'updated_at', 'last_modified_by'),
            'classes': ('wide', 'collapse'),
        }),
    )
    
    actions = ['mark_as_available', 'mark_as_sold', 'mark_as_featured']
    actions_on_top = True
    actions_on_bottom = False
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category', 'supplier', 'owner')
    
    # Display Methods
    def display_name(self, obj):
        try:
            return obj.display_name
        except:
            return "Error"
    display_name.short_description = 'Product'
    display_name.admin_order_field = 'name'
    
    def category_name(self, obj):
        try:
            if not obj.category:
                return "-"
            icon = "📱" if obj.category.is_single_item else "📦"
            return f"{icon} {obj.category.name}"
        except:
            return "-"
    category_name.short_description = 'Category'
    category_name.admin_order_field = 'category__name'
    
    def buying_price_display(self, obj):
        try:
            if obj.buying_price:
                return f"KSH {obj.buying_price:,.0f}"
            return "-"
        except:
            return "-"
    buying_price_display.short_description = 'Cost (KSH)'
    buying_price_display.admin_order_field = 'buying_price'
    
    def selling_price_display(self, obj):
        try:
            if obj.selling_price:
                return f"KSH {obj.selling_price:,.0f}"
            return "-"
        except:
            return "-"
    selling_price_display.short_description = 'Sell (KSH)'
    selling_price_display.admin_order_field = 'selling_price'
    
    def best_price_display(self, obj):
        try:
            if obj.best_price:
                return f"KSH {obj.best_price:,.0f}"
            return "-"
        except:
            return "-"
    best_price_display.short_description = 'Best (KSH)'
    best_price_display.admin_order_field = 'best_price'
    
    def sku_display(self, obj):
        try:
            if obj.sku_value:
                sku = str(obj.sku_value)
                return sku[:15] + "..." if len(sku) > 15 else sku
            return "-"
        except:
            return "-"
    sku_display.short_description = 'Legacy SKU'
    
    def barcode_display(self, obj):
        try:
            if obj.barcode:
                bc = str(obj.barcode)
                return bc[:15] + "..." if len(bc) > 15 else bc
            return "-"
        except:
            return "-"
    barcode_display.short_description = 'Barcode'
    
    def stock_display(self, obj):
        try:
            qty = obj.quantity or 0
            
            if obj.category and obj.category.is_single_item:
                return "✓ In Stock" if qty > 0 else "✗ Out of Stock"
            else:
                if obj.reorder_level and qty <= obj.reorder_level and qty > 0:
                    return f"{qty} ⚠️ (Reorder)"
                elif qty == 0:
                    return "0 ❌ (Out of Stock)"
                return str(qty)
        except:
            return "0"
    stock_display.short_description = 'Stock'
    stock_display.admin_order_field = 'quantity'
    
    def status_display(self, obj):
        try:
            status_map = {
                'available': '✓ Available',
                'sold': '✗ Sold',
                'reserved': '⏳ Reserved',
                'damaged': '⚠️ Damaged',
                'lowstock': '⚠️ Low Stock',
                'outofstock': '❌ Out of Stock',
                'stolen': '⚠️ Stolen/Lost',
                'writeoff': '📝 Written Off',
                'recalled': '🔙 Recalled',
            }
            return status_map.get(obj.status, obj.get_status_display() or 'Unknown')
        except:
            return 'Unknown'
    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'
    
    def condition_display(self, obj):
        try:
            return obj.get_condition_display() or 'Unknown'
        except:
            return 'Unknown'
    condition_display.short_description = 'Condition'
    condition_display.admin_order_field = 'condition'
    
    def profit_calculation(self, obj):
        try:
            if obj.buying_price and obj.selling_price:
                profit = obj.selling_price - obj.buying_price
                margin = (profit / obj.buying_price * 100) if obj.buying_price > 0 else 0
                
                color = "#27ae60" if profit > 0 else "#e74c3c" if profit < 0 else "#95a5a6"
                return format_html(
                    '<span style="color: {}; font-weight: bold;">Profit: KSH {:,.0f} | Margin: {:.1f}%</span>',
                    color, profit, margin
                )
            return "Set buying and selling prices to see profit"
        except:
            return "Error calculating profit"
    profit_calculation.short_description = 'Profit Analysis'
    
    # Actions
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
    readonly_fields = ['total_amount', 'created_at']
    raw_id_fields = ['product', 'created_by']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('product', 'entry_type', 'quantity')
        }),
        ('Financial Information', {
            'fields': (('unit_price', 'total_amount'),)
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
            'purchase': '#27ae60',
            'sale': '#e74c3c',
            'reversal': '#f39c12',
            'adjustment': '#3498db',
            'return': '#9b59b6',
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
    list_filter = ['alert_type', 'severity', 'is_active', 'is_dismissed']
    search_fields = ['product__name', 'product__product_code']
    readonly_fields = ['current_stock', 'alert_count', 'created_at', 'updated_at', 'last_alerted']
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