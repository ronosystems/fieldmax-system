from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Sum, Q, F 
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from .models import Product, Category, Supplier, StockEntry, StockAlert, ProductReview, ReturnRequest
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test  
from django.http import JsonResponse
from django.db import transaction
from utils.notifications import AdminNotifier 
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django.views.decorators.http import require_http_methods
from django.core.mail import send_mail
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
import traceback
from sales.models import Sale, SaleItem 
import json
import logging
from sales.models import Sale





logger = logging.getLogger(__name__)
User = get_user_model()



@login_required
def dashboard(request):
    """Dashboard view with statistics and charts"""
    
    # Basic stats
    total_products = Product.objects.count()
    available_products = Product.objects.filter(status='available').count()
    low_stock_count = Product.objects.filter(
        category__item_type='bulk',
        quantity__lte=F('reorder_level')  # Fixed: using F instead of models.F
    ).count()
    out_of_stock = Product.objects.filter(
        Q(category__item_type='bulk', quantity=0) |
        Q(category__item_type='single', status='sold')
    ).count()
    
    # Recent products
    recent_products = Product.objects.select_related('category').order_by('-created_at')[:5]
    
    # Recent stock movements
    recent_movements = StockEntry.objects.select_related('product', 'created_by').order_by('-created_at')[:5]
    
    # Low stock alerts
    low_stock_alerts = StockAlert.objects.filter(
        is_active=True,
        product__quantity__lte=F('alert_level')  # Fixed: using F instead of models.F
    ).select_related('product')[:10]
    
    # Chart data (last 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    entries = StockEntry.objects.filter(created_at__gte=thirty_days_ago)
    
    chart_labels = []
    stock_in_data = []
    stock_out_data = []
    
    for i in range(30):
        date = thirty_days_ago + timedelta(days=i)
        day_entries = entries.filter(created_at__date=date.date())
        
        chart_labels.append(date.strftime('%d %b'))
        stock_in_data.append(day_entries.filter(quantity__gt=0).aggregate(s=Sum('quantity'))['s'] or 0)
        stock_out_data.append(abs(day_entries.filter(quantity__lt=0).aggregate(s=Sum('quantity'))['s'] or 0))
    
    # Status counts for chart
    status_counts = {
        'available': Product.objects.filter(status='available').count(),
        'sold': Product.objects.filter(status='sold').count(),
        'lowstock': Product.objects.filter(status='lowstock').count(),
        'outofstock': Product.objects.filter(status='outofstock').count(),
    }
    
    context = {
        'total_products': total_products,
        'available_products': available_products,
        'low_stock_count': low_stock_count,
        'out_of_stock': out_of_stock,
        'recent_products': recent_products,
        'recent_movements': recent_movements,
        'low_stock_alerts': low_stock_alerts,
        'chart_labels': chart_labels,
        'stock_in_data': stock_in_data,
        'stock_out_data': stock_out_data,
        'status_counts': status_counts,
    }
    
    return render(request, 'inventory/dashboard.html', context)

