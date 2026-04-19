#!/usr/bin/env python
import os
import sys
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fieldmax.settings')

# Add the current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Setup Django
django.setup()

from finance.services import generate_access_token, stk_push_request
from decouple import config
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_mpesa():
    print("=" * 50)
    print("Testing M-Pesa Connection...")
    print("=" * 50)
    
    # Test 1: Generate Token
    print("\n1. Testing Token Generation...")
    try:
        token = generate_access_token()
        print(f"   ✅ Token generated successfully!")
        print(f"   Token starts with: {token[:50]}...")
        print(f"   Token length: {len(token)} characters")
    except Exception as e:
        print(f"   ❌ Token generation failed: {e}")
        return False
    
    # Test 2: STK Push
    print("\n2. Testing STK Push...")
    try:
        # IMPORTANT: Replace with YOUR phone number in format 2547XXXXXXXX
        test_phone = input("   Enter your phone number (format: 2547XXXXXXXX): ").strip()
        
        if not test_phone:
            print("   ❌ No phone number provided")
            return False
        
        test_amount = 10  # Minimum amount for testing
        
        print(f"   Sending STK Push to {test_phone} for KES {test_amount}...")
        
        # ============================================
        # ADD THIS SECTION - Save transaction BEFORE sending STK Push
        # ============================================
        from finance.models import MpesaTransaction
        
        # First, send the STK Push request
        result = stk_push_request(
            phone_number=test_phone,
            amount=test_amount,
            account_reference="TEST001",
            transaction_desc="Test Payment"
        )
        
        print(f"\n   Response from M-Pesa:")
        print(f"   ResponseCode: {result.get('ResponseCode')}")
        print(f"   ResponseDescription: {result.get('ResponseDescription')}")
        print(f"   MerchantRequestID: {result.get('MerchantRequestID')}")
        print(f"   CheckoutRequestID: {result.get('CheckoutRequestID')}")
        
        if result.get('ResponseCode') == '0':
            # ============================================
            # ADD THIS - Save transaction to database
            # ============================================
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
            
            # ============================================
            # ADD THIS - Wait for callback and check status
            # ============================================
            print("\n   Waiting for payment confirmation...")
            import time
            for i in range(10):  # Wait up to 30 seconds
                time.sleep(3)
                # Check if transaction was completed
                try:
                    trans = MpesaTransaction.objects.get(
                        checkout_request_id=result.get('CheckoutRequestID')
                    )
                    if trans.status == 'completed':
                        print(f"\n   🎉 Payment completed successfully!")
                        print(f"   Receipt Number: {trans.mpesa_receipt_number}")
                        print(f"   Amount: KES {trans.amount}")
                        break
                    elif trans.status == 'failed':
                        print(f"\n   ❌ Payment failed: {trans.result_desc}")
                        break
                except MpesaTransaction.DoesNotExist:
                    pass
            else:
                print("\n   ⏳ Payment still processing... Check your phone and M-Pesa app.")
            
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
    """Check if M-Pesa configuration is properly set"""
    print("\n3. Checking Configuration...")
    
    required_vars = [
        'MPESA_CONSUMER_KEY',
        'MPESA_CONSUMER_SECRET', 
        'MPESA_SHORTCODE',
        'MPESA_PASSKEY'
    ]
    
    all_ok = True
    for var in required_vars:
        value = config(var, default=None)
        if value:
            # Mask the value for display
            masked = value[:10] + "..." if len(value) > 10 else "***"
            print(f"   ✅ {var}: {masked}")
        else:
            print(f"   ❌ {var}: MISSING!")
            all_ok = False
    
    callback_url = config('MPESA_CALLBACK_URL', default=None)
    if callback_url:
        print(f"   ✅ MPESA_CALLBACK_URL: {callback_url}")
    else:
        print(f"   ⚠️  MPESA_CALLBACK_URL: Not set (required for production)")
    
    return all_ok

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("M-Pesa Integration Test")
    print("=" * 50)
    
    # Check configuration first
    config_ok = check_configuration()
    
    if not config_ok:
        print("\n❌ Configuration issues found. Please fix your .env file first.")
        print("\nYour .env file should have:")
        print("MPESA_CONSUMER_KEY=your_key_here")
        print("MPESA_CONSUMER_SECRET=your_secret_here")
        print("MPESA_SHORTCODE=174379  # Use test shortcode")
        print("MPESA_PASSKEY=bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919")
        sys.exit(1)
    
    # Run the test
    success = test_mpesa()
    
    print("\n" + "=" * 50)
    if success:
        print("✅ Test completed! M-Pesa integration is working.")
        print("\nNext steps:")
        print("1. Check your phone for the STK Push prompt")
        print("2. Enter your PIN to complete the transaction")
        print("3. The callback should be received at your ngrok URL")
    else:
        print("❌ Test failed! Please check the errors above.")
        print("\nCommon issues:")
        print("1. Wrong shortcode (use 174379 for sandbox)")
        print("2. Invalid passkey")
        print("3. Wrong phone number format (use 2547XXXXXXXX)")
        print("4. Network connectivity issues")
    print("=" * 50)
