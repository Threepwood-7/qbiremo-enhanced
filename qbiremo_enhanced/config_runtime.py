
"""Config loading/validation and runtime bootstrap helpers."""

import atexit
import logging
import os
import sys
from typing import Any, Dict, List, Tuple

from .constants import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    DEFAULT_TITLE_BAR_SPEED_FORMAT,
    G_APP_NAME,
)
from .utils import _append_instance_id_to_filename, _normalize_http_protocol_scheme, compute_instance_id_from_config


logger = logging.getLogger(G_APP_NAME)


CONFIG_VALIDATION_KNOWN_KEYS = {
    "qb_host", "qb_port", "qb_username", "qb_password",
    "http_basic_auth_username", "http_basic_auth_password",
    "http_protocol_scheme",
    "http_timeout",
    "log_file",
    "title_bar_speed_format",
    "_config_file_path",
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


def load_config(config_file: str) -> Dict[str, Any]:
    """Load configuration from TOML file.

    Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
    Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
    """
    if os.path.exists(config_file):
        try:
            import tomllib
            with open(config_file, 'rb') as f:
                return tomllib.load(f)
        except Exception as e:
            logger.error("Failed to load config file %s: %s", config_file, e)
            return {}
    return {}

def load_config_with_issues(config_file: str) -> Tuple[Dict[str, Any], List[str]]:
    """Load TOML config and collect load-time issues without requiring logging.

    Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
    Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
    """
    issues: List[str] = []
    if not os.path.exists(config_file):
        issues.append(
            f"Config file not found: {config_file}. Using built-in defaults and environment fallbacks."
        )
        return {}, issues

    try:
        import tomllib
        with open(config_file, 'rb') as f:
            data = tomllib.load(f)
    except Exception as e:
        issues.append(f"Failed to parse config file {config_file}: {e}. Using defaults.")
        return {}, issues

    if not isinstance(data, dict):
        issues.append(
            f"Config file {config_file} did not parse to a TOML table/object. Using defaults."
        )
        return {}, issues

    return data, issues

def _config_validation_warn(message: str) -> None:
    """Log one configuration validation warning message.

    Side effects: None.
    Failure modes: None.
    """
    logger.warning("Config validation: %s", message)

def _config_validation_coerce_int(value: Any, default: int) -> int:
    """Coerce one value to int with fallback default.

    Side effects: None.
    Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
    """
    try:
        return int(value)
    except Exception:
        return default

def _apply_legacy_config_mappings(normalized: Dict[str, Any]) -> None:
    """Map legacy config keys to current keys with warnings.

    Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
    Failure modes: None.
    """
    for old_key, new_key in CONFIG_VALIDATION_LEGACY_MAP.items():
        if new_key not in normalized and old_key in normalized:
            normalized[new_key] = normalized.get(old_key)
            _config_validation_warn(
                f"'{old_key}' is deprecated; use '{new_key}'. "
                f"Using '{old_key}' value for now."
            )

def _remove_settings_managed_config_keys(normalized: Dict[str, Any]) -> None:
    """Drop config keys that are intentionally managed by QSettings.

    Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
    Failure modes: None.
    """
    for key in CONFIG_VALIDATION_SETTINGS_MANAGED_KEYS:
        if key in normalized:
            _config_validation_warn(f"'{key}' is ignored in TOML; managed via QSettings.")
            normalized.pop(key, None)

def _normalize_qb_host_value(normalized: Dict[str, Any]) -> None:
    """Normalize qb_host value.

    Side effects: None.
    Failure modes: None.
    """
    host_val = normalized.get("qb_host", "localhost")
    if not isinstance(host_val, str) or not host_val.strip():
        _config_validation_warn(f"'qb_host' invalid ({host_val!r}); using 'localhost'.")
        normalized["qb_host"] = "localhost"
    else:
        normalized["qb_host"] = host_val.strip()

def _normalize_qb_port_value(normalized: Dict[str, Any]) -> None:
    """Normalize qb_port value.

    Side effects: None.
    Failure modes: None.
    """
    raw_port = normalized.get("qb_port", 8080)
    port = _config_validation_coerce_int(raw_port, 8080)
    if port < 1 or port > 65535:
        _config_validation_warn(f"'qb_port' out of range ({raw_port!r}); using 8080.")
        port = 8080
    normalized["qb_port"] = port

def _normalize_http_protocol_scheme_value(normalized: Dict[str, Any]) -> None:
    """Normalize optional http_protocol_scheme value.

    Side effects: None.
    Failure modes: None.
    """
    if "http_protocol_scheme" not in normalized:
        return
    raw_scheme = normalized.get("http_protocol_scheme")
    normalized_scheme = _normalize_http_protocol_scheme(raw_scheme)
    raw_scheme_text = (
        str(raw_scheme).strip().lower()
        if isinstance(raw_scheme, str)
        else ""
    )
    if raw_scheme_text not in ("http", "https"):
        _config_validation_warn(
            f"'http_protocol_scheme' invalid ({raw_scheme!r}); using 'http'."
        )
    normalized["http_protocol_scheme"] = normalized_scheme

def _normalize_http_timeout_value(normalized: Dict[str, Any]) -> None:
    """Normalize optional http_timeout value (seconds).

    Side effects: None.
    Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
    """
    raw_timeout = normalized.get("http_timeout", DEFAULT_HTTP_TIMEOUT_SECONDS)
    try:
        timeout_seconds = int(raw_timeout)
    except Exception:
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

def _normalize_credential_values(normalized: Dict[str, Any]) -> None:
    """Normalize credential-related string values.

    Side effects: None.
    Failure modes: None.
    """
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

def _normalize_log_file_value(normalized: Dict[str, Any]) -> None:
    """Normalize optional log_file path value.

    Side effects: None.
    Failure modes: None.
    """
    raw_log_file = normalized.get("log_file", "qbiremo_enhanced.log")
    if not isinstance(raw_log_file, str) or not raw_log_file.strip():
        _config_validation_warn(
            f"'log_file' invalid ({raw_log_file!r}); using 'qbiremo_enhanced.log'."
        )
        normalized["log_file"] = "qbiremo_enhanced.log"
    else:
        normalized["log_file"] = raw_log_file.strip()

def _normalize_title_bar_speed_format_value(normalized: Dict[str, Any]) -> None:
    """Normalize title_bar_speed_format template string.

    Side effects: None.
    Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
    """
    raw_title_fmt = normalized.get(
        "title_bar_speed_format",
        DEFAULT_TITLE_BAR_SPEED_FORMAT,
    )
    if not isinstance(raw_title_fmt, str) or not raw_title_fmt.strip():
        _config_validation_warn(
            "'title_bar_speed_format' invalid; using default "
            f"{DEFAULT_TITLE_BAR_SPEED_FORMAT!r}."
        )
        title_fmt = DEFAULT_TITLE_BAR_SPEED_FORMAT
    else:
        title_fmt = raw_title_fmt.strip()
    try:
        title_fmt.format(up_text="0", down_text="0")
    except Exception:
        _config_validation_warn(
            "'title_bar_speed_format' failed to format with {up_text}/{down_text}; "
            f"using default {DEFAULT_TITLE_BAR_SPEED_FORMAT!r}."
        )
        title_fmt = DEFAULT_TITLE_BAR_SPEED_FORMAT
    normalized["title_bar_speed_format"] = title_fmt

def _warn_unknown_config_keys(normalized: Dict[str, Any]) -> None:
    """Warn for unknown config keys.

    Side effects: None.
    Failure modes: None.
    """
    unknown_keys = sorted(
        key for key in normalized.keys()
        if key not in CONFIG_VALIDATION_KNOWN_KEYS
        and key not in CONFIG_VALIDATION_LEGACY_MAP
    )
    for key in unknown_keys:
        _config_validation_warn(f"Unknown config key '{key}' will be ignored.")

def validate_and_normalize_config(config: Dict[str, Any], config_file: str) -> Dict[str, Any]:
    """Validate config values, log issues, and return a sanitized config dict.

    Side effects: None.
    Failure modes: None.
    """
    if not isinstance(config, dict):
        logger.warning(
            "Config validation: root config from %s is not a TOML table/object. Using defaults.",
            config_file
        )
        config = {}

    normalized = dict(config)
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

    logger.info("Configuration validated from %s", config_file)
    return normalized

def _setup_logging(config: Dict[str, Any]) -> logging.FileHandler:
    """Configure file logging and return the handler so it can be flushed.

    Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
    Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
    """
    instance_id = str(config.get("_instance_id", "") or "").strip().lower()
    if not instance_id:
        instance_id = compute_instance_id_from_config(config)
    config["_instance_id"] = instance_id

    log_file = config.get('log_file', 'qbiremo_enhanced.log')
    if not isinstance(log_file, str) or not log_file.strip():
        log_file = 'qbiremo_enhanced.log'
    log_file = log_file.strip()
    log_file = _append_instance_id_to_filename(log_file, instance_id)
    config['_log_file_path'] = log_file

    try:
        log_dir = os.path.dirname(os.path.abspath(log_file))
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
    except Exception:
        # Directory creation failure will be handled by FileHandler fallback.
        pass

    try:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
    except Exception:
        # Fallback to local path if configured log path is not writable.
        fallback_log_file = _append_instance_id_to_filename(
            'qbiremo_enhanced.log',
            instance_id,
        )
        config['_log_file_path'] = fallback_log_file
        file_handler = logging.FileHandler(fallback_log_file, encoding='utf-8')

    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)-7s %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.setLevel(logging.DEBUG)
    return file_handler

def _open_file_in_default_app(path: str) -> bool:
    """Open a file in the platform default application.

    Side effects: Updates application state and may trigger UI, queue, file, or timer side effects.
    Failure modes: Handles recoverable exceptions internally and applies fallback behavior where defined.
    """
    if not path:
        return False

    import subprocess

    try:
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
        return True
    except Exception:
        logger.exception("Failed to open file in default app: %s", path)
        return False

def _install_exception_hooks(file_handler: logging.FileHandler) -> None:
    """Install global hooks so that *every* unhandled exception is logged.

    Side effects: None.
    Failure modes: None.
        """
    def _excepthook(exc_type, exc_value, exc_tb) -> None:
        """Log unhandled exceptions and flush log handler immediately.

        Side effects: None.
        Failure modes: None.
        """
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_tb)
        )
        file_handler.flush()

    sys.excepthook = _excepthook

    # Also flush the log file on normal exit so nothing is lost
    atexit.register(file_handler.flush)