@login_required
def product_list(request):
    """List all products with filtering"""
    products = Product.objects.select_related('category').all().order_by('-created_at')
    
    # Apply filters
    category_id = request.GET.get('category')
    if category_id:
        products = products.filter(category_id=category_id)
    
    status = request.GET.get('status')
    if status:
        products = products.filter(status=status)
    
    brand = request.GET.get('brand')
    if brand:
        products = products.filter(brand__icontains=brand)
    
    search = request.GET.get('search')
    if search:
        products = products.filter(
            Q(product_code__icontains=search) |
            Q(name__icontains=search) |
            Q(brand__icontains=search) |
            Q(model__icontains=search) |
            Q(sku_value__icontains=search) |
            Q(barcode__icontains=search)
        )
    
    # Pagination
    paginator = Paginator(products, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    categories = Category.objects.filter(is_active=True)
    
    context = {
        'products': page_obj,
        'categories': categories,
    }
    
    return render(request, 'inventory/products/list.html', context)

@login_required
def product_detail(request, pk):  # Fixed: added 'request' parameter
    """View single product details"""
    product = get_object_or_404(
        Product.objects.select_related('category', 'supplier', 'owner'), 
        pk=pk
    )
    stock_entries = StockEntry.objects.filter(product=product)\
        .select_related('created_by')\
        .order_by('-created_at')
    
    context = {
        'product': product,
        'stock_entries': stock_entries,
    }
    
    return render(request, 'inventory/products/detail.html', context)




@login_required
def product_add(request):
    """Add new product"""
    if request.method == 'POST':
        # Handle form submission
        try:
            # Get data from form
            name = request.POST.get('name')
            category_id = request.POST.get('category')
            brand = request.POST.get('brand', '')
            model = request.POST.get('model', '')
            description = request.POST.get('description', '')
            
            # Pricing - Convert to Decimal
            try:
                buying_price = Decimal(request.POST.get('buying_price', '0'))
                selling_price = Decimal(request.POST.get('selling_price', '0'))
                best_price = request.POST.get('best_price')
                if best_price:
                    best_price = Decimal(best_price)
                else:
                    best_price = None
            except (ValueError, TypeError, Decimal.InvalidOperation) as e:
                messages.error(request, f'Invalid price format: {str(e)}')
                return redirect('inventory:product_add')
            
            # Inventory - Convert to int
            try:
                quantity = int(request.POST.get('quantity', 1))
                reorder_level = int(request.POST.get('reorder_level', 5))
                warranty_months = int(request.POST.get('warranty_months', 12))
            except (ValueError, TypeError) as e:
                messages.error(request, f'Invalid number format: {str(e)}')
                return redirect('inventory:product_add')
            
            sku_value = request.POST.get('sku_value', '')
            barcode = request.POST.get('barcode', '')
            
            # Additional
            condition = request.POST.get('condition', 'new')
            supplier_id = request.POST.get('supplier')
            specifications = request.POST.get('specifications', '{}')
            
            # Get category
            category = Category.objects.get(id=category_id)
            
            # Validate required fields
            if not name:
                messages.error(request, 'Product name is required.')
                return redirect('inventory:product_add')
            
            if buying_price <= 0 or selling_price <= 0:
                messages.error(request, 'Buying and selling prices must be greater than zero.')
                return redirect('inventory:product_add')
            
            # Create product
            product = Product.objects.create(
                name=name,
                category=category,
                brand=brand,
                model=model,
                description=description,
                buying_price=buying_price,
                selling_price=selling_price,
                best_price=best_price,
                sku_value=sku_value if sku_value else None,
                barcode=barcode if barcode else None,
                quantity=quantity,
                reorder_level=reorder_level,
                condition=condition,
                warranty_months=warranty_months,
                specifications=specifications,
                owner=request.user
            )
            
            # Handle supplier if provided
            if supplier_id:
                supplier = Supplier.objects.get(id=supplier_id)
                product.supplier = supplier
                product.save()
            
            # ============================================
            # SEND ADMIN NOTIFICATION
            # ============================================
            try:
                from utils.notifications import AdminNotifier
                AdminNotifier.notify_product_added(product, request.user)
                logger.info(f"Admin notification sent for new product: {product.product_code}")
            except ImportError:
                logger.warning("AdminNotifier not available - skipping notification")
            except Exception as e:
                logger.error(f"Failed to send admin notification: {str(e)}")
                # Don't fail the product creation if notification fails
            
            messages.success(request, f'Product "{name}" created successfully.')
            return redirect('inventory:product_detail', pk=product.id)
            
        except Category.DoesNotExist:
            messages.error(request, 'Selected category does not exist.')
            return redirect('inventory:product_add')
        except Exception as e:
            logger.error(f"Error creating product: {str(e)}")
            messages.error(request, f'Error creating product: {str(e)}')
            return redirect('inventory:product_add')
    
    # GET request - show form
    categories = Category.objects.filter(is_active=True)
    suppliers = Supplier.objects.filter(is_active=True)
    context = {
        'categories': categories,
        'suppliers': suppliers,
    }
    return render(request, 'inventory/products/add.html', context)






@login_required
def product_bulk_add(request):
    """Add multiple single items with same details but different SKUs"""
    if request.method == 'POST':
        try:
            # Get common data from form
            name = request.POST.get('name')
            category_id = request.POST.get('category')
            brand = request.POST.get('brand', '')
            model = request.POST.get('model', '')
            description = request.POST.get('description', '')
            
            # Pricing - Convert to Decimal
            buying_price = Decimal(request.POST.get('buying_price', '0'))
            selling_price = Decimal(request.POST.get('selling_price', '0'))
            best_price = request.POST.get('best_price')
            if best_price:
                best_price = Decimal(best_price)
            else:
                best_price = None
            
            # Inventory settings
            warranty_months = int(request.POST.get('warranty_months', 12))
            condition = request.POST.get('condition', 'new')
            supplier_id = request.POST.get('supplier')
            specifications = request.POST.get('specifications', '{}')
            
            # Get SKUs from textarea (one per line)
            skus_text = request.POST.get('skus', '')
            sku_list = [sku.strip() for sku in skus_text.split('\n') if sku.strip()]
            
            # Validate required fields
            if not name:
                messages.error(request, 'Product name is required.')
                return redirect('inventory:product_bulk_add')
            
            if not category_id:
                messages.error(request, 'Category is required.')
                return redirect('inventory:product_bulk_add')
            
            if buying_price <= 0 or selling_price <= 0:
                messages.error(request, 'Buying and selling prices must be greater than zero.')
                return redirect('inventory:product_bulk_add')
            
            if not sku_list:
                messages.error(request, 'Please enter at least one SKU.')
                return redirect('inventory:product_bulk_add')
            
            # Get category and supplier
            category = Category.objects.get(id=category_id)
            
            # Check if category is single item
            if not category.is_single_item:
                messages.error(request, 'Bulk add is only for single item categories.')
                return redirect('inventory:product_bulk_add')
            
            supplier = None
            if supplier_id:
                supplier = Supplier.objects.get(id=supplier_id)
            
            # Create products for each SKU
            created_count = 0
            skipped_count = 0
            duplicate_skus = []
            created_products = []  # ✅ FIX: Initialize the list to store created products
            
            for sku in sku_list:
                # Check if SKU already exists
                if Product.objects.filter(sku_value=sku).exists():
                    duplicate_skus.append(sku)
                    skipped_count += 1
                    continue
                
                # Create product
                product = Product.objects.create(
                    name=name,
                    category=category,
                    brand=brand,
                    model=model,
                    description=description,
                    buying_price=buying_price,
                    selling_price=selling_price,
                    best_price=best_price,
                    sku_value=sku,
                    quantity=1,  # Single items always have quantity 1
                    condition=condition,
                    warranty_months=warranty_months,
                    specifications=specifications,
                    supplier=supplier,
                    owner=request.user,
                    status='available'
                )
                created_count += 1
                created_products.append(product)  # ✅ FIX: Add product to the list
            
            # ============================================
            # ADD ADMIN NOTIFICATION HERE
            # ============================================
            if created_count > 0:
                try:
                    from utils.notifications import AdminNotifier
                    # Notify for each product or just one summary notification
                    # Limit to first 5 to avoid email spam for large bulk adds
                    for product in created_products[:5]:
                        AdminNotifier.notify_product_added(product, request.user)
                    if created_count > 5:
                        logger.info(f"Bulk added {created_count} products - admin notified for first 5")
                except ImportError:
                    logger.warning("AdminNotifier not available - skipping notification")
                except Exception as e:
                    logger.error(f"Failed to send bulk add notification: {str(e)}")
            
            # Show success message
            if created_count > 0:
                messages.success(
                    request, 
                    f'✅ Successfully created {created_count} products with SKUs.'
                )
            
            if duplicate_skus:
                messages.warning(
                    request,
                    f'⚠️ {skipped_count} SKUs were skipped because they already exist: {", ".join(duplicate_skus[:5])}' + 
                    (f' and {len(duplicate_skus)-5} more' if len(duplicate_skus) > 5 else '')
                )
            
            return redirect('inventory:product_list')
            
        except Category.DoesNotExist:
            messages.error(request, 'Selected category does not exist.')
            return redirect('inventory:product_bulk_add')
        except Exception as e:
            messages.error(request, f'Error creating products: {str(e)}')
            return redirect('inventory:product_bulk_add')
    
    # GET request - show form
    categories = Category.objects.filter(is_active=True, item_type='single')
    suppliers = Supplier.objects.filter(is_active=True)
    
    context = {
        'categories': categories,
        'suppliers': suppliers,
    }
    return render(request, 'inventory/products/bulk_add.html', context)









@login_required
def product_edit(request, pk):
    """Edit existing product"""
    product = get_object_or_404(Product, pk=pk)
    
    if request.method == 'POST':
        try:
            # Update product with form data
            product.name = request.POST.get('name')
            category_id = request.POST.get('category')
            product.category = Category.objects.get(id=category_id)
            product.brand = request.POST.get('brand', '')
            product.model = request.POST.get('model', '')
            product.description = request.POST.get('description', '')
            
            # Pricing - Convert to Decimal
            try:
                product.buying_price = Decimal(request.POST.get('buying_price', '0'))
                product.selling_price = Decimal(request.POST.get('selling_price', '0'))
                best_price = request.POST.get('best_price')
                product.best_price = Decimal(best_price) if best_price else None
            except (ValueError, TypeError, Decimal.InvalidOperation) as e:
                messages.error(request, f'Invalid price format: {str(e)}')
                return redirect('inventory:product_edit', pk=product.pk)
            
            # Inventory - Convert to int
            try:
                product.quantity = int(request.POST.get('quantity', 1))
                product.reorder_level = int(request.POST.get('reorder_level', 5))
                product.warranty_months = int(request.POST.get('warranty_months', 12))
            except (ValueError, TypeError) as e:
                messages.error(request, f'Invalid number format: {str(e)}')
                return redirect('inventory:product_edit', pk=product.pk)
            
            product.sku_value = request.POST.get('sku_value', '') or None
            product.barcode = request.POST.get('barcode', '') or None
            
            # Additional
            product.condition = request.POST.get('condition', 'new')
            
            supplier_id = request.POST.get('supplier')
            if supplier_id:
                product.supplier = Supplier.objects.get(id=supplier_id)
            else:
                product.supplier = None
                
            product.specifications = request.POST.get('specifications', '{}')
            
            # Validate required fields
            if not product.name:
                messages.error(request, 'Product name is required.')
                return redirect('inventory:product_edit', pk=product.pk)
            
            if product.buying_price <= 0 or product.selling_price <= 0:
                messages.error(request, 'Buying and selling prices must be greater than zero.')
                return redirect('inventory:product_edit', pk=product.pk)
            
            product.save()
            messages.success(request, f'Product "{product.name}" updated successfully.')
            return redirect('inventory:product_detail', pk=product.pk)
            
        except Category.DoesNotExist:
            messages.error(request, 'Selected category does not exist.')
            return redirect('inventory:product_edit', pk=product.pk)
        except Exception as e:
            messages.error(request, f'Error updating product: {str(e)}')
            return redirect('inventory:product_edit', pk=product.pk)
    
    # GET request - show form with product data
    categories = Category.objects.filter(is_active=True)
    suppliers = Supplier.objects.filter(is_active=True)
    context = {
        'product': product,
        'categories': categories,
        'suppliers': suppliers,
    }
    return render(request, 'inventory/products/edit.html', context)




@login_required
def product_delete(request, pk):
    """Delete product"""
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        product.delete()
        messages.success(request, 'Product deleted successfully.')
        return redirect('inventory:product_list')
    return render(request, 'inventory/products/delete.html', {'product': product})







# ===========================================
# PRODUCT RESTOCT VIEW
#============================================

class ProductRestockView(LoginRequiredMixin, TemplateView):
    """View for restocking products - search first, then restock"""
    template_name = "inventory/products/restock.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .models import Category
        # Only show bulk item categories
        context['bulk_categories'] = Category.objects.filter(
            is_active=True, 
            item_type='bulk'
        )
        return context





# ===========================================
# SEARCH PRODUCT FOR RESTOCK
#============================================

@login_required
@require_http_methods(["GET"])
def search_product_for_restock(request):
    """Search for a product by name, code, or SKU"""
    search_term = request.GET.get('search', '').strip()
    category_id = request.GET.get('category', '') 
    
    if not search_term:
        return JsonResponse({
            'success': False,
            'message': 'Please enter a product name, code, or SKU'
        }, status=400)
    
    try:
        # Search in multiple fields
        products = Product.objects.filter(
            Q(name__icontains=search_term) |
            Q(product_code__icontains=search_term) |
            Q(sku_value__iexact=search_term),
            is_active=True
        ).select_related('category')
        
        # Apply category filter if provided
        if category_id:
            products = products.filter(category_id=category_id)

        if not products.exists():
            return JsonResponse({
                'success': False,
                'message': f'No product found matching "{search_term}"'
            }, status=404)
        
        # If multiple products found, return list
        if products.count() > 1:
            product_list = [{
                'id': p.id,
                'name': p.name,
                'product_code': p.product_code,
                'sku_value': p.sku_value or 'N/A',
                'category': p.category.name,
                'current_quantity': p.quantity,
                'buying_price': float(p.buying_price) if p.buying_price else 0,
                'selling_price': float(p.selling_price) if p.selling_price else 0,
                'is_single_item': p.category.is_single_item
            } for p in products[:10]]  # Limit to 10 results
            
            return JsonResponse({
                'success': True,
                'multiple': True,
                'products': product_list,
                'count': products.count()
            })
        
        # Single product found
        product = products.first()
        
        # Check if it's a single item
        if product.category.is_single_item:
            return JsonResponse({
                'success': False,
                'message': f'"{product.name}" is a single item and cannot be restocked. Each single item must be added individually.',
                'is_single_item': True
            }, status=400)
        
        return JsonResponse({
            'success': True,
            'multiple': False,
            'product': {
                'id': product.id,
                'name': product.name,
                'product_code': product.product_code,
                'sku_value': product.sku_value or 'N/A',
                'category': product.category.name,
                'current_quantity': product.quantity,
                'buying_price': float(product.buying_price) if product.buying_price else 0,
                'selling_price': float(product.selling_price) if product.selling_price else 0,
                'is_single_item': product.category.is_single_item
            }
        })
    
    except Exception as e:
        logger.error(f"Search error: {str(e)}\n{traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'message': f'Search error: {str(e)}'
        }, status=500)




