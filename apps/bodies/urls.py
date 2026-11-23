from django.urls import path

from . import views

app_name = "bodies"

urlpatterns = [
    path("bodies/", views.index, name="index"),
    path("bodies/unions/new/", views.union_new, name="union_new"),
    path("bodies/unions/<slug:slug>/", views.union_page, name="union"),
    path("bodies/unions/<slug:slug>/invite/", views.union_invite, name="union_invite"),
    path("bodies/unions/<slug:slug>/leave/<slug:unit_slug>/", views.union_leave, name="union_leave"),
    path("bodies/unions/<slug:slug>/decide/", views.union_decide, name="union_decide"),
    path("bodies/union-decisions/<int:pk>/vote/", views.union_vote, name="union_vote"),
    path("tickets/<str:number>/advice/<int:union_pk>/", views.give_advice, name="give_advice"),
    path("bodies/nominations/", views.nominations, name="nominations"),
    path("bodies/nominations/<int:pk>/answer/", views.nomination_answer, name="nomination_answer"),
    path("bodies/local/new/", views.local_new, name="local_new"),
    path("bodies/local/<int:pk>/", views.local_page, name="local"),
    path("bodies/local/<int:pk>/volunteer/", views.local_volunteer, name="local_volunteer"),
    path("bodies/local/<int:pk>/decide/", views.local_decide, name="local_decide"),
    path("bodies/consumers/new/", views.consumer_new, name="consumer_new"),
    path("bodies/consumers/<int:pk>/", views.consumer_page, name="consumer"),
    path("bodies/consumers/<int:pk>/membership/", views.consumer_membership, name="consumer_membership"),
    path("bodies/consumers/<int:pk>/guidelines/", views.guideline_propose, name="guideline_propose"),
    path("bodies/guidelines/<int:pk>/vote/", views.guideline_vote, name="guideline_vote"),
]
