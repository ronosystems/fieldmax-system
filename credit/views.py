from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum, Count
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import logging
from django.http import JsonResponse
from django.conf import settings
from django.core.paginator import Paginator
from django.urls import reverse
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import F, Value, CharField
from django.db.models.functions import Concat

from .models import (
    CreditCompany, CreditCustomer, CreditTransaction, 
    CompanyPayment, CreditTransactionLog
)
from inventory.models import Product





logger = logging.getLogger(__name__)








@login_required
def dashboard(request):
    """Credit dashboard with overview"""
    
    # Summary stats
    total_pending = CreditTransaction.objects.filter(payment_status='pending').aggregate(
        total=Sum('ceiling_price')
    )['total'] or Decimal('0')
    
    total_paid = CreditTransaction.objects.filter(payment_status='paid').aggregate(
        total=Sum('ceiling_price')
    )['total'] or Decimal('0')
    
    pending_count = CreditTransaction.objects.filter(payment_status='pending').count()
    paid_count = CreditTransaction.objects.filter(payment_status='paid').count()
    cancelled_count = CreditTransaction.objects.filter(payment_status='cancelled').count()
    
    # Companies summary - REMOVE ANNOTATIONS, just get the companies
    companies = CreditCompany.objects.filter(is_active=True)[:5]  # Get top 5 active companies
    
    # Recent transactions
    recent_transactions = CreditTransaction.objects.select_related(
        'customer', 'credit_company', 'product'
    ).order_by('-transaction_date')[:10]
    
    # Chart data (last 30 days)
    from datetime import timedelta, date
    import json
    
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)
    
    chart_labels = []
    credit_data = []
    payment_data = []
    
    for i in range(30):
        day = thirty_days_ago + timedelta(days=i)
        next_day = day + timedelta(days=1)
        
        # Credit created on this day
        day_credit = CreditTransaction.objects.filter(
            transaction_date__date=day
        ).aggregate(total=Sum('ceiling_price'))['total'] or 0
        
        # Payments on this day (when transactions were marked as paid)
        day_payments = CreditTransaction.objects.filter(
            paid_date__date=day,
            payment_status='paid'
        ).aggregate(total=Sum('ceiling_price'))['total'] or 0
        
        chart_labels.append(day.strftime('%d %b'))
        credit_data.append(float(day_credit))
        payment_data.append(float(day_payments))
    
    context = {
        'total_pending': total_pending,
        'total_paid': total_paid,
        'pending_count': pending_count,
        'paid_count': paid_count,
        'cancelled_count': cancelled_count,
        'companies': companies,
        'recent_transactions': recent_transactions,
        'chart_labels': json.dumps(chart_labels),
        'credit_data': json.dumps(credit_data),
        'payment_data': json.dumps(payment_data),
    }
    
    return render(request, 'credit/dashboard.html', context)




# ====================================
# COMPANY VIEWS
# ====================================

@login_required
def company_list(request):
    """List all credit companies"""
    # Remove the annotations - use the model properties instead
    companies = CreditCompany.objects.all()
    
    # Optional: Filter by status if needed
    status = request.GET.get('status')
    if status == 'active':
        companies = companies.filter(is_active=True)
    elif status == 'inactive':
        companies = companies.filter(is_active=False)
    
    # Optional: Search
    search = request.GET.get('search')
    if search:
        companies = companies.filter(
            Q(name__icontains=search) |
            Q(code__icontains=search) |
            Q(email__icontains=search)
        )
    
    context = {
        'companies': companies,
    }
    return render(request, 'credit/companies/list.html', context)



@login_required
def company_add(request):
    """Add a new credit company"""
    if request.method == 'POST':
        try:
            company = CreditCompany.objects.create(
                name=request.POST.get('name'),
                email=request.POST.get('email'),
                phone=request.POST.get('phone', ''),
                contact_person=request.POST.get('contact_person', ''),
                address=request.POST.get('address', ''),
                payment_terms=request.POST.get('payment_terms', ''),
                is_active=request.POST.get('is_active') == 'on',
                created_by=request.user
            )
            messages.success(request, f'Company "{company.name}" added successfully.')
            return redirect('credit:company_list')
        except Exception as e:
            messages.error(request, f'Error adding company: {str(e)}')
    
    return render(request, 'credit/companies/add.html')

