"""Tests for {% include_media %} and {% use_media %} template tags."""

import unittest
import warnings

from django.core.exceptions import ImproperlyConfigured
from django.forms import Form, Media
from django.forms.widgets import Script
from django.template import Context, Template, TemplateSyntaxError
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, override_settings

from include_media import register
from include_media.compat import Stylesheet
from include_media.context_processors import registered_media
from include_media.importmap import ImportmapScript, render_importmap
from include_media.registry import _clear, _get_registered_media

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


def page(body, head="{% include_media %}"):
    return (
        "{% load include_media_tags %}"
        "<!DOCTYPE html><html>"
        f"<head>{head}</head>"
        f"<body>{body}</body>"
        "</html>"
    )


# ---------------------------------------------------------------------------
# Template fixtures
# ---------------------------------------------------------------------------

SINGLE_PAGE = page(
    '{% use_media css="myapp/style.css" %}'
    '{% use_media js="myapp/script.js" %}'
    "<p>Hello</p>"
)

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

PAGE_WITH_INCLUDE = page('{% include "component.html" %}')

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

PLAIN_PAGE = page("<p>Hello</p>")
FORM_PAGE = page("{% use_media form.media %}{{ form.as_p }}<p>Hello</p>")
SITE_WIDE_PAGE = page('{% use_media css="page/style.css" %}<p>Hello</p>')
SHARED_JS_PAGE = page('{% use_media js="shared.js" %}<p>Hello</p>')

USE_MEDIA_NONCE_PAGE = page(
    '{% use_media js="widget.js" csp_nonce_attr %}'
    '{% use_media css="widget.css" csp_nonce_attr %}'
    "<p>Hello</p>"
)
FORM_NONCE_PAGE = page("{% use_media form.media csp_nonce_attr %}<p>Hello</p>")
MIXED_NONCE_PAGE = page(
    '{% use_media js="nonce.js" csp_nonce_attr %}'
    '{% use_media js="no-nonce.js" %}'
    "<p>Hello</p>"
)

# Orphan templates (no include_media).
ORPHAN_USE_MEDIA = (
    "{% load include_media_tags %}"
    "<div>"
    '{% use_media css="orphan/style.css" %}'
    "Hello"
    "</div>"
)
ORPHAN_NONCE_PAGE = (
    "{% load include_media_tags %}"
    "<div>"
    '{% use_media js="orphan/script.js" csp_nonce_attr %}'
    "Hello"
    "</div>"
)
ORPHAN_IMPORTMAP_PAGE = (
    "{% load include_media_tags %}"
    "<div>"
    '{% use_media js="vendor/react.js" importmap="react" %}'
    "Hello"
    "</div>"
)

# Component used via {% include "..." only %}.
ONLY_COMPONENT = (
    "{% load include_media_tags %}"
    '{% use_media css="only/style.css" %}'
    "<div>Only content</div>"
)
PAGE_WITH_ONLY_INCLUDE = page('{% include "only_component.html" only %}')

# Importmap fixtures.
IMPORTMAP_PAGE = page(
    '{% use_media js="vendor/react.js" importmap="react" %}'
    '{% use_media js="vendor/lodash.js" importmap="lodash" %}'
    "<p>Hello</p>"
)
IMPORTMAP_WITH_REGULAR_ASSETS_PAGE = page(
    '{% use_media js="vendor/react.js" importmap="react" %}'
    '{% use_media css="app/style.css" %}'
    '{% use_media js="app/main.js" type="module" %}'
    "<p>Hello</p>"
)
IMPORTMAP_DEDUP_PAGE = page(
    '{% use_media js="vendor/react.js" importmap="react" %}'
    '{% use_media js="vendor/react-alt.js" importmap="react" %}'
    "<p>Hello</p>"
)
IMPORTMAP_CDN_PAGE = page(
    '{% use_media js="https://cdn.example.com/react.js" importmap="react" %}'
    "<p>Hello</p>"
)
IMPORTMAP_NONCE_PAGE = page(
    '{% use_media js="vendor/react.js" importmap="react" %}' "<p>Hello</p>"
)

