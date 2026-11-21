from django.urls import path

from . import views

urlpatterns = [
    path("", views.DocumentList.as_view()),
    path("<int:pk>/", views.DocumentDetail.as_view()),
]
