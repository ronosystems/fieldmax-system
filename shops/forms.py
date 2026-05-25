# shops/forms.py
from django import forms
from django.forms import inlineformset_factory
from django.contrib.auth.models import User
from decimal import Decimal
from .models import (
    ShopBranch, MpesaAccount, MpesaDailyBalance, BankAccount, BankDailyBalance,
    CashAccount, CashDailyBalance, ShopExpense, DailyShopReport, 
    DailyMpesaAccountReport, ShopConfiguration, DynamicChoice, BankClosingBalance,
    MpesaAdjustment, MpesaAccount
)

# ==================== DYNAMIC CHOICES FORM ====================

class DynamicChoiceForm(forms.ModelForm):
    class Meta:
        model = DynamicChoice
        fields = ['choice_type', 'value']
        widgets = {
            'choice_type': forms.Select(attrs={'class': 'form-control'}),
            'value': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter choice value'}),
        }


# ==================== SHOP BRANCH FORMS ====================

class ShopBranchForm(forms.ModelForm):
    class Meta:
        model = ShopBranch
        fields = ['name', 'code', 'location', 'manager', 'phone', 'email', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Branch name'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Branch code'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Physical location'}),
            'manager': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Manager name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone number'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email address'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# ==================== MPESA ACCOUNT FORMS ====================

class MpesaAccountForm(forms.ModelForm):
    class Meta:
        model = MpesaAccount
        fields = [
            'shop', 'account_type', 'account_name', 'account_number', 
            'store_number', 'assigned_user', 'business_hours_start', 'business_hours_end'
        ]
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-control', 'required': True}),
            'account_type': forms.Select(attrs={'class': 'form-control', 'required': True}),
            'account_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Main Till', 'required': True}),
            'account_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., 123456', 'required': True}),
            'store_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., STORE001', 'required': True}),
            'assigned_user': forms.Select(attrs={'class': 'form-control'}),
            'business_hours_start': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'business_hours_end': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['shop'].queryset = ShopBranch.objects.filter(is_active=True)
        self.fields['assigned_user'].required = False
        self.fields['assigned_user'].empty_label = "-- Select User (Optional) --"
        self.fields['business_hours_start'].required = False
        self.fields['business_hours_end'].required = False
        self.fields['store_number'].required = True
        
        # If editing an existing account, filter assigned_user by the shop
        if self.instance and self.instance.pk and self.instance.shop:
            self.fields['assigned_user'].queryset = User.objects.filter(
                is_active=True,
                staff_profile__assigned_shop=self.instance.shop
            )
    
    def clean(self):
        cleaned_data = super().clean()
        shop = cleaned_data.get('shop')
        
        # When shop is selected, update the assigned_user queryset dynamically
        if shop and not self.instance.pk:
            self.fields['assigned_user'].queryset = User.objects.filter(
                is_active=True,
                staff_profile__assigned_shop=shop
            )
        
        return cleaned_data


class MpesaDailyBalanceForm(forms.ModelForm):
    class Meta:
        model = MpesaDailyBalance
        fields = [
            'opening_mpesa_float', 'opening_airtel_float', 'opening_cash',
            'closing_mpesa_float', 'closing_airtel_float', 'closing_cash',
            'total_deposits', 'total_withdrawals', 'transaction_count', 'notes'
        ]
        widgets = {
            'opening_mpesa_float': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'opening_airtel_float': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'opening_cash': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'closing_mpesa_float': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'closing_airtel_float': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'closing_cash': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'total_deposits': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'total_withdrawals': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'transaction_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].required = False


# ==================== BANK ACCOUNT FORMS ====================

class BankAccountForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get dynamic bank names from database
        bank_choices = DynamicChoice.objects.filter(choice_type='bank_name', is_active=True)
        if bank_choices.exists():
            self.fields['bank_name'] = forms.ChoiceField(
                choices=[('', '---------')] + [(c.value, c.value) for c in bank_choices],
                widget=forms.Select(attrs={'class': 'form-control'})
            )
        else:
            self.fields['bank_name'] = forms.CharField(
                max_length=100,
                widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter bank name'})
            )
    
    class Meta:
        model = BankAccount
        fields = ['shop', 'bank_name', 'account_name', 'account_number', 'opening_balance', 'is_active']
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-control'}),
            'account_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Account holder name'}),
            'account_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Account number'}),
            'opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class BankDailyBalanceForm(forms.ModelForm):
    class Meta:
        model = BankDailyBalance
        fields = ['opening_balance', 'closing_balance', 'total_deposits', 'total_withdrawals', 'transaction_count', 'notes']
        widgets = {
            'opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'closing_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'total_deposits': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'total_withdrawals': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'transaction_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].required = False


# ==================== CASH ACCOUNT FORMS ====================

class CashAccountForm(forms.ModelForm):
    class Meta:
        model = CashAccount
        fields = ['shop', 'account_name', 'currency', 'opening_balance', 'is_active']
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-control'}),
            'account_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Main Cash, Petty Cash'}),
            'currency': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'KES'}),
            'opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['shop'].queryset = ShopBranch.objects.filter(is_active=True)
        self.fields['currency'].initial = 'KES'
        self.fields['currency'].required = False


