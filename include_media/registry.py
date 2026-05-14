from django.forms import Media

_registered = []


def register(media):
    if not isinstance(media, Media):
        raise TypeError(
            f"include_media.register() expected a Media instance, "
            f"got {type(media).__name__}"
        )
    _registered.append(media)


def clear():
    _registered.clear()


def _get_registered_media():
    result = Media()
    for m in _registered:
        result = result + m
    return result
