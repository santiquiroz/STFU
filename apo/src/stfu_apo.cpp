#include "stfu_apo.h"
#include <cstdio>
#include <cstring>
#include <new>

namespace {
// KSDATAFORMAT_SUBTYPE_IEEE_FLOAT sin arrastrar ksmedia.h completo
const GUID kIeeeFloatSubtype =
    {0x00000003, 0x0000, 0x0010, {0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71}};
}

// Prueba de que audiodg cargó e instanció el APO: si esta línea aparece en
// C:\ProgramData\STFU\apo.log tras abrir el dispositivo, el APO está en la
// cadena. Escribible por audiodg (LocalService) porque ProgramData lo es.
void StfuApo::FileLog(const char* msg) const {
    FILE* f = nullptr;
    if (fopen_s(&f, "C:\\ProgramData\\STFU\\apo.log", "a") == 0 && f) {
        fprintf(f, "[tick %lu] %ls: %s\n", GetTickCount(), friendlyName_.c_str(), msg);
        fclose(f);
    }
}

StfuApo::StfuApo(REFCLSID clsid, const wchar_t* friendlyName, const wchar_t* pipeName)
    : clsid_(clsid), friendlyName_(friendlyName), pipeName_(pipeName) {
    FileLog("APO construido — audiodg encontró e instanció el CLSID");
}

StfuApo::~StfuApo() { worker_.Stop(); }

// ---------------------------------------------------------------- IUnknown

STDMETHODIMP StfuApo::QueryInterface(REFIID riid, void** ppv) {
    if (ppv == nullptr) return E_POINTER;
    *ppv = nullptr;
    if (riid == __uuidof(IUnknown) || riid == __uuidof(IAudioProcessingObject)) {
        *ppv = static_cast<IAudioProcessingObject*>(this);
    } else if (riid == __uuidof(IAudioProcessingObjectRT)) {
        *ppv = static_cast<IAudioProcessingObjectRT*>(this);
    } else if (riid == __uuidof(IAudioProcessingObjectConfiguration)) {
        *ppv = static_cast<IAudioProcessingObjectConfiguration*>(this);
    } else if (riid == __uuidof(IAudioSystemEffects)) {
        *ppv = static_cast<IAudioSystemEffects*>(this);
    } else {
        return E_NOINTERFACE;
    }
    AddRef();
    return S_OK;
}

STDMETHODIMP_(ULONG) StfuApo::AddRef() { return ++refs_; }

STDMETHODIMP_(ULONG) StfuApo::Release() {
    const ULONG n = --refs_;
    if (n == 0) delete this;
    return n;
}

// ------------------------------------------------- IAudioProcessingObject

STDMETHODIMP StfuApo::Reset() {
    worker_.Reset();
    return S_OK;
}

STDMETHODIMP StfuApo::GetLatency(HNSTIME* pTime) {
    if (pTime == nullptr) return E_POINTER;
    *pTime = 0;  // asíncrono: no retiene el grafo; passthrough si no hay datos
    return S_OK;
}

STDMETHODIMP StfuApo::GetRegistrationProperties(APO_REG_PROPERTIES** ppRegProps) {
    if (ppRegProps == nullptr) return E_POINTER;
    auto* props = static_cast<APO_REG_PROPERTIES*>(CoTaskMemAlloc(sizeof(APO_REG_PROPERTIES)));
    if (props == nullptr) return E_OUTOFMEMORY;
    std::memset(props, 0, sizeof(*props));
    props->clsid = clsid_;
    props->Flags = static_cast<APO_FLAG>(APO_FLAG_FRAMESPERSECOND_MUST_MATCH |
                                         APO_FLAG_BITSPERSAMPLE_MUST_MATCH |
                                         APO_FLAG_SAMPLESPERFRAME_MUST_MATCH);
    wcsncpy_s(props->szFriendlyName, friendlyName_.c_str(), _TRUNCATE);
    wcsncpy_s(props->szCopyrightInfo, L"MIT — STFU project", _TRUNCATE);
    props->u32MajorVersion = 1;
    props->u32MinInputConnections = 1;
    props->u32MaxInputConnections = 1;
    props->u32MinOutputConnections = 1;
    props->u32MaxOutputConnections = 1;
    props->u32MaxInstances = 8;
    props->u32NumAPOInterfaces = 0;
    *ppRegProps = props;
    return S_OK;
}

STDMETHODIMP StfuApo::Initialize(UINT32 cbDataSize, BYTE* pbyData) {
    UNREFERENCED_PARAMETER(cbDataSize);
    UNREFERENCED_PARAMETER(pbyData);
    FileLog("Initialize — audiodg instanció el APO");
    return S_OK;
}

HRESULT StfuApo::CheckFloat32(IAudioMediaType* fmt) const {
    if (fmt == nullptr) return E_POINTER;
    UNCOMPRESSEDAUDIOFORMAT ua{};
    HRESULT hr = fmt->GetUncompressedAudioFormat(&ua);
    if (FAILED(hr)) return hr;
    if (ua.guidFormatType != kIeeeFloatSubtype || ua.dwBytesPerSampleContainer != 4) {
        return APOERR_FORMAT_NOT_SUPPORTED;
    }
    return S_OK;
}

