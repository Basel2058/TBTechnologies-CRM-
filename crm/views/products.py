from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from ..forms import PlanFormSet, ProductForm
from ..models import Objection, Product, Subscription
from ..permissions import manager_required


def product_list(request):
    active_filter = Q(subscriptions__status=Subscription.Status.ACTIVE)
    products = (
        Product.objects.prefetch_related("plans")
        .annotate(
            active_subs=Count("subscriptions", filter=active_filter, distinct=True),
            mrr=Sum("subscriptions__monthly_price", filter=active_filter),
        )
    )
    return render(request, "crm/products/list.html", {"products": products})


def product_detail(request, pk):
    product = get_object_or_404(Product.objects.prefetch_related("plans", "objections"), pk=pk)
    return render(request, "crm/products/detail.html", {
        "product": product,
        "general_objections": Objection.objects.filter(product__isnull=True),
    })


@manager_required
def product_form(request, pk=None):
    product = get_object_or_404(Product, pk=pk) if pk else Product()
    form = ProductForm(request.POST or None, instance=product)
    formset = PlanFormSet(request.POST or None, instance=product, prefix="plans")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            product = form.save()
            formset.instance = product
            formset.save()
        messages.success(request, f"تم حفظ التطبيق «{product.name}».")
        return redirect(product)
    return render(request, "crm/products/form.html", {
        "form": form, "formset": formset, "product": product if pk else None,
        "title": f"تعديل: {product.name}" if pk else "تطبيق جديد",
    })
