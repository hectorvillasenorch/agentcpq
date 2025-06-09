from django import forms
from .models import CustomField


DATA_TYPE_CHOICES = [
    ('text', 'Text'),
    ('number', 'Number'),
    ('date', 'Date'),
    ('boolean', 'Boolean'),
    ('dropdown', 'Dropdown'),
    ('textarea', 'Text Area'),
]
CRM_CHOICES = [
    ('HubSpot', 'HubSpot'),
    ('Salesforce', 'Salesforce'),
    ('AgentCPQ', 'AgentCPQ'),
]
class CustomFieldForm(forms.ModelForm):
    data_type = forms.ChoiceField(choices=DATA_TYPE_CHOICES, widget=forms.Select(attrs={'class': 'browser-default'}))
    crm = forms.ChoiceField(choices=CRM_CHOICES)
    class Meta:
        model = CustomField
        fields = ['label', 'name', 'crm', 'object_type', 'data_type', 'required']