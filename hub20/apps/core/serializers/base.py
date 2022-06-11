from rest_framework import serializers


class PolymorphicModelSerializer(serializers.ModelSerializer):
    @classmethod
    def get_subclassed_serializer(cls, obj):
        """
        Finds which derived serializer to use for the model, based on the
        model type defined by `Meta`
        """
        return {c.Meta.model: c for c in cls.__subclasses__()}.get(type(obj), cls)