# Asset-attribute fixtures.
ATTR_JS_PAGE = page('{% use_media js="widget.js" type="module" %}')
ATTR_CSS_PAGE = page('{% use_media css="print.css" media="print" %}')
ATTR_JS_NONSTRING_PAGE = page("{% use_media js=existing_script %}")
ATTR_CSS_NONSTRING_PAGE = page("{% use_media css=existing_sheet %}")


# ---------------------------------------------------------------------------
# Form / widget fixtures
# ---------------------------------------------------------------------------


class ContactForm(Form):
    """Form whose media we can assert on."""

    class Media:
        css = {"all": [Stylesheet("form/form.css")]}
        js = [Script("form/form.js")]


class ModuleForm(Form):
    class Media:
        js = [ImportmapScript("vendor/htmx.js", specifier="htmx")]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": SINGLE_PAGE}),
)
class SinglePageTests(SimpleTestCase):
    def test_renders_assets_in_head_before_body(self):
        html = render_to_string("page.html")
        self.assertInHTML(
            '<link href="/static/myapp/style.css" rel="stylesheet">', html
        )
        self.assertInHTML('<script src="/static/myapp/script.js"></script>', html)
        self.assertLess(html.index("myapp/style.css"), html.index("<p>Hello</p>"))


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"base.html": BASE, "child.html": CHILD_EXTENDS}),
)
class ExtendsTests(SimpleTestCase):
    def test_child_block_assets_in_head(self):
        html = render_to_string("child.html")
        self.assertInHTML(
            '<link href="/static/child/style.css" rel="stylesheet">', html
        )
        self.assertInHTML('<script src="/static/child/script.js"></script>', html)
        self.assertInHTML("<p>Child content</p>", html)


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates(
        {"page.html": PAGE_WITH_INCLUDE, "component.html": COMPONENT}
    ),
)
class IncludesTests(SimpleTestCase):
    def test_included_component_css_in_head(self):
        html = render_to_string("page.html")
        self.assertInHTML(
            '<link href="/static/component/style.css" rel="stylesheet">', html
        )
        self.assertInHTML('<div class="component">Component</div>', html)


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
class ExtendsWithIncludeTests(SimpleTestCase):
    def test_component_css_in_head(self):
        html = render_to_string("page.html")
        self.assertInHTML(
            '<link href="/static/component/style.css" rel="stylesheet">', html
        )

    def test_duplicate_include_deduplicates_assets(self):
        html = render_to_string("page.html")
        self.assertEqual(html.count("/static/component/style.css"), 1)

    def test_component_html_rendered_twice(self):
        html = render_to_string("page.html")
        self.assertEqual(html.count('<div class="component">Component</div>'), 2)


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": PLAIN_PAGE}),
)
class ViewMediaTests(SimpleTestCase):
    def test_view_media_rendered(self):
        context = {"page_media": Media(css={"all": [Stylesheet("view/style.css")]})}
        html = render_to_string("page.html", context)
        self.assertInHTML('<link href="/static/view/style.css" rel="stylesheet">', html)

    def test_no_page_media_in_context_renders_cleanly(self):
        html = render_to_string("page.html", {})
        self.assertInHTML("<p>Hello</p>", html)


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": FORM_PAGE}),
)
class FormMediaTests(SimpleTestCase):
    def test_form_media_collected(self):
        html = render_to_string("page.html", {"form": ContactForm()})
        self.assertInHTML('<link href="/static/form/form.css" rel="stylesheet">', html)
        self.assertInHTML('<script src="/static/form/form.js"></script>', html)


