import copy
import warnings

from django import template
from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured
from django.forms import Media
from django.forms.widgets import Script
from django.utils.module_loading import import_string

from include_media.compat import Stylesheet
from include_media.importmap import ImportmapScript, render_importmap

try:
    from django.utils.csp import CONTEXT_KEY as _CSP_CONTEXT_KEY
except ImportError:
    _CSP_CONTEXT_KEY = "csp_nonce"

register = template.Library()

_COLLECTOR_KEY = "_include_media_collector"

_UNSET = object()
_postprocessor_cache = _UNSET


def _get_postprocessor():
    """
    Return the configured postprocessor callable, or ``None``.
    """
    global _postprocessor_cache
    if _postprocessor_cache is _UNSET:
        path = getattr(django_settings, "INCLUDE_MEDIA_POSTPROCESSOR", None)
        _postprocessor_cache = import_string(path) if path else None
    return _postprocessor_cache


def _on_setting_changed(*, setting, **kwargs):
    """
    Invalidate the cache by Django's ``setting_changed`` signal so that
    ``@override_settings`` works correctly in tests.
    """
    global _postprocessor_cache
    if setting == "INCLUDE_MEDIA_POSTPROCESSOR":
        _postprocessor_cache = _UNSET
    # Signal connection is established in IncludeMediaConfig.ready().


def _apply_nonce(media, nonce):
    def with_nonce(asset, cls):
        if isinstance(asset, str):
            return cls(asset, nonce=nonce)
        new = copy.copy(asset)
        new.attributes = {**asset.attributes, "nonce": nonce}
        return new

    return Media(
        css={
            medium: [with_nonce(a, Stylesheet) for a in assets]
            for medium, assets in media._css.items()
        },
        js=[with_nonce(a, Script) for a in media._js],
    )


class _MediaCollector:
    def __init__(self, initial=None):
        self.media = initial or Media()

    def add(self, media):
        self.media = self.media + media


class IncludeMediaNode(template.Node):
    def __init__(self, nodelist):
        self.nodelist = nodelist

    def render(self, context):
        collector = _MediaCollector()

        for layer in reversed(context.dicts):
            if "page_media" in layer:
                m = layer["page_media"]
                if not isinstance(m, Media):
                    raise ImproperlyConfigured(
                        "page_media in template context must be a Media instance, "
                        f"got {type(m).__name__}"
                    )
                collector.add(m)

        with context.update({_COLLECTOR_KEY: collector}):
            body = self.nodelist.render(context)

        importmap_scripts, regular_js = [], []
        for s in collector.media._js:
            (
                importmap_scripts if isinstance(s, ImportmapScript) else regular_js
            ).append(s)
        nonce = context.get(_CSP_CONTEXT_KEY)
        importmap_html = (
            render_importmap(importmap_scripts, nonce) if importmap_scripts else ""
        )
        regular_media = Media(css=collector.media._css, js=regular_js)
        assets_html = importmap_html + regular_media.render()

        postprocessor = _get_postprocessor()
        if postprocessor is not None:
            assets_html = postprocessor(assets_html, context)
            if not isinstance(assets_html, str):
                raise ImproperlyConfigured(
                    f"INCLUDE_MEDIA_POSTPROCESSOR must return a string, "
                    f"got {type(assets_html).__name__}"
                )

        return assets_html + body


@register.tag("include_media")
def do_include_media(parser, token):
    bits = token.split_contents()
    if len(bits) != 1:
        raise template.TemplateSyntaxError(f"'{bits[0]}' takes no arguments")
    nodelist = parser.parse()
    return IncludeMediaNode(nodelist)


