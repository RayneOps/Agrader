from django import forms
from django.contrib.auth.forms import AuthenticationForm


class EmailLoginForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email", "inputmode": "email"}),
    )

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()
