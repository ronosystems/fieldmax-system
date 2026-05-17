# inventory/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import (
    Supplier, Category, Product, ProductUnit, StockEntry,
    ProductImage, StockAlert, ProductReview, ReturnRequest
)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['name', 'contact_person', 'phone', 'email', 'product_count', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'contact_person', 'phone', 'email']
    readonly_fields = ['created_at', 'updated_at', 'product_count']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'contact_person', 'phone', 'email')
        }),
        ('Business Details', {
            'fields': ('address', 'tax_id', 'payment_terms')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at', 'product_count'),
            'classes': ('collapse',)
        })
    )


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'category_code', 'item_type', 'identifier_type', 'product_count', 'is_active']
    list_filter = ['item_type', 'identifier_type', 'is_active']
    search_fields = ['name', 'category_code', 'description']
    readonly_fields = ['category_code', 'created_at', 'updated_at', 'product_count']
    
    fieldsets = (
        ('Category Information', {
            'fields': ('name', 'description')
        }),
        ('Type Configuration', {
            'fields': ('item_type', 'identifier_type'),
            'description': 'Define how items in this category are tracked'
        }),
        ('System', {
            'fields': ('category_code', 'is_active')
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at', 'product_count'),
            'classes': ('collapse',)
        })
    )


class ProductUnitInline(admin.TabularInline):
    """Inline for product units (individual items)"""
    model = ProductUnit
    extra = 0
    fields = ['imei_number', 'serial_number', 'status', 'condition', 'unique_identifier_link', 'is_in_warranty']
    readonly_fields = ['unique_identifier_link', 'created_at', 'is_in_warranty']
    show_change_link = True
    can_delete = True
    
    def unique_identifier_link(self, obj):
        if obj.id:
            url = reverse('admin:inventory_productunit_change', args=[obj.id])
            return format_html('<a href="{}">{}</a>', url, obj.unique_identifier)
        return "-"
    unique_identifier_link.short_description = "Identifier"


class StockEntryInline(admin.TabularInline):
    """Inline for stock entries"""
    model = StockEntry
    extra = 0
    fields = ['quantity', 'entry_type', 'unit_price', 'total_amount', 'created_at']
    readonly_fields = ['created_at']
    show_change_link = True
    can_delete = False
    max_num = 10


class ProductImageInline(admin.TabularInline):
    """Inline for product images"""
    model = ProductImage
    extra = 1
    fields = ['image_preview', 'is_primary', 'order', 'caption']
    readonly_fields = ['image_preview']
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="50" height="50" style="object-fit: cover; border-radius: 4px;" />', obj.image.url)
        return "-"
    image_preview.short_description = "Preview"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['sku_code', 'display_name_short', 'brand', 'model', 'category', 'current_stock_display', 'selling_price', 'stock_status_badge']
    list_filter = ['category', 'brand', 'is_active', 'is_discontinued', 'category__item_type']
    search_fields = ['sku_code', 'name', 'brand', 'model', 'description']
    readonly_fields = ['sku_code', 'total_quantity', 'available_quantity', 'reserved_quantity', 'damaged_quantity', 'bulk_quantity', 'created_at', 'updated_at', 'stock_status_badge_display']
    
    inlines = [ProductUnitInline, ProductImageInline, StockEntryInline]
    
    fieldsets = (
        ('SKU Information', {
            'fields': ('sku_code', 'name', 'description')
        }),
        ('Product Details', {
            'fields': ('brand', 'model', 'category', 'specifications')
        }),
        ('Pricing', {
            'fields': ('buying_price', 'selling_price', 'best_price')
        }),
        ('Stock Management', {
            'fields': ('total_quantity', 'available_quantity', 'reserved_quantity', 'damaged_quantity', 'bulk_quantity', 'stock_status_badge_display')
        }),
        ('Supplier & Warranty', {
            'fields': ('supplier', 'reorder_level', 'last_restocked', 'warranty_months')
        }),
        ('Images', {
            'fields': ('image',),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active', 'is_discontinued')
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at', 'created_by', 'last_modified_by'),
            'classes': ('collapse',)
        })
    )
    
    def display_name_short(self, obj):
        return obj.name[:50] + "..." if len(obj.name or "") > 50 else obj.name
    display_name_short.short_description = "Name"
    
    def current_stock_display(self, obj):
        return obj.current_stock
    current_stock_display.short_description = "Current Stock"
    
    def stock_status_badge(self, obj):
        colors = {
            'secondary': '#6c757d',
            'danger': '#dc3545',
            'warning': '#ffc107',
            'success': '#28a745'
        }
        color = colors.get(obj.stock_status_badge, '#6c757d')
        status_text = {
            'secondary': 'Out of Stock',
            'danger': 'Needs Reorder',
            'warning': 'Low Stock',
            'success': 'In Stock'
        }.get(obj.stock_status_badge, 'Unknown')
        
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            'white' if obj.stock_status_badge in ['secondary', 'danger'] else 'black',
            status_text
        )
    stock_status_badge.short_description = "Status"
    
    def stock_status_badge_display(self, obj):
        return self.stock_status_badge(obj)
    stock_status_badge_display.short_description = "Stock Status"
    
    actions = ['mark_as_active', 'mark_as_discontinued']
    
    def mark_as_active(self, request, queryset):
        updated = queryset.update(is_active=True, is_discontinued=False)
        self.message_user(request, f"{updated} product(s) marked as active.")
    mark_as_active.short_description = "Mark selected products as Active"
    
    def mark_as_discontinued(self, request, queryset):
        updated = queryset.update(is_discontinued=True, is_active=False)
        self.message_user(request, f"{updated} product(s) marked as discontinued.")
    mark_as_discontinued.short_description = "Mark selected products as Discontinued"
    
    def save_model(self, request, obj, form, change):
        if not change:  # New object
            obj.created_by = request.user
        obj.last_modified_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ProductUnit)
