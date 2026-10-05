from django.urls import path

from . import views

urlpatterns = [
    path("crops", views.crop_list, name="crop_list"),
    path("crops/new", views.crop_new, name="crop_new"),
    path("crops/<uuid:pk>", views.crop_detail, name="crop_detail"),
    path("crops/<uuid:pk>/edit", views.crop_edit, name="crop_edit"),
    path("crops/<uuid:pk>/requirements/new", views.requirement_new, name="requirement_new"),
    path("crops/requirements/<uuid:pk>/approve", views.requirement_approve, name="requirement_approve"),
    path("crops/pairs", views.pair_list, name="pair_list"),
    path("crops/pairs/new", views.pair_new, name="pair_new"),
    path("crops/pairs/<uuid:pk>/edit", views.pair_edit, name="pair_edit"),
    path("crops/pairs/<uuid:pk>/approve", views.pair_approve, name="pair_approve"),
    path("crops/rotation", views.rotation_list, name="rotation_list"),
    path("crops/rotation/new", views.rotation_new, name="rotation_new"),
    path("crops/rotation/<uuid:pk>/edit", views.rotation_edit, name="rotation_edit"),
    path("crops/rotation/<uuid:pk>/approve", views.rotation_approve, name="rotation_approve"),
    path("crops/settings", views.setting_list, name="setting_list"),
    path("crops/settings/<uuid:pk>/edit", views.setting_edit, name="setting_edit"),
    path("crops/settings/<uuid:pk>/verify", views.setting_verify, name="setting_verify"),
]
