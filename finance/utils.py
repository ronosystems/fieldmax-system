# finance/utils.py
from decimal import Decimal
from django.db.models import Sum, Q, F, DecimalField
from django.utils import timezone
from datetime import timedelta
from sales.models import Sale, SaleItem
from inventory.models import StockEntry, Product
from finance.models import Salary, FinancialTransaction, AccountTransaction
from credit.models import SellerCommission, CreditTransaction
from django.db import models

class UnifiedFinanceCalculator:
    """Unified calculator for all financial metrics across the system"""
    
    @staticmethod
    def calculate_revenue(start_date=None, end_date=None, shop=None):
        """Calculate total revenue from sales (excludes reversed/returned sales)"""
        from inventory.models import ReturnRequest
        
        # Get returned sale IDs to exclude
        returned_sale_ids = ReturnRequest.objects.filter(
            ~models.Q(status='rejected')
        ).exclude(
            models.Q(sale_id__isnull=True) | models.Q(sale_id='')
        ).values_list('sale_id', flat=True).distinct()
        
        # Base queryset
        sales = Sale.objects.filter(is_reversed=False)
        
        # Exclude returned sales
        if returned_sale_ids:
            sales = sales.exclude(sale_id__in=returned_sale_ids)
        
        # Apply filters
        if start_date:
            sales = sales.filter(sale_date__date__gte=start_date)
        if end_date:
            sales = sales.filter(sale_date__date__lte=end_date)
        if shop:
            sales = sales.filter(shop=shop)
        
        return sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    @staticmethod
    def calculate_cogs(start_date=None, end_date=None, shop=None):
        """
        Calculate Cost of Goods Sold (COGS) - ONLY for items ACTUALLY SOLD
        This should NOT include inventory purchases that are still in stock
        """
        # Get stock entries for sales only (items that were sold)
        stock_entries = StockEntry.objects.filter(
            entry_type='sale',
            quantity__lt=0  # Negative quantity for sales
        )
        
        # Apply date filters
        if start_date:
            stock_entries = stock_entries.filter(created_at__date__gte=start_date)
        if end_date:
            stock_entries = stock_entries.filter(created_at__date__lte=end_date)
        
        # Calculate COGS - only the cost of items sold
        cogs = Decimal('0.00')
        for entry in stock_entries:
            cogs += abs(entry.quantity) * entry.unit_price
        
        return cogs
    
    @staticmethod
    def calculate_inventory_purchases(start_date=None, end_date=None):
        """
        Calculate total inventory purchases (this is an ASSET, not an expense)
        This should NOT be deducted from profit
        """
        purchases = StockEntry.objects.filter(
            entry_type='purchase',
            quantity__gt=0  # Positive quantity for purchases
        )
        
        if start_date:
            purchases = purchases.filter(created_at__date__gte=start_date)
        if end_date:
            purchases = purchases.filter(created_at__date__lte=end_date)
        
        total_purchases = Decimal('0.00')
        for entry in purchases:
            total_purchases += entry.quantity * entry.unit_price
        
        return total_purchases
    
    @staticmethod
    def calculate_salary_expenses(start_date=None, end_date=None):
        """Calculate salary expenses"""
        salaries = Salary.objects.filter(status='paid')
        
        if start_date:
            salaries = salaries.filter(paid_date__date__gte=start_date)
        if end_date:
            salaries = salaries.filter(paid_date__date__lte=end_date)
        
        return salaries.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    
    @staticmethod
    def calculate_commission_expenses(start_date=None, end_date=None):
        """Calculate commission expenses"""
        commissions = SellerCommission.objects.filter(status='paid')
        
        if start_date:
            commissions = commissions.filter(paid_date__date__gte=start_date)
        if end_date:
            commissions = commissions.filter(paid_date__date__lte=end_date)
        
        return commissions.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    @staticmethod
    def calculate_operational_expenses(start_date=None, end_date=None):
        """
        Calculate operational expenses (rent, utilities, etc.)
        IMPORTANT: Do NOT include inventory purchases here!
        """
        from finance.models import AccountTransaction
        
        # First, get all expense transactions
        expenses = AccountTransaction.objects.filter(
            transaction_type='expense',
            account_type__in=['cash', 'bank']
        )
        
        # Apply date filters
        if start_date:
            expenses = expenses.filter(transaction_date__date__gte=start_date)
        if end_date:
            expenses = expenses.filter(transaction_date__date__lte=end_date)
        
        # Now filter out inventory-related transactions by checking description and reference
        inventory_keywords = [
            'stock', 'inventory', 'purchase', 'buying', 'restock',
            'supplier', 'wholesale', 'bulk', 'PO-', 'INV-'
        ]
        
        # Build exclusion filter
        exclusion_filter = Q()
        for keyword in inventory_keywords:
            exclusion_filter |= Q(description__icontains=keyword)
            exclusion_filter |= Q(reference__icontains=keyword)
            exclusion_filter |= Q(notes__icontains=keyword)
        
        # Exclude inventory purchases
        expenses = expenses.exclude(exclusion_filter)
        
        return expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    @staticmethod
    def calculate_total_expenses(start_date=None, end_date=None):
        """
        Calculate total OPERATING expenses (salaries + commissions + operational)
        Does NOT include inventory purchases (they are assets)
        """
        salaries = UnifiedFinanceCalculator.calculate_salary_expenses(start_date, end_date)
        commissions = UnifiedFinanceCalculator.calculate_commission_expenses(start_date, end_date)
        operational = UnifiedFinanceCalculator.calculate_operational_expenses(start_date, end_date)
        
        return salaries + commissions + operational
    
    @staticmethod
    def calculate_gross_profit(start_date=None, end_date=None, shop=None):
        """Gross Profit = Revenue - COGS"""
        revenue = UnifiedFinanceCalculator.calculate_revenue(start_date, end_date, shop)
        cogs = UnifiedFinanceCalculator.calculate_cogs(start_date, end_date, shop)
        
        return revenue - cogs
    
    @staticmethod
    def calculate_net_profit(start_date=None, end_date=None, shop=None):
        """
        Net Profit = Revenue - COGS - Operating Expenses
        Inventory purchases are NOT deducted here
        """
        revenue = UnifiedFinanceCalculator.calculate_revenue(start_date, end_date, shop)
        cogs = UnifiedFinanceCalculator.calculate_cogs(start_date, end_date, shop)
        expenses = UnifiedFinanceCalculator.calculate_total_expenses(start_date, end_date)
        
        return revenue - cogs - expenses
    
    @staticmethod
    def get_net_account_balance():
        """Get current Net Account balance"""
        from finance.models import NetAccount
        net = NetAccount.get_account()
        return net.balance
    
    @staticmethod
    def get_savings_account_balance():
        """Get current Savings Account balance (profits only)"""
        from finance.models import SavingsAccount
        savings = SavingsAccount.get_account()
        return savings.balance
    
    @staticmethod
    def get_period_data(period='month', shop=None):
        """Get complete financial data for a period"""
        today = timezone.now().date()
        
        if period == 'today':
            start_date = today
            end_date = today
            period_name = "Today"
        elif period == 'week':
            start_date = today - timedelta(days=7)
            end_date = today
            period_name = "This Week"
        elif period == 'month':
            start_date = today.replace(day=1)
            end_date = today
            period_name = "This Month"
        elif period == 'year':
            start_date = today.replace(month=1, day=1)
            end_date = today
            period_name = "This Year"
        else:
            start_date = today.replace(day=1)
            end_date = today
            period_name = "This Month"
        
        revenue = UnifiedFinanceCalculator.calculate_revenue(start_date, end_date, shop)
        cogs = UnifiedFinanceCalculator.calculate_cogs(start_date, end_date, shop)
        gross_profit = revenue - cogs
        salaries = UnifiedFinanceCalculator.calculate_salary_expenses(start_date, end_date)
        commissions = UnifiedFinanceCalculator.calculate_commission_expenses(start_date, end_date)
        operational = UnifiedFinanceCalculator.calculate_operational_expenses(start_date, end_date)
        total_expenses = salaries + commissions + operational
        net_profit = gross_profit - total_expenses
        
        # Calculate current account balances
        net_balance = UnifiedFinanceCalculator.get_net_account_balance()
        savings_balance = UnifiedFinanceCalculator.get_savings_account_balance()
        
        # Calculate inventory purchases for information (not an expense)
        inventory_purchases = UnifiedFinanceCalculator.calculate_inventory_purchases(start_date, end_date)
        
        return {
            'period': period,
            'period_name': period_name,
            'start_date': start_date,
            'end_date': end_date,
            'revenue': revenue,
            'cogs': cogs,
            'gross_profit': gross_profit,
            'gross_margin': (gross_profit / revenue * 100) if revenue > 0 else 0,
            'salaries': salaries,
            'commissions': commissions,
            'operational_expenses': operational,
            'total_expenses': total_expenses,
            'net_profit': net_profit,
            'net_margin': (net_profit / revenue * 100) if revenue > 0 else 0,
            'net_balance': net_balance,
            'savings_balance': savings_balance,
            'inventory_purchases': inventory_purchases,  # For information only
        }