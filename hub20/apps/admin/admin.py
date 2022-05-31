from django.apps import apps
from django.contrib import admin

# De-register all models from other apps
for app_config in apps.get_app_configs():
    for model in app_config.get_models():
        if admin.site.is_registered(model):
            admin.site.unregister(model)
