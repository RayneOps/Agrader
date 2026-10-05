from django.contrib.auth.decorators import login_not_required
from django.shortcuts import render

from audit.models import AuditLog


@login_not_required
def home(request):
    """"/": the public landing page for visitors, the Overview for signed-in admins.

    The landing page must not touch the database, so it stays fast and cannot leak data.
    """
    if not request.user.is_authenticated:
        return render(request, "core/landing.html")
    return overview(request)


def overview(request):
    # TODO(phase 8): counts for farmers, farms, active devices, readings this week, recommendations.
    latest_audit = AuditLog.objects.select_related("actor")[:10]
    return render(request, "core/overview.html", {"latest_audit": latest_audit})
