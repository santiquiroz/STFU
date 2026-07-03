#pragma once
#include <guiddef.h>

// CLSIDs reales de STFU APO. Deben coincidir con:
//   backend/stfu/apo/constants.py  y  frontend/src/services/api.ts
// {A5C595A5-CE9C-41DE-B555-82867799E74B}
DEFINE_GUID(CLSID_StfuApoMic,
    0xa5c595a5, 0xce9c, 0x41de, 0xb5, 0x55, 0x82, 0x86, 0x77, 0x99, 0xe7, 0x4b);
// {BD92FF05-2825-4D63-919B-D89FAF679713}
DEFINE_GUID(CLSID_StfuApoSpk,
    0xbd92ff05, 0x2825, 0x4d63, 0x91, 0x9b, 0xd8, 0x9f, 0xaf, 0x67, 0x97, 0x13);

#define STFU_CLSID_MIC_STR L"{A5C595A5-CE9C-41DE-B555-82867799E74B}"
#define STFU_CLSID_SPK_STR L"{BD92FF05-2825-4D63-919B-D89FAF679713}"

#define STFU_PIPE_MIC L"\\\\.\\pipe\\stfu_apo_mic"
#define STFU_PIPE_SPK L"\\\\.\\pipe\\stfu_apo_spk"
