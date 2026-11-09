from __future__ import annotations


def register() -> None:
    # Importing the optional decoders registers their image formats with Pillow.
    try:
        import pillow_avif  # noqa: F401
    except ImportError:
        pass
    try:
        import pillow_jxl  # noqa: F401
    except ImportError:
        pass