STDMETHODIMP StfuApo::IsInputFormatSupported(IAudioMediaType* pOppositeFormat,
                                             IAudioMediaType* pRequestedInputFormat,
                                             IAudioMediaType** ppSupportedInputFormat) {
    UNREFERENCED_PARAMETER(pOppositeFormat);
    if (pRequestedInputFormat == nullptr || ppSupportedInputFormat == nullptr)
        return E_POINTER;
    HRESULT hr = CheckFloat32(pRequestedInputFormat);
    if (FAILED(hr)) return hr;
    pRequestedInputFormat->AddRef();
    *ppSupportedInputFormat = pRequestedInputFormat;
    return S_OK;
}

STDMETHODIMP StfuApo::IsOutputFormatSupported(IAudioMediaType* pOppositeFormat,
                                              IAudioMediaType* pRequestedOutputFormat,
                                              IAudioMediaType** ppSupportedOutputFormat) {
    UNREFERENCED_PARAMETER(pOppositeFormat);
    if (pRequestedOutputFormat == nullptr || ppSupportedOutputFormat == nullptr)
        return E_POINTER;
    HRESULT hr = CheckFloat32(pRequestedOutputFormat);
    if (FAILED(hr)) return hr;
    pRequestedOutputFormat->AddRef();
    *ppSupportedOutputFormat = pRequestedOutputFormat;
    return S_OK;
}

STDMETHODIMP StfuApo::GetInputChannelCount(UINT32* pu32ChannelCount) {
    if (pu32ChannelCount == nullptr) return E_POINTER;
    *pu32ChannelCount = channels_;
    return S_OK;
}

// ------------------------------------- IAudioProcessingObjectConfiguration

STDMETHODIMP StfuApo::LockForProcess(UINT32 u32NumInputConnections,
                                     APO_CONNECTION_DESCRIPTOR** ppInputConnections,
                                     UINT32 u32NumOutputConnections,
                                     APO_CONNECTION_DESCRIPTOR** ppOutputConnections) {
    if (u32NumInputConnections < 1 || u32NumOutputConnections < 1 ||
        ppInputConnections == nullptr || ppOutputConnections == nullptr)
        return E_INVALIDARG;
    APO_CONNECTION_DESCRIPTOR* in = ppInputConnections[0];
    if (in == nullptr || in->pFormat == nullptr) return E_INVALIDARG;

    UNCOMPRESSEDAUDIOFORMAT ua{};
    HRESULT hr = in->pFormat->GetUncompressedAudioFormat(&ua);
    if (FAILED(hr)) return hr;
    channels_ = ua.dwSamplesPerFrame;
    sampleRate_ = static_cast<UINT32>(ua.fFramesPerSecond);

    {
        wchar_t buf[160];
        swprintf_s(buf, L"[STFU-APO] LockForProcess rate=%u ch=%u maxFrames=%u pipe=%s\n",
                   sampleRate_, channels_, in->u32MaxFrameCount, pipeName_.c_str());
        OutputDebugStringW(buf);
        char abuf[128];
        sprintf_s(abuf, "LockForProcess rate=%u ch=%u — audiodg CARGO el APO",
                  sampleRate_, channels_);
        FileLog(abuf);
    }
    worker_.Start(pipeName_, sampleRate_, channels_, in->u32MaxFrameCount);
    locked_ = true;
    return S_OK;
}

STDMETHODIMP StfuApo::UnlockForProcess() {
    locked_ = false;
    worker_.Stop();
    return S_OK;
}

// ----------------------------------------------- IAudioProcessingObjectRT

STDMETHODIMP_(void) StfuApo::APOProcess(UINT32 u32NumInputConnections,
                                        APO_CONNECTION_PROPERTY** ppInputConnections,
                                        UINT32 u32NumOutputConnections,
                                        APO_CONNECTION_PROPERTY** ppOutputConnections) {
    if (u32NumInputConnections < 1 || u32NumOutputConnections < 1) return;
    APO_CONNECTION_PROPERTY* in = ppInputConnections[0];
    APO_CONNECTION_PROPERTY* out = ppOutputConnections[0];
    const float* src = reinterpret_cast<const float*>(in->pBuffer);
    float* dst = reinterpret_cast<float*>(out->pBuffer);
    const size_t samples = static_cast<size_t>(in->u32ValidFrameCount) * channels_;

    if (locked_ && in->u32BufferFlags == BUFFER_VALID) {
        worker_.InRing().Write(src, samples);
        worker_.SignalData();
        if (!worker_.OutRing().ReadExact(dst, samples)) {
            std::memcpy(dst, src, samples * sizeof(float));  // passthrough
        }
    } else {
        std::memcpy(dst, src, samples * sizeof(float));
    }
    out->u32ValidFrameCount = in->u32ValidFrameCount;
    out->u32BufferFlags = in->u32BufferFlags;
}

STDMETHODIMP_(UINT32) StfuApo::CalcInputFrames(UINT32 u32OutputFrameCount) {
    return u32OutputFrameCount;
}

STDMETHODIMP_(UINT32) StfuApo::CalcOutputFrames(UINT32 u32InputFrameCount) {
    return u32InputFrameCount;
}