# ===========================================
# PROCESS RESTOCK VIEW
#============================================

@login_required
@require_http_methods(["POST"])
def process_restock(request):
    """Process the restock operation"""
    try:
        product_id = request.POST.get('product_id')
        quantity = request.POST.get('quantity')
        buying_price = request.POST.get('buying_price')
        selling_price = request.POST.get('selling_price')
        notes = request.POST.get('notes', '').strip()
        
        # Validation
        if not all([product_id, quantity, buying_price]):
            return JsonResponse({
                'success': False,
                'message': 'Product, quantity, and buying price are required'
            }, status=400)
        
        product = get_object_or_404(Product, pk=product_id, is_active=True)
        
        # Check if single item
        if product.category.is_single_item:
            return JsonResponse({
                'success': False,
                'message': 'Cannot restock single items'
            }, status=400)
        
        try:
            quantity = int(quantity)
            buying_price = float(buying_price)
            selling_price = float(selling_price) if selling_price else None
        except ValueError:
            return JsonResponse({
                'success': False,
                'message': 'Invalid number format'
            }, status=400)
        
        if quantity <= 0:
            return JsonResponse({
                'success': False,
                'message': 'Quantity must be greater than 0'
            }, status=400)
        
        if buying_price < 0:
            return JsonResponse({
                'success': False,
                'message': 'Buying price cannot be negative'
            }, status=400)
        
        # Create stock entry and update prices
        with transaction.atomic():
            # Create stock entry
            stock_entry = StockEntry.objects.create(
                product=product,
                quantity=quantity,
                entry_type='purchase',
                unit_price=buying_price,
                total_amount=buying_price * quantity,
                created_by=request.user,
                notes=notes or "Restock via search"
            )
            
            # Store old quantity for notification
            old_quantity = product.quantity
            
            # Update product prices if provided
            if buying_price:
                product.buying_price = buying_price
            if selling_price and selling_price > 0:
                product.selling_price = selling_price
            product.save()
            
            logger.info(f"Restocked: {product.product_code} - Qty: {quantity}")
            
            # ============================================
            # SEND ADMIN NOTIFICATION
            # ============================================
            try:
                from utils.notifications import AdminNotifier
                
                # Notify about stock addition
                AdminNotifier.notify_stock_added(
                    product=product,
                    quantity=quantity,
                    entry_type='purchase',
                    added_by=request.user
                )
                
                # Check and notify if product was out of stock and now has stock
                if old_quantity == 0 and product.quantity > 0:
                    logger.info(f"Product {product.product_code} is back in stock")
                    
                logger.info(f"Admin notification sent for restock of {product.product_code}")
                
            except ImportError:
                logger.warning("AdminNotifier not available - skipping notification")
            except Exception as e:
                logger.error(f"Failed to send restock notification: {str(e)}")
                # Don't fail the restock if notification fails
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully added {quantity} units to {product.name}',
            'product': {
                'id': product.id,
                'name': product.name,
                'product_code': product.product_code,
                'new_quantity': product.quantity,
                'buying_price': float(product.buying_price),
                'selling_price': float(product.selling_price)
            },
            'stock_entry_id': stock_entry.id
        })
    
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Product not found'
        }, status=404)
    
    except Exception as e:
        logger.error(f"Restock error: {str(e)}\n{traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'message': f'Error: {str(e)}'
        }, status=500)






