import copy
import warnings

from django import template
from django.core.exceptions import ImproperlyConfigured
from django.forms import Media
from django.forms.widgets import MediaAsset, Script

from include_media.compat import Stylesheet

try:
    from django.utils.csp import CONTEXT_KEY as _CSP_CONTEXT_KEY
except ImportError:
    _CSP_CONTEXT_KEY = "csp_nonce"

register = template.Library()

_COLLECTOR_KEY = "_include_media_collector"


def _apply_nonce(media, nonce):
    def with_nonce(asset):
        if not hasattr(asset, "attributes"):
            return asset
        new = copy.copy(asset)
        new.attributes = {**asset.attributes, "nonce": nonce}
        return new

    return Media(
        css={
            medium: [with_nonce(a) for a in assets]
            for medium, assets in media._css.items()
        },
        js=[with_nonce(a) for a in media._js],
    )


class _MediaCollector:
    __slots__ = ("media",)

    def __init__(self, initial=None):
        self.media = initial or Media()

    def add(self, media):
        self.media = self.media + media


class IncludeMediaNode(template.Node):
    def __init__(self, nodelist):
        self.nodelist = nodelist

    def render(self, context):
        existing = None
        for layer in reversed(context.dicts):
            if "page_media" in layer:
                m = layer["page_media"]
                if not isinstance(m, Media):
                    raise ImproperlyConfigured(
                        "page_media in template context must be a Media instance, "
                        f"got {type(m).__name__}"
                    )
                existing = (existing + m) if existing is not None else m

        collector = _MediaCollector(existing)

        with context.update({_COLLECTOR_KEY: collector}):
            body = self.nodelist.render(context)

        return collector.media.render() + body


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
    ):
        self.media_expr = media_expr
        self.css_expr = css_expr
        self.js_expr = js_expr
        self.attrs = attrs or {}
        self.csp_nonce_attr = csp_nonce_attr

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
            if isinstance(css_val, str):
                css_val = Stylesheet(css_val, **resolved_attrs, **extra)
            elif isinstance(css_val, MediaAsset):
                if resolved_attrs:
                    raise template.TemplateSyntaxError(
                        "{% use_media %} cannot apply extra attributes to a pre-built "
                        "Stylesheet object; pass them when constructing it instead."
                    )
            else:
                raise template.TemplateSyntaxError(
                    f"{{% use_media %}} css= expected a path string or Stylesheet, "
                    f"got {type(css_val).__name__}."
                )
            css = {"all": [css_val]}

        if self.js_expr is not None:
            js_val = self.js_expr.resolve(context)
            if isinstance(js_val, str):
                js_val = Script(js_val, **resolved_attrs, **extra)
            elif isinstance(js_val, Script):
                if resolved_attrs:
                    raise template.TemplateSyntaxError(
                        "{% use_media %} cannot apply extra attributes to a pre-built "
                        "Script object; pass them when constructing it instead."
                    )
            else:
                raise template.TemplateSyntaxError(
                    f"{{% use_media %}} js= expected a path string or Script, "
                    f"got {type(js_val).__name__}."
                )
            js = [js_val]

        return Media(css=css, js=js)

    def render(self, context):
        collector = context.get(_COLLECTOR_KEY)
        nonce = context.get(_CSP_CONTEXT_KEY) if self.csp_nonce_attr else None

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

    for bit in bits[1:]:
        if bit == "csp_nonce_attr":
            csp_nonce_attr = True
        elif "=" in bit:
            key, _, value = bit.partition("=")
            if key == "css":
                css_expr = parser.compile_filter(value)
            elif key == "js":
                js_expr = parser.compile_filter(value)
            else:
                attrs[key] = parser.compile_filter(value)
        else:
            if media_expr is not None:
                raise template.TemplateSyntaxError(
                    f"'{tag_name}' received multiple positional arguments"
                )
            media_expr = parser.compile_filter(bit)

    if media_expr is not None and (
        css_expr is not None or js_expr is not None or attrs
    ):
        raise template.TemplateSyntaxError(
            f"'{tag_name}' cannot combine a positional argument with keyword arguments"
        )
    if css_expr is not None and js_expr is not None:
        raise template.TemplateSyntaxError(
            f"'{tag_name}' accepts css= or js= but not both — use separate tags"
        )
    if attrs and css_expr is None and js_expr is None:
        raise template.TemplateSyntaxError(
            f"'{tag_name}' received attributes without a css= or js= path"
        )
    if media_expr is None and css_expr is None and js_expr is None:
        raise template.TemplateSyntaxError(
            f"'{tag_name}' requires at least one argument"
        )

    return UseMediaNode(media_expr, css_expr, js_expr, attrs, csp_nonce_attr)
