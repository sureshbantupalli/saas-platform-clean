from rest_framework.routers import DefaultRouter
from .views import IntakeFormViewSet, FormFieldViewSet

router = DefaultRouter()
router.register(r"forms", IntakeFormViewSet, basename="intake-forms")
router.register(r"fields", FormFieldViewSet, basename="intake-fields")

urlpatterns = router.urls
