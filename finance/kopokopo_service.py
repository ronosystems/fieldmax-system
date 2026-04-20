# finance/kopokopo_service.py - UPDATED VERSION

import requests
import base64
from decouple import config
from django.core.cache import cache
import logging

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
        # Get token from Kopo Kopo
        response = requests.post(
            "https://api.kopokopo.com/oauth/token",
            headers={"Authorization": f"Basic {auth}"},
            data={"grant_type": "client_credentials"},
            timeout=30
        )
        
        logger.info(f"Kopo Kopo token response status: {response.status_code}")
        
        if response.status_code == 200:
            token = response.json().get('access_token')
            cache.set('kopokopo_token', token, 3480)
            logger.info("✅ Kopo Kopo token obtained successfully")
            return token
        else:
            logger.error(f"❌ Kopo Kopo auth failed: {response.status_code} - {response.text}")
            raise Exception(f"Kopo Kopo auth failed: {response.text}")
            
    except Exception as e:
        logger.error(f"Kopo Kopo token error: {str(e)}")
        raise


def clean_phone_number(phone):
    """Clean phone number to format 254XXXXXXXXX"""
    if not phone:
        return ''
    
    # Remove all non-digit characters
    phone = ''.join(filter(str.isdigit, str(phone)))
    
    # If starts with 0 (local format like 0722...)
    if phone.startswith('0') and len(phone) == 10:
        return '254' + phone[1:]
    
    # If starts with 254 and is 12 digits
    if phone.startswith('254') and len(phone) == 12:
        return phone
    
    # If it's 9 digits (like 722...), add 254
    if len(phone) == 9:
        return '254' + phone
    
    return phone


def stk_push_request(phone_number, amount, account_reference, transaction_desc):
    """Initiate STK Push payment via Kopo Kopo"""
    try:
        token = get_kopokopo_token()
        
        # Clean phone number
        phone_number = clean_phone_number(phone_number)
        
        # Get configuration from env
        till_number = config('KOPOKOPO_TILL_NUMBER')
        callback_url = config('MPESA_CALLBACK_URL')
        
        # Prepare request - FIXED ENDPOINT
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.kopokopo.v2+json"  # Add this
        }
        
        payload = {
            "payment_channel": "M-PESA",
            "till_number": till_number,
            "first_name": "Customer",
            "last_name": "Payment",
            "phone_number": phone_number,
            "amount": str(int(amount)),
            "currency": "KES",
            "email": f"payment_{account_reference}@fieldmax.shop",
            "callback_url": callback_url,
            "metadata": {
                "account_reference": account_reference,
                "transaction_desc": transaction_desc
            }
        }
        
        logger.info(f"Sending Kopo Kopo STK Push: Amount={amount}, Phone={phone_number}, Till={till_number}")
        
        # CORRECT Kopo Kopo API endpoint
        response = requests.post(
            "https://api.kopokopo.com/api/v1/merchants/tills/payment_requests",
            headers=headers,
            json=payload,
            timeout=60
        )
        
        logger.info(f"Kopo Kopo response status: {response.status_code}")
        logger.info(f"Kopo Kopo response body: {response.text}")
        
        if response.status_code == 201:
            data = response.json()
            payment_id = data.get('id')
            logger.info(f"✅ STK Push sent successfully. Payment ID: {payment_id}")
            return {
                'ResponseCode': '0',
                'ResponseDescription': 'Success. Request accepted for processing',
                'MerchantRequestID': payment_id,
                'CheckoutRequestID': payment_id,
            }
        else:
            logger.error(f"❌ Kopo Kopo error: {response.text}")
            return {
                'ResponseCode': '1',
                'ResponseDescription': f"Kopo Kopo error: {response.text}"
            }
            
    except Exception as e:
        logger.error(f"STK Push exception: {str(e)}")
        return {
            'ResponseCode': '1',
            'ResponseDescription': str(e)
        }


def check_transaction_status(payment_request_id):
    """Check status of a payment request"""
    try:
        token = get_kopokopo_token()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        response = requests.get(
            f"https://api.kopokopo.com/api/v1/merchants/tills/payment_requests/{payment_request_id}",
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Status check failed: {response.text}")
            return {'error': response.text}
            
    except Exception as e:
        logger.error(f"Status check exception: {str(e)}")
        return {'error': str(e)}