@login_required
def company_detail(request, pk):
    """View company details"""
    company = get_object_or_404(CreditCompany, pk=pk)
    
    # Get transactions
    pending_transactions = company.transactions.filter(payment_status='pending').order_by('-transaction_date')
    paid_transactions = company.transactions.filter(payment_status='paid').order_by('-transaction_date')
    
    context = {
        'company': company,
        'pending_transactions': pending_transactions,
        'paid_transactions': paid_transactions,
    }
    return render(request, 'credit/companies/detail.html', context)

@login_required
def company_edit(request, pk):
    """Edit company details"""
    company = get_object_or_404(CreditCompany, pk=pk)
    
    if request.method == 'POST':
        try:
            company.name = request.POST.get('name')
            company.email = request.POST.get('email')
            company.phone = request.POST.get('phone', '')
            company.contact_person = request.POST.get('contact_person', '')
            company.address = request.POST.get('address', '')
            company.payment_terms = request.POST.get('payment_terms', '')
            company.is_active = request.POST.get('is_active') == 'on'
            company.save()
            
            messages.success(request, f'Company "{company.name}" updated successfully.')
            return redirect('credit:company_detail', pk=company.pk)
        except Exception as e:
            messages.error(request, f'Error updating company: {str(e)}')
    
    context = {'company': company}
    return render(request, 'credit/companies/edit.html', context)

# ====================================
# CUSTOMER VIEWS
# ====================================

@login_required
def customer_list(request):
    """List all credit customers"""
    # Remove the annotations - use the model properties instead
    customers = CreditCustomer.objects.all()
    
    # Apply filters
    search = request.GET.get('search')
    if search:
        customers = customers.filter(
            Q(full_name__icontains=search) |
            Q(id_number__icontains=search) |
            Q(phone_number__icontains=search)
        )
    
    county = request.GET.get('county')
    if county:
        customers = customers.filter(county__icontains=county)
    
    status = request.GET.get('status')
    if status == 'active':
        customers = customers.filter(is_active=True)
    elif status == 'inactive':
        customers = customers.filter(is_active=False)
    
    context = {
        'customers': customers,
    }
    return render(request, 'credit/customers/list.html', context)




