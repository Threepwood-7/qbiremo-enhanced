"""Config loading/validation and runtime bootstrap helpers."""

from __future__ import annotations

import atexit
import logging
import os
import re
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QSettings

from .constants import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    DEFAULT_TITLE_BAR_SPEED_FORMAT,
    G_APP_NAME,
    G_ORG_NAME,
)
from .runtime_paths import configure_qsettings, resolve_app_data_dir
from .utils import (
    _append_instance_id_to_filename,
    _normalize_http_protocol_scheme,
    compute_instance_id_from_config,
)

if TYPE_CHECKING:
    from types import TracebackType

    from .models.config import NormalizedConfig

logger = logging.getLogger(G_APP_NAME)

APP_SLUG = "qbiremo-enhanced"
DEFAULT_LOG_FILE_NAME = "qbiremo_enhanced.log"
CONFIG_SETTINGS_APP_NAME = G_APP_NAME
DEFAULT_PROFILE_ID = "default"
_PROFILE_ROOT = "profiles"

CONFIG_VALIDATION_KNOWN_KEYS = {
    "qb_host",
    "qb_port",
    "qb_username",
    "qb_password",
    "http_basic_auth_username",
    "http_basic_auth_password",
    "http_protocol_scheme",
    "http_timeout",
    "log_file",
    "title_bar_speed_format",
    "_profile_id",
    "_log_file_path",
    "_instance_id",
    "_instance_counter",
    "_instance_lock_file_path",
}

CONFIG_VALIDATION_LEGACY_MAP = {
    "host": "qb_host",
    "port": "qb_port",
    "username": "qb_username",
    "password": "qb_password",
    "http_user": "http_basic_auth_username",
    "http_password": "http_basic_auth_password",
}

CONFIG_VALIDATION_SETTINGS_MANAGED_KEYS = (
    "auto_refresh",
    "refresh_interval",
    "default_window_width",
    "default_window_height",
    "default_status_filter",
    "display_size_mode",
    "display_speed_mode",
)

SECRET_ENV_TO_KEYS = (
    ("QBIREMO_PASSWORD", ("qb_password",)),
    ("QBIREMO_HTTP_BASIC_AUTH_PASSWORD", ("http_basic_auth_password",)),
)

DEFAULT_PROFILE_CONFIG: dict[str, Any] = {
    "qb_host": "127.0.0.1",
    "qb_port": 8080,
    "qb_username": "admin",
    "qb_password": "CHANGE_ME",
    "http_basic_auth_username": "",
    "http_basic_auth_password": "",
    "http_protocol_scheme": "http",
    "http_timeout": DEFAULT_HTTP_TIMEOUT_SECONDS,
    "log_file": DEFAULT_LOG_FILE_NAME,
    "title_bar_speed_format": DEFAULT_TITLE_BAR_SPEED_FORMAT,
}

# (key, expected_type, default)
PROFILE_SCHEMA: tuple[tuple[str, type, Any], ...] = (
    ("qb_host", str, DEFAULT_PROFILE_CONFIG["qb_host"]),
    ("qb_port", int, DEFAULT_PROFILE_CONFIG["qb_port"]),
    ("qb_username", str, DEFAULT_PROFILE_CONFIG["qb_username"]),
    ("qb_password", str, DEFAULT_PROFILE_CONFIG["qb_password"]),
    (
        "http_basic_auth_username",
        str,
        DEFAULT_PROFILE_CONFIG["http_basic_auth_username"],
    ),
    (
        "http_basic_auth_password",
        str,
        DEFAULT_PROFILE_CONFIG["http_basic_auth_password"],
    ),
    ("http_protocol_scheme", str, DEFAULT_PROFILE_CONFIG["http_protocol_scheme"]),
    ("http_timeout", int, DEFAULT_PROFILE_CONFIG["http_timeout"]),
    ("log_file", str, DEFAULT_PROFILE_CONFIG["log_file"]),
    (
        "title_bar_speed_format",
        str,
        DEFAULT_PROFILE_CONFIG["title_bar_speed_format"],
    ),
)


def _new_profile_settings() -> QSettings:
    configure_qsettings()
    return QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        G_ORG_NAME,
        CONFIG_SETTINGS_APP_NAME,
    )


def normalize_profile_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return DEFAULT_PROFILE_ID
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-_")
    return cleaned or DEFAULT_PROFILE_ID


def list_profile_ids() -> list[str]:
    settings = _new_profile_settings()
    settings.beginGroup(_PROFILE_ROOT)
    profiles = [normalize_profile_id(group) for group in settings.childGroups()]
    settings.endGroup()
    deduped = sorted({profile for profile in profiles if profile})
    if DEFAULT_PROFILE_ID not in deduped:
        deduped.insert(0, DEFAULT_PROFILE_ID)
    return deduped


