# finance/services.py
import base64
import requests
import datetime
from decouple import config
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)


def get_mpesa_base_url():
    """Get the correct API URL based on environment"""
    if config('MPESA_ENVIRONMENT', default='sandbox') == 'production':
        return 'https://api.safaricom.co.ke'
    return 'https://sandbox.safaricom.co.ke'


def generate_access_token():
    """Generate M-Pesa access token"""
    consumer_key = config('MPESA_CONSUMER_KEY')
    consumer_secret = config('MPESA_CONSUMER_SECRET')
    base_url = get_mpesa_base_url()
    api_url = f"{base_url}/oauth/v1/generate?grant_type=client_credentials"
    
    # Check cache first (token lasts 1 hour)
    cached_token = cache.get('mpesa_access_token')
    if cached_token:
        return cached_token
    
    encoded_credentials = base64.b64encode(
        f"{consumer_key}:{consumer_secret}".encode()
    ).decode()
    
    headers = {"Authorization": f"Basic {encoded_credentials}"}
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if 'access_token' not in data:
            raise Exception(f"Invalid response: {data}")
        
        access_token = data['access_token']
        cache.set('mpesa_access_token', access_token, 3300)
        return access_token
        
    except requests.exceptions.RequestException as e:
        logger.error(f"M-Pesa token generation failed: {str(e)}")
        raise Exception(f"Failed to connect to M-Pesa: {str(e)}")


def generate_password():
    """Generate password for STK push"""
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    shortcode = config('MPESA_SHORTCODE')
    passkey = config('MPESA_PASSKEY')
    password_str = f"{shortcode}{passkey}{timestamp}"
    return base64.b64encode(password_str.encode()).decode()


def get_timestamp():
    return datetime.datetime.now().strftime('%Y%m%d%H%M%S')


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
    """Initiate STK Push payment"""
    try:
        access_token = generate_access_token()
        api_url = "https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        # Clean phone number
        phone_number = clean_phone_number(phone_number)
        
        # Get callback URL
        callback_url = config('MPESA_CALLBACK_URL', 'https://fieldmax.shop/finance/mpesa-callback/')
        shortcode = config('MPESA_SHORTCODE')
        passkey = config('MPESA_PASSKEY')
        
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        password = base64.b64encode(f"{shortcode}{passkey}{timestamp}".encode()).decode()
        
        request_data = {
            "BusinessShortCode": shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": str(int(amount)),
            "PartyA": phone_number,
            "PartyB": shortcode,
            "PhoneNumber": phone_number,
            "CallBackURL": callback_url,
            "AccountReference": account_reference[:12],
            "TransactionDesc": transaction_desc[:13]
        }
        
        logger.info(f"Sending STK Push request: {request_data}")
        
        response = requests.post(api_url, json=request_data, headers=headers, timeout=30)
        
        logger.info(f"STK Push response status: {response.status_code}")
        logger.info(f"STK Push response body: {response.text}")
        
        if response.status_code == 200:
            return response.json()
        else:
            return {
                'ResponseCode': '1',
                'ResponseDescription': f'HTTP {response.status_code}: {response.text}'
            }
            
    except Exception as e:
        logger.error(f"STK Push exception: {str(e)}")
        return {
            'ResponseCode': '1',
            'ResponseDescription': str(e)
        }


def check_transaction_status(checkout_request_id):
    """Check status of an STK Push transaction"""
    access_token = generate_access_token()
    base_url = get_mpesa_base_url()
    api_url = f"{base_url}/mpesa/stkpushquery/v1/query"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    request_data = {
        "BusinessShortCode": config('MPESA_SHORTCODE'),
        "Password": generate_password(),
        "Timestamp": get_timestamp(),
        "CheckoutRequestID": checkout_request_id
    }
    
    try:
        response = requests.post(api_url, json=request_data, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Status check failed: {str(e)}")
        return {'error': str(e)}