@login_required
def customer_add(request):
    """Add a new credit customer with photo uploads"""
    if request.method == 'POST':
        try:
            # Check if this is an AJAX request
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            
            # Get form data
            full_name = request.POST.get('full_name')
            id_number = request.POST.get('id_number')
            phone_number = request.POST.get('phone_number')
            nok_name = request.POST.get('nok_name', '')
            nok_phone = request.POST.get('nok_phone', '')
            email = request.POST.get('email', '')
            alternate_phone = request.POST.get('alternate_phone', '')
            county = request.POST.get('county', '')
            town = request.POST.get('town', '')
            physical_address = request.POST.get('physical_address', '')
            
            # Check if customer with this ID already exists
            existing_customer = CreditCustomer.objects.filter(id_number=id_number).first()
            if existing_customer:
                # Check if this customer has any active credit transactions
                active_transactions = CreditTransaction.objects.filter(
                    customer=existing_customer,
                    payment_status__in=['pending', 'Active']  # Assuming 'Active' is a valid status for ongoing loans
                ).exists()
                
                if active_transactions:
                    error_message = f"⚠️ CUSTOMER WITH ID {id_number} HAS AN ACTIVE LOAN: {existing_customer.full_name} - Please verify before adding a new customer with the same ID."
                else:
                    error_message = f"Customer with ID {id_number} already exists: {existing_customer.full_name} - No active loans found, but please verify before adding a new customer with the same ID."
                
                if is_ajax:
                    return JsonResponse({
                        'success': False,
                        'error': error_message,
                        'existing_customer': {
                            'id': existing_customer.id,
                            'full_name': existing_customer.full_name,
                            'phone_number': existing_customer.phone_number,
                            'has_active_credit': active_transactions
                        }
                    })
                else:
                    messages.error(request, error_message)
                    return render(request, 'credit/customers/add.html')
            
            # Handle file uploads
            passport_photo = request.FILES.get('passport_photo')
            id_front_photo = request.FILES.get('id_front_photo')
            id_back_photo = request.FILES.get('id_back_photo')
            additional_document = request.FILES.get('additional_document')
            
            # Create new customer
            customer = CreditCustomer.objects.create(
                full_name=full_name,
                id_number=id_number,
                phone_number=phone_number,
                nok_name=nok_name,
                nok_phone=nok_phone,
                email=email,
                alternate_phone=alternate_phone,
                county=county,
                town=town,
                physical_address=physical_address,
                passport_photo=passport_photo,
                id_front_photo=id_front_photo,
                id_back_photo=id_back_photo,
                additional_document=additional_document,
                is_active=True,
                created_by=request.user
            )
            
            if is_ajax:
                # Return JSON response for AJAX requests
                return JsonResponse({
                    'success': True,
                    'customer': {
                        'id': customer.id,
                        'full_name': customer.full_name,
                        'phone_number': customer.phone_number,
                        'id_number': customer.id_number,
                        'nok_name': customer.nok_name,
                        'nok_phone': customer.nok_phone,
                        'has_photos': customer.has_photos
                    }
                })
            else:
                # Regular form submission
                messages.success(request, f'Customer "{customer.full_name}" added successfully with photos.')
                # Check if there's a next parameter
                next_url = request.POST.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect('credit:customer_list')
                
        except Exception as e:
            logger.error(f"Error adding customer: {str(e)}")
            if is_ajax:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                })
            else:
                messages.error(request, f'Error adding customer: {str(e)}')
                return render(request, 'credit/customers/add.html')
    
    # GET request - show form
    return render(request, 'credit/customers/add.html')





@login_required
def customer_detail(request, pk):
    """View customer details"""
    customer = get_object_or_404(CreditCustomer, pk=pk)
    
    # Get transactions
    transactions = customer.transactions.all().order_by('-transaction_date')
    
    context = {
        'customer': customer,
        'transactions': transactions,
    }
    return render(request, 'credit/customers/detail.html', context)




@login_required
def customer_edit(request, pk):
    """Edit customer details"""
    customer = get_object_or_404(CreditCustomer, pk=pk)
    
    if request.method == 'POST':
        try:
            # Get form data
            full_name = request.POST.get('full_name')
            phone_number = request.POST.get('phone_number')
            email = request.POST.get('email', '')
            alternate_phone = request.POST.get('alternate_phone', '')
            county = request.POST.get('county', '')
            town = request.POST.get('town', '')
            physical_address = request.POST.get('physical_address', '')
            nok_name = request.POST.get('nok_name', '')
            nok_phone = request.POST.get('nok_phone', '')
            is_active = request.POST.get('is_active') == 'on'
            notes = request.POST.get('notes', '')
            
            # IMPORTANT: Do NOT update id_number - it should remain unchanged
            # Only update the editable fields
            customer.full_name = full_name
            customer.phone_number = phone_number
            customer.email = email
            customer.alternate_phone = alternate_phone
            customer.county = county
            customer.town = town
            customer.physical_address = physical_address
            customer.nok_name = nok_name
            customer.nok_phone = nok_phone
            customer.is_active = is_active
            customer.notes = notes
            
            customer.save()
            
            messages.success(request, f'Customer "{customer.full_name}" updated successfully.')
            return redirect('credit:customer_detail', pk=customer.pk)
            
        except Exception as e:
            messages.error(request, f'Error updating customer: {str(e)}')
    
    context = {'customer': customer}
    return render(request, 'credit/customers/edit.html', context)





