"""Config + Settings doğrulama testleri."""

import pytest
import yaml
from pydantic import ValidationError

from app.config import AppConfig, load_config
from app.settings import Settings


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.web_port == 8080
    assert s.license_enforce is False
    assert s.auth_enabled is False
    s2 = Settings(_env_file=None, admin_password="secret")
    assert s2.auth_enabled is True


def test_settings_resolve_license_from_file(tmp_path):
    key_file = tmp_path / "license.key"
    key_file.write_text("ABC.DEF\n")
    s = Settings(_env_file=None, license_key="")
    assert s.resolve_license_key(str(key_file)) == "ABC.DEF"
    # env önceliklidir
    s2 = Settings(_env_file=None, license_key="ENVKEY")
    assert s2.resolve_license_key(str(key_file)) == "ENVKEY"


def test_appconfig_rejects_duplicate_camera_ids():
    with pytest.raises(ValidationError):
        AppConfig(
            cameras=[
                {"id": 1, "name": "A", "rtsp": "rtsp://a"},
                {"id": 1, "name": "B", "rtsp": "rtsp://b"},
            ]
        )


def test_appconfig_rejects_bad_regex():
    with pytest.raises(ValidationError):
        AppConfig(
            cameras=[{"id": 1, "name": "A", "rtsp": "rtsp://a"}],
            detection={"order_no_regex": "([unclosed"},
        )


def test_enabled_cameras_property():
    cfg = AppConfig(
        cameras=[
            {"id": 1, "name": "A", "rtsp": "rtsp://a", "enabled": True},
            {"id": 2, "name": "B", "rtsp": "rtsp://b", "enabled": False},
        ]
    )
    assert len(cfg.enabled_cameras) == 1


def test_load_config_fills_rtsp_placeholders(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        yaml.safe_dump(
            {"cameras": [{"id": 1, "name": "Masa 1", "rtsp": "rtsp://{user}:{pass}@1.2.3.4/1"}]}
        )
    )
    s = Settings(_env_file=None, camera_username="admin", camera_password="p4ss")
    cfg = load_config(str(cfg_file), settings=s)
    assert cfg.cameras[0].rtsp == "rtsp://admin:p4ss@1.2.3.4/1"


def test_load_config_missing_file():
    with pytest.raises(FileNotFoundError):
        load_config("yok_boyle_dosya.yaml")
