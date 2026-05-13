# Django include media

An app for Django that allows templates and views to add Script/Stylesheets to
a page using Django's `forms.Media` object, with automatic collection and
deduplication, outputting assets into `<head>`. Inspired by django-sekizai.

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

Place `{% include_media %}` in `<head>` of your base template. Then use the
`use_media` templatetag or `page_media` context to add the assets you need.

All your sub-templates or templates from templatetags can now reliably add
assets to the page.

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

### Component and template assets

Declare assets inline with `{% use_media %}`. Assets are deduplicated by
object identity, including the same component twice will only renders its
assets once:

```html
{% load include_media_tags %}
{% use_media form.media %}
{% use_media css="myapp/widget.css" %}
{% use_media js="myapp/script.js" %}
```

Extra HTML attributes can be passed as keyword arguments and are forwarded
to the rendered tag. Add `csp_nonce_attr` to opt a specific asset into
Django's CSP nonce (Django 6.0+); the nonce is applied if `csp_nonce` is
present in the template context and is a no-op otherwise:

```html
{% use_media js="myapp/widget.js" type="module" %}
{% use_media js="myapp/widget.js" type="module" csp_nonce_attr %}
{% use_media css="myapp/widget.css" media="print" %}
{% use_media form.media csp_nonce_attr %}
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

### Site-wide assets

Declare assets required on every page in a context processor:

```python
# myproject/context_processors.py
from django.forms import Media
from django.forms.widgets import Script
from include_media import Stylesheet

def site_media(request):
    nonce = getattr(request, "csp_nonce", None)
    attrs = {"nonce": nonce} if nonce else {}
    media = Media(
        css={"all":[Stylesheet("base.css", **attrs)]},
        js=[Script("base.js", type="module", **attrs)],
    )
    if request.user.is_authenticated:
        media += Media(js=[Script("dashboard.js", type="module", **attrs)])
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

## Compatibility

- Python 3.10+
- Django 5.2, 6.0+ (`Stylesheet` is backported for Django < 6.1)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
The aim of this repo is to explore this idea and if it feels right to
propose it back to django core, where it could be implemented cleaner.
Any feedback is welcome.

## License

BSD 3-Clause License
