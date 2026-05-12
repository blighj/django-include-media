# django-include-media

A Django third-party app that allows templates and components to declare asset
requirements using Django's `forms.Media` object, with automatic collection and
deduplication, outputting assets into `<head>` without any post-processing of
the HTTP response.

## Installation

```bash
pip install django-include-media
```

Add to `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    ...
    "include_media",
]
```

## Usage

Place `{% include_media %}` in `<head>` of your base template. It renders the
rest of the page as its nodelist, collects all declared assets, then outputs
them followed by the rendered body — no middleware, no two-pass rendering.

```html
{# base.html #}
{% load include_media_tags %}
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    {% include_media %}
</head>
<body>
    {% block content %}{% endblock %}
</body>
</html>
```

### Site-wide assets

Declare assets required on every page in a context processor:

```python
# myproject/context_processors.py
from django.forms import Media
from django.forms.widgets import Script
from include_media import Stylesheet

def site_media(request):
    media = Media(
        css={"all":[Stylesheet("base.css")]},
        js=[Script("base.js", type="module")],
    )
    if request.user.is_authenticated:
        media += Media(js=[Script("dashboard.js", type="module")])
    return {"page_media": media}
```

```python
TEMPLATES = [{
    "OPTIONS": {
        "context_processors": [
            ...
            "myproject.context_processors.site_media",
        ],
    },
}]
```

### View-level assets

Pass `page_media` via `get_context_data`. If a site-wide context processor
also sets `page_media`, the two are merged automatically:

```python
from django.forms import Media
from django.forms.widgets import Script
from include_media import Stylesheet
from django.views.generic import TemplateView

class DatePickerView(TemplateView):
    template_name = "datepicker.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_media"] = Media(
            css={"all":[Stylesheet("datepicker/datepicker.css")]},
            js=[Script("datepicker/datepicker.js", type="module")],
        )
        return ctx
```

### Component and template assets

Declare assets inline with `{% use_media %}`. Assets are deduplicated by
object identity — including the same component twice renders its assets once:

```html
{% load include_media_tags %}
{% use_media form.media %}
{% use_media css="myapp/widget.css" %}
{% use_media js="myapp/widget.js" type="module" %}
```

## Compatibility

- Python 3.10+
- Django 5.2, 6.0, 6.1+ (`Stylesheet` is backported for Django < 6.1)
- csp_nonce_attr is not backported and only supported by 6.1

## License

BSD 3-Clause License
