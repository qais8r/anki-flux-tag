import os

from copy import deepcopy
from collections import defaultdict
from typing import Any

from aqt import colors, gui_hooks, mw
from aqt.browser import Browser, SidebarItem, SidebarItemType, SidebarModel, SidebarTreeView
from aqt.gui_hooks import (
    browser_sidebar_will_show_context_menu,
    browser_will_show,
    collection_did_load,
    main_window_did_init,
)
from aqt.operations import QueryOp
from aqt.qt import (
    QAction,
    QBrush,
    QCheckBox,
    QColor,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFont,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QIcon,
    QLabel,
    QMenu,
    QModelIndex,
    QPainter,
    QPixmap,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    Qt,
    QVariant,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)
from aqt.theme import ColoredIcon, theme_manager
from aqt.utils import tooltip


COLOR_KEYS = [f"Color {i}" for i in range(1, 8)]
THEMES = ("dark", "light")
HEATMAP_STOPS = ("low", "mid", "high")
FLUXTAG_CONFIG_KEY = "fluxtag_config"

DEFAULT_COLOR_OPTIONS = {
    "Color 1": {"dark": "#F54927", "light": "#B3341E"},
    "Color 2": {"dark": "#F58E27", "light": "#A65C00"},
    "Color 3": {"dark": "#F5CC27", "light": "#8A6B00"},
    "Color 4": {"dark": "#40FF83", "light": "#1F7A45"},
    "Color 5": {"dark": "#40B3FF", "light": "#0B5EA8"},
    "Color 6": {"dark": "#B863FF", "light": "#6E3CB8"},
    "Color 7": {"dark": "#FF6BFB", "light": "#A3277D"},
}

DEFAULT_HEATMAP_CUSTOM_STOPS = {
    "dark": {"low": "#252525", "mid": "#252525", "high": "#00E108"},
    "light": {"low": "#F1F1F1", "mid": "#F1F1F1", "high": "#00E108"},
}

DEFAULT_SETTINGS = {
    "show_assigned_colors": True,
    "bold_assigned_tags": True,
    "bold_parent_tags": False,
    "font_size_delta": 1,
    "heatmap_mode": "classic",
    "checkmark_for_completed": True,
    "completed_ratio_threshold": 1.0,
    "color_options": deepcopy(DEFAULT_COLOR_OPTIONS),
    "heatmap_custom_stops": deepcopy(DEFAULT_HEATMAP_CUSTOM_STOPS),
}

PREVIEW_TREE_DATA = [
    {
        "name": "Medical School",
        "ratio": 0.67,
        "assigned": None,
        "children": [
            {
                "name": "Preclinical",
                "ratio": 0.58,
                "assigned": None,
                "children": [
                    {"name": "Anatomy", "ratio": 1.0, "assigned": "Color 1", "children": []},
                    {"name": "Physiology", "ratio": 0.74, "assigned": "Color 5", "children": []},
                    {"name": "Biochemistry", "ratio": 0.46, "assigned": "Color 2", "children": []},
                    {"name": "Histology", "ratio": 0.22, "assigned": None, "children": []},
                ],
            },
            {
                "name": "Systems",
                "ratio": 0.61,
                "assigned": None,
                "children": [
                    {"name": "Cardiology", "ratio": 0.93, "assigned": "Color 4", "children": []},
                    {"name": "Pulmonology", "ratio": 0.52, "assigned": None, "children": []},
                    {"name": "Nephrology", "ratio": 0.38, "assigned": "Color 6", "children": []},
                    {"name": "Gastroenterology", "ratio": 0.81, "assigned": "Color 3", "children": []},
                    {"name": "Neurology", "ratio": 0.27, "assigned": None, "children": []},
                    {"name": "Endocrinology", "ratio": 0.66, "assigned": "Color 7", "children": []},
                ],
            },
            {
                "name": "Clinical",
                "ratio": 0.49,
                "assigned": None,
                "children": [
                    {"name": "Pharmacology", "ratio": 1.0, "assigned": "Color 1", "children": []},
                    {"name": "Pathology", "ratio": 0.57, "assigned": "Color 2", "children": []},
                    {"name": "Microbiology", "ratio": 0.31, "assigned": None, "children": []},
                    {"name": "Immunology", "ratio": 0.84, "assigned": "Color 5", "children": []},
                    {"name": "Internal Medicine", "ratio": 0.62, "assigned": None, "children": []},
                    {"name": "Surgery", "ratio": 0.41, "assigned": "Color 3", "children": []},
                ],
            },
        ],
    }
]

checkmark_overlay_icon = QIcon(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "checkmark.svg")
)
circle_icon = ColoredIcon(
    path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "circle.svg"),
    color=colors.STATE_NEW,
)

fluxtag_config: dict[str, Any] = {}
fluxtag_settings: dict[str, Any] = deepcopy(DEFAULT_SETTINGS)
fluxtag_heatmap: dict[str, dict[str, str]] = {}
fluxtag_completed_tags: set[str] = set()
fluxtag_heatmap_cache_mod: int | None = None
fluxtag_heatmap_dirty = True
fluxtag_heatmap_epoch = 0
fluxtag_heatmap_pending_epoch: int | None = None
settings_action: QAction | None = None
completed_icon_cache: dict[str, QIcon] = {}


def normalize_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def normalize_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def normalize_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def normalize_hex(value: Any, fallback: str) -> str:
    if isinstance(value, str):
        color = QColor(value)
        if color.isValid():
            return color.name()
    return QColor(fallback).name()