class ProductUnitAdmin(admin.ModelAdmin):
    list_display = ['product_link', 'unique_identifier', 'status', 'condition', 'is_in_warranty_badge', 'sold_by_link', 'sold_date']
    list_filter = ['status', 'condition', 'product__category', 'product__brand']
    search_fields = ['imei_number', 'serial_number', 'product__sku_code', 'product__name']
    readonly_fields = ['created_at', 'updated_at', 'unique_identifier', 'is_in_warranty', 'warranty_remaining_days']
    
    raw_id_fields = ['product', 'supplier', 'sold_by', 'created_by', 'last_modified_by', 'loss_reported_by', 'recovered_by']
    
    fieldsets = (
        ('Product Information', {
            'fields': ('product', 'unique_identifier')
        }),
        ('Identifiers', {
            'fields': ('imei_number', 'serial_number')
        }),
        ('Status & Condition', {
            'fields': ('status', 'condition', 'notes')
        }),
        ('Pricing Overrides', {
            'fields': ('unit_buying_price', 'unit_selling_price'),
            'classes': ('collapse',)
        }),
        ('Sales Information', {
            'fields': ('sold_at_price', 'sold_date', 'sold_by')
        }),
        ('Purchase Information', {
            'fields': ('supplier', 'purchase_price', 'purchase_date')
        }),
        ('Warranty', {
            'fields': ('warranty_start', 'warranty_end', 'is_in_warranty', 'warranty_remaining_days')
        }),
        ('Theft/Loss Tracking', {
            'fields': ('loss_type', 'loss_reported_date', 'loss_reported_by', 'loss_notes', 'police_report_number'),
            'classes': ('collapse',)
        }),
        ('Insurance', {
            'fields': ('insurance_claim_filed', 'insurance_claim_number', 'insurance_claim_amount', 'insurance_payout_amount', 'insurance_payout_date'),
            'classes': ('collapse',)
        }),
        ('Recovery', {
            'fields': ('recovered_date', 'recovered_by', 'recovery_notes'),
            'classes': ('collapse',)
        }),
        ('Location', {
            'fields': ('warehouse_location', 'shelf_location'),
            'classes': ('collapse',)
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at', 'created_by', 'last_modified_by'),
            'classes': ('collapse',)
        })
    )
    
    def product_link(self, obj):
        url = reverse('admin:inventory_product_change', args=[obj.product.id])
        return format_html('<a href="{}">{}</a>', url, obj.product.sku_code)
    product_link.short_description = "Product SKU"
    
    def sold_by_link(self, obj):
        if obj.sold_by:
            return obj.sold_by.username
        return "-"
    sold_by_link.short_description = "Sold By"
    
    def is_in_warranty_badge(self, obj):
        if obj.is_in_warranty:
            return format_html('<span style="color: green;">✓ Yes</span>')
        return format_html('<span style="color: red;">✗ No</span>')
    is_in_warranty_badge.short_description = "In Warranty"
    
    actions = ['mark_as_available', 'mark_as_sold', 'mark_as_damaged', 'mark_as_stolen']
    
    def mark_as_available(self, request, queryset):
        for unit in queryset:
            unit.mark_as_available()
        self.message_user(request, f"{queryset.count()} unit(s) marked as available.")
    mark_as_available.short_description = "Mark selected units as Available"
    
    def mark_as_sold(self, request, queryset):
        for unit in queryset:
            unit.mark_as_sold(customer=None, sold_by=request.user)
        self.message_user(request, f"{queryset.count()} unit(s) marked as sold.")
    mark_as_sold.short_description = "Mark selected units as Sold"
    
    def mark_as_damaged(self, request, queryset):
        for unit in queryset:
            unit.mark_as_damaged(reported_by=request.user)
        self.message_user(request, f"{queryset.count()} unit(s) marked as damaged.")
    mark_as_damaged.short_description = "Mark selected units as Damaged"
    
    def mark_as_stolen(self, request, queryset):
        for unit in queryset:
            unit.mark_as_stolen(reported_by=request.user)
        self.message_user(request, f"{queryset.count()} unit(s) marked as stolen.")
    mark_as_stolen.short_description = "Mark selected units as Stolen"
    
    def save_model(self, request, obj, form, change):
        if not change:  # New object
            obj.created_by = request.user
        obj.last_modified_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(StockEntry)
