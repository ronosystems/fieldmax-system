# finance/kopokopo_service.py - CORRECT VERSION
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
    Based on official documentation: https://developers.kopokopo.com/guides/receive-money/mpesa-stk.html [citation:1]
    """
    try:
        # Clean phone number to format +254XXXXXXXXX
        phone_number = clean_phone_number(phone_number)
        
        # Get configuration
        till_number = config('KOPOKOPO_TILL_NUMBER')
        callback_url = config('MPESA_CALLBACK_URL')
        
        # Ensure till number has K prefix as per docs [citation:1]
        if not till_number.startswith('K'):
            till_number = f"K{till_number}"
        
        # Get token
        token = get_kopokopo_token()
        
        # CORRECT headers as per Kopo Kopo docs [citation:1]
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        # CORRECT payload structure from official documentation [citation:1]
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
        logger.info(f"Payload: {payload}")
        
        # CORRECT endpoint [citation:1]
        response = requests.post(
            "https://api.kopokopo.com/api/v1/incoming_payments",
            headers=headers,
            json=payload,
            timeout=60
        )
        
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response body: {response.text}")
        
        # Expected: 201 Created with Location header [citation:1]
        if response.status_code == 201:
            location_url = response.headers.get('Location', '')
            payment_id = location_url.split('/')[-1] if location_url else None
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
                'ResponseDescription': f"Error: {response.text}"
            }
            
    except Exception as e:
        logger.error(f"STK Push exception: {str(e)}")
        return {
            'ResponseCode': '1',
            'ResponseDescription': str(e)
        }


def check_transaction_status(location_url):
    """Check status of a payment request using the location URL [citation:3]"""
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