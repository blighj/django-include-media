"""Tests for {% include_media %} and {% use_media %} template tags."""

import unittest

from django.core.exceptions import ImproperlyConfigured
from django.forms import Form, Media
from django.forms.widgets import Script
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings

from include_media.compat import Stylesheet

try:
    from django.utils.csp import CONTEXT_KEY as CSP_CONTEXT_KEY

    HAS_CSP = True
except ImportError:
    HAS_CSP = False
    CSP_CONTEXT_KEY = "csp_nonce"  # dummy so tests can still reference it


def locmem_templates(templates, debug=False):
    """TEMPLATES setting that loads templates from an in-memory dict."""
    return [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [],
            "APP_DIRS": False,
            "OPTIONS": {
                "debug": debug,
                "loaders": [
                    ("django.template.loaders.locmem.Loader", templates),
                ],
            },
        }
    ]


# ---------------------------------------------------------------------------
# Template fixtures
# ---------------------------------------------------------------------------

# Flat page: include_media in head, use_media in body.
SINGLE_PAGE = """\
{% load include_media_tags %}
<!DOCTYPE html>
<html>
<head>{% include_media %}</head>
<body>
{% use_media css="myapp/style.css" %}
{% use_media js="myapp/script.js" %}
<p>Hello</p>
</body>
</html>
"""

# Base template used by extends tests.
BASE = """\
{% load include_media_tags %}
<!DOCTYPE html>
<html>
<head>{% include_media %}</head>
<body>{% block content %}{% endblock %}</body>
</html>
"""

# Child that extends BASE and declares assets inside a block.
CHILD_EXTENDS = """\
{% extends "base.html" %}
{% load include_media_tags %}
{% block content %}
{% use_media css="child/style.css" %}
{% use_media js="child/script.js" %}
<p>Child content</p>
{% endblock %}
"""

# Reusable component that declares its own asset.
COMPONENT = """\
{% load include_media_tags %}
{% use_media css="component/style.css" %}
<div class="component">Component</div>
"""

# Flat page that {% include %}s a component.
PAGE_WITH_INCLUDE = """\
{% load include_media_tags %}
<!DOCTYPE html>
<html>
<head>{% include_media %}</head>
<body>{% include "component.html" %}</body>
</html>
"""

# Child that extends BASE and also {% include %}s a component.
CHILD_EXTENDS_WITH_INCLUDE = """\
{% extends "base.html" %}
{% load include_media_tags %}
{% block content %}
{% include "component.html" %}
{% include "component.html" %}
<p>Page content</p>
{% endblock %}
"""

# Minimal page for context-based tests (no use_media in template).
PLAIN_PAGE = """\
{% load include_media_tags %}
<!DOCTYPE html>
<html>
<head>{% include_media %}</head>
<body><p>Hello</p></body>
</html>
"""

# Page that passes form.media to use_media.
FORM_PAGE = """\
{% load include_media_tags %}
<!DOCTYPE html>
<html>
<head>{% include_media %}</head>
<body>
{% use_media form.media %}
{{ form.as_p }}
<p>Hello</p>
</body>
</html>
"""

# Page for site-wide + template-level merge test.
SITE_WIDE_PAGE = """\
{% load include_media_tags %}
<!DOCTYPE html>
<html>
<head>{% include_media %}</head>
<body>
{% use_media css="page/style.css" %}
<p>Hello</p>
</body>
</html>
"""

# Page using the "as" clause to expose the collected Media object.
AS_CLAUSE_PAGE = """\
{% load include_media_tags %}
<!DOCTYPE html>
<html>
<head>{% include_media as page_media %}</head>
<body>
{% use_media css="as/style.css" %}
{% use_media js="as/script.js" %}
<p>Hello</p>
</body>
</html>
"""

# "as" clause with csp_nonce_attr (csp_nonce_attr is a Django builtin tag).
AS_CLAUSE_WITH_NONCE_PAGE = """\
{% load include_media_tags %}
<!DOCTYPE html>
<html>
<head>{% include_media as page_media %}{% csp_nonce_attr page_media %}</head>
<body>
{% use_media js="widget.js" %}
{% use_media css="widget.css" %}
<p>Hello</p>
</body>
</html>
"""

