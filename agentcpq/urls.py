from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from cpq.views import root_redirect
from dashboard.views import get_tenant_usage
from dashboard.views import CustomPasswordResetView, signup
from django.views.decorators.clickjacking import xframe_options_exempt

urlpatterns = [
    path('', root_redirect),
    path('dashboard/', include('dashboard.urls')),
    path('agents/', include('agents.urls')),  
    path('cpq/', include('cpq.urls')), 
    path("salesforce/", include("salesforce.urls")),
    path('admin/', admin.site.urls),
    path('hubspot/', include('hubspot.urls')),

    # Auth
    # path('login/', auth_views.LoginView.as_view(template_name='auth/login.html'), name='login'),
    path(
    'login/',
        xframe_options_exempt(auth_views.LoginView.as_view(template_name='auth/login.html')),
        name='login'
    ),
    path('signup/', signup, name='signup'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    ### API Endpoints
    path('api/usage/', get_tenant_usage, name='get_tenant_usage'),
    path("api/v1/", include("api.urls")),
    # Password reset
    path('password_reset/', CustomPasswordResetView.as_view(
        template_name='auth/password_reset.html',
        email_template_name='auth/password_reset_email.txt',
        html_email_template_name='auth/password_reset_email.html',
        subject_template_name='auth/password_reset_subject.txt'
        ), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='auth/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='auth/password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='auth/password_reset_complete.html'), name='password_reset_complete'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