def profile_store_file_path() -> str:
    settings = _new_profile_settings()
    settings.sync()
    return str(settings.fileName() or "").strip()


def _profile_base_key(profile_id: str) -> str:
    return f"{_PROFILE_ROOT}/{normalize_profile_id(profile_id)}"


def _runtime_log_dir() -> Path:
    """Resolve runtime log directory under app data storage."""
    return resolve_app_data_dir() / "logs"


def _resolve_log_file_path(raw_log_file: str, instance_id: str) -> Path:
    """Resolve one log file path, anchoring relative paths under temp dir."""
    path_obj = Path(str(raw_log_file).strip()).expanduser()
    if not path_obj.is_absolute():
        path_obj = _runtime_log_dir() / path_obj
    return Path(_append_instance_id_to_filename(str(path_obj), instance_id))


def _default_instance_log_file_path(instance_id: str) -> str:
    """Build default per-instance log path under the temp runtime directory."""
    return str(_resolve_log_file_path(DEFAULT_LOG_FILE_NAME, instance_id))


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return bool(default)


def _coerce_value(value: Any, expected_type: type, default: Any) -> Any:
    if expected_type is bool:
        return _coerce_bool(value, bool(default))
    if expected_type is int:
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return int(default)
    if expected_type is float:
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return float(default)
    if value is None:
        return default
    return str(value)


def save_profile_config(profile_id: str, config: dict[str, Any]) -> str:
    """Persist one profile into QSettings and return normalized profile id."""
    normalized_profile = normalize_profile_id(profile_id)
    merged = dict(DEFAULT_PROFILE_CONFIG)
    if isinstance(config, dict):
        merged.update(config)

    settings = _new_profile_settings()
    base_key = _profile_base_key(normalized_profile)
    for key, expected_type, default in PROFILE_SCHEMA:
        settings.setValue(
            f"{base_key}/{key}",
            _coerce_value(merged.get(key, default), expected_type, default),
        )
    settings.sync()
    return normalized_profile


def delete_profile_config(profile_id: str) -> None:
    normalized_profile = normalize_profile_id(profile_id)
    settings = _new_profile_settings()
    settings.remove(_profile_base_key(normalized_profile))
    settings.sync()


def _apply_secret_env_overrides(config: dict[str, Any]) -> None:
    for env_name, key_path in SECRET_ENV_TO_KEYS:
        env_value = os.environ.get(env_name, "")
        if env_value:
            config[key_path[0]] = env_value


def _load_profile_settings(profile_id: str, issues: list[str]) -> dict[str, Any]:
    normalized_profile = normalize_profile_id(profile_id)
    settings = _new_profile_settings()
    base_key = _profile_base_key(normalized_profile)

    profile_exists = any(
        settings.contains(f"{base_key}/{key}") for key, _expected_type, _default in PROFILE_SCHEMA
    )
    if not profile_exists:
        issues.append(
            f"Profile '{normalized_profile}' not found in QSettings; seeding defaults."
        )
        save_profile_config(normalized_profile, DEFAULT_PROFILE_CONFIG)

    loaded: dict[str, Any] = dict(DEFAULT_PROFILE_CONFIG)
    for key, expected_type, default in PROFILE_SCHEMA:
        raw = settings.value(f"{base_key}/{key}", default)
        loaded[key] = _coerce_value(raw, expected_type, default)
    loaded["_profile_id"] = normalized_profile
    return loaded


def load_config(profile_id: str | None) -> NormalizedConfig:
    """Load one profile-backed configuration from QSettings."""
    config, _issues = load_config_with_issues(profile_id)
    return config


def load_config_with_issues(profile_id: str | None) -> tuple[NormalizedConfig, list[str]]:
    """Load one profile-backed configuration and collect non-fatal issues."""
    issues: list[str] = []
    normalized_profile = normalize_profile_id(profile_id)
    loaded = _load_profile_settings(normalized_profile, issues)
    _apply_secret_env_overrides(loaded)
    return cast("NormalizedConfig", loaded), issues