# ====================================
# TRANSACTION VIEWS
# ====================================

@login_required
def transaction_list(request):
    """List all credit transactions"""
    transactions = CreditTransaction.objects.select_related(
        'customer', 'credit_company', 'product'
    ).order_by('-transaction_date')
    
    # Filters
    status = request.GET.get('status')
    if status:
        transactions = transactions.filter(payment_status=status)
    
    company_id = request.GET.get('company')
    if company_id:
        transactions = transactions.filter(credit_company_id=company_id)
    
    context = {
        'transactions': transactions,
    }
    return render(request, 'credit/transactions/list.html', context)



@login_required
def transaction_create(request):
    """Create a new credit transaction"""
    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Get form data
                company_id = request.POST.get('company')
                customer_id = request.POST.get('customer')
                product_id = request.POST.get('product')
                ceiling_price = Decimal(request.POST.get('ceiling_price', '0'))
                imei = request.POST.get('imei', '')
                notes = request.POST.get('notes', '')
                
                # Get related objects
                company = CreditCompany.objects.get(id=company_id)
                customer = CreditCustomer.objects.get(id=customer_id)
                product = Product.objects.get(id=product_id)
                
                # Check if product is available for credit
                can_use, message = product.can_be_used_for_credit
                if not can_use:
                    messages.error(request, message)
                    return redirect('credit:transaction_create')
                
                # Check if this product already has ANY credit transaction
                existing_transaction = CreditTransaction.objects.filter(
                    product=product
                ).exists()
                
                if existing_transaction:
                    messages.error(
                        request, 
                        f'Product {product.product_code} already has a credit transaction. '
                        f'Each product can only be used once for credit.'
                    )
                    return redirect('credit:transaction_create')
                
                # Create transaction
                credit_transaction = CreditTransaction.objects.create(
                    credit_company=company,
                    customer=customer,
                    dealer=request.user,
                    product=product,
                    ceiling_price=ceiling_price,
                    imei=imei,
                    notes=notes
                )
                
                # ============================================
                # UPDATE PRODUCT STATUS (Single item only)
                # ============================================
                # For single items, mark as sold
                if product.category.is_single_item:
                    product.status = 'sold'
                    product.quantity = 0
                    product.save()
                    
                    # Create stock entry for inventory tracking
                    from inventory.models import StockEntry
                    StockEntry.objects.create(
                        product=product,
                        quantity=-1,
                        entry_type='sale',
                        unit_price=ceiling_price,
                        total_amount=ceiling_price,
                        reference_id=credit_transaction.transaction_id,
                        notes=f'Credit sale - {customer.full_name} via {company.name}',
                        created_by=request.user
                    )
                
                # Create log
                CreditTransactionLog.objects.create(
                    transaction=credit_transaction,
                    action='created',
                    performed_by=request.user,
                    notes=f'Product {product.product_code} - New status: {product.status}'
                )
                
                logger.info(
                    f"[CREDIT TRANSACTION] Created: {credit_transaction.transaction_id} | "
                    f"Product: {product.product_code} | "
                    f"Type: Single | "
                    f"Status: {product.status}"
                )
                
                messages.success(
                    request, 
                    f'Credit transaction #{credit_transaction.transaction_id} created successfully. '
                    f'Product {product.product_code} has been marked as sold.'
                )
                return redirect('credit:transaction_receipt', pk=credit_transaction.pk)
                
        except Exception as e:
            logger.error(f"Error creating credit transaction: {str(e)}")
            messages.error(request, f'Error creating transaction: {str(e)}')
            return redirect('credit:transaction_create')
    
    # GET request - show form
    companies = CreditCompany.objects.filter(is_active=True)
    customers = CreditCustomer.objects.filter(is_active=True)
    
    # ============================================
    # GET ONLY SINGLE ITEMS AVAILABLE FOR CREDIT
    # ============================================
    
    # Get IDs of products that already have ANY credit transaction
    products_with_credit = CreditTransaction.objects.values_list('product_id', flat=True).distinct()
    
    # Filter products:
    # 1. Category is single item (category__is_single_item=True)
    # 2. Status = 'available'
    # 3. Quantity > 0 (has stock)
    # 4. NOT in products_with_credit (no existing credit transaction)
    products = Product.objects.filter(
        category__item_type='single',
        status='available',
        quantity__gt=0
    ).exclude(
        id__in=products_with_credit
    ).select_related('category').order_by('-created_at')
    
    # Log for debugging
    logger.info(f"Credit product selection - Single items available: {products.count()}")
    
    # If no products available, show warning
    if products.count() == 0:
        messages.warning(
            request, 
            'No single items available for credit. All available items either:\n'
            '- Have existing credit transactions\n'
            '- Are out of stock\n'
            '- Have status other than "available"'
        )
    
    context = {
        'companies': companies,
        'customers': customers,
        'products': products,
    }
    return render(request, 'credit/transactions/create.html', context)