@login_required
def category_list(request):
    """List all categories"""
    categories = Category.objects.all()
    return render(request, 'inventory/categories/list.html', {'categories': categories})

@login_required
def category_add(request):
    """Add new category"""
    if request.method == 'POST':
        name = request.POST.get('name')
        item_type = request.POST.get('item_type')
        sku_type = request.POST.get('sku_type')
        category_code = request.POST.get('category_code')
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            category = Category.objects.create(
                name=name,
                item_type=item_type,
                sku_type=sku_type,
                is_active=is_active
            )
            
            # If custom category code provided, update it
            if category_code:
                category.category_code = f"FSL.{category_code.upper()}"
                category.save()
            
            messages.success(request, f'Category "{name}" created successfully.')
            return redirect('inventory:category_list')
            
        except Exception as e:
            messages.error(request, f'Error creating category: {str(e)}')
    
    return render(request, 'inventory/categories/add.html')

@login_required
def category_edit(request, pk):
    """Edit category"""
    category = get_object_or_404(Category, pk=pk)
    
    if request.method == 'POST':
        name = request.POST.get('name')
        category_code = request.POST.get('category_code')
        is_active = request.POST.get('is_active') == 'on'
        
        try:
            category.name = name
            if category_code:
                category.category_code = f"FSL.{category_code.upper()}"
            category.is_active = is_active
            category.save()
            
            messages.success(request, f'Category "{name}" updated successfully.')
            return redirect('inventory:category_list')
            
        except Exception as e:
            messages.error(request, f'Error updating category: {str(e)}')
    
    context = {
        'category': category,
    }
    return render(request, 'inventory/categories/edit.html', context)


@login_required
def category_delete(request, pk):
    """Delete a category"""
    category = get_object_or_404(Category, pk=pk)
    
    if request.method == 'POST':
        category_name = category.name
        category.delete()
        messages.success(request, f'Category "{category_name}" deleted successfully.')
        return redirect('inventory:category_list')
    
    return render(request, 'inventory/categories/delete.html', {'category': category})

@login_required
def supplier_list(request):
    """List all suppliers"""
    suppliers = Supplier.objects.all()
    return render(request, 'inventory/suppliers/list.html', {'suppliers': suppliers})

@login_required
def supplier_add(request):
    """Add new supplier"""
    if request.method == 'POST':
        try:
            # Get data from form
            name = request.POST.get('name')
            contact_person = request.POST.get('contact_person', '')
            phone = request.POST.get('phone')
            email = request.POST.get('email', '')
            address = request.POST.get('address', '')
            tax_id = request.POST.get('tax_id', '')
            payment_terms = request.POST.get('payment_terms', '')
            is_active = request.POST.get('is_active') == 'on'
            
            # Validate required fields
            if not name:
                messages.error(request, 'Company name is required.')
                return render(request, 'inventory/suppliers/add.html')
            
            if not phone:
                messages.error(request, 'Phone number is required.')
                return render(request, 'inventory/suppliers/add.html')
            
            # Create supplier
            supplier = Supplier.objects.create(
                name=name,
                contact_person=contact_person,
                phone=phone,
                email=email,
                address=address,
                tax_id=tax_id,
                payment_terms=payment_terms,
                is_active=is_active
            )
            
            messages.success(request, f'Supplier "{name}" created successfully.')
            return redirect('inventory:supplier_list')
            
        except Exception as e:
            messages.error(request, f'Error creating supplier: {str(e)}')
            return render(request, 'inventory/suppliers/add.html')
    
    return render(request, 'inventory/suppliers/add.html')









