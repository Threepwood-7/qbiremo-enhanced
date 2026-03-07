"""Application constants and static schemas."""

from __future__ import annotations

from threep_commons.app_identity import AppIdentity

SETTINGS_ORG_NAME = "ThreepSoftwz"
SETTINGS_APP_NAME = "qbiremo_enhanced"
APP_DISPLAY_NAME = "qbiremo-enhanced"
APP_VERSION = "0.1.0"
DEFAULT_LOG_FILENAME = "qbiremo_enhanced.log"
DEFAULT_LOG_MAX_BYTES = 1_048_576
DEFAULT_LOG_BACKUP_COUNT = 3

APP_IDENTITY = AppIdentity(
    org_name=SETTINGS_ORG_NAME,
    app_name=SETTINGS_APP_NAME,
    display_name=APP_DISPLAY_NAME,
    default_log_filename=DEFAULT_LOG_FILENAME,
    default_log_max_bytes=DEFAULT_LOG_MAX_BYTES,
    default_log_backup_count=DEFAULT_LOG_BACKUP_COUNT,
)

# Compatibility aliases used across app modules.
G_ORG_NAME = SETTINGS_ORG_NAME
G_APP_NAME = SETTINGS_APP_NAME

DEFAULT_REFRESH_INTERVAL = 30
DEFAULT_AUTO_REFRESH = True
AUTO_REFRESH_INTERVAL_MAX = 600
DEFAULT_STATUS_FILTER = "active"
DEFAULT_WINDOW_WIDTH = 1400
DEFAULT_WINDOW_HEIGHT = 800
DEFAULT_LEFT_PANEL_WIDTH = 220
DEFAULT_DISPLAY_SIZE_MODE = "bytes"
DEFAULT_DISPLAY_SPEED_MODE = "bytes"
DEFAULT_TITLE_BAR_SPEED_FORMAT = "[D: {down_text}, U: {up_text}]"
DEFAULT_HTTP_TIMEOUT_SECONDS = 300
CACHE_TEMP_SUBDIR = "cache"
CACHE_FILE_NAME = "qbiremo_enhanced.cache"
CACHE_MAX_AGE_DAYS = 3
INSTANCE_ID_LENGTH = 8
CLIPBOARD_SEEN_LIMIT = 256
APP_ICON_FILE_NAME = "qbiremo_enhanced.ico"

STATUS_FILTERS = [
    "all",
    "downloading",
    "seeding",
    "completed",
    "paused",
    "stopped",
    "active",
    "inactive",
    "resumed",
    "running",
    "stalled",
    "stalled_uploading",
    "stalled_downloading",
    "checking",
    "moving",
    "errored",
]

SIZE_BUCKET_COUNT = 5

