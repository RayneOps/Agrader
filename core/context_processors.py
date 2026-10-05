from django.conf import settings


def product(request):
    match = getattr(request, "resolver_match", None)
    return {
        "PRODUCT_NAME": settings.PRODUCT_NAME,
        "PUBLIC_CONTACT": settings.PUBLIC_CONTACT,
        # The app that owns the current view ("farms", "crops", ...), for highlighting the nav.
        "nav_section": match.func.__module__.split(".")[0] if match else "",
    }