@login_required
def supplier_edit(request, pk):
    """Edit supplier"""
    supplier = get_object_or_404(Supplier, pk=pk)
    
    if request.method == 'POST':
        try:
            # Get data from form
            supplier.name = request.POST.get('name')
            supplier.contact_person = request.POST.get('contact_person', '')
            supplier.phone = request.POST.get('phone')
            supplier.email = request.POST.get('email', '')
            supplier.address = request.POST.get('address', '')
            supplier.tax_id = request.POST.get('tax_id', '')
            supplier.payment_terms = request.POST.get('payment_terms', '')
            supplier.is_active = request.POST.get('is_active') == 'on'
            
            # Validate required fields
            if not supplier.name:
                messages.error(request, 'Company name is required.')
                return render(request, 'inventory/suppliers/edit.html', {'supplier': supplier})
            
            if not supplier.phone:
                messages.error(request, 'Phone number is required.')
                return render(request, 'inventory/suppliers/edit.html', {'supplier': supplier})
            
            # Save supplier
            supplier.save()
            
            messages.success(request, f'Supplier "{supplier.name}" updated successfully.')
            return redirect('inventory:supplier_list')
            
        except Exception as e:
            messages.error(request, f'Error updating supplier: {str(e)}')
            return render(request, 'inventory/suppliers/edit.html', {'supplier': supplier})
    
    context = {
        'supplier': supplier,
    }
    return render(request, 'inventory/suppliers/edit.html', context)







@login_required
def supplier_delete(request, pk):
    """Delete a supplier"""
    supplier = get_object_or_404(Supplier, pk=pk)
    
    if request.method == 'POST':
        supplier_name = supplier.name
        supplier.delete()
        messages.success(request, f'Supplier "{supplier_name}" deleted successfully.')
        return redirect('inventory:supplier_list')
    
    return render(request, 'inventory/suppliers/delete.html', {'supplier': supplier})






@login_required
def stock_movements(request):
    """List all stock movements"""
    entries = StockEntry.objects.select_related('product', 'created_by').order_by('-created_at')
    
    # Apply filters
    entry_type = request.GET.get('type')
    if entry_type:
        entries = entries.filter(entry_type=entry_type)
    
    # Pagination
    paginator = Paginator(entries, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'entries': page_obj,
        'entry_types': StockEntry.ENTRY_TYPE_CHOICES,
    }
    return render(request, 'inventory/stock/movements.html', context)






@login_required
def stock_entry_add(request, product_id):
    """Add stock entry for a product"""
    product = get_object_or_404(Product, pk=product_id)
    
    if request.method == 'POST':
        try:
            entry_type = request.POST.get('entry_type')
            quantity = int(request.POST.get('quantity'))
            unit_price = request.POST.get('unit_price')
            reference_id = request.POST.get('reference_id', '')
            notes = request.POST.get('notes', '')
            
            # Store original quantity for notification
            old_quantity = product.quantity
            
            # Adjust quantity sign based on entry type
            if entry_type in ['sale']:
                quantity = -abs(quantity)  # Negative for stock out
            else:
                quantity = abs(quantity)   # Positive for stock in
            
            total_amount = abs(quantity) * float(unit_price)
            
            # Create stock entry
            entry = StockEntry.objects.create(
                product=product,
                quantity=quantity,
                entry_type=entry_type,
                unit_price=unit_price,
                total_amount=total_amount,
                reference_id=reference_id,
                notes=notes,
                created_by=request.user
            )
            
            # ============================================
            # ADD ADMIN NOTIFICATIONS HERE
            # ============================================
            try:
                from utils.notifications import AdminNotifier
                
                # Notify about stock addition (only for positive stock in)
                if quantity > 0:
                    AdminNotifier.notify_stock_added(
                        product=product,
                        quantity=quantity,
                        entry_type=entry_type,
                        added_by=request.user
                    )
                    
                    # Check and notify for low stock after addition
                    if product.quantity <= product.reorder_level:
                        AdminNotifier.notify_low_stock(product)
                    
                    # Check and notify if product was out of stock and now has stock
                    if old_quantity == 0 and product.quantity > 0:
                        logger.info(f"Product {product.product_code} is back in stock")
                        
                # Notify about stock removal (for sales/removals)
                elif quantity < 0:
                    # Check if product is now out of stock
                    if product.quantity == 0:
                        AdminNotifier.notify_out_of_stock(product)
                    
                    # Check for low stock after removal
                    elif product.quantity <= product.reorder_level:
                        AdminNotifier.notify_low_stock(product)
                
                logger.info(f"Admin notifications processed for stock entry on {product.product_code}")
                
            except ImportError:
                logger.warning("AdminNotifier not available - skipping notifications")
            except Exception as e:
                logger.error(f"Failed to send stock notifications: {str(e)}")
            
            messages.success(request, f'Stock entry added successfully for {product.display_name}.')
            return redirect('inventory:product_detail', pk=product.id)
            
        except Exception as e:
            logger.error(f"Error adding stock entry: {str(e)}")
            messages.error(request, f'Error adding stock entry: {str(e)}')
            return render(request, 'inventory/stock/add_entry.html', {'product': product})
    
    # GET request - show form
    return render(request, 'inventory/stock/add_entry.html', {'product': product})





@login_required
def reverse_entry(request, pk):
    """Reverse a stock entry"""
    entry = get_object_or_404(StockEntry, pk=pk)
    
    if request.method == 'POST':
        # Create reversal entry
        StockEntry.objects.create(
            product=entry.product,
            quantity=-entry.quantity,
            entry_type='reversal',
            unit_price=entry.unit_price,
            total_amount=entry.total_amount,
            reference_id=f"REV-{entry.id}",
            notes=f"Reversal of entry #{entry.id}",
            created_by=request.user
        )
        messages.success(request, f'Entry #{entry.id} reversed successfully.')
        return redirect('inventory:stock_movements')
    
    return render(request, 'inventory/stock/reverse.html', {'entry': entry})

@login_required
def stock_alerts(request):
    """List all stock alerts"""
    alerts = StockAlert.objects.select_related('product').filter(is_active=True)
    return render(request, 'inventory/stock/alerts.html', {'alerts': alerts})

@login_required
def restock_product(request, pk):
    """Mark product as restocked"""
    alert = get_object_or_404(StockAlert, pk=pk)
    if request.method == 'POST':
        # Handle restocking
        pass
    return render(request, 'inventory/stock/restock.html', {'alert': alert})





@login_required
def dismiss_alert(request, pk):
    """Dismiss a stock alert"""
    alert = get_object_or_404(StockAlert, pk=pk)
    
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        alert.dismiss(user=request.user, reason=reason)
        messages.success(request, f'Alert for {alert.product.display_name} dismissed.')
        
        # Check if we should redirect to a specific page
        next_url = request.GET.get('next', 'inventory:stock_alerts')
        return redirect(next_url)
    
    return render(request, 'inventory/stock/dismiss_alert.html', {
        'alert': alert,
        'next': request.GET.get('next', '')
    })







