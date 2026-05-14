from include_media.registry import _get_registered_media


def registered_media(request):
    media = _get_registered_media()
    if not media._css and not media._js:
        return {}
    return {"page_media": media}
