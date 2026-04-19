# shops/forms.py - Improved version with a few enhancements

from django import forms
from django.forms import inlineformset_factory
from .models import (
    ShopBranch, BankAccount, MpesaAccount, DailyShopReport, 
    BankClosingBalance, ShopExpense, MpesaDailySummary, DynamicChoice
)
from decimal import Decimal

class DynamicChoiceForm(forms.ModelForm):
    class Meta:
        model = DynamicChoice
        fields = ['choice_type', 'value']
        widgets = {
            'choice_type': forms.Select(attrs={'class': 'form-control'}),
            'value': forms.TextInput(attrs={'class': 'form-control'}),
        }

class ShopBranchForm(forms.ModelForm):
    class Meta:
        model = ShopBranch
        fields = ['name', 'code', 'location', 'manager', 'phone', 'email', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'manager': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

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
            'account_name': forms.TextInput(attrs={'class': 'form-control'}),
            'account_number': forms.TextInput(attrs={'class': 'form-control'}),
            'opening_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class MpesaAccountForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Get dynamic M-Pesa account types from database
        account_type_choices = DynamicChoice.objects.filter(choice_type='mpesa_account_type', is_active=True)
        if account_type_choices.exists():
            self.fields['account_type'] = forms.ChoiceField(
                choices=[('', '---------')] + [(c.value, c.value) for c in account_type_choices],
                widget=forms.Select(attrs={'class': 'form-control'})
            )
        else:
            self.fields['account_type'] = forms.CharField(
                max_length=50,
                widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Till, Paybill, Agent'})
            )
    
    class Meta:
        model = MpesaAccount
        fields = ['shop', 'account_name', 'account_number', 'account_type', 'phone_number', 'is_active']
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-control'}),
            'account_name': forms.TextInput(attrs={'class': 'form-control'}),
            'account_number': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '0712345678'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class DailyShopReportForm(forms.ModelForm):
    class Meta:
        model = DailyShopReport
        fields = ['shop', 'report_date', 'closing_mpesa_float', 'closing_mpesa_cash', 'closing_airtel_float', 'shop_sales', 'notes']
        widgets = {
            'shop': forms.Select(attrs={'class': 'form-control'}),
            'report_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'closing_mpesa_float': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'closing_airtel_float': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}), 
            'closing_mpesa_cash': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'shop_sales': forms.NumberInput(attrs={'class': 'form-control', 'step': '1', 'placeholder': 'Number of transactions (e.g., 50)'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Any additional notes...'}),
        }
        labels = {
            'closing_mpesa_float': 'Closing M-Pesa Float (KES)',
            'closing_mpesa_cash': 'Closing M-Pesa Cash (KES)',
            'closing_airtel_float': 'Closing Airtel Float (KES)',
            'shop_sales': 'Total M-Pesa Transactions (Count)',
        }
    
    def clean_shop_sales(self):
        shop_sales = self.cleaned_data.get('shop_sales')
        if shop_sales is not None:
            # Ensure it's a whole number (transaction count)
            if shop_sales < 0:
                raise forms.ValidationError("Transaction count cannot be negative.")
            if shop_sales > 10000:
                raise forms.ValidationError("Transaction count seems too high. Please verify.")
        return shop_sales
    
    def clean(self):
        cleaned_data = super().clean()
        # Optional: Add validation to ensure at least one balance is entered
        mpesa_float = cleaned_data.get('closing_mpesa_float', 0) or 0
        mpesa_cash = cleaned_data.get('closing_mpesa_cash', 0) or 0
        airtel_float = cleaned_data.get('closing_airtel_float', 0) or 0
        
        # You can add a warning if all balances are zero
        if mpesa_float == 0 and mpesa_cash == 0 and airtel_float == 0:
            # This is just a warning, not an error - so don't raise ValidationError
            # You could add a message to forms using add_error if needed
            pass
        
        return cleaned_data
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['shop'].queryset = ShopBranch.objects.filter(is_active=True)
        self.fields['closing_mpesa_float'].required = False
        self.fields['closing_mpesa_cash'].required = False
        self.fields['closing_airtel_float'].required = False  # Make sure this is optional too
        self.fields['shop_sales'].required = False
        
        # Add help texts for clarity
        self.fields['closing_mpesa_float'].help_text = "M-Pesa float balance at closing time"
        self.fields['closing_mpesa_cash'].help_text = "Physical cash from M-Pesa cash-out"
        self.fields['closing_airtel_float'].help_text = "Airtel Money float balance at closing time"
        self.fields['shop_sales'].help_text = "Total number of M-Pesa transactions today"

class ShopExpenseForm(forms.ModelForm):
    class Meta:
        model = ShopExpense
        fields = ['description', 'amount'] 
        widgets = {
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Description of expense'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control expense-amount', 'step': '0.01', 'placeholder': '0.00'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make fields optional
        self.fields['description'].required = False
        self.fields['amount'].required = False

class BankClosingBalanceForm(forms.ModelForm):
    class Meta:
        model = BankClosingBalance
        fields = ['bank_account', 'closing_balance']
        widgets = {
            'bank_account': forms.Select(attrs={'class': 'form-control bank-select'}),
            'closing_balance': forms.NumberInput(attrs={'class': 'form-control bank-balance', 'step': '0.01', 'placeholder': '0.00'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make bank account fields optional
        self.fields['bank_account'].required = False
        self.fields['closing_balance'].required = False
        self.fields['bank_account'].empty_label = "-- Select Bank Account --"

class MpesaDailySummaryForm(forms.ModelForm):
    class Meta:
        model = MpesaDailySummary
        fields = ['opening_float', 'opening_cash', 'expected_float', 'expected_cash', 'notes']
        widgets = {
            'opening_float': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'opening_cash': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'expected_float': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'expected_cash': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Reconciliation notes...'}),
        }

# FormSets remain the same - they look good
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

ExpenseFormSet = inlineformset_factory(
    DailyShopReport, 
    ShopExpense,
    form=ShopExpenseForm,
    fields=['description', 'amount'],
    extra=1, 
    can_delete=True,
    can_delete_extra=True,
    min_num=0,
    validate_min=False
)