class StockEntryAdmin(admin.ModelAdmin):
    list_display = ['id', 'product_info', 'entry_type', 'quantity_display', 'unit_price', 'total_amount', 'created_by', 'created_at']
    list_filter = ['entry_type', 'created_at']
    search_fields = ['reference_id', 'notes', 'product_sku__sku_code', 'product_unit__imei_number', 'product_unit__serial_number']
    readonly_fields = ['created_at', 'total_amount']
    
    raw_id_fields = ['product_sku', 'product_unit', 'created_by']
    
    fieldsets = (
        ('Transaction Details', {
            'fields': ('entry_type', 'quantity', 'unit_price', 'total_amount')
        }),
        ('Product', {
            'fields': ('product_sku', 'product_unit')
        }),
        ('Reference', {
            'fields': ('reference_id', 'notes')
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at'),
            'classes': ('collapse',)
        })
    )
    
    def product_info(self, obj):
        if obj.product_sku:
            url = reverse('admin:inventory_product_change', args=[obj.product_sku.id])
            return format_html('<a href="{}">SKU: {}</a>', url, obj.product_sku.sku_code)
        elif obj.product_unit:
            url = reverse('admin:inventory_productunit_change', args=[obj.product_unit.id])
            return format_html('<a href="{}">Unit: {}</a>', url, obj.product_unit.unique_identifier)
        return "-"
    product_info.short_description = "Product"
    
    def quantity_display(self, obj):
        if obj.quantity > 0:
            return format_html('<span style="color: green;">+{}</span>', obj.quantity)
        return format_html('<span style="color: red;">{}</span>', obj.quantity)
    quantity_display.short_description = "Quantity"
    
    def save_model(self, request, obj, form, change):
        if not change:  # New object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ['product', 'image_preview', 'is_primary', 'order', 'created_at']
    list_filter = ['is_primary']
    search_fields = ['product__sku_code', 'product__name', 'caption']
    readonly_fields = ['image_preview', 'created_at']
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="100" height="100" style="object-fit: cover; border-radius: 4px;" />', obj.image.url)
        return "-"
    image_preview.short_description = "Preview"
    
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)


@admin.register(StockAlert)
class StockAlertAdmin(admin.ModelAdmin):
    list_display = ['product', 'alert_type', 'severity_badge', 'current_stock', 'threshold', 'is_active', 'alert_count', 'last_alerted']
    list_filter = ['alert_type', 'severity', 'is_active', 'is_dismissed']
    search_fields = ['product__sku_code', 'product__name']
    readonly_fields = ['alert_count', 'last_alerted', 'created_at', 'updated_at']
    
    def severity_badge(self, obj):
        colors = {
            'info': '#17a2b8',
            'warning': '#ffc107',
            'danger': '#fd7e14',
            'critical': '#dc3545'
        }
        color = colors.get(obj.severity, '#6c757d')
        text_color = 'white' if obj.severity in ['danger', 'critical'] else 'black'
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, text_color, obj.get_severity_display()
        )
    severity_badge.short_description = "Severity"
    
    actions = ['dismiss_alerts', 'reactivate_alerts']
    
    def dismiss_alerts(self, request, queryset):
        for alert in queryset:
            alert.dismiss(user=request.user)
        self.message_user(request, f"{queryset.count()} alert(s) dismissed.")
    dismiss_alerts.short_description = "Dismiss selected alerts"
    
    def reactivate_alerts(self, request, queryset):
        for alert in queryset:
            alert.reactivate()
        self.message_user(request, f"{queryset.count()} alert(s) reactivated.")
    reactivate_alerts.short_description = "Reactivate selected alerts"