@override_settings(STATIC_URL="/static/")
class SiteWideMediaTests(SimpleTestCase):
    @override_settings(TEMPLATES=locmem_templates({"page.html": SITE_WIDE_PAGE}))
    def test_site_wide_and_template_both_present(self):
        context = {"page_media": Media(css={"all": [Stylesheet("site/global.css")]})}
        html = render_to_string("page.html", context)
        self.assertInHTML(
            '<link href="/static/site/global.css" rel="stylesheet">', html
        )
        self.assertInHTML('<link href="/static/page/style.css" rel="stylesheet">', html)

    @override_settings(TEMPLATES=locmem_templates({"page.html": SHARED_JS_PAGE}))
    def test_dedup_across_context_and_use_media(self):
        shared = Script("shared.js")
        context = {"page_media": Media(js=[shared])}
        html = render_to_string("page.html", context)
        self.assertEqual(html.count("/static/shared.js"), 1)


class MultiLayerPageMediaTests(SimpleTestCase):
    @override_settings(STATIC_URL="/static/")
    def test_both_layers_appear_in_output(self):
        tmpl = Template("{% load include_media_tags %}{% include_media %}<body></body>")
        ctx = Context({"page_media": Media(js=[Script("view.js")])})
        ctx.update({"page_media": Media(css={"all": [Stylesheet("site/global.css")]})})
        html = tmpl.render(ctx)
        self.assertInHTML('<script src="/static/view.js"></script>', html)
        self.assertInHTML(
            '<link href="/static/site/global.css" rel="stylesheet">', html
        )

    @override_settings(STATIC_URL="/static/")
    def test_higher_layer_assets_come_first(self):
        tmpl = Template("{% load include_media_tags %}{% include_media %}<body></body>")
        ctx = Context({"page_media": Media(js=[Script("view.js")])})
        ctx.update({"page_media": Media(js=[Script("site.js")])})
        html = tmpl.render(ctx)
        self.assertLess(html.index("site.js"), html.index("view.js"))

    @override_settings(STATIC_URL="/static/")
    def test_invalid_page_media_in_any_layer_raises(self):
        tmpl = Template("{% load include_media_tags %}{% include_media %}<body></body>")
        ctx = Context({"page_media": "not-a-media"})
        ctx.update({"page_media": Media()})
        with self.assertRaises(ImproperlyConfigured):
            tmpl.render(ctx)

    @override_settings(STATIC_URL="/static/")
    def test_dedup_across_layers(self):
        tmpl = Template("{% load include_media_tags %}{% include_media %}<body></body>")
        shared = Script("shared.js")
        ctx = Context({"page_media": Media(js=[shared])})
        ctx.update({"page_media": Media(js=[shared])})
        html = tmpl.render(ctx)
        self.assertEqual(html.count("/static/shared.js"), 1)


@unittest.skipUnless(HAS_CSP, "requires Django CSP nonce support (Django 6.1+)")
@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": USE_MEDIA_NONCE_PAGE}),
)
class CspNonceTests(SimpleTestCase):
    def test_nonce_applied_to_assets(self):
        html = render_to_string("page.html", {CSP_CONTEXT_KEY: "testtoken"})
        self.assertInHTML(
            '<script src="/static/widget.js" nonce="testtoken"></script>', html
        )
        self.assertInHTML(
            '<link href="/static/widget.css" rel="stylesheet" nonce="testtoken">', html
        )
        self.assertLess(html.index("widget.js"), html.index("<p>Hello</p>"))

    def test_assets_present_without_nonce_in_context(self):
        html = render_to_string("page.html", {})
        self.assertInHTML('<script src="/static/widget.js"></script>', html)
        self.assertInHTML('<link href="/static/widget.css" rel="stylesheet">', html)

    @override_settings(TEMPLATES=locmem_templates({"page.html": FORM_NONCE_PAGE}))
    def test_nonce_applied_to_form_media(self):
        html = render_to_string(
            "page.html", {CSP_CONTEXT_KEY: "testtoken", "form": ContactForm()}
        )
        self.assertInHTML(
            '<script src="/static/form/form.js" nonce="testtoken"></script>', html
        )
        self.assertInHTML(
            '<link href="/static/form/form.css" rel="stylesheet" nonce="testtoken">',
            html,
        )

    @override_settings(TEMPLATES=locmem_templates({"page.html": FORM_NONCE_PAGE}))
    def test_nonce_applied_to_string_assets(self):
        """Plain string assets in Media are upgraded to Script/Stylesheet with nonce."""

        class LegacyForm(Form):
            class Media:
                css = {"all": ["legacy/style.css"]}
                js = ["legacy/script.js"]

        html = render_to_string(
            "page.html", {CSP_CONTEXT_KEY: "testtoken", "form": LegacyForm()}
        )
        self.assertInHTML(
            '<script src="/static/legacy/script.js" nonce="testtoken"></script>', html
        )
        self.assertInHTML(
            '<link href="/static/legacy/style.css" rel="stylesheet"'
            'media="all" nonce="testtoken">',
            html,
        )

    @override_settings(
        TEMPLATES=locmem_templates({"page.html": ORPHAN_NONCE_PAGE}, debug=False)
    )
    def test_nonce_applied_in_inline_fallback(self):
        html = render_to_string("page.html", {CSP_CONTEXT_KEY: "testtoken"})
        self.assertInHTML(
            '<script src="/static/orphan/script.js" nonce="testtoken"></script>', html
        )

    @override_settings(TEMPLATES=locmem_templates({"page.html": MIXED_NONCE_PAGE}))
    def test_nonce_not_applied_to_tag_without_flag(self):
        html = render_to_string("page.html", {CSP_CONTEXT_KEY: "testtoken"})
        self.assertInHTML(
            '<script src="/static/nonce.js" nonce="testtoken"></script>', html
        )
        self.assertInHTML('<script src="/static/no-nonce.js"></script>', html)


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


