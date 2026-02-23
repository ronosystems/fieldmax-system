from rest_framework import serializers
from .models import PendingOrder, PendingOrderItem
from django.contrib.auth.models import User

class PendingOrderSerializer(serializers.ModelSerializer):
    approved_by = serializers.SerializerMethodField()
    rejected_by = serializers.SerializerMethodField()
    approved_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', required=False, allow_null=True)
    rejected_at = serializers.DateTimeField(format='%Y-%m-%d %H:%M:%S', required=False, allow_null=True)

    class Meta:
        model = PendingOrder
        fields = [
            'order_id', 'buyer_name', 'buyer_phone', 'buyer_id_number', 
            'buyer_email', 'total_amount', 'status', 'created_at',
            'approved_by', 'rejected_by', 'approved_at', 'rejected_at', 
            'rejection_reason'
        ]

    def get_approved_by(self, obj):
        if obj.approved_by:
            return obj.approved_by.get_full_name() or obj.approved_by.username
        return None

    def get_rejected_by(self, obj):
        if obj.rejected_by:
            return obj.rejected_by.get_full_name() or obj.rejected_by.username
        return None

class PendingOrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PendingOrderItem
        fields = ['id', 'product_name', 'quantity', 'unit_price', 'total_price']