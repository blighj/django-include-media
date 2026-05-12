# Stylesheet was added as a named class in Django 6.1. This shim provides it
# for older versions. Can be removed once Django 6.1 is the minimum version.
try:
    from django.forms.widgets import Stylesheet
except ImportError:
    from django.forms.widgets import MediaAsset

    class Stylesheet(MediaAsset):
        element_template = '<link href="{path}"{attributes}>'

        def __init__(self, href, **attributes):
            super().__init__(path=href, rel="stylesheet", **attributes)
