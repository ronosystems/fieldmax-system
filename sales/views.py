
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.utils import timezone
from decimal import Decimal
import json
import logging

from inventory.models import Product, StockEntry
from .models import Sale, SaleItem, generate_custom_sale_id

logger = logging.getLogger(__name__)






@login_required
def search_products(request):
    """AJAX endpoint to search products from inventory"""
    query = request.GET.get('q', '').strip()
    products = []
    
    try:
        from inventory.models import Product
        
        # Base queryset - only show available products with stock
        queryset = Product.objects.filter(
            status='available',
            quantity__gt=0,
            is_active=True
        )
        
        if query and len(query) >= 2:
            # Search by product_code, name, brand, model, or sku_value
            queryset = queryset.filter(
                Q(product_code__icontains=query) |
                Q(name__icontains=query) |
                Q(brand__icontains=query) |
                Q(model__icontains=query) |
                Q(sku_value__icontains=query) |
                Q(barcode__icontains=query)
            )
        
        # Limit to 30 results for performance
        results = queryset[:30]
        
        for product in results:
            # Build display name
            display_name = product.display_name
            
            # Add SKU info for single items
            sku_info = ""
            if product.category and product.category.is_single_item and product.sku_value:
                sku_info = f" | {product.category.sku_type}: {product.sku_value}"
            
            products.append({
                'code': product.product_code,
                'name': display_name,
                'price': float(product.selling_price),
                'best_price': float(product.best_price) if product.best_price else None,
                'stock': product.quantity,
                'sku': product.sku_value,
                'sku_type': product.category.sku_type if product.category else None,
                'is_single': product.category.is_single_item if product.category else False,
                'display_text': f"{display_name} ({product.product_code}){sku_info}"
            })
            
    except Exception as e:
        logger.error(f"Error searching products: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse(products, safe=False)







@login_required
def sales_dashboard(request):
    """Sales dashboard with statistics and charts"""
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Sum, Count
    from .models import Sale, SaleItem
    
    today = timezone.now().date()
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    # Basic stats
    total_sales = Sale.objects.count()
    today_sales = Sale.objects.filter(
        sale_date__date=today
    ).aggregate(total=Sum('total_amount'))['total'] or 0
    
    today_transactions = Sale.objects.filter(sale_date__date=today).count()
    
    items_sold_today = SaleItem.objects.filter(
        sale__sale_date__date=today
    ).aggregate(total=Sum('quantity'))['total'] or 0
    
    avg_sale_today = today_sales / today_transactions if today_transactions > 0 else 0
    
    # Recent sales
    recent_sales = Sale.objects.order_by('-sale_date')[:5]
    
    # Top selling products - FIXED: removed is_single_item from values()
    top_products = SaleItem.objects.values(
        'product__name', 
        'product__category__item_type'  # Use item_type instead of is_single_item
    ).annotate(
        total_sold=Sum('quantity'),
        total_revenue=Sum('total_price')
    ).order_by('-total_sold')[:5]
    
    # Convert item_type to boolean for template
    for product in top_products:
        product['is_single_item'] = (product['product__category__item_type'] == 'single')
    
    # Chart data (last 30 days)
    chart_labels = []
    sales_data = []
    
    for i in range(30):
        date = thirty_days_ago.date() + timedelta(days=i)
        day_sales = Sale.objects.filter(
            sale_date__date=date
        ).aggregate(total=Sum('total_amount'))['total'] or 0
        
        chart_labels.append(date.strftime('%d %b'))
        sales_data.append(float(day_sales))
    
    # Payment method distribution
    payment_data = [
        Sale.objects.filter(payment_method='Cash').count(),
        Sale.objects.filter(payment_method='M-Pesa').count(),
        Sale.objects.filter(payment_method='Card').count(),
        Sale.objects.filter(payment_method='Points').count(),
    ]
    
    context = {
        'total_sales': total_sales,
        'today_sales': today_sales,
        'today_transactions': today_transactions,
        'items_sold_today': items_sold_today,
        'avg_sale_today': avg_sale_today,
        'recent_sales': recent_sales,
        'top_products': top_products,
        'chart_labels': chart_labels,
        'sales_data': sales_data,
        'payment_data': payment_data,
    }
    
    return render(request, 'sales/dashboard.html', context)






@login_required
def sale_list(request):
    """List all sales with filtering"""
    from django.db.models import Q, Count
    from django.core.paginator import Paginator
    
    # Debug: Check unique payment methods in database
    payment_methods = Sale.objects.values_list('payment_method', flat=True).distinct()
    print("=== PAYMENT METHODS IN DATABASE ===")
    for method in payment_methods:
        print(f"'{method}'")
    
    # Base queryset
    sales = Sale.objects.all().order_by('-sale_date')
    
    # ============================================
    # Apply filters
    # ============================================
    
    # Date filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    if date_from:
        sales = sales.filter(sale_date__date__gte=date_from)
    if date_to:
        sales = sales.filter(sale_date__date__lte=date_to)
    
    # Payment method filter - FIXED: Use iexact for case-insensitive matching
    payment_method = request.GET.get('payment_method')
    if payment_method:
        # Use iexact for case-insensitive matching
        sales = sales.filter(payment_method__iexact=payment_method)
    
    # Sale type filter (cash vs credit)
    sale_type = request.GET.get('sale_type')
    if sale_type == 'cash':
        sales = sales.filter(is_credit=False)
    elif sale_type == 'credit':
        sales = sales.filter(is_credit=True)
    
    # Search filter
    search = request.GET.get('search')
    if search:
        sales = sales.filter(
            Q(sale_id__icontains=search) |
            Q(buyer_name__icontains=search) |
            Q(buyer_phone__icontains=search)
        )
    
    # ============================================
    # Pagination
    # ============================================
    paginator = Paginator(sales, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Pass the current filter values to template for maintaining selections
    context = {
        'sales': page_obj,
        'current_filters': {
            'date_from': date_from,
            'date_to': date_to,
            'payment_method': payment_method,
            'sale_type': sale_type,
            'search': search,
        }
    }
    return render(request, 'sales/list.html', context)





@login_required
def sale_create(request):
    """Create a new sale"""
    if request.method == 'POST':
        # Check if it's an AJAX request
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        # Get data based on request type
        if is_ajax:
            # Handle JSON data from AJAX
            try:
                data = json.loads(request.body)
                buyer_phone = data.get('buyer_phone', '')
                payment_method = data.get('payment_method', 'Cash')
                is_credit = data.get('is_credit', False)
                amount_paid = Decimal(str(data.get('amount_paid', '0')))
                
                # Set other fields to empty
                buyer_name = ''
                buyer_id_number = ''
                nok_name = ''
                nok_phone = ''
                
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'error': 'Invalid JSON data'})
        else:
            # Handle traditional form POST
            buyer_phone = request.POST.get('buyer_phone', '')
            payment_method = request.POST.get('payment_method', 'Cash')
            is_credit = request.POST.get('is_credit') == 'on'
            
            buyer_name = ''
            buyer_id_number = ''
            nok_name = ''
            nok_phone = ''
            
            if is_credit:
                amount_paid = Decimal('0.00')
            else:
                amount_paid = Decimal(request.POST.get('amount_paid', '0'))
        
        # Get cart items from session
        cart = request.session.get('sales_cart', [])
        
        if not cart:
            if is_ajax:
                return JsonResponse({'success': False, 'error': 'No items in cart.'})
            messages.error(request, 'No items in cart.')
            return redirect('sales:sale_create')
        
        try:
            with transaction.atomic():
                # Calculate totals
                subtotal = sum(item['total'] for item in cart)
                total_amount = subtotal
                
                # Create the sale
                sale = Sale.objects.create(
                    seller=request.user,
                    buyer_name=buyer_name,
                    buyer_phone=buyer_phone,
                    buyer_id_number=buyer_id_number,
                    nok_name=nok_name,
                    nok_phone=nok_phone,
                    payment_method=payment_method,
                    amount_paid=amount_paid,
                    total_amount=total_amount,
                    subtotal=subtotal,
                    is_credit=is_credit
                )
                
                # Process each cart item
                items_processed = []  # Track items for notification
                for item in cart:
                    product = Product.objects.select_for_update().get(
                        product_code=item['product_code']
                    )
                    
                    # Check stock availability
                    if product.quantity < item['quantity']:
                        raise ValueError(
                            f"Insufficient stock for {product.display_name}. "
                            f"Available: {product.quantity}, Requested: {item['quantity']}"
                        )
                    
                    # CRITICAL FIX: For single items, validate they haven't been sold already
                    if product.category and product.category.is_single_item:
                        # Double-check if this single item was already sold in another transaction
                        if SaleItem.objects.filter(sku_value=product.sku_value).exists():
                            raise ValueError(
                                f"This {product.display_name} (SKU: {product.sku_value}) has already been sold in another transaction!"
                            )
                    
                    # Create sale item
                    sale_item = SaleItem.objects.create(
                        sale=sale,
                        product=product,
                        product_code=product.product_code,
                        product_name=product.display_name,
                        sku_value=product.sku_value,
                        quantity=item['quantity'],
                        unit_price=item['price'],
                        total_price=item['total']
                    )
                    
                    # Update product quantity
                    product.quantity -= item['quantity']
                    
                    # CRITICAL FIX: For single items, mark as sold and set status
                    if product.category and product.category.is_single_item:
                        product.status = 'sold'
                        # Ensure quantity is 0 for sold single items
                        product.quantity = 0
                    
                    product.save()
                    items_processed.append({
                        'name': product.display_name,
                        'code': product.product_code,
                        'quantity': item['quantity'],
                        'price': item['price']
                    })
                
                # Clear the cart
                request.session['sales_cart'] = []
                
                # Handle credit sale if needed
                if is_credit:
                    try:
                        from credit.models import CreditSale
                        credit_sale = CreditSale.objects.create(
                            sale_id=sale.sale_id,
                            customer_name=buyer_name or "Walk-in Customer",
                            customer_phone=buyer_phone,
                            customer_id_number=buyer_id_number,
                            nok_name=nok_name,
                            nok_phone=nok_phone,
                            total_amount=total_amount,
                            created_by=request.user,
                        )
                        sale.credit_sale_id = credit_sale.id
                        sale.save(update_fields=['credit_sale_id'])
                    except ImportError:
                        logger.warning(f"Credit app not found for sale #{sale.sale_id}")
                    except Exception as e:
                        logger.error(f"Credit record creation failed: {str(e)}")
                
                # ============================================
                # ADD NOTIFICATION HERE - AFTER SUCCESSFUL SALE
                # ============================================
                # Import the notifier
                from utils.notifications import AdminNotifier
                
                # Send notification to admin
                try:
                    AdminNotifier.notify_sale_completed(sale, len(items_processed))
                    logger.info(f"Admin notification sent for sale #{sale.sale_id}")
                except Exception as e:
                    logger.error(f"Failed to send admin notification: {str(e)}")
                    # Don't fail the sale if notification fails
                
                # Return appropriate response
                if is_ajax:
                    return JsonResponse({
                        'success': True,
                        'sale_id': sale.sale_id,
                        'message': 'Sale completed successfully!'
                    })
                else:
                    messages.success(request, f'Sale #{sale.sale_id} completed successfully!')
                    return redirect('sales:sale_detail', sale_id=sale.sale_id)
                
        except Exception as e:
            logger.error(f"Error processing sale: {str(e)}")
            if is_ajax:
                return JsonResponse({'success': False, 'error': str(e)})
            messages.error(request, f'Error processing sale: {str(e)}')
            return redirect('sales:sale_create')
    
    # GET request - show the sale form with cart
    cart = request.session.get('sales_cart', [])
    subtotal = sum(item.get('total', 0) for item in cart)
    
    context = {
        'cart': cart,
        'subtotal': subtotal,
        'cart_count': len(cart),
        'now': timezone.now(),
    }
    return render(request, 'sales/create.html', context)









