from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from payments.views import (
    GatewayWebhookView,
    LogoutView,
    MeView,
    MiddlewareProbeView,
    RegisterView,
    WalletViewSet,
)

router = DefaultRouter()
router.register("wallets", WalletViewSet)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("api/webhooks/gateway/", GatewayWebhookView.as_view(), name="gateway-webhook"),
    path("api/middleware-probe/", MiddlewareProbeView.as_view(), name="middleware-probe"),
    path("api/auth/register/", RegisterView.as_view(), name="register"),
    path("api/auth/me/", MeView.as_view(), name="me"),
    path("api/auth/logout/", LogoutView.as_view(), name="logout"),
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
