import warnings

from django import template
from django.core.exceptions import ImproperlyConfigured
from django.forms import Media
from django.forms.widgets import Script

from include_media.compat import Stylesheet

register = template.Library()

_COLLECTOR_KEY = "_include_media_collector"


def _get_debug(context):
    try:
        return context.template.engine.debug
    except AttributeError:
        from django.template import Engine

        return Engine.get_default().debug


class _MediaCollector:
    """Mutable accumulator shared by reference across all context frames.

    Stored as a mutable object so use_media can accumulate from within
    block, include, and other context-pushing scopes without reassigning
    the context key (which would only affect the innermost frame).

    Also acts as a proxy for csp_nonce_attr: when the tag calls
    collector.render(attrs=...) it captures the nonce attrs and returns an
    empty string; IncludeMediaNode renders the final media with those attrs
    after the body has been fully collected.
    """

    __slots__ = ("media", "_nonce_captured", "_nonce_attrs")

    def __init__(self, initial=None):
        self.media = initial or Media()
        self._nonce_captured = False
        self._nonce_attrs = None

    def add(self, media):
        self.media = self.media + media

    def render(self, *, attrs=None):
        self._nonce_captured = True
        self._nonce_attrs = attrs
        return ""


class IncludeMediaNode(template.Node):
    def __init__(self, nodelist, var_name=None):
        self.nodelist = nodelist
        self.var_name = var_name

    def render(self, context):
        existing = context.get("page_media")
        if existing is not None and not isinstance(existing, Media):
            raise ImproperlyConfigured(
                "page_media in template context must be a Media instance, "
                f"got {type(existing).__name__}"
            )

        collector = _MediaCollector(existing)

        ctx_update = {_COLLECTOR_KEY: collector}
        if self.var_name:
            # Expose the collector under var_name before body render so that
            # {% csp_nonce_attr page_media %} can call collector.render() and
            # capture the nonce.  The collector is replaced with the final
            # Media object in the outer context after body render.
            ctx_update[self.var_name] = collector

        with context.update(ctx_update):
            body = self.nodelist.render(context)

        page_media = collector.media

        if self.var_name:
            context[self.var_name] = page_media

        if collector._nonce_captured:
            return page_media.render(attrs=collector._nonce_attrs) + body

        css = list(page_media.render_css())
        js = list(page_media.render_js())
        return "".join(css + js) + body


@register.tag("include_media")
def do_include_media(parser, token):
    bits = token.split_contents()
    var_name = None
    if len(bits) == 3 and bits[1] == "as":
        var_name = bits[2]
    elif len(bits) != 1:
        raise template.TemplateSyntaxError(
            f"'{bits[0]}' takes no arguments or 'as <var_name>'"
        )
    nodelist = parser.parse()
    return IncludeMediaNode(nodelist, var_name)


class UseMediaNode(template.Node):
    def __init__(self, media_expr=None, css_expr=None, js_expr=None, attrs=None):
        self.media_expr = media_expr
        self.css_expr = css_expr
        self.js_expr = js_expr
        self.attrs = attrs or {}  # {attr_name: FilterExpression}

    def _build_media(self, context):
        """Resolve expressions and return a Media object, or None if invalid."""
        if self.media_expr is not None:
            media = self.media_expr.resolve(context)
            if isinstance(media, Media):
                return media
            if _get_debug(context):
                raise template.TemplateSyntaxError(
                    f"{{% use_media %}} expected a Media object, got "
                    f"{type(media).__name__}. Did you forget .media?"
                )
            return None

        resolved_attrs = {k: v.resolve(context) for k, v in self.attrs.items()}
        css = {}
        js = []

        if self.css_expr is not None:
            css_val = self.css_expr.resolve(context)
            if isinstance(css_val, str):
                css_val = Stylesheet(css_val, **resolved_attrs)
            elif resolved_attrs:
                raise template.TemplateSyntaxError(
                    "{% use_media %} cannot apply extra attributes to a pre-built "
                    "Stylesheet object; pass them when constructing it instead."
                )
            css = {"all": [css_val]}

        if self.js_expr is not None:
            js_val = self.js_expr.resolve(context)
            if isinstance(js_val, str):
                js_val = Script(js_val, **resolved_attrs)
            elif resolved_attrs:
                raise template.TemplateSyntaxError(
                    "{% use_media %} cannot apply extra attributes to a pre-built "
                    "Script object; pass them when constructing it instead."
                )
            js = [js_val]

        return Media(css=css, js=js)

    def render(self, context):
        collector = context.get(_COLLECTOR_KEY)
        if collector is None:
            if _get_debug(context):
                warnings.warn(
                    "{% use_media %} rendered outside {% include_media %}: assets "
                    "are being output inline. Add {% include_media %} to your base "
                    "template to collect assets into <head>.",
                    UserWarning,
                    stacklevel=2,
                )
            media = self._build_media(context)
            if media is None:
                return ""
            return "".join(list(media.render_css()) + list(media.render_js()))

        media = self._build_media(context)
        if media is not None:
            collector.add(media)
        return ""


@register.tag("use_media")
def do_use_media(parser, token):
    bits = token.split_contents()
    tag_name = bits[0]

    media_expr = None
    css_expr = None
    js_expr = None
    attrs = {}

    for bit in bits[1:]:
        if "=" in bit:
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

    return UseMediaNode(media_expr, css_expr, js_expr, attrs)
