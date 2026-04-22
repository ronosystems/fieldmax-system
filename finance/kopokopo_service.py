# finance/kopokopo_service.py

import requests
import base64
from decouple import config
from django.core.cache import cache
import logging
import json
import hmac
import hashlib
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


logger = logging.getLogger(__name__)


def get_kopokopo_token():
    """Get access token from Kopo Kopo"""
    client_id = config('KOPOKOPO_CLIENT_ID')
    client_secret = config('KOPOKOPO_CLIENT_SECRET')
    
    # Check cache
    cached_token = cache.get('kopokopo_token')
    if cached_token:
        return cached_token
    
    # Encode credentials
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    
    try:
        response = requests.post(
            "https://api.kopokopo.com/oauth/token",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={"grant_type": "client_credentials"},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            token = data.get('access_token')
            cache.set('kopokopo_token', token, 3480)
            logger.info("✅ Kopo Kopo token obtained")
            return token
        else:
            logger.error(f"❌ Auth failed: {response.text}")
            raise Exception(f"Auth failed: {response.text}")
    except Exception as e:
        logger.error(f"Token error: {str(e)}")
        raise


def clean_phone_number(phone):
    """Clean phone number to format +254XXXXXXXXX"""
    if not phone:
        return ''
    
    phone = ''.join(filter(str.isdigit, str(phone)))
    
    if phone.startswith('0') and len(phone) == 10:
        return '+254' + phone[1:]
    if phone.startswith('254') and len(phone) == 12:
        return '+' + phone
    if len(phone) == 9:
        return '+254' + phone
    
    return f'+{phone}' if not phone.startswith('+') else phone


def stk_push_request(phone_number, amount, account_reference, transaction_desc):
    """
    Initiate STK Push payment via Kopo Kopo
    """
    try:
        # Clean phone number to format +254XXXXXXXXX
        phone_number = clean_phone_number(phone_number)
        
        # Get configuration
        till_number = config('KOPOKOPO_TILL_NUMBER')
        callback_url = config('MPESA_CALLBACK_URL')
        
        # Ensure till number has K prefix as per docs
        if not till_number.startswith('K'):
            till_number = f"K{till_number}"
        
        # Get token
        token = get_kopokopo_token()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        payload = {
            "payment_channel": "M-PESA STK Push",
            "till_number": till_number,
            "subscriber": {
                "first_name": "Customer",
                "last_name": "Payment",
                "phone_number": phone_number
            },
            "amount": {
                "currency": "KES",
                "value": int(amount)
            },
            "metadata": {
                "reference": account_reference,
                "description": transaction_desc
            },
            "_links": {
                "callback_url": callback_url
            }
        }
        
        logger.info(f"Sending STK Push: Amount={amount}, Phone={phone_number}, Till={till_number}")
        
        response = requests.post(
            "https://api.kopokopo.com/api/v1/incoming_payments",
            headers=headers,
            json=payload,
            timeout=60
        )
        
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response body: {response.text}")
        
        # ============================================
        # CRITICAL FIX: Check response content, not just status code
        # ============================================
        try:
            response_data = response.json()
        except:
            response_data = {}
        
        # Check if response contains an error
        if response_data.get('error_code'):
            error_code = response_data.get('error_code')
            error_message = response_data.get('error_message', 'Unknown error')
            
            logger.error(f"Kopo Kopo API error: {error_code} - {error_message}")
            
            # Handle specific error codes
            if error_code == 429:
                return {
                    'ResponseCode': '429',
                    'ResponseDescription': error_message,
                    'error_code': '429',
                    'error_message': error_message
                }
            else:
                return {
                    'ResponseCode': '1',
                    'ResponseDescription': error_message,
                    'error_code': error_code,
                    'error_message': error_message
                }
        
        # Check if request was successful (HTTP 201 Created)
        if response.status_code == 201:
            location_url = response.headers.get('Location', '')
            payment_id = location_url.split('/')[-1] if location_url else None
            
            # Also check if response_data has resource_id
            if not payment_id and response_data.get('resource_id'):
                payment_id = response_data.get('resource_id')
            
            logger.info(f"✅ STK Push sent successfully. Payment ID: {payment_id}")
            return {
                'ResponseCode': '0',
                'ResponseDescription': 'Success. Check your phone for M-Pesa prompt.',
                'MerchantRequestID': payment_id,
                'CheckoutRequestID': payment_id,
                'LocationUrl': location_url
            }
        else:
            logger.error(f"❌ Kopo Kopo error: {response.text}")
            return {
                'ResponseCode': '1',
                'ResponseDescription': f"HTTP {response.status_code}: {response.text}"
            }
            
    except Exception as e:
        logger.error(f"STK Push exception: {str(e)}")
        return {
            'ResponseCode': '1',
            'ResponseDescription': str(e)
        }


def check_transaction_status(location_url):
    """Check status of a payment request using the location URL"""
    try:
        token = get_kopokopo_token()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(location_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Status check failed: {response.text}")
            return {'error': response.text}
    except Exception as e:
        logger.error(f"Status check exception: {str(e)}")
        return {'error': str(e)}


def check_pending_transaction(phone_number):
    """Check if there's a pending transaction for a phone number"""
    from finance.models import MpesaTransaction
    from django.utils import timezone
    from datetime import timedelta
    
    if not phone_number:
        return False
    
    cleaned_phone = clean_phone_number(phone_number)
    
    # Check for pending transactions in the last 10 minutes
    time_threshold = timezone.now() - timedelta(minutes=10)
    
    pending_exists = MpesaTransaction.objects.filter(
        phone_number=cleaned_phone,
        status='pending',
        created_at__gte=time_threshold
    ).exists()
    
    if pending_exists:
        logger.warning(f"Pending transaction found for {cleaned_phone}")
    
    return pending_exists


# ============================================
# WEBHOOK FOR DIRECT TILL PAYMENTS
# ============================================

@csrf_exempt
@require_http_methods(["POST"])
def kopokopo_webhook(request):
    """
    Handles incoming webhook notifications from Kopo Kopo for direct till payments.
    """
    try:
        # 1. Log the raw payload for debugging
        raw_body = request.body.decode('utf-8')
        logger.info(f"Received Kopo Kopo webhook. Raw body: {raw_body}")
        payload = json.loads(raw_body)

        # 2. Extract the relevant transaction data from the 'event' object
        # The structure is based on Kopo Kopo's official documentation [citation:4]
        event_data = payload.get('event', {})
        resource_data = event_data.get('resource', {})
        
        # These are the fields we need to find a sale and record payment
        transaction_status = resource_data.get('status')
        till_number = resource_data.get('till_number')
        amount = Decimal(resource_data.get('amount', '0'))
        sender_phone = resource_data.get('sender_phone_number', '')
        transaction_reference = resource_data.get('reference', '') # Kopo Kopo's reference
        # The 'metadata.reference' is what you set in the STK push, useful for direct payments too
        metadata = payload.get('metadata', {})
        your_reference = metadata.get('reference', '') 

        logger.info(f"Processed webhook data: Status={transaction_status}, Till={till_number}, Amount={amount}, YourRef={your_reference}")

        # 3. Verify the transaction is for your till and was successful
        if transaction_status != 'Received':
            logger.info(f"Ignoring non-successful transaction with status: {transaction_status}")
            return JsonResponse({"success": True, "message": "Transaction not yet received."})

        if till_number != config('KOPOKOPO_TILL_NUMBER', '5627132'): # Compare with your till number from env
            logger.warning(f"Ignoring transaction for a different till: {till_number}")
            return JsonResponse({"success": True, "message": "Ignored, not for this till."})

        # 4. Find the sale and update it
        from sales.models import Sale
        from finance.models import MpesaTransaction

        # Try to find the sale using the reference you set (from metadata)
        sale = None
        if your_reference:
            sale = Sale.objects.filter(sale_id=your_reference).first()
        
        # If not found, you could try searching by the sender's phone number or other logic
        if not sale:
            logger.warning(f"Sale not found for reference: {your_reference}")
            # Optional: Create a new sale or log for manual review
            return JsonResponse({"success": False, "error": "Sale not found"}, status=404)

        # 5. Record the payment
        if sale.amount_paid + amount > sale.total_amount:
            logger.warning(f"Payment amount {amount} exceeds remaining balance for sale {sale.sale_id}")
            return JsonResponse({"success": False, "error": "Payment exceeds total due"}, status=409)

        sale.amount_paid += amount
        if sale.amount_paid >= sale.total_amount:
            sale.payment_method = 'M-Pesa' # Mark as paid via M-Pesa
        sale.save(update_fields=['amount_paid', 'payment_method'])

        # Create an audit record for this transaction
        MpesaTransaction.objects.create(
            checkout_request_id=payload.get('id', ''),
            amount=amount,
            phone_number=sender_phone,
            account_reference=your_reference or transaction_reference,
            transaction_desc=f"Direct payment for Sale #{sale.sale_id}",
            sale=sale,
            status='completed'
        )
        logger.info(f"✅ Successfully recorded direct payment of {amount} for sale {sale.sale_id}")

        return JsonResponse({"success": True, "message": "Payment recorded successfully"})

    except json.JSONDecodeError:
        logger.error(f"Invalid JSON payload received: {request.body}")
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.exception(f"Error processing webhook: {str(e)}")
        return JsonResponse({"success": False, "error": "Internal server error"}, status=500)