@login_required
def product_reviews(request):
    """List all product reviews"""
    reviews = ProductReview.objects.select_related('product').order_by('-created_at')
    return render(request, 'inventory/reviews/list.html', {'reviews': reviews})








from django.contrib.auth import get_user_model
from django.http import JsonResponse

User = get_user_model()

@login_required
def search_users(request):
    """AJAX endpoint to search users by username, email, or full name"""
    query = request.GET.get('q', '').strip()
    users = []
    
    if query and len(query) >= 2:
        users_qs = User.objects.filter(
            Q(username__icontains=query) |
            Q(email__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query)
        ).filter(is_active=True)[:20]
        
        for user in users_qs:
            users.append({
                'id': user.id,
                'username': user.username,
                'full_name': user.get_full_name() or user.username,
                'email': user.email,
            })
    
    return JsonResponse(users, safe=False)




@login_required
def product_transfer(request):
    """Transfer multiple products from current user to another user"""
    if request.method == 'POST':
        try:
            # Get receiver user ID
            receiver_id = request.POST.get('receiver_id')
            if not receiver_id:
                messages.error(request, 'Please select a receiver user.')
                return redirect('inventory:product_list')
            
            # Get SKUs from textarea (one per line)
            skus_text = request.POST.get('skus', '')
            sku_list = [sku.strip() for sku in skus_text.split('\n') if sku.strip()]
            
            if not sku_list:
                messages.error(request, 'Please enter at least one SKU.')
                return redirect('inventory:product_list')
            
            # Get receiver user
            try:
                receiver = User.objects.get(id=receiver_id, is_active=True)
            except User.DoesNotExist:
                messages.error(request, 'Selected user does not exist.')
                return redirect('inventory:product_list')
            
            # Check if receiver is the same as sender
            if receiver.id == request.user.id:
                messages.error(request, 'You cannot transfer products to yourself.')
                return redirect('inventory:product_list')
            
            # Find products by SKU
            products_to_transfer = []
            not_found_skus = []
            not_owned_skus = []
            sold_skus = []
            out_of_stock_skus = []
            
            with transaction.atomic():
                for sku in sku_list:
                    try:
                        # Get product with related data
                        product = Product.objects.select_related('category', 'owner').get(
                            sku_value=sku,
                            is_active=True
                        )
                        
                        # Check if current user owns this product (or is admin)
                        is_admin = request.user.is_superuser or request.user.is_staff
                        if not is_admin and product.owner != request.user:
                            not_owned_skus.append(sku)
                            continue
                        
                        # ========================================
                        # SINGLE ITEM TRANSFER
                        # ========================================
                        if product.category.is_single_item:
                            if product.status == 'sold':
                                sold_skus.append(sku)
                                continue
                            
                            # For single items, quantity must be 1
                            if product.quantity != 1:
                                # This should never happen, but just in case
                                out_of_stock_skus.append(sku)
                                continue
                            
                            products_to_transfer.append({
                                'product': product,
                                'quantity': 1,
                                'is_single': True
                            })
                        
                        # ========================================
                        # BULK ITEM TRANSFER (Only full transfers allowed)
                        # ========================================
                        else:
                            current_qty = product.quantity or 0
                            
                            if current_qty == 0:
                                out_of_stock_skus.append(sku)
                                continue
                            
                            # Bulk items must be transferred fully
                            products_to_transfer.append({
                                'product': product,
                                'quantity': current_qty,
                                'is_single': False
                            })
                        
                    except Product.DoesNotExist:
                        not_found_skus.append(sku)
                
                # Show warnings for problematic SKUs
                if not_found_skus:
                    messages.warning(
                        request,
                        f'❌ SKUs not found: {", ".join(not_found_skus[:5])}' +
                        (f' and {len(not_found_skus)-5} more' if len(not_found_skus) > 5 else '')
                    )
                
                if not_owned_skus:
                    messages.warning(
                        request,
                        f'⛔ SKUs not owned by you: {", ".join(not_owned_skus[:5])}' +
                        (f' and {len(not_owned_skus)-5} more' if len(not_owned_skus) > 5 else '')
                    )
                
                if sold_skus:
                    messages.warning(
                        request,
                        f'💰 Sold items cannot be transferred: {", ".join(sold_skus[:5])}' +
                        (f' and {len(sold_skus)-5} more' if len(sold_skus) > 5 else '')
                    )
                
                if out_of_stock_skus:
                    messages.warning(
                        request,
                        f'📦 Out of stock items: {", ".join(out_of_stock_skus[:5])}' +
                        (f' and {len(out_of_stock_skus)-5} more' if len(out_of_stock_skus) > 5 else '')
                    )
                
                if not products_to_transfer:
                    messages.error(request, 'No valid products found to transfer.')
                    return redirect('inventory:product_list')
                
                # Process transfers
                transferred_count = 0
                transferred_products = []  # Store actual product objects for notification
                transferred_skus = []
                
                for item in products_to_transfer:
                    product = item['product']
                    old_owner = product.owner.username if product.owner else "FIELDMAX"
                    
                    # Transfer to new owner
                    product.owner = receiver
                    product.save()
                    
                    # Log the transfer
                    logger.info(
                        f"[PRODUCT TRANSFER] {product.product_code} | "
                        f"{old_owner} → {receiver.username} | "
                        f"Type: {'Single' if item['is_single'] else 'Bulk'} | "
                        f"By: {request.user.username}"
                    )
                    
                    transferred_count += 1
                    transferred_products.append(product)
                    transferred_skus.append(product.sku_value)
                
                # ============================================
                # ADD ADMIN NOTIFICATION HERE
                # ============================================
                try:
                    from utils.notifications import AdminNotifier
                    AdminNotifier.notify_products_transferred(
                        products=transferred_products,
                        from_user=request.user,
                        to_user=receiver,
                        transferred_by=request.user
                    )
                    logger.info(f"Admin notification sent for transfer of {transferred_count} products")
                except ImportError:
                    logger.warning("AdminNotifier not available - skipping notification")
                except Exception as e:
                    logger.error(f"Failed to send transfer notification: {str(e)}")
                
                messages.success(
                    request,
                    f'✅ Successfully transferred {transferred_count} products to {receiver.get_full_name() or receiver.username}.'
                )
                
                # Show which SKUs were transferred
                if transferred_skus:
                    messages.info(
                        request,
                        f'📋 Transferred SKUs: {", ".join(transferred_skus[:5])}' +
                        (f' and {len(transferred_skus)-5} more' if len(transferred_skus) > 5 else '')
                    )
            
            return redirect('inventory:product_list')
            
        except Exception as e:
            logger.error(f"Error transferring products: {str(e)}")
            messages.error(request, f'Error transferring products: {str(e)}')
            return redirect('inventory:product_list')
    
    # GET request - redirect to product list
    return redirect('inventory:product_list')