# ---------------------------------------------------------------------------
# Importmap tests
# ---------------------------------------------------------------------------


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": IMPORTMAP_PAGE}),
)
class ImportmapTests(SimpleTestCase):
    def test_importmap_rendered(self):
        html = render_to_string("page.html")
        self.assertIn('<script type="importmap">', html)
        self.assertEqual(html.count('<script type="importmap">'), 1)
        self.assertIn('"react"', html)
        self.assertIn('"/static/vendor/react.js"', html)
        self.assertIn('"lodash"', html)
        self.assertIn('"/static/vendor/lodash.js"', html)
        self.assertNotIn('src="/static/vendor/react.js"', html)
        self.assertNotIn('src="/static/vendor/lodash.js"', html)


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": IMPORTMAP_WITH_REGULAR_ASSETS_PAGE}),
)
class ImportmapWithRegularAssetsTests(SimpleTestCase):
    def test_importmap_before_regular_assets(self):
        html = render_to_string("page.html")
        self.assertLess(
            html.index('<script type="importmap">'), html.index("app/style.css")
        )
        self.assertLess(
            html.index('<script type="importmap">'), html.index("app/main.js")
        )
        self.assertInHTML('<link href="/static/app/style.css" rel="stylesheet">', html)
        self.assertInHTML(
            '<script src="/static/app/main.js" type="module"></script>', html
        )


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": IMPORTMAP_DEDUP_PAGE}),
)
class ImportmapDedupTests(SimpleTestCase):
    def test_first_specifier_wins(self):
        html = render_to_string("page.html")
        self.assertIn('"/static/vendor/react.js"', html)
        self.assertNotIn("react-alt", html)


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": IMPORTMAP_CDN_PAGE}),
)
class ImportmapCdnUrlTests(SimpleTestCase):
    def test_absolute_url_used_verbatim(self):
        html = render_to_string("page.html")
        self.assertIn('"https://cdn.example.com/react.js"', html)
        self.assertNotIn("/static/https", html)


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": PLAIN_PAGE}),
)
class NoImportmapTests(SimpleTestCase):
    def test_no_importmap_tag_when_no_entries(self):
        html = render_to_string("page.html")
        self.assertNotIn('type="importmap"', html)


class ImportmapOrphanTests(SimpleTestCase):
    def test_renders_inline(self):
        for debug in (True, False):
            with self.subTest(debug=debug):
                with override_settings(
                    STATIC_URL="/static/",
                    TEMPLATES=locmem_templates(
                        {"page.html": ORPHAN_IMPORTMAP_PAGE}, debug=debug
                    ),
                ):
                    with warnings.catch_warnings():
                        warnings.simplefilter("error")
                        html = render_to_string("page.html")
                    self.assertIn('<script type="importmap">', html)
                    self.assertIn('"/static/vendor/react.js"', html)