@login_required
def transaction_receipt(request, pk):
    """View transaction receipt"""
    transaction = get_object_or_404(
        CreditTransaction.objects.select_related('customer', 'credit_company', 'product', 'dealer'),
        pk=pk
    )
    
    context = {
        'transaction': transaction,
    }
    return render(request, 'credit/transactions/receipt.html', context)



@login_required
def transaction_detail(request, pk):
    """View transaction details"""
    transaction = get_object_or_404(
        CreditTransaction.objects.select_related('customer', 'credit_company', 'product', 'dealer'),
        pk=pk
    )
    logs = transaction.logs.all().order_by('-created_at')
    
    context = {
        'transaction': transaction,
        'logs': logs,
    }
    return render(request, 'credit/transactions/detail.html', context)

@login_required
def transaction_pay(request, pk):
    """Mark a transaction as paid"""
    transaction = get_object_or_404(CreditTransaction, pk=pk)
    
    if request.method == 'POST':
        try:
            payment_ref = request.POST.get('payment_reference', '')
            transaction.mark_as_paid(payment_ref=payment_ref, paid_by=request.user)
            messages.success(request, f'Transaction #{transaction.transaction_id} marked as paid.')
        except Exception as e:
            messages.error(request, f'Error marking transaction as paid: {str(e)}')
        
        return redirect('credit:transaction_detail', pk=pk)
    
    return render(request, 'credit/transactions/pay.html', {'transaction': transaction})

@login_required
def transaction_cancel(request, pk):
    """Cancel a transaction"""
    transaction = get_object_or_404(CreditTransaction, pk=pk)
    
    if request.method == 'POST':
        try:
            reason = request.POST.get('reason', '')
            transaction.cancel(reason=reason, cancelled_by=request.user)
            messages.success(request, f'Transaction #{transaction.transaction_id} cancelled.')
        except Exception as e:
            messages.error(request, f'Error cancelling transaction: {str(e)}')
        
        return redirect('credit:transaction_detail', pk=pk)
    
    return render(request, 'credit/transactions/cancel.html', {'transaction': transaction})




@login_required
def transaction_reverse(request, pk):
    """Reverse a credit transaction (restore product to inventory)"""
    transaction = get_object_or_404(CreditTransaction, pk=pk)
    
    if request.method == 'POST':
        try:
            reason = request.POST.get('reason', '')
            
            # Check if transaction can be reversed
            if transaction.payment_status == 'reversed':
                messages.error(request, 'Transaction is already reversed.')
                return redirect('credit:transaction_detail', pk=pk)
            
            if transaction.payment_status == 'paid':
                messages.error(request, 'Paid transactions cannot be reversed. Please contact admin.')
                return redirect('credit:transaction_detail', pk=pk)
            
            # Reverse the transaction
            transaction.reverse_transaction(
                reversed_by=request.user,
                reason=reason
            )
            
            messages.success(
                request, 
                f'Transaction #{transaction.transaction_id} reversed successfully. '
                f'Product {transaction.product.product_code} is now available again.'
            )
            return redirect('credit:transaction_detail', pk=pk)
            
        except Exception as e:
            messages.error(request, f'Error reversing transaction: {str(e)}')
            return redirect('credit:transaction_detail', pk=pk)
    
    return render(request, 'credit/transactions/reverse.html', {'transaction': transaction})






