from django.urls import path
from . import views
from .views import (
    AssignEnquiryView,
    EnquiryUpdateView,
    CRMConvertEnquiryView,
    UpdateEnquiryStageView,
)

app_name = "crm"

urlpatterns = [

    # ======================================
    # CRM DASHBOARD
    # ======================================
    path(
        "dashboard/",
        views.CRMdashboardView.as_view(),
        name="dashboard"
    ),

    # ======================================
    # ENQUIRY LIST
    # ======================================
    path(
        "enquiries/",
        views.EnquiryListView.as_view(),
        name="enquiry_list"
    ),

    # ======================================
    # CREATE ENQUIRY
    # ======================================
    path(
        "enquiries/add/",
        views.EnquiryCreateView.as_view(),
        name="enquiry_add"
    ),

    # ======================================
    # ENQUIRY DETAIL
    # ======================================
    path(
        "enquiries/<int:pk>/",
        views.EnquiryDetailView.as_view(),
        name="enquiry_detail"
    ),

    # ======================================
    # EDIT ENQUIRY
    # ======================================
    path(
        "enquiries/<int:pk>/edit/",
        EnquiryUpdateView.as_view(),
        name="enquiry_edit"
    ),

    # ======================================
    # ASSIGN ENQUIRY
    # ======================================
    path(
        "enquiries/<int:pk>/assign/",
        AssignEnquiryView.as_view(),
        name="assign_enquiry"
    ),

    # ======================================
    # CONVERT TO MEMBER
    # ======================================
    path(
        "enquiries/<int:pk>/convert/",
        CRMConvertEnquiryView.as_view(),
        name="enquiry_convert"
    ),

    # ======================================
    # ADD NOTE
    # ======================================
    path(
        "enquiries/<int:pk>/add-note/",
        views.AddEnquiryNoteView.as_view(),
        name="enquiry_add_note"
    ),

    # ======================================
    # UPDATE STAGE (AJAX)
    # ======================================
    path(
        "update-stage/",
        UpdateEnquiryStageView.as_view(),
        name="update_enquiry_stage"
    ),

    # ======================================
    # KANBAN PIPELINE
    # ======================================
    path(
        "kanban/",
        views.EnquiryKanbanView.as_view(),
        name="enquiry_kanban"
    ),

    # ======================================
    # CHANGE STAGE (Dropdown version)
    # ======================================
    path(
        "enquiry/<int:enquiry_id>/change-stage/",
        views.change_enquiry_stage,
        name="change_enquiry_stage",
    ),

    # ======================================
    # FOLLOW-UP UPDATE
    # ======================================
    path(
        "enquiry/<int:enquiry_id>/followup/",
        views.update_followup_date,
        name="update_followup_date",
    ),

    # ======================================
    # QUICK CALL LOGGING
    # ======================================
    path(
        "enquiry/<int:enquiry_id>/quick-call/",
        views.quick_log_call,
        name="quick_log_call",
    ),

    # ======================================
    # QUICK FOLLOW-UP
    # ======================================
    path(
        "enquiry/<int:enquiry_id>/quick-followup/",
        views.quick_schedule_followup,
        name="quick_schedule_followup",
    ),

    # ======================================
    # FOLLOW-UP QUEUE
    # ======================================
    path(
        "followups/",
        views.follow_up_queue,
        name="followup_queue",
    ),

    path(
        "followups/<int:pk>/done/",
        views.mark_followup_done,
        name="mark_followup_done",
    ),

    path(
        "followups/<int:pk>/log-call/",
        views.log_call_from_followup,
        name="log_call_from_followup",
    ),

]