TORRENT_COLUMNS = [
    {"key": "hash", "label": "Hash", "width": 240, "default_visible": True},
    {"key": "name", "label": "Name", "width": 360, "default_visible": True},
    {"key": "size", "label": "Size", "width": 110, "default_visible": True},
    {"key": "total_size", "label": "Total Size", "width": 110, "default_visible": True},
    {"key": "progress", "label": "Progress", "width": 80, "default_visible": True},
    {"key": "state", "label": "Status", "width": 110, "default_visible": True},
    {"key": "dlspeed", "label": "DL Speed", "width": 100, "default_visible": True},
    {"key": "upspeed", "label": "UP Speed", "width": 100, "default_visible": True},
    {"key": "dl_limit", "label": "Download Speed Limit", "width": 150, "default_visible": True},
    {"key": "up_limit", "label": "Upload Speed Limit", "width": 150, "default_visible": True},
    {"key": "downloaded", "label": "Downloaded", "width": 110, "default_visible": True},
    {"key": "uploaded", "label": "Uploaded", "width": 110, "default_visible": True},
    {"key": "amount_left", "label": "Amount Left", "width": 120, "default_visible": True},
    {"key": "completed", "label": "Completed", "width": 110, "default_visible": True},
    {
        "key": "downloaded_session",
        "label": "Downloaded Session",
        "width": 160,
        "default_visible": True,
    },
    {"key": "uploaded_session", "label": "Uploaded Session", "width": 160, "default_visible": True},
    {"key": "ratio", "label": "Ratio", "width": 70, "default_visible": True},
    {"key": "ratio_limit", "label": "Ratio Limit", "width": 100, "default_visible": True},
    {"key": "max_ratio", "label": "Max Ratio", "width": 90, "default_visible": True},
    {"key": "availability", "label": "Availability", "width": 110, "default_visible": True},
    {"key": "num_seeds", "label": "Seeds", "width": 70, "default_visible": True},
    {"key": "num_leechs", "label": "Peers", "width": 70, "default_visible": True},
    {"key": "num_complete", "label": "Complete", "width": 80, "default_visible": True},
    {"key": "num_incomplete", "label": "Incomplete", "width": 90, "default_visible": True},
    {"key": "priority", "label": "Priority", "width": 80, "default_visible": True},
    {"key": "eta", "label": "ETA", "width": 90, "default_visible": True},
    {"key": "reannounce", "label": "Reannounce", "width": 110, "default_visible": True},
    {"key": "seeding_time", "label": "Seeding Time", "width": 120, "default_visible": True},
    {
        "key": "seeding_time_limit",
        "label": "Seeding Time Limit",
        "width": 140,
        "default_visible": True,
    },
    {"key": "max_seeding_time", "label": "Max Seeding Time", "width": 130, "default_visible": True},
    {"key": "time_active", "label": "Time Active", "width": 120, "default_visible": True},
    {"key": "added_on", "label": "Added On", "width": 150, "default_visible": True},
    {"key": "completion_on", "label": "Completed On", "width": 150, "default_visible": True},
    {"key": "last_activity", "label": "Last Activity", "width": 150, "default_visible": True},
    {"key": "seen_complete", "label": "Seen Complete", "width": 150, "default_visible": True},
    {"key": "auto_tmm", "label": "Auto TMM", "width": 100, "default_visible": True},
    {"key": "force_start", "label": "Force Start", "width": 100, "default_visible": True},
    {"key": "seq_dl", "label": "Sequential Download", "width": 150, "default_visible": True},
    {
        "key": "f_l_piece_prio",
        "label": "First/Last Piece Prio",
        "width": 160,
        "default_visible": True,
    },
    {"key": "super_seeding", "label": "Super Seeding", "width": 120, "default_visible": True},
    {"key": "private", "label": "Private", "width": 80, "default_visible": True},
    {"key": "category", "label": "Category", "width": 120, "default_visible": True},
    {"key": "tags", "label": "Tags", "width": 150, "default_visible": True},
    {"key": "tracker", "label": "Tracker", "width": 170, "default_visible": True},
    {"key": "save_path", "label": "Save Path", "width": 220, "default_visible": True},
    {"key": "content_path", "label": "Content Path", "width": 260, "default_visible": True},
    {"key": "magnet_uri", "label": "Magnet URI", "width": 280, "default_visible": True},
    {"key": "num_files", "label": "Files", "width": 70, "default_visible": True},
]

BASIC_TORRENT_VIEW_KEYS = (
    "name",
    "state",
    "progress",
    "size",
    "dlspeed",
    "upspeed",
    "ratio",
    "eta",
    "num_seeds",
    "num_leechs",
    "category",
    "tags",
)

MEDIUM_TORRENT_VIEW_KEYS = (
    "name",
    "state",
    "progress",
    "size",
    "total_size",
    "dlspeed",
    "upspeed",
    "dl_limit",
    "up_limit",
    "downloaded",
    "uploaded",
    "ratio",
    "eta",
    "num_seeds",
    "num_leechs",
    "num_complete",
    "num_incomplete",
    "category",
    "tags",
    "tracker",
    "private",
    "added_on",
    "last_activity",
    "save_path",
)

_medium_default_keys = set(MEDIUM_TORRENT_VIEW_KEYS)
for _column in TORRENT_COLUMNS:
    _column["default_visible"] = _column["key"] in _medium_default_keys