# ====================================
# PAYMENT VIEWS
# ====================================

@login_required
def payment_list(request):
    """List all company payments"""
    payments = CompanyPayment.objects.select_related('credit_company').order_by('-payment_date')
    
    context = {'payments': payments}
    return render(request, 'credit/payments/list.html', context)

@login_required
def payment_add(request):
    """Add a new company payment"""
    if request.method == 'POST':
        try:
            with transaction.atomic():
                company_id = request.POST.get('company')
                amount = Decimal(request.POST.get('amount', '0'))
                payment_method = request.POST.get('payment_method')
                payment_reference = request.POST.get('payment_reference')
                payment_date = request.POST.get('payment_date')
                transaction_ids = request.POST.getlist('transactions')
                
                # Create payment
                payment = CompanyPayment.objects.create(
                    credit_company_id=company_id,
                    amount=amount,
                    payment_method=payment_method,
                    payment_reference=payment_reference,
                    payment_date=payment_date,
                    created_by=request.user
                )
                
                # Add transactions
                if transaction_ids:
                    transactions = CreditTransaction.objects.filter(
                        id__in=transaction_ids,
                        payment_status='pending'
                    )
                    payment.transactions.set(transactions)
                
                # Process payment
                payment.process_payment()
                
                messages.success(request, f'Payment #{payment.payment_id} recorded and processed.')
                return redirect('credit:payment_detail', pk=payment.pk)
                
        except Exception as e:
            messages.error(request, f'Error recording payment: {str(e)}')
    
    # GET request
    companies = CreditCompany.objects.filter(is_active=True)
    pending_transactions = CreditTransaction.objects.filter(
        payment_status='pending'
    ).select_related('customer', 'product')
    
    context = {
        'companies': companies,
        'pending_transactions': pending_transactions,
    }
    return render(request, 'credit/payments/add.html', context)

@login_required
def payment_detail(request, pk):
    """View payment details"""
    payment = get_object_or_404(
        CompanyPayment.objects.select_related('credit_company', 'created_by'),
        pk=pk
    )
    transactions = payment.transactions.all()
    
    context = {
        'payment': payment,
        'transactions': transactions,
    }
    return render(request, 'credit/payments/detail.html', context)

# ====================================
# SALES INTEGRATION API
# ====================================

@login_required
def convert_sale_to_credit(request, sale_id):
    """
    API endpoint called from Sales app when a credit sale is created
    """
    try:
        from sales.models import Sale
        
        sale = Sale.objects.get(sale_id=sale_id)
        
        if not sale.is_credit:
            return JsonResponse({
                'success': False,
                'error': 'This is not a credit sale'
            })
        
        # Create credit transaction
        credit_transaction = CreditTransaction.objects.create(
            credit_company=None,  # To be assigned later
            customer=CreditCustomer.objects.get_or_create(
                phone_number=sale.buyer_phone or '0000000000',
                defaults={
                    'full_name': sale.buyer_name or 'Unknown Customer',
                    'id_number': sale.buyer_id_number or '00000000',
                }
            )[0],
            dealer=sale.seller,
            product=sale.items.first().product,
            ceiling_price=sale.total_amount,
            notes=f"From sale #{sale.sale_id}"
        )
        
        # Link back to sale
        sale.credit_sale = credit_transaction
        sale.save()
        
        return JsonResponse({
            'success': True,
            'credit_transaction_id': credit_transaction.transaction_id
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })