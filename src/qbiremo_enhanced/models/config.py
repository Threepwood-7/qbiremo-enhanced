"""Typed config contracts used across runtime and UI layers."""

from typing import TypedDict


class NormalizedConfig(TypedDict, total=False):
    """Normalized application config loaded from QSettings profiles and defaults."""

    qb_host: str
    qb_port: int
    qb_username: str
    qb_password: str
    http_basic_auth_username: str
    http_basic_auth_password: str
    http_protocol_scheme: str
    http_timeout: int
    log_file: str
    title_bar_speed_format: str
    _profile_id: str
    _log_file_path: str
    _instance_id: str
    _instance_counter: int
    _instance_lock_file_path: str
