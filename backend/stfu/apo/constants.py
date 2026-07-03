"""CLSIDs y pipes del STFU APO. Deben coincidir con apo/src/guids.h."""

APO_CLSID_MIC = "{A5C595A5-CE9C-41DE-B555-82867799E74B}"
APO_CLSID_SPK = "{BD92FF05-2825-4D63-919B-D89FAF679713}"

CLSID_BY_FLOW = {
    "Capture": APO_CLSID_MIC,
    "Render": APO_CLSID_SPK,
}

PIPE_BY_FLOW = {
    "Capture": r"\\.\pipe\stfu_apo_mic",
    "Render": r"\\.\pipe\stfu_apo_spk",
}
