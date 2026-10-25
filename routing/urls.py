from django.urls import path

from .views import RouteView, map_page

urlpatterns = [
    path("api/route/", RouteView.as_view()),
    path("", map_page),
]