@unittest.skipUnless(HAS_CSP, "requires Django CSP nonce support (Django 6.1+)")
@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": IMPORTMAP_NONCE_PAGE}),
)
class ImportmapNonceTests(SimpleTestCase):
    def test_nonce_applied_to_importmap_tag(self):
        html = render_to_string("page.html", {CSP_CONTEXT_KEY: "testnonce"})
        self.assertIn('<script type="importmap" nonce="testnonce">', html)

    def test_no_nonce_attr_when_no_nonce_in_context(self):
        html = render_to_string("page.html", {})
        self.assertIn('<script type="importmap">', html)
        self.assertNotIn("nonce=", html)


class ImportmapScriptTests(SimpleTestCase):
    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": FORM_PAGE}),
    )
    def test_importmap_script_in_form_media(self):
        html = render_to_string("page.html", {"form": ModuleForm()})
        self.assertIn('<script type="importmap">', html)
        self.assertIn('"htmx"', html)
        self.assertIn('"/static/vendor/htmx.js"', html)
        self.assertNotIn('src="/static/vendor/htmx.js"', html)

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": PLAIN_PAGE}),
    )
    def test_importmap_script_in_page_media(self):
        context = {
            "page_media": Media(
                js=[ImportmapScript("vendor/htmx.js", specifier="htmx")]
            )
        }
        html = render_to_string("page.html", context)
        self.assertIn('"htmx"', html)
        self.assertIn('"/static/vendor/htmx.js"', html)
        self.assertNotIn('src="/static/vendor/htmx.js"', html)

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": PLAIN_PAGE}),
    )
    def test_regular_scripts_alongside_importmap_scripts(self):
        context = {
            "page_media": Media(
                js=[
                    ImportmapScript("vendor/htmx.js", specifier="htmx"),
                    Script("app/main.js"),
                ]
            )
        }
        html = render_to_string("page.html", context)
        self.assertIn('"htmx"', html)
        self.assertInHTML('<script src="/static/app/main.js"></script>', html)
        self.assertNotIn('src="/static/vendor/htmx.js"', html)

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": PLAIN_PAGE}),
    )
    def test_importmap_script_dedup_by_specifier_and_path(self):
        entry = ImportmapScript("vendor/htmx.js", specifier="htmx")
        context = {"page_media": Media(js=[entry, entry])}
        html = render_to_string("page.html", context)
        self.assertEqual(html.count('"htmx"'), 1)

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": PLAIN_PAGE}),
    )
    def test_importmap_script_and_template_tag_same_specifier_first_wins(self):
        context = {
            "page_media": Media(
                js=[ImportmapScript("vendor/htmx-1.js", specifier="htmx")]
            ),
        }
        tmpl = Template(
            "{% load include_media_tags %}{% include_media %}"
            '{% use_media js="vendor/htmx-2.js" importmap="htmx" %}'
        )
        html = tmpl.render(Context(context))
        self.assertIn('"htmx"', html)
        self.assertIn('"/static/vendor/htmx-1.js"', html)
        self.assertNotIn("htmx-2", html)


@override_settings(STATIC_URL="/static/")
class ImportmapJsonEscapingTests(SimpleTestCase):
    def test_angle_brackets_and_ampersand_escaped(self):
        s = ImportmapScript("vendor/a.js", specifier="a<b>&<c")
        html = render_importmap([s])
        self.assertNotIn("<b>", html)
        self.assertNotIn("&<", html)
        self.assertIn("\\u003c", html)
        self.assertIn("\\u003e", html)
        self.assertIn("\\u0026", html)

    def test_script_breakout_blocked(self):
        s = ImportmapScript("vendor/a.js", specifier="</script><script>alert(1)")
        html = render_importmap([s])
        # Exactly one </script> — the legitimate closing tag, no injected breakout.
        self.assertEqual(html.count("</script>"), 1)
        # No raw <script> injection inside the JSON body.
        self.assertEqual(html.count("<script>"), 0)


