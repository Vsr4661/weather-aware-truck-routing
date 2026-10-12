from django.urls import include, path

# The React build (index.html + assets) is served from the site root by
# WhiteNoise (see WHITENOISE_ROOT); Django only handles /api/*.
urlpatterns = [
    path("api/", include("routing.urls")),
]
