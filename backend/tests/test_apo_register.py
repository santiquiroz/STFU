import winreg
import pytest
from unittest.mock import patch, MagicMock
from stfu.apo.register import register_apo, unregister_apo, get_apo_status

FAKE_GUID = "12345678-1234-1234-1234-123456789abc"
FAKE_CLSID = "{00000000-0000-0000-0000-000000000001}"

def test_get_apo_status_returns_not_registered_when_key_missing():
    with patch("winreg.OpenKey", side_effect=FileNotFoundError):
        status = get_apo_status(FAKE_GUID, "Capture")
    assert status["registered"] is False

def test_get_apo_status_returns_registered_when_clsid_present():
    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)
    with patch("winreg.OpenKey", return_value=mock_key):
        with patch("winreg.QueryValueEx", return_value=(FAKE_CLSID, winreg.REG_SZ)):
            status = get_apo_status(FAKE_GUID, "Capture")
    assert status["registered"] is True
    assert status["clsid"] == FAKE_CLSID
