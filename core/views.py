from django.shortcuts import render

from audit.models import AuditLog


def overview(request):
    # TODO(phase 8): counts for farmers, farms, active devices, readings this week, recommendations.
    latest_audit = AuditLog.objects.select_related("actor")[:10]
    return render(request, "core/overview.html", {"latest_audit": latest_audit})