class CashDailyBalanceForm(forms.ModelForm):
    class Meta:
        model = CashDailyBalance
        fields = ['opening_balance', 'closing_balance', 'cash_in', 'cash_out', 'transaction_count', 'notes']
        widgets = {
            'opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'closing_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'cash_in': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'cash_out': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'transaction_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            self.fields[field].required = False


# ==================== SHOP EXPENSE FORM ====================

class ShopExpenseForm(forms.ModelForm):
    class Meta:
        model = ShopExpense
        fields = ['expense_category', 'description', 'amount', 'payment_method', 'mpesa_account', 'bank_account', 'cash_account', 'receipt_number']
        widgets = {
            'expense_category': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Category'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Description of expense'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control expense-amount', 'step': '0.01', 'placeholder': '0.00'}),
            'payment_method': forms.Select(attrs={'class': 'form-control', 'onchange': 'togglePaymentFields(this)'}),
            'mpesa_account': forms.Select(attrs={'class': 'form-control mpesa-select'}),
            'bank_account': forms.Select(attrs={'class': 'form-control bank-select'}),
            'cash_account': forms.Select(attrs={'class': 'form-control cash-select'}),
            'receipt_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Receipt number'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['expense_category'].required = False
        self.fields['mpesa_account'].required = False
        self.fields['bank_account'].required = False
        self.fields['cash_account'].required = False
        self.fields['receipt_number'].required = False
        
        # Set empty labels
        self.fields['mpesa_account'].empty_label = "-- Select M-Pesa Account --"
        self.fields['bank_account'].empty_label = "-- Select Bank Account --"
        self.fields['cash_account'].empty_label = "-- Select Cash Account --"


# ==================== DAILY SHOP REPORT FORM ====================

class DailyShopReportForm(forms.ModelForm):
    class Meta:
        model = DailyShopReport
        fields = ['shop', 'report_date', 'total_mpesa_transactions', 'total_mpesa_amount', 'notes']
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-control'}),
            'report_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'total_mpesa_transactions': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'placeholder': 'Number of transactions'}),
            'total_mpesa_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Any additional notes...'}),
        }
    
    def clean_total_mpesa_transactions(self):
        value = self.cleaned_data.get('total_mpesa_transactions')
        if value and value < 0:
            raise forms.ValidationError("Transaction count cannot be negative.")
        return value
    
    def clean_total_mpesa_amount(self):
        value = self.cleaned_data.get('total_mpesa_amount')
        if value and value < 0:
            raise forms.ValidationError("Amount cannot be negative.")
        return value
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['shop'].queryset = ShopBranch.objects.filter(is_active=True)
        self.fields['total_mpesa_transactions'].required = False
        self.fields['total_mpesa_amount'].required = False
        self.fields['notes'].required = False
        
        # Set help texts
        self.fields['total_mpesa_transactions'].help_text = "Total number of M-Pesa transactions today"
        self.fields['total_mpesa_amount'].help_text = "Total amount of M-Pesa transactions today"


# ==================== DAILY MPESA ACCOUNT REPORT FORM ====================