class UseMediaNode(template.Node):
    def __init__(
        self,
        media_expr=None,
        css_expr=None,
        js_expr=None,
        attrs=None,
        csp_nonce_attr=False,
        importmap_expr=None,
    ):
        self.media_expr = media_expr
        self.css_expr = css_expr
        self.js_expr = js_expr
        self.attrs = attrs or {}
        self.csp_nonce_attr = csp_nonce_attr
        self.importmap_expr = importmap_expr

    def _build_media(self, context, nonce=None):
        if self.media_expr is not None:
            media = self.media_expr.resolve(context)
            if not isinstance(media, Media):
                raise template.TemplateSyntaxError(
                    f"{{% use_media %}} expected a Media object, got "
                    f"{type(media).__name__}. Did you forget .media?"
                )
            return _apply_nonce(media, nonce) if nonce else media

        resolved_attrs = {k: v.resolve(context) for k, v in self.attrs.items()}
        extra = {"nonce": nonce} if nonce else {}
        css = {}
        js = []

        if self.css_expr is not None:
            css_val = self.css_expr.resolve(context)
            if not isinstance(css_val, str):
                raise template.TemplateSyntaxError(
                    f"{{% use_media %}} css= expected a path string, "
                    f"got {type(css_val).__name__}."
                )
            css = {"all": [Stylesheet(css_val, **resolved_attrs, **extra)]}

        if self.js_expr is not None:
            js_val = self.js_expr.resolve(context)
            if not isinstance(js_val, str):
                raise template.TemplateSyntaxError(
                    f"{{% use_media %}} js= expected a path string, "
                    f"got {type(js_val).__name__}."
                )
            js = [Script(js_val, **resolved_attrs, **extra)]

        return Media(css=css, js=js)

    def render(self, context):
        collector = context.get(_COLLECTOR_KEY)
        nonce = context.get(_CSP_CONTEXT_KEY) if self.csp_nonce_attr else None

        if self.importmap_expr is not None:
            specifier = self.importmap_expr.resolve(context)
            js_val = self.js_expr.resolve(context)
            if not isinstance(specifier, str):
                raise template.TemplateSyntaxError(
                    f"{{% use_media %}} importmap= expected a string specifier, "
                    f"got {type(specifier).__name__}."
                )
            if not isinstance(js_val, str):
                raise template.TemplateSyntaxError(
                    f"{{% use_media %}} js= expected a path string, "
                    f"got {type(js_val).__name__}."
                )
            script = ImportmapScript(js_val, specifier=specifier)
            if collector is None:
                return render_importmap([script], nonce)
            collector.add(Media(js=[script]))
            return ""

        if collector is None:
            if context.template.engine.debug:
                warnings.warn(
                    "{% use_media %} rendered outside {% include_media %}: assets "
                    "are being output inline. Add {% include_media %} to your base "
                    "template to collect assets into <head>.",
                    UserWarning,
                    stacklevel=2,
                )
            media = self._build_media(context, nonce)
            return "".join(list(media.render_css()) + list(media.render_js()))

        collector.add(self._build_media(context, nonce))
        return ""


@register.tag("use_media")
def do_use_media(parser, token):
    bits = token.split_contents()
    tag_name = bits[0]

    media_expr = None
    css_expr = None
    js_expr = None
    attrs = {}
    csp_nonce_attr = False
    importmap_expr = None

    for bit in bits[1:]:
        if bit == "csp_nonce_attr":
            csp_nonce_attr = True
        elif "=" in bit:
            key, _, value = bit.partition("=")
            if key == "css":
                css_expr = parser.compile_filter(value)
            elif key == "js":
                js_expr = parser.compile_filter(value)
            elif key == "importmap":
                importmap_expr = parser.compile_filter(value)
            else:
                attrs[key] = parser.compile_filter(value)
        else:
            if media_expr is not None:
                raise template.TemplateSyntaxError(
                    f"'{tag_name}' received multiple positional arguments"
                )
            media_expr = parser.compile_filter(bit)

    if importmap_expr is not None:
        if media_expr is not None:
            raise template.TemplateSyntaxError(
                f"'{tag_name}' importmap= cannot be combined with a positional argument"
            )
        if css_expr is not None:
            raise template.TemplateSyntaxError(
                f"'{tag_name}' importmap= cannot be combined with css="
            )
        if js_expr is None:
            raise template.TemplateSyntaxError(f"'{tag_name}' importmap= requires js=")
        if attrs:
            raise template.TemplateSyntaxError(
                f"'{tag_name}' importmap= cannot be combined with extra attributes"
            )
    elif media_expr is not None and (
        css_expr is not None or js_expr is not None or attrs
    ):
        raise template.TemplateSyntaxError(
            f"'{tag_name}' cannot combine a positional argument with keyword arguments"
        )
    elif css_expr is not None and js_expr is not None:
        raise template.TemplateSyntaxError(
            f"'{tag_name}' accepts css= or js= but not both — use separate tags"
        )
    elif attrs and css_expr is None and js_expr is None:
        raise template.TemplateSyntaxError(
            f"'{tag_name}' received attributes without a css= or js= path"
        )
    elif (
        media_expr is None
        and css_expr is None
        and js_expr is None
        and importmap_expr is None
    ):
        raise template.TemplateSyntaxError(
            f"'{tag_name}' requires at least one argument"
        )

    return UseMediaNode(
        media_expr, css_expr, js_expr, attrs, csp_nonce_attr, importmap_expr
    )
