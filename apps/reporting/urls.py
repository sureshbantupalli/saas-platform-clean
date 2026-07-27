from django.urls import path

from . import views

urlpatterns = [
    path("gst/",              views.gst_report_json,     name="gst_json"),
    path("gst/csv/",          views.gst_report_csv,      name="gst_csv"),
    path("income-expense/",   views.income_expense_json,  name="income_expense_json"),
    path("income-expense/csv/", views.income_expense_csv, name="income_expense_csv"),
]
