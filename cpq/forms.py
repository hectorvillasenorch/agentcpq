from django import forms
from .models import CustomField, BusinessRule, RuleCondition, CustomObject, QuoteLine, CustomFieldValue, ContentType
from django.forms import modelformset_factory
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from django.contrib.auth.models import User
from .models import EmailAlert
import json


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

        if custom_object:
            cleaned_data["object_type"] = custom_object.name

        if not object_type and not custom_object:
            raise forms.ValidationError("You must select an Object Type and a Custom Object if required.")

        if data_type == "lookup" and not lookup_model:
            raise forms.ValidationError("Lookup fields require a lookup model (e.g., cpq.Account).")

        return cleaned_data
    
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

        if custom_object:
            cleaned_data["object_type"] = custom_object.name

        if not object_type and not custom_object:
            raise forms.ValidationError("You must select an Object Type and a Custom Object if required.")

        if data_type == "lookup" and not lookup_model:
            raise forms.ValidationError("Lookup fields require a lookup model (e.g., cpq.Account).")

        return cleaned_data


class CustomObjectForm(forms.ModelForm):
    class Meta:
        model = CustomObject
        fields = ['label', 'name', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'class': 'materialize-textarea'
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
                elif field.data_type == 'dropdown':
                    field_type = forms.ChoiceField
                    options = field.options or []

                    # Si es string, conviértelo en lista
                    if isinstance(options, str):
                        options = [opt.strip() for opt in options.split(",")]

                    choices = [(opt, opt) for opt in options]
                    self.fields[field.name] = field_type(
                        label=field.label or field.name,
                        choices=choices,
                        required=field.required
                    )
                    continue

                self.fields[field.name] = field_type(
                    label=field.label or field.name,
                    required=field.required,
                    widget=widget
                )

    return DynamicCustomForm


def get_dynamic_form(model_class, crm, object_type):

    class DynamicCustomForm(forms.ModelForm):
        class Meta:
            model = model_class
            fields = '__all__'
            exclude = ('updated_by',)

        def __init__(self, *args, user=None, **kwargs):
            self.user = user
            super().__init__(*args, **kwargs)
            User = get_user_model()

            # --- Manejo de due_date ---
            if hasattr(self._meta.model, "due_date"):
                instance = kwargs.get("instance")
                self.fields["due_date"] = forms.DateField(
                    label="Due Date",
                    required=False,
                    initial=instance.due_date if instance else None,
                    widget=forms.DateInput(attrs={"type": "date"})
                )

            # --- Manejo de created_by (readonly visible) ---
            if hasattr(self._meta.model, "created_by"):
                if kwargs.get("instance") and kwargs["instance"].created_by:
                    initial_user = kwargs["instance"].created_by
                elif self.user:
                    initial_user = self.user
                else:
                    initial_user = None

                self.fields["created_by"] = forms.ModelChoiceField(
                    queryset=User.objects.all(),
                    initial=initial_user,
                    required=False,
                    disabled=True,  # readonly
                    label="Created by"
                )

            # --- Manejo de campos dinámicos ---
            instance = kwargs.get("instance")
            self._custom_fields = CustomField.objects.filter(crm=crm, object_type=object_type)

            for field in self._custom_fields:
                field_name = field.name
                value = self.get_custom_field_value(instance, field) if instance else ""

                # Solo si el campo dinámico no existe en el formulario, crearlo
                if field_name not in self.fields:
                    self.fields[field_name] = forms.CharField(
                        label=field.label or field.name,
                        required=field.required,
                        initial=value
                    )

        def get_custom_field_value(self, instance, custom_field):
            if not instance:
                return ""
            try:
                ct = ContentType.objects.get_for_model(instance)
                return CustomFieldValue.objects.get(
                    content_type=ct,
                    object_id=instance.id,
                    field=custom_field
                ).value
            except CustomFieldValue.DoesNotExist:
                return ""

        def save(self, commit=True):
            instance = super().save(commit=False)

            # --- Asignar created_by SOLO al crear ---
            if hasattr(instance, "created_by") and not instance.pk and self.user:
                instance.created_by = self.user

            # --- Asignar updated_by siempre ---
            if hasattr(instance, "updated_by") and self.user:
                instance.updated_by = self.user

            if commit:
                instance.save()

            # --- Guardar CustomFieldValues ---
            content_type = ContentType.objects.get_for_model(instance)
            for field in self._custom_fields:
                value = self.cleaned_data.get(field.name)
                if value is not None:
                    cfv, created = CustomFieldValue.objects.get_or_create(
                        content_type=content_type,
                        object_id=instance.id,
                        field=field,
                    )
                    cfv.value = value
                    cfv.updated_by_user = self.user
                    cfv.save()

            return instance

    return DynamicCustomForm



class DynamicQuoteLineForm(forms.ModelForm):
    class Meta:
        model = QuoteLine
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get("instance")
        print("🧠 DynamicQuoteLineForm is being used.")

        # Only load custom fields for AgentCPQ > QuoteLine
        custom_fields = CustomField.objects.filter(
            crm="AgentCPQ",
            object_type="QuoteLine"
        )
        custom_fields = CustomField.objects.filter(crm='AgentCPQ', object_type='QuoteLine')
        print("📦 Loaded custom fields:", list(custom_fields.values_list("name", flat=True)))

        for field in custom_fields:
            field_name = field.name  # Now 'uom__c', not 'custom__uom__c'

            try:
                if field.data_type == "dropdown":
                    self.fields[field_name] = forms.ChoiceField(
                        label=field.label or field.name,
                        choices=[("Each", "Each"), ("Hour", "Hour"), ("Pack", "Pack")],  # example
                        required=field.required,
                        initial=self.get_custom_field_value(instance, field) if instance else ''
                    )
                else:
                    self.fields[field_name] = forms.CharField(
                        label=field.label or field.name,
                        required=field.required,
                        initial=self.get_custom_field_value(instance, field) if instance else ''
                    )

                print(f"✅ Added dynamic field: {field_name}")
            except Exception as e:
                print(f"❌ Error adding {field_name}: {e}")
                

    def get_custom_field_value(self, instance, custom_field):
        try:
            content_type = ContentType.objects.get_for_model(instance)
            cfv = CustomFieldValue.objects.get(
                content_type=content_type,
                object_id=instance.id,
                field=custom_field
            )
            return cfv.value
        except CustomFieldValue.DoesNotExist:
            return ""

    def save(self, commit=True):
        instance = super().save(commit)
        content_type = ContentType.objects.get_for_model(instance.__class__)

        custom_fields = CustomField.objects.filter(crm="AgentCPQ", object_type="QuoteLine")

        for field in custom_fields:
            value = self.cleaned_data.get(field.name)
            if value is not None:
                cfv, _ = CustomFieldValue.objects.get_or_create(
                    content_type=content_type,
                    object_id=instance.id,
                    field=field,
                    defaults={"value": value}
                )
                # Update value if it already exists
                cfv.value = value
                cfv.save()

        return instance
    
class EmailAlertForm(forms.ModelForm):
    recipients_users = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=forms.MultipleHiddenInput()  # 👈 lo escondemos
    )

    # Cambiamos a CharField en lugar de MultipleChoiceField
    recipients_roles = forms.CharField(
        required=False,
        widget=forms.HiddenInput()  # recibimos JSON desde JS
    )

    recipients_external = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'placeholder': 'Separate emails with commas',
            'rows': 2,
            'class': 'materialize-textarea'
        })
    )

    class Meta:
        model = EmailAlert
        fields = '__all__'
        exclude = ('created_by', 'updated_by')
        widgets = {
            "description": forms.Textarea(attrs={"class": "materialize-textarea"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['custom_object'].required = False
        self.fields['offset_days'].required = False
        self.fields['scheduled_cron'].required = False
        self.fields['name'].disabled = True

    def clean_recipients_roles(self):
        data = self.cleaned_data.get("recipients_roles", "")
        try:
            # Intentamos decodificar JSON enviado desde JS
            roles_list = json.loads(data) if data else []
        except json.JSONDecodeError:
            roles_list = []

        # Validamos que cada rol exista en ROLE_CHOICES
        valid_roles = [key for key, _ in EmailAlert.ROLE_CHOICES]
        invalid = [r for r in roles_list if r not in valid_roles]
        if invalid:
            raise forms.ValidationError(f"Invalid roles: {invalid}")

        # Guardamos como string separado por comas
        return ",".join(roles_list)

    def clean(self):
        cleaned_data = super().clean()

        offset_days = cleaned_data.get('offset_days')
        scheduled_cron = cleaned_data.get('scheduled_cron')

        if offset_days and scheduled_cron:
            raise forms.ValidationError(
                "You cannot configure offset days and scheduled cron at the same time; choose one or the other."
            )

        native_object = cleaned_data.get("native_object")
        custom_object = cleaned_data.get("custom_object")
        recipients_users = cleaned_data.get("recipients_users")
        recipients_roles = cleaned_data.get("recipients_roles")
        recipients_external = cleaned_data.get("recipients_external")

        if not native_object and not custom_object:
            raise forms.ValidationError("You must select a native object or a custom object.")

        if not recipients_users and not recipients_roles and not recipients_external:
            raise forms.ValidationError("You must specify at least one recipient (user, role, or external email).")

        return cleaned_data