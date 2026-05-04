from django.contrib import admin
from shops.models import ShopBranch

class ShopBranchFilter(admin.SimpleListFilter):
    title = 'Shop Branch'
    parameter_name = 'shop_branch'
    
    def lookups(self, request, model_admin):
        shops = ShopBranch.objects.filter(is_active=True)
        return [(shop.id, shop.name) for shop in shops]
    
    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(shop_id=self.value())
        return queryset