class DailyMpesaAccountReportForm(forms.ModelForm):
    class Meta:
        model = DailyMpesaAccountReport
        fields = ['mpesa_account', 'closing_mpesa_float', 'closing_airtel_float', 'closing_cash', 'transaction_count', 'total_amount', 'notes']
        widgets = {
            'mpesa_account': forms.Select(attrs={'class': 'form-control mpesa-select'}),
            'closing_mpesa_float': forms.NumberInput(attrs={'class': 'form-control mpesa-balance', 'step': '0.01', 'placeholder': '0.00'}),
            'closing_airtel_float': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'closing_cash': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'transaction_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'total_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['mpesa_account'].queryset = MpesaAccount.objects.filter(is_active=True)
        self.fields['closing_mpesa_float'].required = False
        self.fields['closing_airtel_float'].required = False
        self.fields['closing_cash'].required = False
        self.fields['transaction_count'].required = False
        self.fields['total_amount'].required = False
        self.fields['notes'].required = False


# ==================== SHOP CONFIGURATION FORM ====================

class ShopConfigurationForm(forms.ModelForm):
    class Meta:
        model = ShopConfiguration
        fields = ['shop', 'config_type', 'config_key', 'config_value', 'description']
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-control'}),
            'config_type': forms.Select(attrs={'class': 'form-control'}),
            'config_key': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Configuration key'}),
            'config_value': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Configuration value'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Description'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['shop'].queryset = ShopBranch.objects.filter(is_active=True)
        self.fields['description'].required = False


# ==================== LEGACY/COMPATIBILITY FORMS ====================

class BankClosingBalanceForm(forms.ModelForm):
    """Legacy form for bank closing balances"""
    class Meta:
        model = BankClosingBalance
        fields = ['bank_account', 'closing_balance']
        widgets = {
            'bank_account': forms.Select(attrs={'class': 'form-control bank-select'}),
            'closing_balance': forms.NumberInput(attrs={'class': 'form-control bank-balance', 'step': '0.01', 'placeholder': '0.00'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bank_account'].required = False
        self.fields['closing_balance'].required = False
        self.fields['bank_account'].empty_label = "-- Select Bank Account --"


# ==================== FORMSETS ====================

# Bank Closing FormSet (for dynamic bank entries in daily report)
BankClosingFormSet = inlineformset_factory(
    DailyShopReport,
    BankClosingBalance,
    form=BankClosingBalanceForm,
    fields=['bank_account', 'closing_balance'],
    extra=1,
    can_delete=True,
    can_delete_extra=True,
    min_num=0,
    validate_min=False
)

# Expense FormSet (for dynamic expense entries in daily report)
ExpenseFormSet = inlineformset_factory(
    DailyShopReport,
    ShopExpense,
    form=ShopExpenseForm,
    fields=['expense_category', 'description', 'amount', 'payment_method'],
    extra=1,
    can_delete=True,
    can_delete_extra=True,
    min_num=0,
    validate_min=False
)

# M-Pesa Account Report FormSet (for dynamic M-Pesa account entries in daily report)
MpesaAccountReportFormSet = inlineformset_factory(
    DailyShopReport,
    DailyMpesaAccountReport,
    form=DailyMpesaAccountReportForm,
    fields=['mpesa_account', 'closing_mpesa_float', 'closing_airtel_float', 'closing_cash', 'notes'],
    extra=1,
    can_delete=True,
    can_delete_extra=True,
    min_num=0,
    validate_min=False
)


# ==================== HELPER FUNCTIONS ====================

def get_payment_method_choices():
    """Get payment method choices from dynamic choices"""
    payment_methods = DynamicChoice.objects.filter(choice_type='payment_method', is_active=True)
    if payment_methods.exists():
        return [(c.value, c.value) for c in payment_methods]
    return [
        ('cash', 'Cash'),
        ('mpesa', 'M-Pesa'),
        ('bank', 'Bank Transfer'),
        ('cheque', 'Cheque'),
    ]


def get_expense_category_choices():
    """Get expense category choices from dynamic choices"""
    categories = DynamicChoice.objects.filter(choice_type='expense_category', is_active=True)
    if categories.exists():
        return [(c.value, c.value) for c in categories]
    return [
        ('utilities', 'Utilities'),
        ('rent', 'Rent'),
        ('salaries', 'Salaries'),
        ('supplies', 'Office Supplies'),
        ('maintenance', 'Maintenance'),
        ('transport', 'Transport'),
        ('other', 'Other'),
    ]

# shops/forms.py

from django import forms
from .models import AccountTransaction, MpesaAccount, BankAccount, CashAccount, ShopBranch

class AccountInjectionForm(forms.ModelForm):
    class Meta:
        model = AccountTransaction
        fields = ['account_type', 'mpesa_account', 'bank_account', 'cash_account', 'amount', 'reference_number', 'reason', 'notes']
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Explain why this injection is needed...'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Additional notes (optional)'}),
            'reference_number': forms.TextInput(attrs={'placeholder': 'Receipt/Reference number (optional)'}),
        }
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Set account type choices
        self.fields['account_type'].choices = [
            ('mpesa', 'M-Pesa Account'),
            ('bank', 'Bank Account'),
            ('cash', 'Cash Account'),
        ]
        
        # Initialize empty querysets
        self.fields['mpesa_account'].queryset = MpesaAccount.objects.none()
        self.fields['bank_account'].queryset = BankAccount.objects.none()
        self.fields['cash_account'].queryset = CashAccount.objects.none()
        
        # If user is not superuser, restrict to their shop
        if user and not user.is_superuser:
            if hasattr(user, 'staff_profile') and user.staff_profile:
                assigned_shop = user.staff_profile.assigned_shop
                self.fields['mpesa_account'].queryset = MpesaAccount.objects.filter(
                    shop=assigned_shop, is_active=True, status='active'
                )
                self.fields['bank_account'].queryset = BankAccount.objects.filter(
                    shop=assigned_shop, is_active=True
                )
                self.fields['cash_account'].queryset = CashAccount.objects.filter(
                    shop=assigned_shop, is_active=True
                )
        else:
            # For superuser, show all
            self.fields['mpesa_account'].queryset = MpesaAccount.objects.filter(is_active=True, status='active')
            self.fields['bank_account'].queryset = BankAccount.objects.filter(is_active=True)
            self.fields['cash_account'].queryset = CashAccount.objects.filter(is_active=True)
        
        # Add shop filter for superuser
        if user and user.is_superuser:
            self.fields['shop_filter'] = forms.ModelChoiceField(
                queryset=ShopBranch.objects.filter(is_active=True),
                required=False,
                label="Filter by Shop (Optional)"
            )
    
    def clean(self):
        cleaned_data = super().clean()
        account_type = cleaned_data.get('account_type')
        amount = cleaned_data.get('amount')
        
        if amount and amount <= 0:
            self.add_error('amount', 'Amount must be greater than 0')
        
        return cleaned_data

class MpesaAdjustmentForm(forms.ModelForm):
    class Meta:
        model = MpesaAdjustment
        fields = ['mpesa_account', 'adjustment_type', 'amount', 'reference_number', 'reason', 'notes']
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Explain why this adjustment is needed...'}),
            'notes': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Additional notes (optional)'}),
            'reference_number': forms.TextInput(attrs={'placeholder': 'Receipt/Reference number (optional)'}),
        }
    
    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        adjustment_type = self.cleaned_data.get('adjustment_type')
        mpesa_account = self.cleaned_data.get('mpesa_account')
        
        if adjustment_type == 'withdrawal' and mpesa_account:
            if amount > mpesa_account.current_balance:
                raise forms.ValidationError(
                    f'Cannot withdraw KES {amount}. Current balance is KES {mpesa_account.current_balance:,.2f}'
                )
        return amount
    
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if user and not user.is_superuser:
            # Limit to user's assigned shop's M-Pesa accounts
            if hasattr(user, 'staff_profile') and user.staff_profile:
                assigned_shop = user.staff_profile.assigned_shop
                self.fields['mpesa_account'].queryset = MpesaAccount.objects.filter(
                    shop=assigned_shop,
                    is_active=True,
                    status='active'
                )