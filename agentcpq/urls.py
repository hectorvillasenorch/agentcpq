from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('dashboard/', include('dashboard.urls')),
    path('agents/', include('agents.urls')),  
    path('cpq/', include('cpq.urls')), 
    path("salesforce/", include("salesforce.urls")),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
