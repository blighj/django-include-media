import json

from django.forms.widgets import Script
from django.utils.html import escape

_json_script_escapes = {
    ord(">"): "\\u003e",
    ord("<"): "\\u003c",
    ord("&"): "\\u0026",
}


def render_importmap(scripts, nonce=None):
    entries = {}
    for s in scripts:
        if s._importmap_specifier not in entries:
            entries[s._importmap_specifier] = s.path
    content = json.dumps({"imports": entries}).translate(_json_script_escapes)
    nonce_attr = f' nonce="{escape(nonce)}"' if nonce else ""
    return f'<script type="importmap"{nonce_attr}>{content}</script>\n'


class ImportmapScript(Script):
    """
    A Script variant that registers as an importmap entry instead of rendering
    a <script src> tag.

    Use in Widget.media, Form.media, or page_media to declare that a JS file
    should be available under a bare module specifier::

        from include_media import ImportmapScript

        class MyWidget(Widget):
            class Media:
                js = [ImportmapScript("vendor/htmx.js", specifier="htmx")]

    The specifier is the bare name used in ``import "htmx"`` statements.
    The path follows the same rules as a regular Script path — relative paths
    are resolved through staticfiles, absolute URLs are used as-is.
    """

    def __init__(self, path, specifier, **attributes):
        self._importmap_specifier = specifier
        super().__init__(path, **attributes)

    def __eq__(self, other):
        return (
            self.__class__ is other.__class__
            and self._path == other._path
            and self._importmap_specifier == other._importmap_specifier
            and self.attributes == other.attributes
        )

    def __hash__(self):
        if self.attributes:
            return (
                hash(self._path)
                ^ hash(self._importmap_specifier)
                ^ hash(frozenset(self.attributes.items()))
            )
        return hash(self._path) ^ hash(self._importmap_specifier)
