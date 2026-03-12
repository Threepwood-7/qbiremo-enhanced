"""Profile setup and selection dialogs for qbiremo runtime config."""

from __future__ import annotations

import base64
from typing import Any

import qbittorrentapi
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config_runtime import DEFAULT_PROFILE_ID, normalize_profile_id


class ProfileSetupDialog(QDialog):
    def __init__(
        self, profile_id: str, initial: dict[str, Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("qBiremo Profile Setup")
        self.resize(680, 420)

        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                "Configure one qBiremo profile. Values are stored in the shared profile settings store."
            )
        )

        form = QFormLayout()
        self.txt_profile_id = QLineEdit(profile_id)
        self.txt_qb_host = QLineEdit(
            str(initial.get("qb_host", "127.0.0.1") or "127.0.0.1")
        )
        self.spn_qb_port = QSpinBox()
        self.spn_qb_port.setRange(1, 65535)
        self.spn_qb_port.setValue(int(initial.get("qb_port", 8080) or 8080))
        self.txt_qb_username = QLineEdit(
            str(initial.get("qb_username", "admin") or "admin")
        )
        self.txt_qb_password = QLineEdit(str(initial.get("qb_password", "") or ""))
        self.txt_qb_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_http_user = QLineEdit(
            str(initial.get("http_basic_auth_username", "") or "")
        )
        self.txt_http_password = QLineEdit(
            str(initial.get("http_basic_auth_password", "") or "")
        )
        self.txt_http_password.setEchoMode(QLineEdit.EchoMode.Password)

        self.txt_scheme = QLineEdit(
            str(initial.get("http_protocol_scheme", "http") or "http")
        )
        self.spn_timeout = QSpinBox()
        self.spn_timeout.setRange(1, 3600)
        self.spn_timeout.setValue(int(initial.get("http_timeout", 300) or 300))

        form.addRow("Profile ID", self.txt_profile_id)
        form.addRow("qB Host", self.txt_qb_host)
        form.addRow("qB Port", self.spn_qb_port)
        form.addRow("qB Username", self.txt_qb_username)
        form.addRow("qB Password", self.txt_qb_password)
        form.addRow("HTTP Basic Auth User", self.txt_http_user)
        form.addRow("HTTP Basic Auth Password", self.txt_http_password)
        form.addRow("HTTP Scheme (http/https)", self.txt_scheme)
        form.addRow("HTTP Timeout (s)", self.spn_timeout)
        root.addLayout(form)

        btn_test_connection = QPushButton("Test Connection")
        btn_test_connection.clicked.connect(self._on_test_connection)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(btn_test_connection)
        row.addStretch(1)
        row.addWidget(buttons)
        root.addLayout(row)

    def _on_accept(self) -> None:
        profile_id = normalize_profile_id(self.txt_profile_id.text())
        if not profile_id:
            QMessageBox.warning(self, "Validation", "Profile ID is required.")
            return

        host = str(self.txt_qb_host.text() or "").strip()
        username = str(self.txt_qb_username.text() or "").strip()
        password = str(self.txt_qb_password.text() or "").strip()
        scheme = str(self.txt_scheme.text() or "http").strip().lower()

        if not host:
            QMessageBox.warning(self, "Validation", "qB host is required.")
            return
        if not username:
            QMessageBox.warning(self, "Validation", "qB username is required.")
            return
        if not password or password.upper() == "CHANGE_ME":
            QMessageBox.warning(self, "Validation", "Set a real qB password.")
            return
        if scheme not in {"http", "https"}:
            QMessageBox.warning(
                self, "Validation", "HTTP scheme must be 'http' or 'https'."
            )
            return
        self.accept()

    def _on_test_connection(self) -> None:
        host = str(self.txt_qb_host.text() or "").strip()
        username = str(self.txt_qb_username.text() or "").strip()
        password = str(self.txt_qb_password.text() or "").strip()
        http_user = str(self.txt_http_user.text() or "").strip()
        http_password = str(self.txt_http_password.text() or "").strip()
        scheme = str(self.txt_scheme.text() or "http").strip().lower()
        timeout = int(self.spn_timeout.value())
        port = int(self.spn_qb_port.value())

        if not host:
            QMessageBox.warning(self, "Connection Test", "qB host is required.")
            return
        if not username:
            QMessageBox.warning(self, "Connection Test", "qB username is required.")
            return
        if not password or password.upper() == "CHANGE_ME":
            QMessageBox.warning(self, "Connection Test", "Set a real qB password.")
            return
        if scheme not in {"http", "https"}:
            QMessageBox.warning(
                self, "Connection Test", "HTTP scheme must be 'http' or 'https'."
            )
            return

        host_with_scheme = host if "://" in host else f"{scheme}://{host}"
        client_args: dict[str, Any] = {
            "host": host_with_scheme,
            "port": port,
            "username": username,
            "password": password,
            "FORCE_SCHEME_FROM_HOST": True,
            "VERIFY_WEBUI_CERTIFICATE": False,
            "DISABLE_LOGGING_DEBUG_OUTPUT": False,
            "REQUESTS_ARGS": {"timeout": timeout},
        }
        if http_user:
            credentials = base64.b64encode(
                f"{http_user}:{http_password}".encode()
            ).decode()
            client_args["EXTRA_HEADERS"] = {"Authorization": f"Basic {credentials}"}

        try:
            client = qbittorrentapi.Client(**client_args)
            client.auth_log_in()
            version = str(getattr(client.app, "version", "unknown"))
            QMessageBox.information(
                self,
                "Connection Test",
                f"qBittorrent connection successful.\nVersion: {version}",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Connection Test Failed",
                f"qBittorrent connection failed:\n{exc}",
            )

    def to_profile_payload(self) -> tuple[str, dict[str, Any]]:
        profile_id = normalize_profile_id(
            self.txt_profile_id.text() or DEFAULT_PROFILE_ID
        )
        payload: dict[str, Any] = {
            "qb_host": str(self.txt_qb_host.text() or "").strip(),
            "qb_port": int(self.spn_qb_port.value()),
            "qb_username": str(self.txt_qb_username.text() or "").strip(),
            "qb_password": str(self.txt_qb_password.text() or "").strip(),
            "http_basic_auth_username": str(self.txt_http_user.text() or "").strip(),
            "http_basic_auth_password": str(
                self.txt_http_password.text() or ""
            ).strip(),
            "http_protocol_scheme": str(self.txt_scheme.text() or "http")
            .strip()
            .lower(),
            "http_timeout": int(self.spn_timeout.value()),
        }
        return profile_id, payload


def run_profile_setup_wizard(
    profile_id: str,
    initial: dict[str, Any],
    parent: QWidget | None = None,
) -> tuple[str, dict[str, Any]] | None:
    dialog = ProfileSetupDialog(profile_id, initial, parent=parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.to_profile_payload()


def prompt_profile_selection(
    profile_ids: list[str],
    current_profile: str,
    parent: QWidget | None = None,
) -> str | None:
    ordered = list(dict.fromkeys([normalize_profile_id(p) for p in profile_ids if p]))
    if not ordered:
        ordered = [DEFAULT_PROFILE_ID]
    normalized_current = normalize_profile_id(current_profile)
    default_index = (
        ordered.index(normalized_current) if normalized_current in ordered else 0
    )
    selected, ok = QInputDialog.getItem(
        parent,
        "Select Profile",
        "Launch new instance with profile:",
        ordered,
        default_index,
        editable=False,
    )
    if not ok:
        return None
    return normalize_profile_id(selected)