class ImportmapParseErrorTests(SimpleTestCase):
    @override_settings(STATIC_URL="/static/")
    def test_importmap_parse_errors(self):
        bad = [
            '{% use_media importmap="react" %}',
            '{% use_media css="app.css" importmap="react" %}',
            '{% use_media some_media importmap="react" %}',
            '{% use_media js="react.js" importmap="react" integrity="sha256-abc" %}',
        ]
        for snippet in bad:
            with self.subTest(snippet=snippet):
                with self.assertRaises(TemplateSyntaxError):
                    Template("{% load include_media_tags %}" + snippet)


@override_settings(STATIC_URL="/static/")
class AssetAttributesTests(SimpleTestCase):
    @override_settings(TEMPLATES=locmem_templates({"page.html": ATTR_JS_PAGE}))
    def test_js_string_attribute(self):
        html = render_to_string("page.html")
        self.assertInHTML(
            '<script src="/static/widget.js" type="module"></script>', html
        )

    @override_settings(TEMPLATES=locmem_templates({"page.html": ATTR_CSS_PAGE}))
    def test_css_string_attribute(self):
        html = render_to_string("page.html")
        self.assertInHTML(
            '<link href="/static/print.css" rel="stylesheet" media="print">', html
        )

    @override_settings(
        TEMPLATES=locmem_templates({"page.html": ATTR_JS_NONSTRING_PAGE}, debug=True)
    )
    def test_non_string_js_raises(self):
        with self.assertRaises(TypeError):
            render_to_string("page.html", {"existing_script": Script("widget.js")})

    @override_settings(
        TEMPLATES=locmem_templates({"page.html": ATTR_CSS_NONSTRING_PAGE}, debug=True)
    )
    def test_non_string_css_raises(self):
        with self.assertRaises(TypeError):
            render_to_string("page.html", {"existing_sheet": Stylesheet("print.css")})


@override_settings(STATIC_URL="/static/")
class ErrorHandlingTests(SimpleTestCase):
    @override_settings(TEMPLATES=locmem_templates({"page.html": PLAIN_PAGE}))
    def test_raises_when_page_media_not_media_instance(self):
        with self.assertRaises(ImproperlyConfigured):
            render_to_string("page.html", {"page_media": "not a media object"})

    def test_include_media_with_args_raises(self):
        with self.assertRaises(TemplateSyntaxError):
            Template("{% load include_media_tags %}{% include_media arg %}")

    def test_use_media_parse_errors(self):
        bad = [
            "{% use_media form form %}",
            '{% use_media form css="x.css" %}',
            '{% use_media css="x.css" js="x.js" %}',
            '{% use_media type="module" %}',
            "{% use_media %}",
        ]
        for snippet in bad:
            with self.subTest(snippet=snippet):
                with self.assertRaises(TemplateSyntaxError):
                    Template("{% load include_media_tags %}" + snippet)

    @override_settings(
        TEMPLATES=locmem_templates(
            {"page.html": page("{% use_media form %}", head="{% include_media %}")},
            debug=True,
        ),
    )
    def test_non_media_positional_arg_raises(self):
        with self.assertRaises(TypeError):
            render_to_string("page.html", {"form": ContactForm()})

    @override_settings(
        TEMPLATES=locmem_templates(
            {"page.html": page("{% use_media js=js_path importmap=specifier %}")},
            debug=True,
        )
    )
    def test_non_string_importmap_specifier_raises(self):
        with self.assertRaises(TypeError):
            render_to_string("page.html", {"js_path": "react.js", "specifier": 42})

    @override_settings(
        TEMPLATES=locmem_templates(
            {"page.html": page('{% use_media js=js_path importmap="react" %}')},
            debug=True,
        )
    )
    def test_non_string_importmap_js_raises(self):
        with self.assertRaises(TypeError):
            render_to_string("page.html", {"js_path": Script("react.js")})


