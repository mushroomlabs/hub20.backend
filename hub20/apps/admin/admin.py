from django.apps import apps
from django.contrib import admin
from django.contrib.auth import get_user_model

User = get_user_model()

# De-register all models from other apps
for app_config in apps.get_app_configs():
    for model in app_config.get_models():
        if admin.site.is_registered(model):
            admin.site.unregister(model)


admin.site.register(User)
