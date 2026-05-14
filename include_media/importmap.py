from django.forms.widgets import Script


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
            type(self) is type(other)
            and self._path == other._path
            and self._importmap_specifier == other._importmap_specifier
        )

    def __hash__(self):
        return hash((type(self), self._path, self._importmap_specifier))
