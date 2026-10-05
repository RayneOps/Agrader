from django.urls import path

from . import views, wizard

urlpatterns = [
    path("farmers", views.farmer_list, name="farmer_list"),
    path("farmers/new", views.farmer_create, name="farmer_create"),
    path("farmers/<uuid:pk>", views.farmer_detail, name="farmer_detail"),
    path("farmers/<uuid:pk>/edit", views.farmer_edit, name="farmer_edit"),
    path("farmers/<uuid:farmer_id>/farms/new", views.farm_create, name="farm_create"),
    path("farms/<uuid:pk>", views.farm_detail, name="farm_detail"),
    path("farms/<uuid:pk>/edit", views.farm_edit, name="farm_edit"),
    path("farms/<uuid:farm_id>/seasons/new", wizard.season_start, name="season_start"),
    path("seasons/<uuid:pk>/step/<int:step>", wizard.season_step, name="season_step"),
]