@login_required
def return_product(request):
    """Search for product to return"""
    if request.method == 'POST':
        search_term = request.POST.get('search_term', '').strip()
        
        if not search_term:
            messages.error(request, 'Please enter ETR number, product code, or SKU.')
            return redirect('inventory:return_product')
        
        # Search by various identifiers
        product = None
        sale = None
        
        # Try to find by product code or SKU
        try:
            product = Product.objects.filter(
                Q(product_code__iexact=search_term) |
                Q(sku_value__iexact=search_term)
            ).first()
        except:
            pass
        
        # Try to find sale by ETR number or sale ID
        try:
            sale = Sale.objects.filter(
                Q(etr_receipt_number__iexact=search_term) |
                Q(sale_id__iexact=search_term)
            ).first()
        except:
            pass
        
        # If product found, get its latest sale
        sale_info = None
        if product:
            latest_sale_item = SaleItem.objects.filter(
                product=product,
                sale__is_reversed=False
            ).select_related('sale').order_by('-sale__sale_date').first()
            
            if latest_sale_item:
                sale_info = latest_sale_item.sale
        
        context = {
            'search_term': search_term,
            'product': product,
            'sale': sale or sale_info,
        }
        
        return render(request, 'inventory/returns/search_result.html', context)
    
    return render(request, 'inventory/returns/add.html')







