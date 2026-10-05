from django.urls import path

from . import views

urlpatterns = [
    path("seasons/<uuid:pk>/ranking", views.season_ranking, name="season_ranking"),
]