@login_required
def sale_detail(request, sale_id):
    """View sale details"""
    sale = get_object_or_404(Sale.objects.prefetch_related('items__product'), sale_id=sale_id)
    
    # Calculate change and balance in the view
    change = sale.amount_paid - sale.total_amount
    balance = sale.total_amount - sale.amount_paid if sale.amount_paid < sale.total_amount else 0
    
    context = {
        'sale': sale,
        'items': sale.items.all(),
        'change': change,
        'balance': balance,
    }
    return render(request, 'sales/detail.html', context)







@login_required
def sale_receipt(request, sale_id):
    """View/print sale receipt"""
    sale = get_object_or_404(Sale.objects.prefetch_related('items__product'), sale_id=sale_id)
    
    # Calculate change
    change = sale.amount_paid - sale.total_amount if sale.amount_paid else 0
    
    context = {
        'sale': sale,
        'items': sale.items.all(),
        'change': change,  # Add this
    }
    return render(request, 'sales/receipt.html', context)





@login_required
def sale_reverse(request, sale_id):
    """Reverse a sale"""
    sale = get_object_or_404(Sale, sale_id=sale_id)
    
    if sale.is_reversed:
        messages.error(request, 'This sale has already been reversed.')
        return redirect('sales:sale_detail', sale_id=sale_id)
    
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        
        try:
            with transaction.atomic():
                # Reverse the sale
                result = sale.reverse_sale(reversed_by=request.user)
                
                # ============================================
                # ADD NOTIFICATION FOR SALE REVERSAL (with error handling)
                # ============================================
                try:
                    from utils.notifications import AdminNotifier
                    AdminNotifier.notify_sale_reversed(sale, request.user, reason)
                    logger.info(f"Admin notification sent for reversed sale #{sale.sale_id}")
                except ImportError:
                    logger.warning("AdminNotifier not available - skipping notification")
                except Exception as e:
                    logger.error(f"Failed to send reversal notification: {str(e)}")
                
                messages.success(request, result)
                return redirect('sales:sale_detail', sale_id=sale_id)
                
        except Exception as e:
            messages.error(request, f'Error reversing sale: {str(e)}')
            return redirect('sales:sale_detail', sale_id=sale_id)
    
    context = {
        'sale': sale,
    }
    return render(request, 'sales/reverse.html', context)






