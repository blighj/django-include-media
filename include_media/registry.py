"""
Process-global registry of Media objects contributed by installed apps.

Apps call :func:`register` exactly once, from ``AppConfig.ready()``.  Do not
call it during request handling — the registry is read on every request and
writes after startup will race with those reads.

Thread-safety: writes happen only at startup (single-threaded), reads are
concurrent but lock-free because the list is never mutated after startup.
"""

from django.forms import Media

_registered = []


def register(media):
    """
    Add a :class:`~django.forms.Media` instance to the global registry.

    Call this from ``AppConfig.ready()`` to contribute assets that should
    appear on every page::

        class MyAppConfig(AppConfig):
            def ready(self):
                from django.forms import Media
                from django.forms.widgets import Script
                from include_media import register, Stylesheet

                register(Media(
                    css={"all": [Stylesheet("myapp/base.css")]},
                    js=[Script("myapp/base.js", type="module")],
                ))

    Registering the same ``Media`` instance more than once is harmless —
    Django's ``Media.__add__`` deduplicates at render time — but wasteful.
    """
    if not isinstance(media, Media):
        raise TypeError(
            f"include_media.register() expected a Media instance, "
            f"got {type(media).__name__}"
        )
    _registered.append(media)


def clear():
    """
    Remove all registered media.

    Intended for test teardown.  In production code the registry is populated
    once at startup and never cleared.  Example ``pytest`` fixture::

        @pytest.fixture(autouse=True)
        def reset_media_registry():
            yield
            from include_media.registry import clear
            clear()
    """
    _registered.clear()


def _get_registered_media():
    result = Media()
    for m in _registered:
        result = result + m
    return result