# ---------------------------------------------------------------------------
# Registry and context processor tests
# ---------------------------------------------------------------------------


class RegisterTests(SimpleTestCase):
    def setUp(self):
        _clear()

    def tearDown(self):
        _clear()

    def test_register_valid_media(self):
        register(Media(js=[Script("myapp/base.js")]))
        self.assertIn(Script("myapp/base.js"), _get_registered_media()._js)

    def test_register_non_media_raises(self):
        with self.assertRaises(TypeError):
            register("not-a-media")

    def test_register_non_media_error_message(self):
        with self.assertRaises(TypeError) as cm:
            register(42)
        self.assertIn("int", str(cm.exception))

    def test_multiple_registrations_accumulated(self):
        register(Media(js=[Script("a.js")]))
        register(Media(css={"all": [Stylesheet("b.css")]}))
        combined = _get_registered_media()
        self.assertIn(Script("a.js"), combined._js)
        self.assertIn(Stylesheet("b.css"), combined._css["all"])

    def test_get_registered_media_merges_all(self):
        register(Media(js=[Script("a.js")]))
        register(Media(css={"all": [Stylesheet("b.css")]}))
        combined = _get_registered_media()
        self.assertIn(Script("a.js"), combined._js)
        self.assertIn(Stylesheet("b.css"), combined._css["all"])

    def test_get_registered_media_empty_registry(self):
        combined = _get_registered_media()
        self.assertEqual(combined._js, [])
        self.assertEqual(combined._css, {})

    def test_clear_empties_registry(self):
        register(Media(js=[Script("a.js")]))
        _clear()
        self.assertEqual(_get_registered_media()._js, [])


class RegisteredMediaContextProcessorTests(SimpleTestCase):
    def setUp(self):
        _clear()
        self.request = RequestFactory().get("/")

    def tearDown(self):
        _clear()

    def test_returns_empty_dict_when_nothing_registered(self):
        self.assertEqual(registered_media(self.request), {})

    def test_returns_page_media_when_registered(self):
        register(Media(js=[Script("myapp/base.js")]))
        result = registered_media(self.request)
        self.assertIn("page_media", result)
        self.assertIsInstance(result["page_media"], Media)

    def test_returned_media_contains_registered_assets(self):
        register(Media(js=[Script("myapp/base.js")]))
        register(Media(css={"all": [Stylesheet("myapp/base.css")]}))
        result = registered_media(self.request)
        self.assertIn(Script("myapp/base.js"), result["page_media"]._js)
        self.assertIn(Stylesheet("myapp/base.css"), result["page_media"]._css["all"])

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": PLAIN_PAGE}),
    )
    def test_registered_media_renders_in_template(self):
        register(Media(js=[Script("myapp/base.js")]))
        ctx = registered_media(self.request)
        html = render_to_string("page.html", ctx)
        self.assertInHTML('<script src="/static/myapp/base.js"></script>', html)

    @override_settings(
        STATIC_URL="/static/",
        TEMPLATES=locmem_templates({"page.html": SITE_WIDE_PAGE}),
    )
    def test_merges_with_template_level_media(self):
        register(Media(js=[Script("myapp/base.js")]))
        ctx = registered_media(self.request)
        html = render_to_string("page.html", ctx)
        self.assertInHTML('<script src="/static/myapp/base.js"></script>', html)
        self.assertInHTML('<link href="/static/page/style.css" rel="stylesheet">', html)

    @override_settings(STATIC_URL="/static/")
    def test_context_processor_and_view_page_media_both_rendered(self):
        register(Media(js=[Script("app/base.js")]))
        cp_ctx = registered_media(self.request)
        tmpl = Template("{% load include_media_tags %}{% include_media %}<body></body>")
        ctx = Context({"page_media": Media(css={"all": [Stylesheet("view/view.css")]})})
        ctx.update(cp_ctx)
        html = tmpl.render(ctx)
        self.assertInHTML('<script src="/static/app/base.js"></script>', html)
        self.assertInHTML('<link href="/static/view/view.css" rel="stylesheet">', html)