def normalize_color_options(raw: Any) -> dict[str, dict[str, str]]:
    normalized = deepcopy(DEFAULT_COLOR_OPTIONS)
    if not isinstance(raw, dict):
        return normalized

    for key in COLOR_KEYS:
        candidate = raw.get(key)
        if not isinstance(candidate, dict):
            continue
        for theme in THEMES:
            normalized[key][theme] = normalize_hex(candidate.get(theme), normalized[key][theme])

    return normalized


def normalize_heatmap_stops(raw: Any) -> dict[str, dict[str, str]]:
    normalized = deepcopy(DEFAULT_HEATMAP_CUSTOM_STOPS)
    if not isinstance(raw, dict):
        return normalized

    for theme in THEMES:
        candidate = raw.get(theme)
        if not isinstance(candidate, dict):
            continue
        for stop in HEATMAP_STOPS:
            normalized[theme][stop] = normalize_hex(candidate.get(stop), normalized[theme][stop])

    return normalized


def normalize_settings(raw: Any) -> dict[str, Any]:
    settings = deepcopy(DEFAULT_SETTINGS)
    if not isinstance(raw, dict):
        return settings

    settings["show_assigned_colors"] = normalize_bool(
        raw.get("show_assigned_colors"), settings["show_assigned_colors"]
    )
    settings["bold_assigned_tags"] = normalize_bool(
        raw.get("bold_assigned_tags"), settings["bold_assigned_tags"]
    )
    settings["bold_parent_tags"] = normalize_bool(
        raw.get("bold_parent_tags"), settings["bold_parent_tags"]
    )
    settings["checkmark_for_completed"] = normalize_bool(
        raw.get("checkmark_for_completed"), settings["checkmark_for_completed"]
    )
    settings["font_size_delta"] = normalize_int(raw.get("font_size_delta"), settings["font_size_delta"], 0, 6)
    settings["completed_ratio_threshold"] = normalize_float(
        raw.get("completed_ratio_threshold"), settings["completed_ratio_threshold"], 0.0, 1.0
    )

    mode = raw.get("heatmap_mode")
    if mode in ("classic", "custom"):
        settings["heatmap_mode"] = mode

    settings["color_options"] = normalize_color_options(raw.get("color_options"))
    settings["heatmap_custom_stops"] = normalize_heatmap_stops(raw.get("heatmap_custom_stops"))
    return settings


def get_config() -> dict[str, Any]:
    config = mw.col.get_config(FLUXTAG_CONFIG_KEY, {})
    return config if isinstance(config, dict) else {}


def update_config(config: dict[str, Any]) -> None:
    mw.col.set_config(FLUXTAG_CONFIG_KEY, config)


def load_runtime_state() -> None:
    global fluxtag_config, fluxtag_settings
    fluxtag_config = get_config()
    fluxtag_settings = normalize_settings(fluxtag_config.get("settings", {}))


def is_dark_mode() -> bool:
    return bool(theme_manager.night_mode)


def theme_color(colors_by_theme: dict[str, str]) -> str:
    return colors_by_theme["dark"] if is_dark_mode() else colors_by_theme["light"]


def refresh_active_browser_sidebar() -> None:
    browser = getattr(mw, "browser", None)
    if not browser:
        return
    sidebar = getattr(browser, "sidebarTree", None)
    if sidebar:
        sidebar.refresh()


def has_custom_color(tag: str) -> bool:
    idx = fluxtag_config.get("tags", {}).get(tag, None)
    return idx in fluxtag_settings["color_options"]


def get_color_for_tag(tag: str) -> str | None:
    idx = fluxtag_config.get("tags", {}).get(tag, None)
    if idx:
        by_theme = fluxtag_settings["color_options"].get(idx)
        if by_theme:
            return theme_color(by_theme)
    return None


def set_color_for_tag(sidebar: SidebarTreeView, tag: str, color_idx: str) -> None:
    global fluxtag_config
    if not fluxtag_config.get("tags"):
        fluxtag_config["tags"] = {}
    fluxtag_config["tags"][tag] = color_idx
    update_config(fluxtag_config)
    sidebar.refresh()


def remove_color_for_tag(sidebar: SidebarTreeView, tag: str) -> None:
    global fluxtag_config
    fluxtag_config.get("tags", {}).pop(tag, None)
    update_config(fluxtag_config)
    sidebar.refresh()


def is_heatmap_enabled() -> bool:
    return fluxtag_config.get("heatmap_enabled", True)


def set_heatmap_enabled(enabled: bool, sidebar: SidebarTreeView) -> None:
    global fluxtag_config
    fluxtag_config["heatmap_enabled"] = enabled
    update_config(fluxtag_config)
    if enabled:
        invalidate_heatmap_cache(clear_existing=True)
        schedule_heatmap_rebuild(force=True)
    else:
        clear_heatmap_cache()
    sidebar.refresh()


def refresh_heatmap(sidebar: SidebarTreeView) -> None:
    invalidate_heatmap_cache()
    schedule_heatmap_rebuild(force=True, success_message="Tag heatmap refreshed!")
    tooltip("Refreshing tag heatmap...", parent=sidebar.browser)