# ====================================
# API VIEWS FOR CART MANAGEMENT
# ====================================

@login_required
def get_product_details(request, product_code):
    """AJAX endpoint to get product details by code or barcode"""
    try:
        # Search by product_code or barcode
        product = Product.objects.get(
            Q(product_code=product_code) | Q(barcode=product_code)
        )
        
        # Check if single item is already sold
        if product.category.is_single_item:
            if product.status == 'sold' or product.quantity <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'This item has already been sold'
                })
            if product.quantity <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Product out of stock'
                })
        else:
            # Bulk items check quantity
            if product.quantity <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Product out of stock'
                })
        
        return JsonResponse({
            'success': True,
            'product': {
                'product_code': product.product_code,
                'name': product.display_name,
                'price': float(product.selling_price),
                'stock': product.quantity,
                'sku': product.sku_value,
                'is_single': product.category.is_single_item,
                'status': product.status
            }
        })
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Product not found'
        })






@login_required
def get_cart(request):
    """AJAX endpoint to get current cart contents"""
    cart = request.session.get('sales_cart', [])
    subtotal = sum(item.get('total', 0) for item in cart)
    
    return JsonResponse({
        'success': True,
        'cart': cart,
        'subtotal': subtotal,
        'cart_count': len(cart)
    })





@login_required
def add_to_cart(request):
    """AJAX endpoint to add item to cart with custom price"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_code = data.get('product_code')
            quantity = int(data.get('quantity', 1))
            custom_price = data.get('custom_price')
            allow_price_edit = data.get('allow_price_edit', False)
            
            try:
                product = Product.objects.get(product_code=product_code)
            except Product.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': f'Product with code "{product_code}" not found'
                })
            
            # CRITICAL FIX: Check if single item is already sold
            if product.category and product.category.is_single_item:
                # Check if already sold
                if product.status == 'sold' or product.quantity <= 0:
                    return JsonResponse({
                        'success': False,
                        'error': f'This item ({product.display_name}) has already been sold and cannot be added to cart'
                    })
                
                # Check if quantity is more than 1 for single items
                if quantity != 1:
                    return JsonResponse({
                        'success': False,
                        'error': 'Single items can only be sold one at a time'
                    })
            
            # Check stock for bulk items
            if product.quantity < quantity:
                return JsonResponse({
                    'success': False,
                    'error': f'Insufficient stock. Available: {product.quantity}'
                })
            
            # Determine the price
            if custom_price is not None and custom_price and allow_price_edit:
                try:
                    price = float(custom_price)
                except (ValueError, TypeError):
                    price = float(product.selling_price)
            else:
                price = float(product.selling_price)
            
            # Get or create cart in session
            cart = request.session.get('sales_cart', [])
            
            # For single items, check if already in cart
            if product.category and product.category.is_single_item:
                for item in cart:
                    if item.get('product_code') == product_code:
                        return JsonResponse({
                            'success': False,
                            'error': 'This item is already in the cart'
                        })
            
            # Check if product with SAME PRICE already exists in cart (for bulk items)
            found = False
            for item in cart:
                # Only combine if same product code AND same price (for bulk items)
                if item.get('product_code') == product_code and item.get('price') == price:
                    # Don't combine single items
                    if product.category and product.category.is_single_item:
                        continue
                    
                    # Same product with same price - combine quantities
                    new_quantity = item['quantity'] + quantity
                    if product.quantity < new_quantity:
                        return JsonResponse({
                            'success': False,
                            'error': f'Only {product.quantity} available'
                        })
                    
                    item['quantity'] = new_quantity
                    item['total'] = item['price'] * item['quantity']
                    found = True
                    break
            
            if not found:
                # Add as new row
                cart.append({
                    'product_id': product.id,
                    'product_code': product.product_code,
                    'name': product.display_name,
                    'price': price,
                    'original_price': float(product.selling_price),
                    'quantity': quantity,
                    'total': price * quantity,
                    'is_single': product.category.is_single_item if product.category else False,
                    'price_editable': allow_price_edit,
                    'unique_id': f"{product_code}_{price}_{len(cart)}"
                })
            
            # Save cart to session
            request.session['sales_cart'] = cart
            request.session.modified = True
            
            # Calculate new totals
            subtotal = sum(item['total'] for item in cart)
            cart_count = len(cart)
            
            return JsonResponse({
                'success': True,
                'cart': cart,
                'subtotal': subtotal,
                'cart_count': cart_count,
                'message': f'{product.display_name} added to cart' + 
                          (f' at KSH {price}' if custom_price else '')
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})






def validate_single_items_in_cart(cart):
    """
    Validate that no single items in cart have been sold already
    """
    for item in cart:
        if item.get('is_single'):
            try:
                product = Product.objects.get(product_code=item['product_code'])
                if product.status == 'sold' or product.quantity <= 0:
                    return False, f"Item {product.display_name} has already been sold"
                
                # Check if this SKU appears in any sale
                if SaleItem.objects.filter(sku_value=product.sku_value).exists():
                    return False, f"Item {product.display_name} (SKU: {product.sku_value}) has already been sold"
                    
            except Product.DoesNotExist:
                return False, f"Product {item['product_code']} not found"
    
    return True, "All items are available"





@login_required
def remove_from_cart(request):
    """AJAX endpoint to remove item from cart"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_code = data.get('product_code')
            price = float(data.get('price', 0))  # Get price to identify specific row
            
            cart = request.session.get('sales_cart', [])
            
            # Remove the specific item with matching code AND price
            new_cart = [item for item in cart 
                       if not (item['product_code'] == product_code and item['price'] == price)]
            
            request.session['sales_cart'] = new_cart
            request.session.modified = True
            
            subtotal = sum(item['total'] for item in new_cart)
            
            return JsonResponse({
                'success': True,
                'cart': new_cart,
                'subtotal': subtotal,
                'cart_count': len(new_cart)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})





