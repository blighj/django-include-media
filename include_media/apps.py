from django.apps import AppConfig


class IncludeMediaConfig(AppConfig):
    name = "include_media"
    verbose_name = "Include Media"

    def ready(self):
        # setting_changed lives under django.test but fires in production too —
        # it is the correct signal for invalidating caches when settings change.
        from django.test.signals import setting_changed

        from include_media.templatetags.include_media_tags import _on_setting_changed

        setting_changed.connect(_on_setting_changed)

        from django.core.checks import Tags, register

        register(_check_postprocessor_setting, Tags.compatibility)


def _check_postprocessor_setting(app_configs, **kwargs):
    from django.conf import settings
    from django.core.checks import Error
    from django.utils.module_loading import import_string

    path = getattr(settings, "INCLUDE_MEDIA_POSTPROCESSOR", None)
    if path is None:
        return []

    if not isinstance(path, str):
        return [
            Error(
                "INCLUDE_MEDIA_POSTPROCESSOR must be a dotted Python path string.",
                id="include_media.E001",
            )
        ]

    try:
        obj = import_string(path)
    except ImportError as e:
        return [
            Error(
                f"INCLUDE_MEDIA_POSTPROCESSOR '{path}' cannot be imported: {e}",
                id="include_media.E002",
            )
        ]

    if not callable(obj):
        return [
            Error(
                f"INCLUDE_MEDIA_POSTPROCESSOR '{path}' must be callable, "
                f"got {type(obj).__name__}.",
                id="include_media.E003",
            )
        ]

    return []
