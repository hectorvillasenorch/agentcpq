"""Forms for the dashboard app."""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class SignupForm(UserCreationForm):
    """User creation form that captures profile details."""

    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    email = forms.EmailField(required=True)
    email_consent = forms.BooleanField(
        required=True,
        label="I agree to receive product updates and communications from SympleTech Solutions.",
        error_messages={
            "required": "You must consent to receive communications from SympleTech Solutions to create an account.",
        },
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "filled-in"
                continue

            css_classes = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css_classes} validate".strip()

        self.order_fields([
            "username",
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
            "email_consent",
        ])

    def save(self, commit: bool = True) -> User:
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user