@login_required
def update_cart(request):
    """AJAX endpoint to update item quantity in cart"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_code = data.get('product_code')
            quantity = int(data.get('quantity', 1))
            price = float(data.get('price', 0))  # Also get price to identify the specific row
            
            cart = request.session.get('sales_cart', [])
            
            if quantity < 1:
                return JsonResponse({
                    'success': False,
                    'error': 'Quantity must be at least 1'
                })
            
            # Find the specific item with matching code AND price
            found = False
            for item in cart:
                if item['product_code'] == product_code and item['price'] == price:
                    # Check stock
                    try:
                        product = Product.objects.get(product_code=product_code)
                        if product.quantity < quantity:
                            return JsonResponse({
                                'success': False,
                                'error': f'Only {product.quantity} available'
                            })
                    except Product.DoesNotExist:
                        pass
                    
                    item['quantity'] = quantity
                    item['total'] = item['price'] * quantity
                    found = True
                    break
            
            if not found:
                return JsonResponse({
                    'success': False,
                    'error': 'Item not found in cart'
                })
            
            request.session['sales_cart'] = cart
            request.session.modified = True
            
            subtotal = sum(item['total'] for item in cart)
            
            return JsonResponse({
                'success': True,
                'cart': cart,
                'subtotal': subtotal,
                'cart_count': len(cart)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})





@login_required
def update_cart_price(request):
    """AJAX endpoint to update item price in cart"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_code = data.get('product_code')
            old_price = float(data.get('old_price', 0))
            new_price = float(data.get('price', 0))
            
            if new_price < 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Price cannot be negative'
                })
            
            cart = request.session.get('sales_cart', [])
            
            # Find the specific item with matching code AND old price
            found = False
            for item in cart:
                if item['product_code'] == product_code and item['price'] == old_price:
                    if not item.get('price_editable', False):
                        return JsonResponse({
                            'success': False,
                            'error': 'This item price is locked'
                        })
                    
                    item['price'] = new_price
                    item['total'] = new_price * item['quantity']
                    found = True
                    break
            
            if not found:
                return JsonResponse({
                    'success': False,
                    'error': 'Item not found in cart'
                })
            
            request.session['sales_cart'] = cart
            request.session.modified = True
            
            subtotal = sum(item['total'] for item in cart)
            
            return JsonResponse({
                'success': True,
                'cart': cart,
                'subtotal': subtotal,
                'cart_count': len(cart)
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})


    


@login_required
def clear_cart(request):
    """AJAX endpoint to clear the entire cart"""
    if request.method == 'POST':
        request.session['sales_cart'] = []
        return JsonResponse({
            'success': True,
            'message': 'Cart cleared'
        })
    return JsonResponse({'success': False, 'error': 'Invalid request'})