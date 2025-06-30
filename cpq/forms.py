from django import forms
from .models import CustomField, BusinessRule, RuleCondition, CustomObject
from django.forms import modelformset_factory
from django.apps import apps


DATA_TYPE_CHOICES = [
    ('text', 'Text'),
    ('number', 'Number'),
    ('date', 'Date'),
    ('boolean', 'Boolean'),
    ('dropdown', 'Dropdown'),
    ('textarea', 'Text Area'),
    ('lookup', 'Look Up'),
]
CRM_CHOICES = [
    ('HubSpot', 'HubSpot'),
    ('Salesforce', 'Salesforce'),
    ('AgentCPQ', 'AgentCPQ'),
]

QUOTE_FIELDS = [
    ("discount_percentage", "Discount Percentage"),
    ("discount_amount", "Discount Amount"),
    ("subtotal", "Subtotal"),
    ("net_amount", "Net Amount"),
    ("tax_amount", "Tax Amount"),
    ("total_price", "Total Price"),
]

QUOTE_LINE_FIELDS = [
    ("quantity", "Quantity"),
    ("unit_price", "Unit Price"),
    ("special_price", "Special Price"),
    ("discount_percentage", "Discount Percentage"),
    ("discount_amount", "Discount Amount"),
    ("subtotal", "Subtotal"),
    ("total_price", "Total Price"),
    ("term", "Term"),
]

PRODUCT_FIELDS = [
    ("price", "Price"),
    ("term", "Term")
]

def get_model_choices():
    choices = []
    for model in apps.get_models():
        app_label = model._meta.app_label
        model_name = model.__name__
        full_label = f"{app_label}.{model_name}"
        choices.append((full_label, full_label))
    return sorted(choices)

class CustomFieldForm(forms.ModelForm):
    lookup_model = forms.ChoiceField(
        required=False,
        choices=get_model_choices(),  # dynamically populated
        widget=forms.Select(attrs={'class': 'browser-default'})
    )
    data_type = forms.ChoiceField(
        choices=DATA_TYPE_CHOICES, 
        widget=forms.Select(attrs={'class': 'browser-default'})
    )
    crm = forms.ChoiceField(choices=CRM_CHOICES)

    class Meta:
        model = CustomField
        fields = [
            'label', 'name', 'crm', 'object_type', 
            'custom_object', 'data_type', 'required', 'lookup_model'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['custom_object'].required = False
        self.fields['object_type'].required = False
        self.fields['lookup_model'].required = False

    def clean(self):
        cleaned_data = super().clean()
        object_type = cleaned_data.get("object_type")
        custom_object = cleaned_data.get("custom_object")
        data_type = cleaned_data.get("data_type")
        lookup_model = cleaned_data.get("lookup_model")

        if not object_type and not custom_object:
            raise forms.ValidationError("You must select either an Object Type or a Custom Object.")

        if object_type and custom_object:
            raise forms.ValidationError("Select only one: Object Type or Custom Object.")

        if data_type == "lookup" and not lookup_model:
            raise forms.ValidationError("Lookup fields require a lookup model (e.g., cpq.Account).")

        return cleaned_data


class CustomObjectForm(forms.ModelForm):
    class Meta:
        model = CustomObject
        fields = ['label', 'name', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

class BusinessRuleForm(forms.ModelForm):
    class Meta:
        model = BusinessRule
        fields = ['name', 'target_type', 'priority', 'active', 'error_message']

class RuleConditionForm(forms.ModelForm):
    field_name = forms.ChoiceField(choices=[])  # Inicialmente vacío

    def __init__(self, *args, **kwargs):
        target_type = kwargs.pop("target_type", None)
        super().__init__(*args, **kwargs)

        if target_type == "quote":
            self.fields["field_name"].choices = QUOTE_FIELDS
        elif target_type == "quote_line":
            self.fields["field_name"].choices = QUOTE_LINE_FIELDS
        elif target_type == "product":
            self.fields["field_name"].choices = PRODUCT_FIELDS
        else:
            self.fields["field_name"].choices = []  # En caso de error o vacío

    class Meta:
        model = RuleCondition
        fields = ['field_name', 'operator', 'value']

def get_rule_condition_formset(target_type, data=None):
    return modelformset_factory(
        RuleCondition,
        form=RuleConditionForm,
        extra=1,
    )(queryset=RuleCondition.objects.none(), form_kwargs={'target_type': target_type}, data=data)



def generate_dynamic_form(custom_object):
    class DynamicCustomForm(forms.Form):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            fields = CustomField.objects.filter(custom_object=custom_object)

            for field in fields:
                field_type = forms.CharField  # default
                widget = None

                if field.data_type == 'number':
                    field_type = forms.FloatField
                elif field.data_type == 'date':
                    field_type = forms.DateField
                elif field.data_type == 'boolean':
                    field_type = forms.BooleanField
                elif field.data_type == 'text':
                    field_type = forms.CharField
                    # widget = forms.Textarea()

                self.fields[field.name] = field_type(
                    label=field.label or field.name,
                    required=field.required,
                    widget=widget
                )

    return DynamicCustomForm