def get_heatmap_color_classic(ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    b = 0
    if ratio >= 0.5:
        t = (ratio - 0.5) * 2
        r = round(255 * (1 - t))
        g = 255
    else:
        t = ratio * 2
        g = round(255 * t)
        r = 255
    return f"#{r:02x}{g:02x}{b:02x}"


def blend_color(start: tuple[int, int, int], end: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    r = round(start[0] + (end[0] - start[0]) * t)
    g = round(start[1] + (end[1] - start[1]) * t)
    b = round(start[2] + (end[2] - start[2]) * t)
    return (r, g, b)


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    qcolor = QColor(color)
    return (qcolor.red(), qcolor.green(), qcolor.blue())


def get_heatmap_color_custom(ratio: float, dark_mode: bool) -> str:
    ratio = max(0.0, min(1.0, ratio))
    stops = fluxtag_settings["heatmap_custom_stops"]["dark" if dark_mode else "light"]
    low = hex_to_rgb(stops["low"])
    mid = hex_to_rgb(stops["mid"])
    high = hex_to_rgb(stops["high"])
    if ratio >= 0.5:
        t = (ratio - 0.5) * 2
        r, g, b = blend_color(mid, high, t)
    else:
        t = ratio * 2
        r, g, b = blend_color(low, mid, t)
    return f"#{r:02x}{g:02x}{b:02x}"


def get_heatmap_color(ratio: float, dark_mode: bool) -> str:
    if fluxtag_settings["heatmap_mode"] == "custom":
        return get_heatmap_color_custom(ratio, dark_mode)
    return get_heatmap_color_classic(ratio)


def get_heatmap_for_tag(tag: str) -> dict[str, str] | None:
    return fluxtag_heatmap.get(tag, None)


def get_heatmap_color_for_settings(ratio: float, dark_mode: bool, settings: dict[str, Any]) -> str:
    if settings["heatmap_mode"] == "custom":
        ratio = max(0.0, min(1.0, ratio))
        stops = settings["heatmap_custom_stops"]["dark" if dark_mode else "light"]
        low = hex_to_rgb(stops["low"])
        mid = hex_to_rgb(stops["mid"])
        high = hex_to_rgb(stops["high"])
        if ratio >= 0.5:
            t = (ratio - 0.5) * 2
            r, g, b = blend_color(mid, high, t)
        else:
            t = ratio * 2
            r, g, b = blend_color(low, mid, t)
        return f"#{r:02x}{g:02x}{b:02x}"
    return get_heatmap_color_classic(ratio)


def get_collection_mod(col=None) -> int | None:
    target_col = col or getattr(mw, "col", None)
    if not target_col:
        return None
    try:
        value = target_col.db.scalar("SELECT mod FROM col")
    except Exception:
        return None
    if value is None:
        return None
    return int(value)


def invalidate_heatmap_cache(clear_existing: bool = False) -> None:
    global fluxtag_heatmap, fluxtag_completed_tags, fluxtag_heatmap_cache_mod
    global fluxtag_heatmap_dirty, fluxtag_heatmap_epoch
    fluxtag_heatmap_dirty = True
    fluxtag_heatmap_cache_mod = None
    fluxtag_heatmap_epoch += 1
    if clear_existing:
        fluxtag_heatmap = {}
        fluxtag_completed_tags = set()


def clear_heatmap_cache() -> None:
    global fluxtag_heatmap, fluxtag_completed_tags, fluxtag_heatmap_cache_mod
    global fluxtag_heatmap_dirty, fluxtag_heatmap_epoch
    fluxtag_heatmap = {}
    fluxtag_completed_tags = set()
    fluxtag_heatmap_cache_mod = None
    fluxtag_heatmap_dirty = False
    fluxtag_heatmap_epoch += 1


def heatmap_cache_needs_refresh() -> bool:
    if not is_heatmap_enabled():
        return False
    if fluxtag_heatmap_dirty or fluxtag_heatmap_cache_mod is None:
        return True
    return fluxtag_heatmap_cache_mod != get_collection_mod()


def build_heatmap_snapshot(col, settings: dict[str, Any]) -> tuple[dict[str, dict[str, str]], set[str], int | None]:
    heatmap: dict[str, dict[str, str]] = {}
    completed_tags: set[str] = set()

    total = defaultdict(int)
    unsuspended = defaultdict(int)
    seen_prefixes = set()

    rows = col.db.all(
        """
        SELECT
            n.tags,
            COUNT(c.id) AS total_cards,
            SUM(CASE WHEN c.queue != -1 THEN 1 ELSE 0 END) AS unsuspended_cards
        FROM notes n
        JOIN cards c ON c.nid = n.id
        GROUP BY n.id
        """
    )

    for tagstr, total_cards, unsuspended_cards in rows:
        prefixes_for_note = set()
        for tag in col.tags.split(tagstr):
            parts = tag.split("::")
            for i in range(1, len(parts) + 1):
                prefixes_for_note.add("::".join(parts[:i]))

        for prefix in prefixes_for_note:
            total[prefix] += total_cards
            unsuspended[prefix] += unsuspended_cards

        seen_prefixes |= prefixes_for_note

    all_tags = set(col.tags.all()) | seen_prefixes
    completed_threshold = settings["completed_ratio_threshold"]

    for tag in all_tags:
        tagged_cards = total.get(tag, 0)
        unsusp = unsuspended.get(tag, 0)
        ratio = (unsusp / tagged_cards) if tagged_cards else 0.0
        if tagged_cards and ratio >= completed_threshold:
            completed_tags.add(tag)
        heatmap[tag] = {
            "dark": get_heatmap_color_for_settings(ratio, dark_mode=True, settings=settings),
            "light": get_heatmap_color_for_settings(ratio, dark_mode=False, settings=settings),
        }
    return heatmap, completed_tags, get_collection_mod(col)


def generate_heatmap() -> None:
    global fluxtag_heatmap, fluxtag_completed_tags, fluxtag_heatmap_cache_mod, fluxtag_heatmap_dirty
    if not mw.col:
        clear_heatmap_cache()
        return
    fluxtag_heatmap, fluxtag_completed_tags, fluxtag_heatmap_cache_mod = build_heatmap_snapshot(
        mw.col, normalize_settings(fluxtag_settings)
    )
    fluxtag_heatmap_dirty = False


def on_heatmap_rebuild_success(
    snapshot: tuple[dict[str, dict[str, str]], set[str], int | None], epoch: int, success_message: str | None
) -> None:
    global fluxtag_heatmap, fluxtag_completed_tags, fluxtag_heatmap_cache_mod
    global fluxtag_heatmap_dirty, fluxtag_heatmap_pending_epoch
    fluxtag_heatmap_pending_epoch = None

    if epoch != fluxtag_heatmap_epoch or not is_heatmap_enabled():
        if heatmap_cache_needs_refresh():
            schedule_heatmap_rebuild()
        return

    fluxtag_heatmap, fluxtag_completed_tags, fluxtag_heatmap_cache_mod = snapshot
    fluxtag_heatmap_dirty = False
    refresh_active_browser_sidebar()

    if heatmap_cache_needs_refresh():
        invalidate_heatmap_cache()
        schedule_heatmap_rebuild()
        return

    if success_message:
        tooltip(success_message, parent=mw)


def on_heatmap_rebuild_failure(exception: Exception, epoch: int) -> None:
    global fluxtag_heatmap_dirty, fluxtag_heatmap_pending_epoch
    fluxtag_heatmap_pending_epoch = None
    if epoch == fluxtag_heatmap_epoch:
        fluxtag_heatmap_dirty = True
    raise exception


def schedule_heatmap_rebuild(force: bool = False, success_message: str | None = None) -> None:
    global fluxtag_heatmap_pending_epoch
    if not mw.col or not is_heatmap_enabled():
        return
    if fluxtag_heatmap_pending_epoch is not None:
        if force:
            invalidate_heatmap_cache()
        return
    if not force and not heatmap_cache_needs_refresh():
        return

    epoch = fluxtag_heatmap_epoch
    fluxtag_heatmap_pending_epoch = epoch
    settings_snapshot = normalize_settings(fluxtag_settings)
    (
        QueryOp(
            parent=mw,
            op=lambda col: build_heatmap_snapshot(col, settings_snapshot),
            success=lambda snapshot: on_heatmap_rebuild_success(snapshot, epoch, success_message),
        )
        .failure(lambda exc: on_heatmap_rebuild_failure(exc, epoch))
        .run_in_background()
    )


def invalidate_heatmap_for_collection_change() -> None:
    invalidate_heatmap_cache()
    if getattr(mw, "browser", None):
        schedule_heatmap_rebuild()


def should_invalidate_heatmap_from_changes(changes: Any) -> bool:
    relevant_flags = (
        "card",
        "cards",
        "note",
        "notes",
        "tag",
        "tags",
        "card_state",
        "browser_sidebar",
    )
    return any(bool(getattr(changes, name, False)) for name in relevant_flags)


class PatchedSidebarItem(SidebarItem):
    color: str | None = None
    bold: bool | None = False


def patched_data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> QVariant:
    if not index.isValid():
        return QVariant()

    if role not in (
        Qt.ItemDataRole.DisplayRole,
        Qt.ItemDataRole.DecorationRole,
        Qt.ItemDataRole.ToolTipRole,
        Qt.ItemDataRole.EditRole,
        Qt.ItemDataRole.FontRole,
        Qt.ItemDataRole.ForegroundRole,
    ):
        return QVariant()

    item: PatchedSidebarItem = index.internalPointer()

    if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
        return QVariant(item.name)
    if role == Qt.ItemDataRole.ToolTipRole:
        return QVariant(item.tooltip)
    if role == Qt.ItemDataRole.DecorationRole:
        if isinstance(item.icon, QIcon):
            return QVariant(item.icon)
        return QVariant(theme_manager.icon_from_resources(item.icon))

    if role == Qt.ItemDataRole.FontRole:
        if item.item_type == SidebarItemType.TAG and item.bold:
            font = QFont()
            font.setBold(True)
            point_delta = fluxtag_settings["font_size_delta"]
            if point_delta:
                font.setPointSize(max(1, font.pointSize() + point_delta))
            return QVariant(font)

    if role == Qt.ItemDataRole.ForegroundRole:
        if (
            item.item_type == SidebarItemType.TAG
            and item.color
            and fluxtag_settings["show_assigned_colors"]
        ):
            return QVariant(QColor(item.color))

    return QVariant()


def patched_add_child(self: PatchedSidebarItem, child: PatchedSidebarItem) -> None:
    child._parent_item = self

    if child.item_type == SidebarItemType.TAG:
        child.color = None
        child.bold = False

        custom_color = get_color_for_tag(child.full_name)
        if custom_color:
            if fluxtag_settings["show_assigned_colors"]:
                child.color = custom_color
            if fluxtag_settings["bold_assigned_tags"]:
                child.bold = True

                if fluxtag_settings["bold_parent_tags"]:

                    def bold_parent(parent: PatchedSidebarItem) -> None:
                        if not (hasattr(parent, "color") or hasattr(parent, "bold")):
                            return

                        parent.bold = True
                        if parent._parent_item:
                            bold_parent(parent._parent_item)

                    bold_parent(self)

        heatmap_colors = get_heatmap_for_tag(child.full_name)
        if heatmap_colors:
            if fluxtag_settings["checkmark_for_completed"] and child.full_name in fluxtag_completed_tags:
                child.icon = get_completed_icon(theme_color(heatmap_colors))
            else:
                child.icon = circle_icon.with_color(heatmap_colors)

    self.children.append(child)


def colored_action(parent: QMenu, text: str, color_by_theme: dict[str, str]) -> QWidgetAction:
    action = QWidgetAction(parent)
    label = QLabel(text)
    color = theme_color(color_by_theme)
    hover_bg = "#565656" if is_dark_mode() else "#DCDCDC"
    label.setStyleSheet(
        f"""
        QLabel {{
            color: {color};
            padding: 5px;
            padding-right: 30px;
        }}
        QLabel:hover {{
            background: {hover_bg};
        }}
    """
    )
    action.setDefaultWidget(label)
    return action


def button_text_color(bg_color: str) -> str:
    color = QColor(bg_color)
    luminance = (299 * color.red() + 587 * color.green() + 114 * color.blue()) // 1000
    return "#000000" if luminance >= 150 else "#FFFFFF"


def style_color_button(button: QPushButton, color: str) -> None:
    color = normalize_hex(color, "#000000")
    button.setProperty("hex_color", color)
    button.setText(color.upper())
    button.setStyleSheet(
        f"""
        QPushButton {{
            background: {color};
            color: {button_text_color(color)};
            border: 1px solid #666666;
            border-radius: 5px;
            padding: 4px 8px;
            font-family: Menlo, Monaco, monospace;
        }}
    """
    )


def get_completed_icon(fill_color: str) -> QIcon:
    fill_color = normalize_hex(fill_color, "#00FF00")
    cached = completed_icon_cache.get(fill_color)
    if cached:
        return cached

    size = 20
    base_icon = theme_manager.icon_from_resources(
        circle_icon.with_color({"dark": fill_color, "light": fill_color})
    )
    base_pixmap = base_icon.pixmap(size, size)
    if base_pixmap.isNull():
        base_pixmap = QPixmap(size, size)
        base_pixmap.fill(Qt.GlobalColor.transparent)

    overlay_pixmap = checkmark_overlay_icon.pixmap(size, size)
    painter = QPainter(base_pixmap)
    painter.drawPixmap(0, 0, overlay_pixmap)
    painter.end()

    completed_icon = QIcon(base_pixmap)
    completed_icon_cache[fill_color] = completed_icon
    return completed_icon


class FluxTagConfigDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("FluxTag Settings")
        self.resize(760, 520)

        self.settings = normalize_settings(fluxtag_settings)
        self.heatmap_enabled = is_heatmap_enabled()
        self.preset_buttons: dict[tuple[str, str], QPushButton] = {}
        self.heatmap_buttons: dict[tuple[str, str], QPushButton] = {}
        self.preview_items: dict[str, QTreeWidgetItem] = {}
        self.preview_metadata: dict[str, dict[str, Any]] = {}

        main_layout = QVBoxLayout(self)

        info = QLabel(
            "Customize tag colors, typography, and heatmap behavior.\n"
            "All changes are saved to this collection."
        )
        info.setWordWrap(True)
        main_layout.addWidget(info)

        content_layout = QHBoxLayout()
        self.tabs = QTabWidget()
        self.tabs.addTab(self.build_behavior_tab(), "Behavior")
        self.tabs.addTab(self.build_presets_tab(), "Color Presets")
        self.tabs.addTab(self.build_heatmap_tab(), "Heatmap")
        content_layout.addWidget(self.tabs, 3)

        self.preview_group = self.build_preview_group()
        self.preview_group.setMinimumWidth(280)
        content_layout.addWidget(self.preview_group, 2)
        main_layout.addLayout(content_layout, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.reset_button = buttons.addButton("Reset All Defaults", QDialogButtonBox.ButtonRole.ResetRole)
        self.reset_button.clicked.connect(self.restore_all_defaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        self.load_controls_from_settings()

    def build_preview_group(self) -> QGroupBox:
        group = QGroupBox("Live Preview")
        layout = QVBoxLayout(group)

        self.preview_theme_label = QLabel()
        self.preview_theme_label.setWordWrap(True)
        layout.addWidget(self.preview_theme_label)

        self.preview_tree = QTreeWidget()
        self.preview_tree.setHeaderHidden(True)
        self.preview_tree.setRootIsDecorated(True)
        self.preview_tree.setUniformRowHeights(True)
        self.preview_tree.setMinimumHeight(180)
        layout.addWidget(self.preview_tree)

        self.populate_preview_tree()
        return group

    def populate_preview_tree(self) -> None:
        self.preview_tree.clear()
        self.preview_items = {}
        self.preview_metadata = {}

        def add_nodes(parent: QTreeWidgetItem | None, nodes: list[dict[str, Any]], prefix: str = "") -> None:
            for node in nodes:
                full_name = node["name"] if not prefix else f"{prefix}::{node['name']}"
                item = QTreeWidgetItem([node["name"]])
                if parent is None:
                    self.preview_tree.addTopLevelItem(item)
                else:
                    parent.addChild(item)

                self.preview_items[full_name] = item
                self.preview_metadata[full_name] = {
                    "ratio": float(node["ratio"]),
                    "assigned": node["assigned"],
                }
                add_nodes(item, node["children"], full_name)

        add_nodes(None, PREVIEW_TREE_DATA)
        self.preview_tree.expandAll()

    def get_preview_settings(self) -> dict[str, Any]:
        settings = normalize_settings(self.settings)
        settings["show_assigned_colors"] = self.chk_show_assigned_colors.isChecked()
        settings["bold_assigned_tags"] = self.chk_bold_assigned_tags.isChecked()
        settings["bold_parent_tags"] = self.chk_bold_parent_tags.isChecked()
        settings["font_size_delta"] = self.spin_font_delta.value()
        settings["checkmark_for_completed"] = self.chk_checkmark_for_completed.isChecked()
        settings["completed_ratio_threshold"] = self.spin_completion_threshold.value() / 100.0
        settings["heatmap_mode"] = self.cmb_heatmap_mode.currentData()
        settings["heatmap_enabled"] = self.chk_heatmap_enabled.isChecked()
        return settings

    def get_preview_heatmap_color(self, ratio: float, dark_mode: bool, settings: dict[str, Any]) -> str:
        ratio = max(0.0, min(1.0, ratio))
        if settings["heatmap_mode"] == "custom":
            stops = settings["heatmap_custom_stops"]["dark" if dark_mode else "light"]
            low = hex_to_rgb(stops["low"])
            mid = hex_to_rgb(stops["mid"])
            high = hex_to_rgb(stops["high"])
            if ratio >= 0.5:
                t = (ratio - 0.5) * 2
                r, g, b = blend_color(mid, high, t)
            else:
                t = ratio * 2
                r, g, b = blend_color(low, mid, t)
            return f"#{r:02x}{g:02x}{b:02x}"
        return get_heatmap_color_classic(ratio)

    def update_live_preview(self) -> None:
        settings = self.get_preview_settings()
        dark_mode = is_dark_mode()
        active_theme = "dark" if dark_mode else "light"
        self.preview_theme_label.setText(
            f"Example tag structure preview ({active_theme.title()} mode, current Anki theme)."
        )

        assigned_names = {
            full_name
            for full_name, meta in self.preview_metadata.items()
            if meta["assigned"] and settings["bold_assigned_tags"]
        }
        parent_bold_names: set[str] = set()
        if settings["bold_parent_tags"]:
            for full_name in self.preview_metadata:
                if any(name.startswith(f"{full_name}::") for name in assigned_names):
                    parent_bold_names.add(full_name)

        for full_name, item in self.preview_items.items():
            meta = self.preview_metadata[full_name]
            assigned = meta["assigned"]
            ratio = float(meta["ratio"])

            show_color = bool(assigned and settings["show_assigned_colors"])
            if show_color:
                color = settings["color_options"][assigned][active_theme]
                item.setForeground(0, QBrush(QColor(color)))
            else:
                item.setForeground(0, QBrush())

            should_bold = full_name in assigned_names or full_name in parent_bold_names
            font = QFont(self.preview_tree.font())
            font.setBold(should_bold)
            if should_bold and settings["font_size_delta"]:
                font.setPointSize(max(1, font.pointSize() + settings["font_size_delta"]))
            item.setFont(0, font)

            if settings["heatmap_enabled"]:
                heatmap_colors = {
                    "dark": self.get_preview_heatmap_color(ratio, dark_mode=True, settings=settings),
                    "light": self.get_preview_heatmap_color(ratio, dark_mode=False, settings=settings),
                }
                completed = ratio >= settings["completed_ratio_threshold"]
                if settings["checkmark_for_completed"] and completed:
                    item.setIcon(0, get_completed_icon(heatmap_colors[active_theme]))
                else:
                    item.setIcon(0, theme_manager.icon_from_resources(circle_icon.with_color(heatmap_colors)))
                item.setToolTip(0, f"Unsuspended ratio: {round(ratio * 100)}%")
            else:
                item.setIcon(0, QIcon())
                item.setToolTip(0, "")

    def build_behavior_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        tag_group = QGroupBox("Tag Rendering")
        tag_layout = QVBoxLayout(tag_group)

        self.chk_show_assigned_colors = QCheckBox("Show assigned tag text colors")
        self.chk_bold_assigned_tags = QCheckBox("Bold tags with assigned colors")
        self.chk_bold_parent_tags = QCheckBox("Also bold parent tags")

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Font size boost for bold tags:"))
        self.spin_font_delta = QSpinBox()
        self.spin_font_delta.setRange(0, 6)
        font_row.addWidget(self.spin_font_delta)
        font_row.addStretch()

        tag_layout.addWidget(self.chk_show_assigned_colors)
        tag_layout.addWidget(self.chk_bold_assigned_tags)
        tag_layout.addWidget(self.chk_bold_parent_tags)
        tag_layout.addLayout(font_row)

        heatmap_group = QGroupBox("Heatmap Behavior")
        heatmap_layout = QVBoxLayout(heatmap_group)

        self.chk_heatmap_enabled = QCheckBox("Enable heatmap")
        self.chk_checkmark_for_completed = QCheckBox("Show checkmark icon for completed tags")

        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("Completed when unsuspended ratio is at least:"))
        self.spin_completion_threshold = QSpinBox()
        self.spin_completion_threshold.setRange(0, 100)
        self.spin_completion_threshold.setSuffix("%")
        threshold_row.addWidget(self.spin_completion_threshold)
        threshold_row.addStretch()

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Heatmap color mode:"))
        self.cmb_heatmap_mode = QComboBox()
        self.cmb_heatmap_mode.addItem("Classic (original red-yellow-green)", "classic")
        self.cmb_heatmap_mode.addItem("Custom 3-stop gradient", "custom")
        self.cmb_heatmap_mode.currentIndexChanged.connect(lambda _idx: self.on_behavior_controls_changed())
        mode_row.addWidget(self.cmb_heatmap_mode)
        mode_row.addStretch()

        self.chk_show_assigned_colors.stateChanged.connect(lambda _state: self.update_live_preview())
        self.chk_bold_assigned_tags.stateChanged.connect(lambda _state: self.update_live_preview())
        self.chk_bold_parent_tags.stateChanged.connect(lambda _state: self.update_live_preview())
        self.spin_font_delta.valueChanged.connect(lambda _value: self.update_live_preview())
        self.chk_heatmap_enabled.stateChanged.connect(lambda _state: self.on_behavior_controls_changed())
        self.chk_checkmark_for_completed.stateChanged.connect(lambda _state: self.update_live_preview())
        self.spin_completion_threshold.valueChanged.connect(lambda _value: self.update_live_preview())

        heatmap_layout.addWidget(self.chk_heatmap_enabled)
        heatmap_layout.addWidget(self.chk_checkmark_for_completed)
        heatmap_layout.addLayout(threshold_row)
        heatmap_layout.addLayout(mode_row)

        layout.addWidget(tag_group)
        layout.addWidget(heatmap_group)
        layout.addStretch()
        return tab

    def build_presets_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        header = QLabel("Edit the tag color presets shown when you right click a tag to assign a color.")
        header.setWordWrap(True)
        layout.addWidget(header)

        grid = QGridLayout()
        grid.addWidget(QLabel("Preset"), 0, 0)
        grid.addWidget(QLabel("Dark"), 0, 1)
        grid.addWidget(QLabel("Light"), 0, 2)

        for row, key in enumerate(COLOR_KEYS, start=1):
            grid.addWidget(QLabel(key), row, 0)
            for col, theme in enumerate(THEMES, start=1):
                button = QPushButton()
                button.clicked.connect(
                    lambda _checked=False, preset_key=key, preset_theme=theme: self.pick_preset_color(
                        preset_key, preset_theme
                    )
                )
                self.preset_buttons[(key, theme)] = button
                grid.addWidget(button, row, col)

        layout.addLayout(grid)

        button_row = QHBoxLayout()
        reset_presets = QPushButton("Reset Presets")
        reset_presets.clicked.connect(self.restore_default_presets)
        button_row.addWidget(reset_presets)
        button_row.addStretch()
        layout.addLayout(button_row)
        layout.addStretch()
        return tab

    def build_heatmap_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        note = QLabel(
            "Custom mode uses a 3-stop gradient. Classic mode keeps the original math and ignores these colors."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.classic_mode_banner = QLabel(
            "Classic mode is active. Changes to these custom gradient stops are saved, "
            "but only applied after switching Heatmap color mode to 'Custom 3-stop gradient' "
            "in the Behavior tab."
        )
        self.classic_mode_banner.setWordWrap(True)
        self.classic_mode_banner.setStyleSheet(
            """
            QLabel {
                background: #FFF4CE;
                color: #5C4300;
                border: 1px solid #E3C770;
                border-radius: 6px;
                padding: 8px;
            }
        """
        )
        layout.addWidget(self.classic_mode_banner)

        self.custom_heatmap_group = QGroupBox("Custom Gradient Stops")
        grid = QGridLayout(self.custom_heatmap_group)
        grid.addWidget(QLabel("Theme"), 0, 0)
        grid.addWidget(QLabel("Low"), 0, 1)
        grid.addWidget(QLabel("Mid"), 0, 2)
        grid.addWidget(QLabel("High"), 0, 3)

        for row, theme in enumerate(THEMES, start=1):
            grid.addWidget(QLabel(theme.title()), row, 0)
            for col, stop in enumerate(HEATMAP_STOPS, start=1):
                button = QPushButton()
                button.clicked.connect(
                    lambda _checked=False, stop_theme=theme, stop_name=stop: self.pick_heatmap_stop_color(
                        stop_theme, stop_name
                    )
                )
                self.heatmap_buttons[(theme, stop)] = button
                grid.addWidget(button, row, col)

        layout.addWidget(self.custom_heatmap_group)

        button_row = QHBoxLayout()
        reset_stops = QPushButton("Reset Custom Gradient")
        reset_stops.clicked.connect(self.restore_default_heatmap_stops)
        button_row.addWidget(reset_stops)
        button_row.addStretch()
        layout.addLayout(button_row)
        layout.addStretch()
        return tab

    def load_controls_from_settings(self) -> None:
        self.chk_show_assigned_colors.setChecked(self.settings["show_assigned_colors"])
        self.chk_bold_assigned_tags.setChecked(self.settings["bold_assigned_tags"])
        self.chk_bold_parent_tags.setChecked(self.settings["bold_parent_tags"])
        self.spin_font_delta.setValue(self.settings["font_size_delta"])

        self.chk_heatmap_enabled.setChecked(self.heatmap_enabled)
        self.chk_checkmark_for_completed.setChecked(self.settings["checkmark_for_completed"])
        self.spin_completion_threshold.setValue(round(self.settings["completed_ratio_threshold"] * 100))

        mode_index = self.cmb_heatmap_mode.findData(self.settings["heatmap_mode"])
        self.cmb_heatmap_mode.setCurrentIndex(mode_index if mode_index >= 0 else 0)

        for key in COLOR_KEYS:
            for theme in THEMES:
                style_color_button(
                    self.preset_buttons[(key, theme)],
                    self.settings["color_options"][key][theme],
                )

        for theme in THEMES:
            for stop in HEATMAP_STOPS:
                style_color_button(
                    self.heatmap_buttons[(theme, stop)],
                    self.settings["heatmap_custom_stops"][theme][stop],
                )

        self.sync_heatmap_mode_ui()
        self.update_live_preview()

    def sync_heatmap_mode_ui(self) -> None:
        enabled = bool(self.chk_heatmap_enabled.isChecked())
        self.custom_heatmap_group.setEnabled(enabled)
        self.classic_mode_banner.setVisible(enabled and self.cmb_heatmap_mode.currentData() == "classic")

    def on_behavior_controls_changed(self) -> None:
        self.sync_heatmap_mode_ui()
        self.update_live_preview()

    def pick_preset_color(self, key: str, theme: str) -> None:
        current = self.settings["color_options"][key][theme]
        selected = QColorDialog.getColor(QColor(current), self, f"Choose {key} ({theme})")
        if not selected.isValid():
            return
        self.settings["color_options"][key][theme] = selected.name()
        style_color_button(self.preset_buttons[(key, theme)], selected.name())
        self.update_live_preview()

    def pick_heatmap_stop_color(self, theme: str, stop: str) -> None:
        current = self.settings["heatmap_custom_stops"][theme][stop]
        selected = QColorDialog.getColor(QColor(current), self, f"Choose {theme} {stop} stop")
        if not selected.isValid():
            return
        self.settings["heatmap_custom_stops"][theme][stop] = selected.name()
        style_color_button(self.heatmap_buttons[(theme, stop)], selected.name())
        self.update_live_preview()

    def restore_default_presets(self) -> None:
        self.settings["color_options"] = deepcopy(DEFAULT_COLOR_OPTIONS)
        for key in COLOR_KEYS:
            for theme in THEMES:
                style_color_button(self.preset_buttons[(key, theme)], self.settings["color_options"][key][theme])
        self.update_live_preview()

    def restore_default_heatmap_stops(self) -> None:
        self.settings["heatmap_custom_stops"] = deepcopy(DEFAULT_HEATMAP_CUSTOM_STOPS)
        for theme in THEMES:
            for stop in HEATMAP_STOPS:
                style_color_button(
                    self.heatmap_buttons[(theme, stop)],
                    self.settings["heatmap_custom_stops"][theme][stop],
                )
        self.update_live_preview()

    def restore_all_defaults(self) -> None:
        self.settings = normalize_settings({})
        self.heatmap_enabled = True
        self.load_controls_from_settings()

    def save_controls_into_settings(self) -> None:
        self.settings["show_assigned_colors"] = self.chk_show_assigned_colors.isChecked()
        self.settings["bold_assigned_tags"] = self.chk_bold_assigned_tags.isChecked()
        self.settings["bold_parent_tags"] = self.chk_bold_parent_tags.isChecked()
        self.settings["font_size_delta"] = self.spin_font_delta.value()
        self.settings["checkmark_for_completed"] = self.chk_checkmark_for_completed.isChecked()
        self.settings["completed_ratio_threshold"] = self.spin_completion_threshold.value() / 100.0
        self.settings["heatmap_mode"] = self.cmb_heatmap_mode.currentData()

    def accept(self) -> None:
        global fluxtag_config, fluxtag_settings
        self.save_controls_into_settings()

        fluxtag_settings = normalize_settings(self.settings)
        fluxtag_config["settings"] = fluxtag_settings
        fluxtag_config["heatmap_enabled"] = self.chk_heatmap_enabled.isChecked()
        update_config(fluxtag_config)

        if fluxtag_config["heatmap_enabled"]:
            invalidate_heatmap_cache()
            schedule_heatmap_rebuild(force=True)
        else:
            clear_heatmap_cache()

        refresh_active_browser_sidebar()
        tooltip("FluxTag settings saved.", parent=mw)
        super().accept()


def open_fluxtag_settings() -> None:
    if not mw.col:
        tooltip("Open a collection before editing FluxTag settings.", parent=mw)
        return
    load_runtime_state()
    dialog = FluxTagConfigDialog(mw)
    dialog.exec()


def on_browser_sidebar_will_show_context_menu(
    sidebar: SidebarTreeView, menu: QMenu, item: PatchedSidebarItem, index: QModelIndex
) -> None:
    if item.item_type == SidebarItemType.TAG:
        menu.addSeparator()
        menu_color = QMenu("Assign color", menu)

        for key in COLOR_KEYS:
            action = colored_action(menu_color, key, fluxtag_settings["color_options"][key])
            action.triggered.connect(lambda _checked=False, selected_key=key: set_color_for_tag(sidebar, item.full_name, selected_key))
            menu_color.addAction(action)

        menu.addMenu(menu_color)

        if has_custom_color(item.full_name):
            menu.addAction("Remove Color", lambda: remove_color_for_tag(sidebar, item.full_name))

        menu.addSeparator()

        if is_heatmap_enabled():
            menu.addAction("Refresh Heatmap", lambda: refresh_heatmap(sidebar))
            menu.addSeparator()
            menu.addAction("Disable Heatmap", lambda: set_heatmap_enabled(False, sidebar))
        else:
            menu.addAction("Enable Heatmap", lambda: set_heatmap_enabled(True, sidebar))

        menu.addSeparator()
        menu.addAction("FluxTag Settings...", open_fluxtag_settings)


def on_browser_will_show(browser: Browser) -> None:
    load_runtime_state()
    schedule_heatmap_rebuild()


def on_collection_did_load(col) -> None:
    load_runtime_state()
    invalidate_heatmap_cache(clear_existing=True)


def on_operation_did_execute(*args: Any) -> None:
    changes = args[0] if args else None
    if changes is not None and should_invalidate_heatmap_from_changes(changes):
        invalidate_heatmap_for_collection_change()


def on_main_window_did_init(*_args: Any, **_kwargs: Any) -> None:
    global settings_action
    mw.addonManager.setConfigAction(__name__, open_fluxtag_settings)
    if settings_action is None:
        settings_action = QAction("FluxTag Settings...", mw)
        settings_action.triggered.connect(open_fluxtag_settings)
        mw.form.menuTools.addAction(settings_action)


SidebarItem.add_child = patched_add_child
SidebarModel.data = patched_data
browser_sidebar_will_show_context_menu.append(on_browser_sidebar_will_show_context_menu)
browser_will_show.append(on_browser_will_show)
collection_did_load.append(on_collection_did_load)
main_window_did_init.append(on_main_window_did_init)
operation_did_execute_hook = getattr(gui_hooks, "operation_did_execute", None)
if operation_did_execute_hook is not None:
    operation_did_execute_hook.append(on_operation_did_execute)
