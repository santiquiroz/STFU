from unittest.mock import patch
from stfu.apo import endpoint_finder as ef


def test_matches_via_full_friendly_name():
    def read(props, prop):
        return "Altavoces (2- FiiO Q series)" if prop == ef._PROP_FRIENDLY else ""
    with patch.object(ef, "_read_prop", read):
        assert ef._matches("Altavoces (2- FiiO Q series)", "p") is True


def test_matches_via_interface_name_when_friendly_absent():
    # el registro real parte el nombre: sin ,14, discrimina por interfaz
    def read(props, prop):
        return {ef._PROP_FRIENDLY: "", ef._PROP_DESC: "Altavoces",
                ef._PROP_IFACE: "FiiO Q series"}[prop]
    with patch.object(ef, "_read_prop", read):
        assert ef._matches("Altavoces (2- FiiO Q series)", "p") is True


def test_does_not_match_other_device_sharing_desc():
    # "Altavoces" solo (Realtek) no debe calzar con el nombre del FiiO
    def read(props, prop):
        return {ef._PROP_FRIENDLY: "", ef._PROP_DESC: "Altavoces",
                ef._PROP_IFACE: "Realtek(R) Audio"}[prop]
    with patch.object(ef, "_read_prop", read):
        assert ef._matches("Altavoces (2- FiiO Q series)", "p") is False


def test_prefers_active_endpoint_over_inactive():
    guids = ["inactive-guid", "active-guid"]
    with patch.object(ef.winreg, "OpenKey"), \
         patch.object(ef.winreg, "EnumKey", side_effect=[*guids, OSError()]), \
         patch.object(ef, "_matches", return_value=True), \
         patch.object(ef, "_device_state", side_effect=lambda base, g: ef._STATE_ACTIVE if g == "active-guid" else 8):
        assert ef.find_endpoint_guid("x", "Render") == "active-guid"