@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ['product', 'customer_name', 'rating_stars', 'is_verified', 'is_active', 'helpful_count', 'created_at']
    list_filter = ['rating', 'is_verified', 'is_active']
    search_fields = ['product__name', 'customer_name', 'customer_email', 'comment']
    readonly_fields = ['helpful_count', 'not_helpful_count', 'created_at']
    
    def rating_stars(self, obj):
        stars = '★' * obj.rating + '☆' * (5 - obj.rating)
        return format_html('<span style="color: #ffc107; font-size: 14px;">{}</span>', stars)
    rating_stars.short_description = "Rating"
    
    actions = ['approve_reviews', 'reject_reviews']
    
    def approve_reviews(self, request, queryset):
        updated = queryset.update(is_verified=True, is_active=True)
        self.message_user(request, f"{updated} review(s) approved.")
    approve_reviews.short_description = "Approve selected reviews"
    
    def reject_reviews(self, request, queryset):
        updated = queryset.update(is_verified=False, is_active=False)
        self.message_user(request, f"{updated} review(s) rejected.")
    reject_reviews.short_description = "Reject selected reviews"



@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):
    list_display = ['return_id', 'product_info', 'quantity', 'reason', 'status_badge', 'verification_status_badge', 'requested_by', 'requested_at']
    list_filter = ['status',  'reason'] 
    search_fields = ['return_id', 'product__sku_code', 'product__name', 'sale_id', 'etr_number']
    readonly_fields = ['return_id', 'requested_at', 'verified_at', 'approved_at', 'processed_at']
    
    raw_id_fields = ['product', 'product_unit', 'related_sale', 'requested_by', 'verified_by', 'approved_by', 'processed_by']
    
    fieldsets = (
        ('Return Information', {
            'fields': ('return_id', 'status', 'reason', 'reason_text')
        }),
        ('Product', {
            'fields': ('product', 'product_unit', 'quantity', 'reported_condition')
        }),
        ('Reference', {
            'fields': ('sale_id', 'etr_number', 'related_sale')
        }),
        ('Financial', {
            'fields': ('refund_amount',)
        }),
        ('Verification', {
            'fields': ('verified_by', 'verified_at', 'verification_notes')
        }),
        ('Approval', {
            'fields': ('approved_by', 'approved_at', 'notes')
        }),
        ('Processing', {
            'fields': ('processed_by', 'processed_at')
        }),
        ('Audit', {
            'fields': ('requested_by', 'requested_at'),
            'classes': ('collapse',)
        })
    )
    
    def product_info(self, obj):
        return obj.product.sku_code
    product_info.short_description = "Product"
    
    def status_badge(self, obj):
        colors = {
            'pending': '#6c757d',
            'submitted': '#17a2b8',
            'verified': '#007bff',
            'approved': '#28a745',
            'rejected': '#dc3545',
            'processed': '#20c997',
            'damaged_loss': '#fd7e14'
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = "Status"
    
    def verification_status_badge(self, obj):
        colors = {
            'pending': '#6c757d',
            'passed': '#28a745',
            'failed': '#dc3545',
            'partial': '#ffc107'
        }
        color = colors.get(obj.verification_status, '#6c757d')
        text_color = 'white' if obj.verification_status in ['passed', 'failed'] else 'black'
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{}</span>',
            color, text_color, obj.get_verification_status_display()
        )
    verification_status_badge.short_description = "Verification"
    
    actions = ['verify_returns', 'approve_returns', 'reject_returns', 'process_returns']
    
    def verify_returns(self, request, queryset):
        count = 0
        for ret in queryset:
            if ret.status == 'submitted':
                ret.verification_status = 'passed'
                ret.status = 'verified'
                ret.verified_by = request.user
                ret.verified_at = timezone.now()
                ret.save()
                count += 1
        self.message_user(request, f"{count} return(s) verified.")
    verify_returns.short_description = "Verify selected returns"
    
    def approve_returns(self, request, queryset):
        count = 0
        for ret in queryset:
            if ret.verification_status == 'passed' and ret.status == 'verified':
                ret.approve(request.user)
                count += 1
        self.message_user(request, f"{count} return(s) approved.")
    approve_returns.short_description = "Approve selected returns"
    
    def reject_returns(self, request, queryset):
        count = 0
        for ret in queryset:
            if ret.status not in ['processed', 'rejected']:
                ret.reject(request.user, "Rejected by admin")
                count += 1
        self.message_user(request, f"{count} return(s) rejected.")
    reject_returns.short_description = "Reject selected returns"
    
    def process_returns(self, request, queryset):
        count = 0
        for ret in queryset:
            if ret.status == 'approved':
                ret.process_restock(request.user)
                count += 1
        self.message_user(request, f"{count} return(s) processed.")
    process_returns.short_description = "Process selected returns (restock)"