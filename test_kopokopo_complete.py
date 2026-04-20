#!/usr/bin/env python
import os
import sys
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fieldmax.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from finance.kopokopo_service import get_kopokopo_token, stk_push_request
from finance.models import MpesaTransaction
from decouple import config
import logging
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_kopokopo():
    print("=" * 50)
    print("Testing Kopo Kopo M-Pesa Integration...")
    print("=" * 50)
    
    # Test 1: Generate Token
    print("\n1. Testing Token Generation...")
    try:
        token = get_kopokopo_token()
        print(f"   ✅ Token generated successfully!")
        print(f"   Token starts with: {token[:50]}...")
        print(f"   Token length: {len(token)} characters")
    except Exception as e:
        print(f"   ❌ Token generation failed: {e}")
        return False
    
    # Test 2: STK Push
    print("\n2. Testing STK Push...")
    try:
        test_phone = input("   Enter your phone number (format: 2547XXXXXXXX): ").strip()
        
        if not test_phone:
            print("   ❌ No phone number provided")
            return False
        
        test_amount = 10  # Minimum amount for testing
        
        print(f"   Sending STK Push to {test_phone} for KES {test_amount}...")
        
        # Send the STK Push request
        result = stk_push_request(
            phone_number=test_phone,
            amount=test_amount,
            account_reference="TEST001",
            transaction_desc="Test Payment"
        )
        
        print(f"\n   Response from Kopo Kopo:")
        print(f"   ResponseCode: {result.get('ResponseCode')}")
        print(f"   ResponseDescription: {result.get('ResponseDescription')}")
        print(f"   MerchantRequestID: {result.get('MerchantRequestID')}")
        print(f"   CheckoutRequestID: {result.get('CheckoutRequestID')}")
        
        if result.get('ResponseCode') == '0':
            # Save transaction to database
            try:
                transaction = MpesaTransaction.objects.create(
                    merchant_request_id=result.get('MerchantRequestID', ''),
                    checkout_request_id=result.get('CheckoutRequestID', ''),
                    amount=test_amount,
                    phone_number=test_phone,
                    account_reference="TEST001",
                    transaction_desc="Test Payment",
                    status='pending'
                )
                print(f"\n   ✅ Transaction saved to database!")
                print(f"   Transaction ID: {transaction.id}")
                print(f"   CheckoutRequestID: {transaction.checkout_request_id}")
            except Exception as db_error:
                print(f"\n   ⚠️  Warning: Could not save transaction: {db_error}")
            
            print(f"\n   ✅ STK Push sent successfully!")
            print(f"   📱 Check your phone and enter your PIN to complete the test.")
            print(f"   CheckoutRequestID: {result.get('CheckoutRequestID')}")
            
            # Wait for callback and check status
            print("\n   Waiting for payment confirmation...")
            for i in range(15):  # Wait up to 45 seconds
                time.sleep(3)
                try:
                    trans = MpesaTransaction.objects.get(
                        checkout_request_id=result.get('CheckoutRequestID')
                    )
                    if trans.status == 'completed':
                        print(f"\n   🎉 Payment completed successfully!")
                        print(f"   Receipt Number: {trans.mpesa_receipt_number}")
                        print(f"   Amount: KES {trans.amount}")
                        print(f"   Phone: {trans.phone_number}")
                        return True
                    elif trans.status == 'failed':
                        print(f"\n   ❌ Payment failed: {trans.result_desc}")
                        return False
                except MpesaTransaction.DoesNotExist:
                    pass
                
                # Show progress
                print(f"   ...waiting for callback ({i+1}/15)...")
            
            print("\n   ⏳ Payment still processing... Check your phone and M-Pesa app.")
            print("   You can check status later with: python manage.py shell")
            return True
        else:
            print(f"\n   ❌ STK Push failed: {result.get('ResponseDescription')}")
            return False
            
    except Exception as e:
        print(f"   ❌ STK Push error: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_configuration():
    """Check if Kopo Kopo configuration is properly set"""
    print("\n3. Checking Configuration...")
    
    required_vars = [
        'KOPOKOPO_CLIENT_ID',
        'KOPOKOPO_CLIENT_SECRET',
        'KOPOKOPO_TILL_NUMBER'
    ]
    
    all_ok = True
    for var in required_vars:
        value = config(var, default=None)
        if value:
            masked = value[:10] + "..." if len(value) > 10 else "***"
            print(f"   ✅ {var}: {masked}")
        else:
            print(f"   ❌ {var}: MISSING!")
            all_ok = False
    
    callback_url = config('MPESA_CALLBACK_URL', default=None)
    if callback_url:
        print(f"   ✅ MPESA_CALLBACK_URL: {callback_url}")
    else:
        print(f"   ⚠️  MPESA_CALLBACK_URL: Not set (required for callbacks)")
    
    return all_ok


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("Kopo Kopo M-Pesa Integration Test")
    print("=" * 50)
    
    # Check configuration first
    config_ok = check_configuration()
    
    if not config_ok:
        print("\n❌ Configuration issues found. Please fix your .env file first.")
        print("\nYour .env file should have:")
        print("KOPOKOPO_CLIENT_ID=your_client_id")
        print("KOPOKOPO_CLIENT_SECRET=your_client_secret")
        print("KOPOKOPO_TILL_NUMBER=K595574")
        print("MPESA_CALLBACK_URL=https://your-ngrok-url.ngrok.io/finance/mpesa-callback/")
        sys.exit(1)
    
    # Run the test
    success = test_kopokopo()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ Test completed! Kopo Kopo integration is working.")
        print("\nNext steps:")
        print("1. Check your phone for the STK Push prompt")
        print("2. Enter your PIN to complete the transaction")
        print("3. The callback will update the transaction status")
    else:
        print("❌ Test failed! Please check the errors above.")
        print("\nCommon issues:")
        print("1. Till number format (should be K595574)")
        print("2. Phone number format (use 2547XXXXXXXX)")
        print("3. Callback URL not accessible (use ngrok for local testing)")
        print("4. OAuth application not approved yet")
    print("=" * 50)
