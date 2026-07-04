import json
from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPixmap


ICON_MAP_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "icons" / "lucide_icon_map.json"
)
DEFAULT_ICON_COLOR = "#242424"

_factory_cache = {}
_icon_map_cache = None
_icon_cache = {}
_iconipy_available = None


def _load_icon_map():
    global _icon_map_cache
    if _icon_map_cache is not None:
        return _icon_map_cache

    try:
        with ICON_MAP_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        data = {}

    _icon_map_cache = {
        str(slot): _normalize_names(names)
        for slot, names in data.items()
    }
    return _icon_map_cache


def _normalize_names(names):
    if isinstance(names, str):
        return [names]
    if isinstance(names, (list, tuple)):
        return [str(name) for name in names if str(name).strip()]
    return []


def iconipy_available():
    global _iconipy_available
    if _iconipy_available is not None:
        return _iconipy_available

    try:
        from iconipy import IconFactory  # noqa: F401
    except Exception:
        _iconipy_available = False
    else:
        _iconipy_available = True
    return _iconipy_available


def _factory(size, color):
    if not iconipy_available():
        return None

    cache_key = (int(size), str(color))
    if cache_key in _factory_cache:
        return _factory_cache[cache_key]

    try:
        from iconipy import IconFactory

        factory = IconFactory(
            icon_set="lucide",
            icon_size=int(size),
            font_color=str(color),
        )
        try:
            factory._temp_dir.cleanup()
        except Exception:
            pass
    except Exception:
        factory = None

    _factory_cache[cache_key] = factory
    return factory


def lucide_icon(name, size=24, color=DEFAULT_ICON_COLOR, fallback=None):
    if not name:
        return fallback

    cache_key = (str(name), int(size), str(color))
    if cache_key in _icon_cache:
        return _icon_cache[cache_key]

    factory = _factory(size, color)
    if factory is None:
        return fallback

    try:
        qimage = factory.asQImage(str(name))
        pixmap = QPixmap.fromImage(qimage)
    except Exception:
        return fallback

    icon = QIcon(pixmap)
    _icon_cache[cache_key] = icon
    return icon


def app_icon(slot, *, fallback_names=(), size=24, color=DEFAULT_ICON_COLOR, fallback=None):
    icon_names = []
    icon_names.extend(_load_icon_map().get(str(slot), []))
    icon_names.extend(_normalize_names(fallback_names))

    for name in icon_names:
        icon = lucide_icon(name, size=size, color=color)
        if isinstance(icon, QIcon) and not icon.isNull():
            return icon

    return fallback


def available_lucide_icons(search_text=""):
    factory = _factory(24, DEFAULT_ICON_COLOR)
    if factory is None:
        return []

    if search_text:
        return factory.search(str(search_text))
    return list(getattr(factory, "icon_names", []))


def tint_for_widget(widget, fallback=DEFAULT_ICON_COLOR):
    if widget is None:
        return fallback

    try:
        color = widget.palette().buttonText().color()
    except Exception:
        return fallback

    if isinstance(color, QColor) and color.isValid():
        return color.name()
    return fallback