# ---------------------------------------------------------------------------
# Postprocessor hook tests
# ---------------------------------------------------------------------------

# Module-level helpers referenced by dotted path in INCLUDE_MEDIA_POSTPROCESSOR.
_capture_calls = []


def _capture_postprocessor(html, context):
    _capture_calls.append((html, context))
    return html


def _replace_postprocessor(html, context):
    return "REPLACED"


def _none_postprocessor(html, context):
    return None


def _raising_postprocessor(html, context):
    raise ValueError("boom")


_NOT_CALLABLE = "not a callable"
MODULE_PATH = "include_media_tests.test_include_media"


@override_settings(
    STATIC_URL="/static/",
    TEMPLATES=locmem_templates({"page.html": SINGLE_PAGE}),
)
class PostprocessorTests(SimpleTestCase):
    def setUp(self):
        _capture_calls.clear()

    def test_no_setting_renders_normally(self):
        html = render_to_string("page.html")
        self.assertInHTML(
            '<link href="/static/myapp/style.css" rel="stylesheet">', html
        )
        self.assertInHTML('<script src="/static/myapp/script.js"></script>', html)

    @override_settings(
        INCLUDE_MEDIA_POSTPROCESSOR=f"{MODULE_PATH}._capture_postprocessor"
    )
    def test_postprocessor_called_with_assets_html_and_context(self):
        render_to_string("page.html", {"sentinel": "hello"})
        self.assertEqual(len(_capture_calls), 1)
        assets_html, ctx = _capture_calls[0]
        self.assertIn("myapp/style.css", assets_html)
        self.assertIn("myapp/script.js", assets_html)
        self.assertEqual(ctx["sentinel"], "hello")

    @override_settings(
        INCLUDE_MEDIA_POSTPROCESSOR=f"{MODULE_PATH}._replace_postprocessor"
    )
    def test_postprocessor_return_value_replaces_assets(self):
        html = render_to_string("page.html")
        self.assertIn("REPLACED", html)
        self.assertNotIn("myapp/style.css", html)
        self.assertNotIn("myapp/script.js", html)

    @override_settings(
        INCLUDE_MEDIA_POSTPROCESSOR=f"{MODULE_PATH}._capture_postprocessor"
    )
    def test_body_content_still_rendered(self):
        html = render_to_string("page.html")
        self.assertIn("<p>Hello</p>", html)

    @override_settings(INCLUDE_MEDIA_POSTPROCESSOR=f"{MODULE_PATH}._none_postprocessor")
    def test_postprocessor_returning_none_raises_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured) as cm:
            render_to_string("page.html")
        self.assertIn("NoneType", str(cm.exception))

    @override_settings(
        INCLUDE_MEDIA_POSTPROCESSOR=f"{MODULE_PATH}._raising_postprocessor"
    )
    def test_postprocessor_exception_propagates(self):
        with self.assertRaises(ValueError, msg="boom"):
            render_to_string("page.html")


@override_settings(STATIC_URL="/static/")
class PostprocessorSystemCheckTests(SimpleTestCase):
    def _run_checks(self):
        from django.core.checks import run_checks

        return [e for e in run_checks() if e.id and e.id.startswith("include_media.")]

    def test_no_setting_passes(self):
        self.assertEqual(self._run_checks(), [])

    @override_settings(
        INCLUDE_MEDIA_POSTPROCESSOR=f"{MODULE_PATH}._capture_postprocessor"
    )
    def test_valid_callable_passes(self):
        self.assertEqual(self._run_checks(), [])

    @override_settings(INCLUDE_MEDIA_POSTPROCESSOR="does.not.exist")
    def test_bad_import_path_raises_E002(self):
        errors = self._run_checks()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "include_media.E002")

    @override_settings(INCLUDE_MEDIA_POSTPROCESSOR=f"{MODULE_PATH}._NOT_CALLABLE")
    def test_non_callable_raises_E003(self):
        errors = self._run_checks()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "include_media.E003")
