from django import forms
from .models import CustomField,CustomObject


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
        fields = ['label', 'name', 'crm', 'object_type', 'custom_object', 'data_type', 'required']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['custom_object'].required = False
        self.fields['object_type'].required = False

    def clean(self):
        cleaned_data = super().clean()
        object_type = cleaned_data.get("object_type")
        custom_object = cleaned_data.get("custom_object")

        if not object_type and not custom_object:
            raise forms.ValidationError("You must select either an Object Type or a Custom Object.")

        if object_type and custom_object:
            raise forms.ValidationError("Select only one: Object Type or Custom Object.")

        return cleaned_data





class CustomObjectForm(forms.ModelForm):
    class Meta:
        model = CustomObject
        fields = ['name', 'label', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }