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

### Import maps

`{% include_media %}` can generate a `<script type="importmap">` tag,
letting templates and reusable components declare their ES module specifiers
in the same places they already declare CSS and JS assets. All entries from
across the template hierarchy are merged into a single importmap tag, placed
before other assets in `<head>`.

**Template tag** — for one-off or inline declarations:

```html
{% use_media js="vendor/htmx.js" importmap="htmx" %}
{% use_media js="https://cdn.example.com/lodash.js" importmap="lodash" %}
```

**`ImportmapScript`** — for reusable widgets and forms that need a module
specifier wherever they are used:

```python
from django.forms import Form
from include_media import ImportmapScript

class DatePickerForm(Form):
    class Media:
        js = [
            ImportmapScript("vendor/pikaday.js", specifier="pikaday"),
            Script("datepicker/widget.js", type="module"),
        ]
```

To hook up a JS build system's manifest, you could add `ImportmapScript`
entries to `page_media` from a context processor:

```python
import json
from pathlib import Path
from django.forms import Media
from include_media import ImportmapScript

_manifest = json.loads((BASE_DIR / "static/dist/manifest.json").read_text())

def importmap(request):
    return {
        "page_media": Media(js=[
            ImportmapScript(f"/static/dist/{entry['file']}", specifier=name)
            for name, entry in _manifest.items()
        ])
    }
```

**Merging and precedence** — all sources (template tags, `ImportmapScript` in
`page_media`) are merged into one `<script type="importmap">` tag with
first-wins semantics: `page_media` is processed before template tags, so
view-level declarations take precedence when the same specifier appears in
multiple places.

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

## Changelog

### 0.1.0 — (Initial version)

- Provide template tags `{% include_media %}` and `{% use_media %}` for collecting Django Media assets into `<head>`
- Supports CSS, JavaScript, and arbitrary HTML attributes on individual assets
- CSP nonce support avialable via `csp_nonce_attr` flag on `{% use_media %}`
- Import map support via `importmap=` keyword and `ImportmapScript`
- Site-wide media via `page_media` context variable; merges with template-level assets
- `{% use_media %}` falls back to rendering inline with debug-mode warning, if the include is not there.
