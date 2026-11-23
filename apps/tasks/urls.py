from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("tasks/", views.task_list, name="list"),
    path("tasks/ticket/<str:number>/", views.ticket_page, name="ticket"),
    path("tasks/apply/<str:number>/", views.apply, name="apply"),
    path("tasks/<int:pk>/<str:action>/", views.task_action, name="task_action"),
    path("tasks/mandates/<int:pk>/", views.mandate_page, name="mandate"),
    path("tasks/mandates/<int:pk>/<str:action>/", views.mandate_action, name="mandate_action"),
]