@login_required
def return_submit(request):
    """Submit a return request"""
    print("=" * 50)
    print("RETURN SUBMIT VIEW CALLED")
    print(f"Method: {request.method}")
    print("=" * 50)
    
    if request.method == 'POST':
        print("POST data received:")
        for key, value in request.POST.items():
            print(f"  {key}: {value}")
        
        try:
            # Get basic required fields
            product_id = request.POST.get('product_id')
            reason = request.POST.get('reason')
            sale_id = request.POST.get('sale_id', '')
            etr_number = request.POST.get('etr_number', '')
            
            print(f"Product ID: {product_id}")
            print(f"Reason: {reason}")
            print(f"Sale ID: {sale_id}")
            
            if not product_id:
                messages.error(request, 'Product ID is required.')
                return redirect('inventory:return_product')
            
            if not reason:
                messages.error(request, 'Reason is required.')
                return redirect('inventory:return_product')
            
            # Get the product
            from inventory.models import Product
            try:
                product = Product.objects.get(id=product_id)
                print(f"Product found: {product.product_code} - {product.display_name}")
            except Product.DoesNotExist:
                print(f"ERROR: Product with ID {product_id} not found")
                messages.error(request, 'Product not found.')
                return redirect('inventory:return_product')
            
            # Handle file uploads
            product_photo_1 = request.FILES.get('product_photo_1')
            product_photo_2 = request.FILES.get('product_photo_2')
            damage_photo = request.FILES.get('damage_photo')
            
            # Prepare return data with CORRECT field names
            return_data = {
                'product': product,
                'product_code': product.product_code,
                'product_name': product.display_name,
                'sku_value': product.sku_value,
                'quantity': request.POST.get('quantity', 1),
                'reason': reason,
                'reason_text': request.POST.get('reason_text', ''),
                'reported_condition': request.POST.get('reported_condition', 'good'),
                'refund_amount': request.POST.get('refund_amount', product.selling_price),
                'etr_number': etr_number,
                'sale_id': sale_id,  # This matches your model field name
                'requested_by': request.user,
                'status': 'submitted',
                'verification_status': 'pending',
            }
            
            # Create return request
            from inventory.models import ReturnRequest
            return_request = ReturnRequest.objects.create(**return_data)
            
            # Save photos if uploaded
            if product_photo_1:
                return_request.product_photo_1 = product_photo_1
            if product_photo_2:
                return_request.product_photo_2 = product_photo_2
            if damage_photo:
                return_request.damage_photo = damage_photo
            
            return_request.save()
            
            print(f"✅ RETURN CREATED: ID={return_request.id}, Return ID={return_request.return_id}")
            
            messages.success(
                request, 
                f'Return request #{return_request.return_id} submitted successfully!'
            )
            
            return redirect('inventory:return_list')
            
        except Exception as e:
            print(f"❌ ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            messages.error(request, f'Error: {str(e)}')
            return redirect('inventory:return_product')
    
    print("Not a POST request")
    return redirect('inventory:return_product')







@login_required
def return_list(request):
    """List all return requests"""
    from django.core.paginator import Paginator
    
    returns = ReturnRequest.objects.all().select_related(
        'product', 'requested_by', 'verified_by', 'approved_by'
    ).order_by('-requested_at')
    
    # Filter by status
    status = request.GET.get('status')
    if status:
        returns = returns.filter(status=status)
    
    # Filter by date
    date_from = request.GET.get('date_from')
    if date_from:
        returns = returns.filter(requested_at__date__gte=date_from)
    
    date_to = request.GET.get('date_to')
    if date_to:
        returns = returns.filter(requested_at__date__lte=date_to)
    
    # Search
    search = request.GET.get('search')
    if search:
        returns = returns.filter(
            Q(return_id__icontains=search) |
            Q(product_name__icontains=search) |
            Q(product_code__icontains=search) |
            Q(sku_value__icontains=search)
        )
    
    # Pagination
    paginator = Paginator(returns, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Counts for stats
    total_count = ReturnRequest.objects.count()
    pending_verification_count = ReturnRequest.objects.filter(status='submitted').count()
    approved_count = ReturnRequest.objects.filter(status='approved').count()
    rejected_count = ReturnRequest.objects.filter(status='rejected').count()
    
    context = {
        'returns': page_obj,
        'status_choices': ReturnRequest.RETURN_STATUS_CHOICES,
        'total_count': total_count,
        'pending_verification_count': pending_verification_count,
        'approved_count': approved_count,
        'rejected_count': rejected_count,
    }
    return render(request, 'inventory/returns/list.html', context)









@login_required
def return_detail(request, pk):
    """View return request details"""
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    context = {
        'return': return_request,
    }
    return render(request, 'inventory/returns/detail.html', context)









@login_required
def return_approve(request, pk):
    """Approve a return request (manager only)"""
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, 'You do not have permission to approve returns.')
        return redirect('inventory:return_list')
    
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'approve':
            return_request.approve(request.user)
            messages.success(request, f'Return #{return_request.return_id} approved.')
            
        elif action == 'reject':
            reason = request.POST.get('rejection_reason', '')
            return_request.reject(request.user, reason)
            messages.success(request, f'Return #{return_request.return_id} rejected.')
        
        return redirect('inventory:return_detail', pk=return_request.id)
    
    context = {
        'return': return_request,
    }
    return render(request, 'inventory/returns/approve.html', context)








@login_required
def return_process(request, pk):
    """Process an approved return (restock product)"""
    if not request.user.is_staff and not request.user.is_superuser:
        messages.error(request, 'You do not have permission to process returns.')
        return redirect('inventory:return_list')
    
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    if return_request.status != 'approved':
        messages.error(request, 'Only approved returns can be processed.')
        return redirect('inventory:return_detail', pk=return_request.id)
    
    if request.method == 'POST':
        try:
            return_request.process(request.user)
            messages.success(request, f'Return #{return_request.return_id} processed successfully. Product restocked.')
        except Exception as e:
            messages.error(request, f'Error processing return: {str(e)}')
        
        return redirect('inventory:return_detail', pk=return_request.id)
    
    context = {
        'return': return_request,
    }
    return render(request, 'inventory/returns/process.html', context)












@login_required
def return_search_api(request):
    """AJAX endpoint for searching products by ETR, code, or SKU"""
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return JsonResponse({'results': []})
    
    # Search products by code, name, or SKU
    products = Product.objects.filter(
        Q(product_code__icontains=query) |
        Q(name__icontains=query) |
        Q(sku_value__icontains=query)  # Search by SKU value
    )[:10]
    
    # Search sales by sale_id or ETR number
    sales = Sale.objects.filter(
        Q(sale_id__icontains=query) |
        Q(etr_receipt_number__icontains=query)
    )[:10]
    
    results = []
    
    for product in products:
        # Find if this product was sold (get latest sale)
        latest_sale = SaleItem.objects.filter(
            product=product,
            sale__is_reversed=False
        ).select_related('sale').order_by('-sale__sale_date').first()
        
        results.append({
            'type': 'product',
            'id': product.id,
            'code': product.product_code,
            'name': product.display_name,
            'sku': product.sku_value or '',
            'price': float(product.selling_price),
            'sale_id': latest_sale.sale.sale_id if latest_sale else None,
            'sale_date': latest_sale.sale.sale_date.strftime('%Y-%m-%d') if latest_sale else None,
            'customer': latest_sale.sale.buyer_name if latest_sale and latest_sale.sale.buyer_name else 'Unknown',
        })
    
    for sale in sales:
        results.append({
            'type': 'sale',
            'id': sale.id,
            'sale_id': sale.sale_id,
            'etr': sale.etr_receipt_number,
            'date': sale.sale_date.strftime('%Y-%m-%d'),
            'amount': float(sale.total_amount),
            'customer': sale.buyer_name or 'Unknown',
            'items': list(sale.items.values('product_code', 'product_name', 'sku_value')),
        })
    
    return JsonResponse({'results': results})





@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)  # Manager only
def return_verify(request, pk):
    """Manager verification of returned product"""
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    if return_request.status != 'submitted':
        messages.error(request, 'This return is not pending verification.')
        return redirect('inventory:return_detail', pk=return_request.id)
    
    if request.method == 'POST':
        # Collect verification data
        verification_data = {
            'physical_product_seen': request.POST.get('physical_product_seen') == 'on',
            'serial_number_matches': request.POST.get('serial_number_matches') == 'on',
            'condition_matches_report': request.POST.get('condition_matches_report') == 'on',
            'accessories_present': request.POST.get('accessories_present') == 'on',
            'box_present': request.POST.get('box_present') == 'on',
            'receipt_present': request.POST.get('receipt_present') == 'on',
            'actual_sku': request.POST.get('actual_sku', ''),
            'actual_serial': request.POST.get('actual_serial', ''),
            'actual_condition': request.POST.get('actual_condition', ''),
            'notes': request.POST.get('verification_notes', ''),
        }
        
        # Handle photo uploads
        if request.FILES.get('product_photo_1'):
            return_request.product_photo_1 = request.FILES['product_photo_1']
        if request.FILES.get('product_photo_2'):
            return_request.product_photo_2 = request.FILES['product_photo_2']
        if request.FILES.get('product_photo_3'):
            return_request.product_photo_3 = request.FILES['product_photo_3']
        if request.FILES.get('damage_photo'):
            return_request.damage_photo = request.FILES['damage_photo']
        
        # Perform verification
        matches, issues = return_request.verify_product(request.user, verification_data)
        
        if matches:
            messages.success(
                request, 
                f'Product verified successfully. Return #{return_request.return_id} is now awaiting approval.'
            )
        else:
            messages.warning(
                request, 
                f'Product verification failed. Issues: {", ".join(issues)}'
            )
        
        return redirect('inventory:return_detail', pk=return_request.id)
    
    # GET request - show verification form
    context = {
        'return': return_request,
    }
    return render(request, 'inventory/returns/verify.html', context)



@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def return_reject(request, pk):
    """Reject a return request (manager only)"""
    return_request = get_object_or_404(ReturnRequest, pk=pk)
    
    # Check if return can be rejected (only verified or submitted status)
    if return_request.status not in ['submitted', 'verified']:
        messages.error(request, f'This return cannot be rejected. Current status: {return_request.get_status_display()}')
        return redirect('inventory:return_detail', pk=return_request.id)
    
    if request.method == 'POST':
        reason = request.POST.get('rejection_reason', '')
        
        if not reason:
            messages.error(request, 'Please provide a reason for rejection.')
            return render(request, 'inventory/returns/reject.html', {'return': return_request})
        
        # Update the return request
        return_request.status = 'rejected'
        return_request.verification_status = 'failed'
        return_request.approved_by = request.user
        return_request.approved_at = timezone.now()
        return_request.notes = f"Rejected: {reason}"
        return_request.save()
        
        # Log the rejection
        logger.info(
            f"[RETURN REJECTED] Return #{return_request.return_id} | "
            f"Product: {return_request.product_code} | "
            f"Rejected by: {request.user.username} | "
            f"Reason: {reason}"
        )
        
        messages.success(
            request, 
            f'Return #{return_request.return_id} has been rejected.'
        )
        return redirect('inventory:return_detail', pk=return_request.id)
    
    # GET request - show rejection form
    context = {
        'return': return_request,
    }
    return render(request, 'inventory/returns/reject.html', context)