def get_missing_required_config(config: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if "qb_host" in config:
        host = str(config.get("qb_host", "") or "").strip()
        if not host:
            missing.append("qb_host is required")
    if "qb_username" in config:
        username = str(config.get("qb_username", "") or "").strip()
        if not username:
            missing.append("qb_username is required")
    if "qb_password" in config:
        password = str(config.get("qb_password", "") or "").strip()
        if not password or password.upper() == "CHANGE_ME":
            missing.append("qb_password is required")
    return missing


def _config_validation_warn(message: str) -> None:
    """Log one configuration validation warning message."""
    logger.warning("Config validation: %s", message)


def _config_validation_coerce_int(value: object, default: int) -> int:
    """Coerce one value to int with fallback default."""
    if isinstance(value, (int, float, str, bytes, bytearray)):
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default
    return default


def _apply_legacy_config_mappings(normalized: dict[str, object]) -> None:
    """Map legacy config keys to current keys with warnings."""
    for old_key, new_key in CONFIG_VALIDATION_LEGACY_MAP.items():
        if new_key not in normalized and old_key in normalized:
            normalized[new_key] = normalized.get(old_key)
            _config_validation_warn(
                f"'{old_key}' is deprecated; use '{new_key}'. Using '{old_key}' value for now."
            )


def _remove_settings_managed_config_keys(normalized: dict[str, object]) -> None:
    """Drop config keys that are intentionally managed by QSettings."""
    for key in CONFIG_VALIDATION_SETTINGS_MANAGED_KEYS:
        if key in normalized:
            _config_validation_warn(f"'{key}' is ignored in runtime profile config; managed via UI settings.")
            normalized.pop(key, None)


def _normalize_qb_host_value(normalized: dict[str, object]) -> None:
    """Normalize qb_host value."""
    host_val = normalized.get("qb_host", "localhost")
    if not isinstance(host_val, str) or not host_val.strip():
        _config_validation_warn(f"'qb_host' invalid ({host_val!r}); using 'localhost'.")
        normalized["qb_host"] = "localhost"
    else:
        normalized["qb_host"] = host_val.strip()


def _normalize_qb_port_value(normalized: dict[str, object]) -> None:
    """Normalize qb_port value."""
    raw_port = normalized.get("qb_port", 8080)
    port = _config_validation_coerce_int(raw_port, 8080)
    if port < 1 or port > 65535:
        _config_validation_warn(f"'qb_port' out of range ({raw_port!r}); using 8080.")
        port = 8080
    normalized["qb_port"] = port


def _normalize_http_protocol_scheme_value(normalized: dict[str, object]) -> None:
    """Normalize optional http_protocol_scheme value."""
    if "http_protocol_scheme" not in normalized:
        return
    raw_scheme = normalized.get("http_protocol_scheme")
    normalized_scheme = _normalize_http_protocol_scheme(raw_scheme)
    raw_scheme_text = str(raw_scheme).strip().lower() if isinstance(raw_scheme, str) else ""
    if raw_scheme_text not in ("http", "https"):
        _config_validation_warn(f"'http_protocol_scheme' invalid ({raw_scheme!r}); using 'http'.")
    normalized["http_protocol_scheme"] = normalized_scheme


def _normalize_http_timeout_value(normalized: dict[str, object]) -> None:
    """Normalize optional http_timeout value (seconds)."""
    raw_timeout = normalized.get("http_timeout", DEFAULT_HTTP_TIMEOUT_SECONDS)
    if isinstance(raw_timeout, (int, float, str, bytes, bytearray)):
        try:
            timeout_seconds = int(raw_timeout)
        except (TypeError, ValueError, OverflowError):
            _config_validation_warn(
                f"'http_timeout' invalid ({raw_timeout!r}); using {DEFAULT_HTTP_TIMEOUT_SECONDS}."
            )
            timeout_seconds = DEFAULT_HTTP_TIMEOUT_SECONDS
    else:
        _config_validation_warn(
            f"'http_timeout' invalid ({raw_timeout!r}); using {DEFAULT_HTTP_TIMEOUT_SECONDS}."
        )
        timeout_seconds = DEFAULT_HTTP_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        _config_validation_warn(
            f"'http_timeout' invalid ({raw_timeout!r}); using {DEFAULT_HTTP_TIMEOUT_SECONDS}."
        )
        timeout_seconds = DEFAULT_HTTP_TIMEOUT_SECONDS
    normalized["http_timeout"] = int(timeout_seconds)


def _normalize_credential_values(normalized: dict[str, object]) -> None:
    """Normalize credential-related string values."""
    for key, default_value in [
        ("qb_username", "admin"),
        ("qb_password", ""),
        ("http_basic_auth_username", ""),
        ("http_basic_auth_password", ""),
    ]:
        value = normalized.get(key, default_value)
        if value is None:
            value = default_value
        if not isinstance(value, str):
            _config_validation_warn(f"'{key}' should be a string; using default.")
            value = str(default_value)
        normalized[key] = value


def _normalize_log_file_value(normalized: dict[str, object]) -> None:
    """Normalize optional log_file path value."""
    raw_log_file = normalized.get("log_file", DEFAULT_LOG_FILE_NAME)
    if not isinstance(raw_log_file, str) or not raw_log_file.strip():
        _config_validation_warn(
            f"'log_file' invalid ({raw_log_file!r}); using {DEFAULT_LOG_FILE_NAME!r}."
        )
        normalized["log_file"] = DEFAULT_LOG_FILE_NAME
    else:
        normalized["log_file"] = raw_log_file.strip()


def _normalize_title_bar_speed_format_value(normalized: dict[str, object]) -> None:
    """Normalize title_bar_speed_format template string."""
    raw_title_fmt = normalized.get(
        "title_bar_speed_format",
        DEFAULT_TITLE_BAR_SPEED_FORMAT,
    )
    if not isinstance(raw_title_fmt, str) or not raw_title_fmt.strip():
        _config_validation_warn(
            f"'title_bar_speed_format' invalid; using default {DEFAULT_TITLE_BAR_SPEED_FORMAT!r}."
        )
        title_fmt = DEFAULT_TITLE_BAR_SPEED_FORMAT
    else:
        title_fmt = raw_title_fmt.strip()
    try:
        title_fmt.format(up_text="0", down_text="0")
    except (IndexError, KeyError, ValueError):
        _config_validation_warn(
            "'title_bar_speed_format' failed to format with {up_text}/{down_text}; "
            f"using default {DEFAULT_TITLE_BAR_SPEED_FORMAT!r}."
        )
        title_fmt = DEFAULT_TITLE_BAR_SPEED_FORMAT
    normalized["title_bar_speed_format"] = title_fmt


def _warn_unknown_config_keys(normalized: dict[str, object]) -> None:
    """Warn for unknown config keys."""
    unknown_keys = sorted(
        key
        for key in normalized
        if key not in CONFIG_VALIDATION_KNOWN_KEYS and key not in CONFIG_VALIDATION_LEGACY_MAP
    )
    for key in unknown_keys:
        _config_validation_warn(f"Unknown config key '{key}' will be ignored.")


def validate_and_normalize_config(config: object, profile_id: str) -> NormalizedConfig:
    """Validate config values and return one sanitized config mapping."""
    if not isinstance(config, dict):
        logger.warning(
            "Config validation: root config from profile %s is not a mapping. Using defaults.",
            profile_id,
        )
        config = {}

    normalized: dict[str, object] = dict(config)
    _apply_legacy_config_mappings(normalized)
    _remove_settings_managed_config_keys(normalized)
    _normalize_qb_host_value(normalized)
    _normalize_qb_port_value(normalized)
    _normalize_http_protocol_scheme_value(normalized)
    _normalize_http_timeout_value(normalized)
    _normalize_credential_values(normalized)
    _normalize_log_file_value(normalized)
    _normalize_title_bar_speed_format_value(normalized)
    _warn_unknown_config_keys(normalized)

    normalized_profile = normalize_profile_id(normalized.get("_profile_id", profile_id))
    normalized["_profile_id"] = normalized_profile
    logger.info("Configuration validated from profile %s", normalized_profile)
    return cast("NormalizedConfig", normalized)


def _setup_logging(config: NormalizedConfig) -> logging.FileHandler:
    """Configure file logging and return the active file handler."""
    instance_id = str(config.get("_instance_id", "") or "").strip().lower()
    if not instance_id:
        instance_id = compute_instance_id_from_config(config)
    config["_instance_id"] = instance_id

    log_file = config.get("log_file", DEFAULT_LOG_FILE_NAME)
    if not isinstance(log_file, str) or not log_file.strip():
        log_file = DEFAULT_LOG_FILE_NAME
    log_file_path = _resolve_log_file_path(log_file, instance_id)
    config["_log_file_path"] = str(log_file_path)

    with suppress(OSError):
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    except OSError:
        fallback_log_file = Path(_default_instance_log_file_path(instance_id))
        fallback_log_file.parent.mkdir(parents=True, exist_ok=True)
        config["_log_file_path"] = str(fallback_log_file)
        file_handler = logging.FileHandler(fallback_log_file, encoding="utf-8")

    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.setLevel(logging.DEBUG)
    return file_handler


def _open_file_in_default_app(path: str) -> bool:
    """Open one path in the platform default application."""
    if not path:
        return False

    import subprocess

    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except (AttributeError, OSError, subprocess.SubprocessError):
        logger.exception("Failed to open file in default app: %s", path)
        return False


def _install_exception_hooks(file_handler: logging.FileHandler) -> None:
    """Install global exception hooks that flush and persist fatal errors."""

    def _excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        """Log one unhandled exception and flush the log handler."""
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        file_handler.flush()

    sys.excepthook = _excepthook
    atexit.register(file_handler.flush)
