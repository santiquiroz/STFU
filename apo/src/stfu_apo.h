#pragma once
#include <windows.h>
#include <audioenginebaseapo.h>
#include <atomic>
#include <string>
#include "pipe_worker.h"

// APO de sistema (user-mode, corre dentro de audiodg.exe).
// APOProcess es RT-safe: intercambia audio con el worker del pipe vía rings
// lock-free; si el servicio Python no responde, passthrough transparente.
class StfuApo : public IAudioProcessingObject,
                public IAudioProcessingObjectRT,
                public IAudioProcessingObjectConfiguration,
                public IAudioSystemEffects {
public:
    StfuApo(REFCLSID clsid, const wchar_t* friendlyName, const wchar_t* pipeName);
    virtual ~StfuApo();

    // IUnknown
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override;
    STDMETHODIMP_(ULONG) AddRef() override;
    STDMETHODIMP_(ULONG) Release() override;

    // IAudioProcessingObject
    STDMETHODIMP Reset() override;
    STDMETHODIMP GetLatency(HNSTIME* pTime) override;
    STDMETHODIMP GetRegistrationProperties(APO_REG_PROPERTIES** ppRegProps) override;
    STDMETHODIMP Initialize(UINT32 cbDataSize, BYTE* pbyData) override;
    STDMETHODIMP IsInputFormatSupported(IAudioMediaType* pOppositeFormat,
                                        IAudioMediaType* pRequestedInputFormat,
                                        IAudioMediaType** ppSupportedInputFormat) override;
    STDMETHODIMP IsOutputFormatSupported(IAudioMediaType* pOppositeFormat,
                                         IAudioMediaType* pRequestedOutputFormat,
                                         IAudioMediaType** ppSupportedOutputFormat) override;
    STDMETHODIMP GetInputChannelCount(UINT32* pu32ChannelCount) override;

    // IAudioProcessingObjectConfiguration
    STDMETHODIMP LockForProcess(UINT32 u32NumInputConnections,
                                APO_CONNECTION_DESCRIPTOR** ppInputConnections,
                                UINT32 u32NumOutputConnections,
                                APO_CONNECTION_DESCRIPTOR** ppOutputConnections) override;
    STDMETHODIMP UnlockForProcess() override;

    // IAudioProcessingObjectRT
    STDMETHODIMP_(void) APOProcess(UINT32 u32NumInputConnections,
                                   APO_CONNECTION_PROPERTY** ppInputConnections,
                                   UINT32 u32NumOutputConnections,
                                   APO_CONNECTION_PROPERTY** ppOutputConnections) override;
    STDMETHODIMP_(UINT32) CalcInputFrames(UINT32 u32OutputFrameCount) override;
    STDMETHODIMP_(UINT32) CalcOutputFrames(UINT32 u32InputFrameCount) override;

private:
    HRESULT CheckFloat32(IAudioMediaType* fmt) const;
    void FileLog(const char* msg) const;

    std::atomic<ULONG> refs_{1};
    CLSID clsid_;
    std::wstring friendlyName_;
    std::wstring pipeName_;
    PipeWorker worker_;
    bool locked_ = false;
    UINT32 channels_ = 2;
    UINT32 sampleRate_ = 48000;
};
