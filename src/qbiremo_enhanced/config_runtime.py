"""Config loading/validation and runtime bootstrap helpers."""

import atexit
import logging
import os
import sys
import tempfile
from pathlib import Path
from types import TracebackType
from typing import cast

from .constants import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    DEFAULT_TITLE_BAR_SPEED_FORMAT,
    G_APP_NAME,
)
from .models.config import NormalizedConfig
from .utils import (
    _append_instance_id_to_filename,
    _normalize_http_protocol_scheme,
    compute_instance_id_from_config,
)

logger = logging.getLogger(G_APP_NAME)

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
APP_SLUG = "qbiremo-enhanced"
DEFAULT_CONFIG_REL = Path("config/app.defaults.toml")
LOCAL_CONFIG_REL = Path("config/app.local.toml")
APP_CONFIG_PATH_ENV = "APP_CONFIG_PATH"
APP_SECRETS_PATH_ENV = "APP_SECRETS_PATH"
SECRET_ENV_TO_KEYS = (
    ("QBIREMO_PASSWORD", ("qb_password",)),
    ("QBIREMO_HTTP_BASIC_AUTH_PASSWORD", ("http_basic_auth_password",)),
)
DEFAULT_LOG_FILE_NAME = "qbiremo_enhanced.log"


def _deep_merge_dicts(base: dict, overlay: dict) -> dict:
    merged: dict = dict(base)
    for key, value in overlay.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dicts(base_value, value)
        else:
            merged[key] = value
    return merged


def _set_nested_value(target: dict, key_path: tuple[str, ...], value: str) -> None:
    current = target
    for key in key_path[:-1]:
        next_value = current.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            current[key] = next_value
        current = next_value
    current[key_path[-1]] = value


def _resolve_local_config_path(config_file: str | None) -> Path:
    explicit_path = config_file or os.environ.get(APP_CONFIG_PATH_ENV, "")
    if explicit_path:
        path = Path(explicit_path).expanduser()
        return path if path.is_absolute() else Path.cwd() / path
    return Path.cwd() / LOCAL_CONFIG_REL


def _resolve_defaults_path() -> Path:
    return Path.cwd() / DEFAULT_CONFIG_REL


def _resolve_secrets_path() -> Path:
    explicit_path = os.environ.get(APP_SECRETS_PATH_ENV, "")
    if explicit_path:
        path = Path(explicit_path).expanduser()
        return path if path.is_absolute() else Path.cwd() / path
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_SLUG / "secrets.toml"
        return Path.home() / "AppData" / "Roaming" / APP_SLUG / "secrets.toml"
    return Path.home() / ".config" / APP_SLUG / "secrets.toml"


def _runtime_log_dir() -> Path:
    """Resolve runtime log directory under OS temp storage."""
    return Path(tempfile.gettempdir()) / APP_SLUG


def _resolve_log_file_path(raw_log_file: str, instance_id: str) -> Path:
    """Resolve one log file path, anchoring relative paths under temp dir."""
    path_obj = Path(str(raw_log_file).strip()).expanduser()
    if not path_obj.is_absolute():
        path_obj = _runtime_log_dir() / path_obj
    return Path(_append_instance_id_to_filename(str(path_obj), instance_id))


def _default_instance_log_file_path(instance_id: str) -> str:
    """Build default per-instance log path under the temp runtime directory."""
    return str(_resolve_log_file_path(DEFAULT_LOG_FILE_NAME, instance_id))


def _load_optional_toml(path: Path, issues: list[str], role: str) -> dict:
    if not path.exists():
        issues.append(f"{role} config file not found: {path}")
        return {}
    try:
        import tomllib

        with path.open("rb") as f:
            loaded = tomllib.load(f)
        return loaded if isinstance(loaded, dict) else {}
    except (ModuleNotFoundError, OSError, TypeError, ValueError) as e:
        issues.append(f"Failed to parse {role} config file {path}: {e}")
        return {}


def _load_optional_toml_if_exists(path: Path, issues: list[str], role: str) -> dict:
    if not path.exists():
        return {}
    return _load_optional_toml(path, issues, role)


def _apply_secret_env_overrides(config: dict) -> None:
    for env_name, key_path in SECRET_ENV_TO_KEYS:
        env_value = os.environ.get(env_name, "")
        if env_value:
            _set_nested_value(config, key_path, env_value)


def _empty_config() -> NormalizedConfig:
    """Build one empty normalized config value for typed fallbacks."""
    return cast("NormalizedConfig", {})


def load_config(config_file: str | None) -> NormalizedConfig:
    """Load layered TOML configuration (defaults/local/secrets/env)."""
    config, _issues = load_config_with_issues(config_file)
    return config


def load_config_with_issues(config_file: str | None) -> tuple[NormalizedConfig, list[str]]:
    """Load layered TOML configuration and collect non-fatal issues."""
    issues: list[str] = []
    defaults_path = _resolve_defaults_path()
    local_path = _resolve_local_config_path(config_file)
    secrets_path = _resolve_secrets_path()

    defaults_config = _load_optional_toml(defaults_path, issues, "defaults")
    local_config = _load_optional_toml(local_path, issues, "local")
    secrets_config = _load_optional_toml_if_exists(secrets_path, issues, "secrets")

    merged = _deep_merge_dicts(defaults_config, local_config)
    merged = _deep_merge_dicts(merged, secrets_config)
    _apply_secret_env_overrides(merged)

    if not merged:
        issues.append("No valid config loaded from defaults/local/secrets; using built-in defaults.")
        return _empty_config(), issues

    return cast("NormalizedConfig", merged), issues


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
            _config_validation_warn(f"'{key}' is ignored in TOML; managed via QSettings.")
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


def validate_and_normalize_config(config: object, config_file: str) -> NormalizedConfig:
    """Validate config values and return one sanitized config mapping."""
    if not isinstance(config, dict):
        logger.warning(
            "Config validation: root config from %s is not a TOML table/object. Using defaults.",
            config_file,
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

    logger.info("Configuration validated from %s", config_file)
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

    try:
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Directory creation failure will be handled by FileHandler fallback.
        pass

    try:
        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    except OSError:
        # Fallback to temp-dir default if configured log path is not writable.
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

    # Also flush the log file on normal exit so nothing is lost
    atexit.register(file_handler.flush)
