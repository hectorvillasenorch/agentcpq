from django import forms
from .models import CustomField, BusinessRule, RuleCondition, CustomObject, QuoteLine, CustomFieldValue, ContentType, CustomRecord
from django.forms import modelformset_factory
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import models

from django.contrib.auth.models import User
from .models import EmailAlert
import json
import re
from decimal import Decimal, InvalidOperation


DATA_TYPE_CHOICES = [
    ('text', 'Text'),
    ('number', 'Number'),
    ('currency', 'Currency'),
    ('percent', 'Percent'),
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


def _parse_loose_decimal(value):
    if value is None:
        return None

    if isinstance(value, Decimal):
        return value

    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None

    # Allow currency-like / percent-like inputs: "$1,234.56", "1.234,56", "12%", "MXN 500"
    text = re.sub(r"[^0-9,.\-]+", "", text)
    if not text:
        return None

    has_dot = "." in text
    has_comma = "," in text

    if has_dot and has_comma:
        # Decide decimal separator by last occurrence.
        if text.rfind(",") > text.rfind("."):
            # "1.234,56" -> "1234.56"
            text = text.replace(".", "")
            text = text.replace(",", ".")
        else:
            # "1,234.56" -> "1234.56"
            text = text.replace(",", "")
    elif has_comma and not has_dot:
        # "1234,56" -> "1234.56" (assume decimal comma if it looks like cents)
        parts = text.split(",")
        if len(parts) == 2 and 1 <= len(parts[1]) <= 2:
            text = ".".join(parts)
        else:
            text = text.replace(",", "")

    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


class CurrencyField(forms.DecimalField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("max_digits", 18)
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        decimal_value = _parse_loose_decimal(value)
        if decimal_value is None:
            return None
        return decimal_value.quantize(Decimal("0.01"))


class PercentField(forms.DecimalField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("max_digits", 8)
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        decimal_value = _parse_loose_decimal(value)
        if decimal_value is None:
            return None
        return decimal_value.quantize(Decimal("0.01"))


DATA_TYPE_MAPPING = {
    "text": forms.CharField,
    "number": forms.DecimalField,  # o forms.IntegerField si quieres solo enteros
    "currency": CurrencyField,
    "percent": PercentField,
    "date": forms.DateField,
    "boolean": forms.BooleanField,
    "dropdown": forms.ChoiceField,
    "textarea": forms.CharField,
    "lookup": forms.ModelChoiceField,  # se asigna queryset dinámico
}

WIDGET_MAPPING = {
    "text": forms.TextInput(attrs={"class": "w-full border rounded p-2"}),
    "number": forms.NumberInput(attrs={"class": "w-full border rounded p-2"}),
    "currency": forms.NumberInput(attrs={"class": "w-full border rounded p-2", "step": "0.01", "inputmode": "decimal"}),
    "percent": forms.NumberInput(attrs={"class": "w-full border rounded p-2", "step": "0.01", "inputmode": "decimal"}),
    "date": forms.DateInput(attrs={"type": "date", "class": "w-full border rounded p-2"}),
    "boolean": forms.CheckboxInput(),
    "dropdown": forms.Select(attrs={"class": "w-full border rounded p-2"}),
    "textarea": forms.Textarea(attrs={"class": "w-full border rounded p-2", "rows": 3}),
    "lookup": forms.Select(attrs={"class": "w-full border rounded p-2"}),  # luego asignas queryset
}


def resolve_lookup_model(model_ref, field_name=None, field_label=None):
    """
    Safely resolve a lookup model reference.
    Accepts fully-qualified labels (e.g. 'cpq.Account') or shorthand names like 'account'/'opportunity'.
    If lookup_model is empty, attempts to infer based on the field name/label (account, opportunity, contact).
    """
    def _infer_from_hint(hint: str):
        hint_lower = hint.lower()
        if "account" in hint_lower:
            return ("cpq", "Account")
        if "opportunity" in hint_lower or "opp" in hint_lower:
            return ("cpq", "Opportunity")
        if "contact" in hint_lower:
            return ("cpq", "Contact")
        return None

    # Use provided model ref if present
    if model_ref:
        if not isinstance(model_ref, str):
            return None

        candidate = model_ref.strip()

        # Try fully qualified path first (app_label.ModelName)
        if "." in candidate:
            try:
                app_label, model_name = candidate.split(".", 1)
                return apps.get_model(app_label, model_name)
            except (LookupError, ValueError):
                pass

        # Friendly fallbacks for common CRM objects
        fallback_map = {
            "account": ("cpq", "Account"),
            "accounts": ("cpq", "Account"),
            "opportunity": ("cpq", "Opportunity"),
            "opportunities": ("cpq", "Opportunity"),
            "contact": ("cpq", "Contact"),
            "contacts": ("cpq", "Contact"),
        }

        normalized = candidate.lower()
        if normalized in fallback_map:
            try:
                app_label, model_name = fallback_map[normalized]
                return apps.get_model(app_label, model_name)
            except LookupError:
                return None

        # Last attempt: assume cpq app if only the model name was provided
        try:
            return apps.get_model("cpq", candidate)
        except LookupError:
            pass

    # If lookup_model is empty or unresolved, infer from field hints
    for hint in (field_name, field_label):
        if hint:
            inferred = _infer_from_hint(str(hint))
            if inferred:
                try:
                    app_label, model_name = inferred
                    return apps.get_model(app_label, model_name)
                except LookupError:
                    continue

    # Nothing matched
    try:
        return None
    except Exception:
        return None


def get_model_choices():
    choices = []
    for model in apps.get_models():
        app_label = model._meta.app_label
        model_name = model.__name__
        full_label = f"{app_label}.{model_name}"
        choices.append((full_label, full_label))

    # Also allow pointing to a Custom Object by name (stored directly in lookup_model)
    try:
        for co in CustomObject.objects.all():
            label = co.label or co.name
            choices.append((co.name, f"Custom: {label} ({co.name})"))
    except Exception:
        pass

    return sorted(choices, key=lambda x: x[1])

class CustomFieldForm(forms.ModelForm):
    lookup_model = forms.ChoiceField(
        required=False,
        choices=[],
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
        widgets = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['custom_object'].required = False
        self.fields['object_type'].required = False
        self.fields['lookup_model'].required = False

        # --------------------------------------------------
        # 🔹 BUILD LOOKUP MODEL CHOICES
        # --------------------------------------------------

        lookup_choices = []

        # ✅ 1. Standard / Django models (lo que ya tenías)
        try:
            standard_choices = get_model_choices()
            lookup_choices.extend(standard_choices)
        except Exception:
            pass

        # ✅ 2. Custom Objects (NUEVO)
        custom_object_choices = [
            (
                f"{obj.name}",          # valor guardado
                f"{obj.name} (Custom Object)" # label visible
            )
            for obj in CustomObject.objects.all()
        ]

        lookup_choices.extend(custom_object_choices)

        # 🔁 Orden opcional (UX)
        lookup_choices = sorted(lookup_choices, key=lambda x: x[1].lower())

        self.fields['lookup_model'].choices = lookup_choices

        def append_classes(widget, *class_names):
            existing = widget.attrs.get('class', '')
            classes = [cls for cls in existing.split() if cls]
            for name in class_names:
                if name not in classes:
                    classes.append(name)
            widget.attrs['class'] = ' '.join(classes)

        for field_name, field in self.fields.items():
            widget = field.widget

            if isinstance(widget, forms.CheckboxInput):
                append_classes(widget, 'cpq-checkbox-input')
                widget.attrs.setdefault('aria-label', field.label)
                continue

            append_classes(widget, 'cpq-input')

            if isinstance(widget, (forms.Select, forms.SelectMultiple)):
                append_classes(widget, 'cpq-select', 'browser-default')

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



#class CustomFieldForm(forms.ModelForm):
#    lookup_model = forms.ChoiceField(
#        required=False,
#        choices=get_model_choices(),  # dynamically populated
#        widget=forms.Select(attrs={'class': 'browser-default'})
#    )
#    data_type = forms.ChoiceField(
#        choices=DATA_TYPE_CHOICES,
#        widget=forms.Select(attrs={'class': 'browser-default'})
#    )
#    crm = forms.ChoiceField(choices=CRM_CHOICES)
#
#    class Meta:
#        model = CustomField
#        fields = [
#            'label', 'name', 'crm', 'object_type',
#            'custom_object', 'data_type', 'required', 'lookup_model'
#        ]
#
#    def __init__(self, *args, **kwargs):
#        super().__init__(*args, **kwargs)
#        self.fields['custom_object'].required = False
#        self.fields['object_type'].required = False
#        self.fields['lookup_model'].required = False
#
#    def clean(self):
#        cleaned_data = super().clean()
#        object_type = cleaned_data.get("object_type")
#        custom_object = cleaned_data.get("custom_object")
#        data_type = cleaned_data.get("data_type")
#        lookup_model = cleaned_data.get("lookup_model")
#
#        if custom_object:
#            cleaned_data["object_type"] = custom_object.name
#
#        if not object_type and not custom_object:
#            raise forms.ValidationError("You must select an Object Type and a Custom Object if required.")
#
#        if data_type == "lookup" and not lookup_model:
#            raise forms.ValidationError("Lookup fields require a lookup model (e.g., cpq.Account).")
#
#        return cleaned_data


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
                    widget = forms.DateInput(attrs={"type": "date", "class": "browser-default"})
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
                        required=field.required,
                        widget=forms.Select(attrs={"class": "browser-default"})
                    )
                    continue
                elif field.data_type == 'lookup':
                    model_class = resolve_lookup_model(field.lookup_model, field_name=field.name, field_label=field.label)
                    target_custom_object = None

                    # Support lookups that target another custom object by name
                    if model_class is None and field.lookup_model:
                        try:
                            target_custom_object = CustomObject.objects.get(name=field.lookup_model)
                            model_class = CustomRecord
                        except CustomObject.DoesNotExist:
                            target_custom_object = None

                    if model_class:
                        qs = model_class.objects.all()
                        if model_class is CustomRecord and target_custom_object:
                            qs = qs.filter(object_type=target_custom_object)

                        self.fields[field.name] = forms.ModelChoiceField(
                            label=field.label or field.name,
                            queryset=qs,
                            required=field.required,
                            widget=forms.Select(attrs={
                                "class": "browser-default lookup-field",
                                "data-lookup-field": "true",
                                "data-field-label": field.label or field.name,
                            })
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
            exclude = ('updated_by', 'created_by', 'created_at', 'updated_at')

        def __init__(self, *args, user=None, **kwargs):
            self.user = user
            super().__init__(*args, **kwargs)
            for field_name in ['created_at', 'updated_at']:
                self.fields.pop(field_name, None)
            User = get_user_model()

            instance = kwargs.get("instance")

            # --- Reemplazar TODOS los DateField por inputs de fecha ---
            for field in model_class._meta.fields:  # 👈 en lugar de fields_map
                if isinstance(field, models.DateField):
                    self.fields[field.name] = forms.DateField(
                        required=not field.blank,
                        initial=getattr(instance, field.name, None) if instance else None,
                        widget=forms.DateInput(attrs={'type': 'date'})
                    )

                if field.name in ["primary_color", "secondary_color"]:
                    self.fields[field.name] = forms.CharField(
                        label=field.verbose_name.title(),
                        required=not field.blank,
                        initial=getattr(instance, field.name, None) if instance else None,
                        widget=forms.TextInput(attrs={"type": "color"})
                    )

            # --- Manejo de due_date ---
            if hasattr(self._meta.model, "due_date"):
                self.fields["due_date"] = forms.DateField(
                    label="Due Date",
                    required=False,
                    initial=instance.due_date if instance else None,
                    widget=forms.DateInput(attrs={"type": "date"})
                )

            # --- Manejo de created_by (readonly visible) ---
            if hasattr(self._meta.model, "created_by"):
                # ❗ Eliminar el campo original del formulario
                self.fields.pop("created_by", None)

                if instance and instance.created_by:
                    display_value = str(instance.created_by)
                    initial_user = instance.created_by
                elif self.user:
                    display_value = str(self.user)
                    initial_user = self.user
                else:
                    display_value = ""
                    initial_user = None

                # Muestra como texto, no como dropdown
                self.fields["created_by_display"] = forms.CharField(
                    label="Created by",
                    initial=display_value,
                    required=False,
                    disabled=True,
                    widget=forms.TextInput(attrs={"readonly": "readonly"})
                )

                # Mantén el verdadero campo oculto (para guardar correctamente)
                self.fields["created_by_hidden"] = forms.ModelChoiceField(
                    queryset=User.objects.all(),
                    initial=initial_user,
                    required=False,
                    widget=forms.HiddenInput()
                )

            # --- Manejo de campos dinámicos ---
            self._custom_fields = CustomField.objects.filter(crm=crm, object_type=object_type)

            for field in self._custom_fields:
                field_name = field.name
                value = self.get_custom_field_value(instance, field) if instance else ""

                if field_name not in self.fields:
                    field_class = DATA_TYPE_MAPPING.get(field.data_type, forms.CharField)
                    widget = WIDGET_MAPPING.get(field.data_type, forms.TextInput())

                    # --- Dropdown ---
                    if field.data_type == "dropdown" and field.options:
                        if not field.required:
                            choices = [("", "---")] + [(opt, opt) for opt in field.options]
                        else:
                            choices = [(opt, opt) for opt in field.options]

                        self.fields[field_name] = field_class(
                            label=field.label or field.name,
                            required=field.required,
                            initial=value if value else "",
                            choices=choices,
                            widget=widget
                        )

                    # --- Lookup (FK) ---
                    elif field.data_type == "lookup":
                        target_custom_object = None
                        lookup_model = resolve_lookup_model(field.lookup_model, field_name=field.name, field_label=field.label)

                        if lookup_model is None and field.lookup_model:
                            try:
                                target_custom_object = CustomObject.objects.get(name=field.lookup_model)
                                lookup_model = CustomRecord
                            except CustomObject.DoesNotExist:
                                target_custom_object = None

                        if lookup_model is not None:
                            qs = lookup_model.objects.all()
                            if lookup_model is CustomRecord and target_custom_object:
                                qs = qs.filter(object_type=target_custom_object)
                            self.fields[field_name] = field_class(
                                label=field.label or field.name,
                                required=field.required,
                                initial=value,
                                queryset=qs,
                                widget=widget
                            )
                        else:
                            # Fallback to a simple text field if the model cannot be resolved
                            self.fields[field_name] = forms.CharField(
                                label=field.label or field.name,
                                required=field.required,
                                initial=value,
                                widget=forms.TextInput(attrs={"class": "w-full border rounded p-2"})
                            )

                    # --- Textarea ---
                    elif field.data_type == "textarea":
                        self.fields[field_name] = field_class(
                            label=field.label or field.name,
                            required=field.required,
                            initial=value,
                            widget=widget
                        )

                    # --- Number / Currency / Percent ---
                    elif field.data_type in {"number", "currency", "percent"}:
                        self.fields[field_name] = field_class(
                            label=field.label or field.name,
                            required=field.required,
                            initial=value,
                            widget=widget
                        )

                    # --- Text (default) ---
                    else:
                        self.fields[field_name] = field_class(
                            label=field.label or field.name,
                            required=field.required,
                            initial=value,
                            widget=widget
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
                instance.created_by = self.cleaned_data.get("created_by_hidden") or self.user

            # --- Asignar updated_by siempre ---
            if hasattr(instance, "updated_by") and self.user:
                instance.updated_by = self.user

            if commit:
                instance.save()

            # --- Guardar CustomFieldValues ---
            content_type = ContentType.objects.get_for_model(instance)
            for field in self._custom_fields:
                value = self.cleaned_data.get(field.name)
                # Guardar None si está vacío
                if value is None:
                    value = ""

                cfv, created = CustomFieldValue.objects.get_or_create(
                    content_type=content_type,
                    object_id=instance.id,
                    field=field,
                )
                if field.data_type == "lookup" and value:
                    value_to_store = str(value.pk)
                elif isinstance(value, bool):
                    value_to_store = str(value)
                else:
                    value_to_store = "" if value is None else str(value)

                cfv.value = value_to_store
                if hasattr(cfv, 'updated_by_user'):
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
