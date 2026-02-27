from django.shortcuts import render

def test_ui(request):
    return render(request, "base.html")