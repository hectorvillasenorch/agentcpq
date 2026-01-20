from django.urls import path
from salesforce.views import salesforce_login, salesforce_callback, token_receiver, test_salesforce_api, sync_quote_to_salesforce

urlpatterns = [
    path("login/", salesforce_login, name="salesforce_login"),
    path("callback/", salesforce_callback, name="salesforce_callback"),
    path("callback", salesforce_callback, name="salesforce_callback_noslash"),
    path("token-receiver/", token_receiver, name="token_receiver"),
    path("test-api/", test_salesforce_api, name="test_salesforce_api"),
    path("sync-quote/<int:quote_id>/", sync_quote_to_salesforce, name="sync_quote_to_salesforce")
]