# Template with use_media but no include_media.
ORPHAN_USE_MEDIA = """\
{% load include_media_tags %}
<div>
{% use_media css="orphan/style.css" %}
Hello
</div>
"""

# Component used via {% include "..." only %}.
ONLY_COMPONENT = """\
{% load include_media_tags %}
{% use_media css="only/style.css" %}
<div>Only content</div>
"""

# Page that includes a component with the "only" option.
PAGE_WITH_ONLY_INCLUDE = """\
{% load include_media_tags %}
<!DOCTYPE html>
<html>
<head>{% include_media %}</head>
<body>{% include "only_component.html" only %}</body>
</html>
"""

# Page for dedup-across-sources test.
SHARED_JS_PAGE = """\
{% load include_media_tags %}
<!DOCTYPE html>
<html>
<head>{% include_media %}</head>
<body>
{% use_media js="shared.js" %}
<p>Hello</p>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Form / widget fixtures
# ---------------------------------------------------------------------------


class ContactForm(Form):
    """Form whose media we can assert on."""

    class Media:
        css = {"all": [Stylesheet("form/form.css")]}
        js = [Script("form/form.js")]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": SINGLE_PAGE}),
)
class SinglePageTests(SimpleTestCase):
    """Flat template: include_media in head, use_media inline in body."""

    def test_css_collected_into_head(self):
        html = render_to_string("page.html")
        self.assertInHTML(
            '<link href="/static/myapp/style.css" rel="stylesheet">', html
        )

    def test_js_collected_into_head(self):
        html = render_to_string("page.html")
        self.assertInHTML('<script src="/static/myapp/script.js"></script>', html)

    def test_assets_appear_before_body_content(self):
        html = render_to_string("page.html")
        self.assertLess(html.index("myapp/style.css"), html.index("<p>Hello</p>"))

    def test_body_content_still_rendered(self):
        html = render_to_string("page.html")
        self.assertInHTML("<p>Hello</p>", html)


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"base.html": BASE, "child.html": CHILD_EXTENDS}),
)
class ExtendsTests(SimpleTestCase):
    """Child template extends base; use_media lives inside a block."""

    def test_css_from_child_block_in_head(self):
        html = render_to_string("child.html")
        self.assertInHTML(
            '<link href="/static/child/style.css" rel="stylesheet">', html
        )

    def test_js_from_child_block_in_head(self):
        html = render_to_string("child.html")
        self.assertInHTML('<script src="/static/child/script.js"></script>', html)

    def test_block_content_rendered_in_body(self):
        html = render_to_string("child.html")
        self.assertInHTML("<p>Child content</p>", html)


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates(
        {"page.html": PAGE_WITH_INCLUDE, "component.html": COMPONENT}
    ),
)
class IncludesTests(SimpleTestCase):
    """Flat page that includes a component; component declares use_media."""

    def test_included_component_css_in_head(self):
        html = render_to_string("page.html")
        self.assertInHTML(
            '<link href="/static/component/style.css" rel="stylesheet">', html
        )

    def test_component_body_rendered(self):
        html = render_to_string("page.html")
        self.assertInHTML('<div class="component">Component</div>', html)


class ExtendsWithIncludeTests(SimpleTestCase):
    """Child extends base AND includes a component; both media sources collected."""

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates(
            {
                "base.html": BASE,
                "page.html": CHILD_EXTENDS_WITH_INCLUDE,
                "component.html": COMPONENT,
            }
        ),
    )
    def test_component_css_in_head(self):
        html = render_to_string("page.html")
        self.assertInHTML(
            '<link href="/static/component/style.css" rel="stylesheet">', html
        )

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates(
            {
                "base.html": BASE,
                "page.html": CHILD_EXTENDS_WITH_INCLUDE,
                "component.html": COMPONENT,
            }
        ),
    )
    def test_duplicate_include_deduplicates_assets(self):
        """Component included twice; its CSS link appears exactly once."""
        html = render_to_string("page.html")
        self.assertEqual(html.count("/static/component/style.css"), 1)

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates(
            {
                "base.html": BASE,
                "page.html": CHILD_EXTENDS_WITH_INCLUDE,
                "component.html": COMPONENT,
            }
        ),
    )
    def test_component_html_rendered_twice(self):
        """Assets are deduplicated but the component HTML still appears twice."""
        html = render_to_string("page.html")
        self.assertEqual(html.count('<div class="component">Component</div>'), 2)


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": PLAIN_PAGE}),
)
class ViewMediaTests(SimpleTestCase):
    """page_media passed in context, as a view would via get_context_data."""

    def test_view_css_in_head(self):
        context = {"page_media": Media(css={"all": [Stylesheet("view/style.css")]})}
        html = render_to_string("page.html", context)
        self.assertInHTML('<link href="/static/view/style.css" rel="stylesheet">', html)

    def test_view_js_in_head(self):
        context = {"page_media": Media(js=[Script("view/script.js", type="module")])}
        html = render_to_string("page.html", context)
        self.assertInHTML(
            '<script src="/static/view/script.js" type="module"></script>', html
        )

    def test_no_page_media_in_context_renders_cleanly(self):
        """include_media initialises page_media itself if absent from context."""
        html = render_to_string("page.html", {})
        self.assertInHTML("<p>Hello</p>", html)


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": FORM_PAGE}),
)
class FormMediaTests(SimpleTestCase):
    """use_media form.media collects assets declared on a form."""

    def test_form_css_in_head(self):
        html = render_to_string("page.html", {"form": ContactForm()})
        self.assertInHTML('<link href="/static/form/form.css" rel="stylesheet">', html)

    def test_form_js_in_head(self):
        html = render_to_string("page.html", {"form": ContactForm()})
        self.assertInHTML('<script src="/static/form/form.js"></script>', html)

    def test_form_html_rendered_in_body(self):
        html = render_to_string("page.html", {"form": ContactForm()})
        self.assertInHTML("<p>Hello</p>", html)


class SiteWideMediaTests(SimpleTestCase):
    """page_media set in context (site-wide) merges with use_media from template."""

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": SITE_WIDE_PAGE}),
    )
    def test_site_wide_css_in_head(self):
        context = {"page_media": Media(css={"all": [Stylesheet("site/global.css")]})}
        html = render_to_string("page.html", context)
        self.assertInHTML(
            '<link href="/static/site/global.css" rel="stylesheet">', html
        )

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": SITE_WIDE_PAGE}),
    )
    def test_template_level_css_in_head(self):
        context = {"page_media": Media(css={"all": [Stylesheet("site/global.css")]})}
        html = render_to_string("page.html", context)
        self.assertInHTML('<link href="/static/page/style.css" rel="stylesheet">', html)

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": SITE_WIDE_PAGE}),
    )
    def test_site_wide_and_template_both_present(self):
        """Both site-wide and template-level assets appear in the same head."""
        context = {"page_media": Media(css={"all": [Stylesheet("site/global.css")]})}
        html = render_to_string("page.html", context)
        self.assertInHTML(
            '<link href="/static/site/global.css" rel="stylesheet">', html
        )
        self.assertInHTML('<link href="/static/page/style.css" rel="stylesheet">', html)

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": SHARED_JS_PAGE}),
    )
    def test_dedup_across_context_and_use_media(self):
        """Script in context page_media and via use_media appears exactly once."""
        shared = Script("shared.js")
        context = {"page_media": Media(js=[shared])}
        html = render_to_string("page.html", context)
        self.assertEqual(html.count("/static/shared.js"), 1)


@override_settings(STATIC_URL="/static/")
class AsClauseTests(SimpleTestCase):
    """{% include_media as varname %} exposes the collected Media in context."""

    @override_settings(
        TEMPLATES=locmem_templates({"page.html": AS_CLAUSE_PAGE}),
    )
    def test_css_still_collected_into_head(self):
        html = render_to_string("page.html")
        self.assertInHTML('<link href="/static/as/style.css" rel="stylesheet">', html)

    @override_settings(
        TEMPLATES=locmem_templates({"page.html": AS_CLAUSE_PAGE}),
    )
    def test_js_still_collected_into_head(self):
        html = render_to_string("page.html")
        self.assertInHTML('<script src="/static/as/script.js"></script>', html)

    @override_settings(
        TEMPLATES=locmem_templates({"page.html": AS_CLAUSE_PAGE}),
    )
    def test_body_still_rendered(self):
        html = render_to_string("page.html")
        self.assertInHTML("<p>Hello</p>", html)

    @override_settings(
        TEMPLATES=locmem_templates({"page.html": AS_CLAUSE_PAGE}),
    )
    def test_assets_appear_before_body_content(self):
        html = render_to_string("page.html")
        self.assertLess(html.index("as/style.css"), html.index("<p>Hello</p>"))


@unittest.skipUnless(HAS_CSP, "requires Django CSP nonce support (Django 6.1+)")
@override_settings(STATIC_URL="/static/")
class CspNonceTests(SimpleTestCase):
    @override_settings(
        TEMPLATES=locmem_templates({"page.html": AS_CLAUSE_WITH_NONCE_PAGE}),
    )
    def test_nonce_applied_to_script(self):
        html = render_to_string("page.html", {CSP_CONTEXT_KEY: "testtoken"})
        self.assertInHTML(
            '<script src="/static/widget.js" nonce="testtoken"></script>', html
        )

    @override_settings(
        TEMPLATES=locmem_templates({"page.html": AS_CLAUSE_WITH_NONCE_PAGE}),
    )
    def test_nonce_applied_to_stylesheet(self):
        html = render_to_string("page.html", {CSP_CONTEXT_KEY: "testtoken"})
        self.assertInHTML(
            '<link href="/static/widget.css" rel="stylesheet" nonce="testtoken">', html
        )

    @override_settings(
        TEMPLATES=locmem_templates({"page.html": AS_CLAUSE_WITH_NONCE_PAGE}),
    )
    def test_assets_present_without_nonce_in_context(self):
        """Without a nonce in context, assets still render (no nonce attribute)."""
        html = render_to_string("page.html", {})
        self.assertInHTML('<script src="/static/widget.js"></script>', html)
        self.assertInHTML('<link href="/static/widget.css" rel="stylesheet">', html)

    @override_settings(
        TEMPLATES=locmem_templates({"page.html": AS_CLAUSE_WITH_NONCE_PAGE}),
    )
    def test_assets_appear_before_body_content(self):
        html = render_to_string("page.html", {CSP_CONTEXT_KEY: "tok"})
        self.assertLess(html.index("widget.js"), html.index("<p>Hello</p>"))


class UseMediaOutsideIncludeMediaTests(SimpleTestCase):
    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": ORPHAN_USE_MEDIA}, debug=True),
    )
    def test_warns_and_renders_inline_in_debug(self):
        with self.assertWarns(UserWarning) as cm:
            html = render_to_string("page.html")
        self.assertIn("Hello", html)
        self.assertInHTML(
            '<link href="/static/orphan/style.css" rel="stylesheet">', html
        )
        self.assertIn("include_media", str(cm.warning))

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": ORPHAN_USE_MEDIA}, debug=False),
    )
    def test_renders_inline_silently_in_production(self):
        html = render_to_string("page.html")
        self.assertIn("Hello", html)
        self.assertInHTML(
            '<link href="/static/orphan/style.css" rel="stylesheet">', html
        )

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates(
            {
                "page.html": PAGE_WITH_ONLY_INCLUDE,
                "only_component.html": ONLY_COMPONENT,
            },
            debug=True,
        ),
    )
    def test_only_include_warns_in_debug(self):
        """use_media inside {% include '...' only %} behaves like an orphan."""
        with self.assertWarns(UserWarning):
            html = render_to_string("page.html")
        self.assertIn("only/style.css", html)

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates(
            {
                "page.html": PAGE_WITH_ONLY_INCLUDE,
                "only_component.html": ONLY_COMPONENT,
            },
            debug=False,
        ),
    )
    def test_only_include_renders_inline_silently_in_production(self):
        html = render_to_string("page.html")
        self.assertIn("only/style.css", html)


@override_settings(STATIC_URL="/static/")
class AssetAttributesTests(SimpleTestCase):
    """Arbitrary HTML attributes passed via use_media kwargs reach Script/Stylesheet."""

    @override_settings(
        TEMPLATES=locmem_templates(
            {
                "page.html": (
                    "{% load include_media_tags %}"
                    "<!DOCTYPE html><html>"
                    "<head>{% include_media %}</head>"
                    "<body>"
                    '{% use_media js="widget.js" type="module" %}'
                    "</body></html>"
                )
            }
        ),
    )
    def test_js_string_attribute(self):
        html = render_to_string("page.html")
        self.assertInHTML(
            '<script src="/static/widget.js" type="module"></script>', html
        )

    @override_settings(
        TEMPLATES=locmem_templates(
            {
                "page.html": (
                    "{% load include_media_tags %}"
                    "<!DOCTYPE html><html>"
                    "<head>{% include_media %}</head>"
                    "<body>"
                    '{% use_media css="print.css" media="print" %}'
                    "</body></html>"
                )
            }
        ),
    )
    def test_css_string_attribute(self):
        html = render_to_string("page.html")
        self.assertInHTML(
            '<link href="/static/print.css" rel="stylesheet" media="print">', html
        )

    @override_settings(
        TEMPLATES=locmem_templates(
            {
                "page.html": (
                    "{% load include_media_tags %}"
                    "<!DOCTYPE html><html>"
                    "<head>{% include_media %}</head>"
                    "<body>"
                    '{% use_media js=existing_script type="module" %}'
                    "</body></html>"
                )
            },
            debug=True,
        ),
    )
    def test_attrs_on_prebuilt_script_raises(self):
        """Extra attrs alongside a pre-built Script object raise an error."""
        from django.template import TemplateSyntaxError

        with self.assertRaises(TemplateSyntaxError):
            render_to_string("page.html", {"existing_script": Script("widget.js")})

    @override_settings(
        TEMPLATES=locmem_templates(
            {
                "page.html": (
                    "{% load include_media_tags %}"
                    "<!DOCTYPE html><html>"
                    "<head>{% include_media %}</head>"
                    "<body>"
                    '{% use_media css=existing_sheet media="print" %}'
                    "</body></html>"
                )
            },
            debug=True,
        ),
    )
    def test_attrs_on_prebuilt_stylesheet_raises(self):
        """Extra attrs alongside a pre-built Stylesheet object raise an error."""
        from django.template import TemplateSyntaxError

        with self.assertRaises(TemplateSyntaxError):
            render_to_string("page.html", {"existing_sheet": Stylesheet("print.css")})


@override_settings(STATIC_URL="/static/")
class ErrorHandlingTests(SimpleTestCase):
    """Error paths: wrong page_media type, non-Media positional arg."""

    @override_settings(
        TEMPLATES=locmem_templates({"page.html": PLAIN_PAGE}),
    )
    def test_raises_when_page_media_not_media_instance(self):
        with self.assertRaises(ImproperlyConfigured):
            render_to_string("page.html", {"page_media": "not a media object"})

    @override_settings(
        TEMPLATES=locmem_templates(
            {
                "page.html": (
                    "{% load include_media_tags %}"
                    "<!DOCTYPE html><html>"
                    "<head>{% include_media %}</head>"
                    "<body>{% use_media form %}</body>"
                    "</html>"
                )
            },
            debug=True,
        ),
    )
    def test_non_media_positional_arg_raises_in_debug(self):
        """{% use_media form %} (forgetting .media) raises in debug mode."""
        from django.template import TemplateSyntaxError

        with self.assertRaises(TemplateSyntaxError):
            render_to_string("page.html", {"form": ContactForm()})

    @override_settings(
        TEMPLATES=locmem_templates(
            {
                "page.html": (
                    "{% load include_media_tags %}"
                    "<!DOCTYPE html><html>"
                    "<head>{% include_media %}</head>"
                    "<body>{% use_media form %}</body>"
                    "</html>"
                )
            },
            debug=False,
        ),
    )
    def test_non_media_positional_arg_silent_in_production(self):
        """{% use_media form %} is a silent no-op in production."""
        html = render_to_string("page.html", {"form": ContactForm()})
        self.assertNotIn("form/form.css", html)
        self.assertNotIn("form/form.js", html)
