from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.urls import reverse


def login_view(request):

    # If already logged in → redirect
    if request.user.is_authenticated:
        return _redirect_user(request.user)

    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")

        if not email or not password:
            messages.error(request, "Please enter both email and password.")
            return render(request, "accounts/login.html")

        user = authenticate(request, username=email, password=password)

        if user is not None:
            login(request, user)
            return _redirect_user(user)
        else:
            messages.error(request, "Invalid email or password.")

    return render(request, "accounts/login.html")


def logout_view(request):
    logout(request)
    return redirect("login")


def _redirect_user(user):
    if user.is_platform_admin:
        return redirect(reverse("platform:dashboard"))
    return redirect(reverse("crm:dashboard"))