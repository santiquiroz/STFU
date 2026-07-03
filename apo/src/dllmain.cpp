#include <windows.h>
#include <initguid.h>
#include <atomic>
#include <new>
#include <string>
#include "guids.h"
#include "stfu_apo.h"

namespace {

std::atomic<LONG> g_lockCount{0};
HMODULE g_module = nullptr;

class ClassFactory : public IClassFactory {
public:
    explicit ClassFactory(bool isMic) : isMic_(isMic) {}

    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (ppv == nullptr) return E_POINTER;
        if (riid == __uuidof(IUnknown) || riid == __uuidof(IClassFactory)) {
            *ppv = static_cast<IClassFactory*>(this);
            AddRef();
            return S_OK;
        }
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return ++refs_; }
    STDMETHODIMP_(ULONG) Release() override {
        const ULONG n = --refs_;
        if (n == 0) delete this;
        return n;
    }

    STDMETHODIMP CreateInstance(IUnknown* pOuter, REFIID riid, void** ppv) override {
        if (ppv == nullptr) return E_POINTER;
        *ppv = nullptr;
        if (pOuter != nullptr) return CLASS_E_NOAGGREGATION;
        StfuApo* apo = isMic_
            ? new (std::nothrow) StfuApo(CLSID_StfuApoMic, L"STFU Noise Canceller (Mic)", STFU_PIPE_MIC)
            : new (std::nothrow) StfuApo(CLSID_StfuApoSpk, L"STFU Noise Canceller (Speaker)", STFU_PIPE_SPK);
        if (apo == nullptr) return E_OUTOFMEMORY;
        const HRESULT hr = apo->QueryInterface(riid, ppv);
        apo->Release();
        return hr;
    }

    STDMETHODIMP LockServer(BOOL fLock) override {
        fLock ? ++g_lockCount : --g_lockCount;
        return S_OK;
    }

private:
    std::atomic<ULONG> refs_{1};
    bool isMic_;
};

std::wstring ModulePath() {
    wchar_t path[MAX_PATH]{};
    GetModuleFileNameW(g_module, path, MAX_PATH);
    return path;
}

HRESULT RegisterClsid(const wchar_t* clsidStr, const wchar_t* name) {
    const std::wstring base = std::wstring(L"CLSID\\") + clsidStr;
    HKEY key = nullptr;
    if (RegCreateKeyExW(HKEY_CLASSES_ROOT, base.c_str(), 0, nullptr, 0,
                        KEY_WRITE, nullptr, &key, nullptr) != ERROR_SUCCESS)
        return E_ACCESSDENIED;
    RegSetValueExW(key, nullptr, 0, REG_SZ, reinterpret_cast<const BYTE*>(name),
                   static_cast<DWORD>((wcslen(name) + 1) * sizeof(wchar_t)));
    RegCloseKey(key);

    const std::wstring inproc = base + L"\\InprocServer32";
    if (RegCreateKeyExW(HKEY_CLASSES_ROOT, inproc.c_str(), 0, nullptr, 0,
                        KEY_WRITE, nullptr, &key, nullptr) != ERROR_SUCCESS)
        return E_ACCESSDENIED;
    const std::wstring path = ModulePath();
    RegSetValueExW(key, nullptr, 0, REG_SZ, reinterpret_cast<const BYTE*>(path.c_str()),
                   static_cast<DWORD>((path.size() + 1) * sizeof(wchar_t)));
    const wchar_t both[] = L"Both";
    RegSetValueExW(key, L"ThreadingModel", 0, REG_SZ, reinterpret_cast<const BYTE*>(both),
                   sizeof(both));
    RegCloseKey(key);
    return S_OK;
}

void UnregisterClsid(const wchar_t* clsidStr) {
    const std::wstring base = std::wstring(L"CLSID\\") + clsidStr;
    RegDeleteTreeW(HKEY_CLASSES_ROOT, base.c_str());
}

}  // namespace

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}

STDAPI DllCanUnloadNow() {
    return g_lockCount.load() == 0 ? S_OK : S_FALSE;
}

STDAPI DllGetClassObject(REFCLSID rclsid, REFIID riid, void** ppv) {
    if (ppv == nullptr) return E_POINTER;
    *ppv = nullptr;
    bool isMic;
    if (rclsid == CLSID_StfuApoMic) {
        isMic = true;
    } else if (rclsid == CLSID_StfuApoSpk) {
        isMic = false;
    } else {
        return CLASS_E_CLASSNOTAVAILABLE;
    }
    auto* factory = new (std::nothrow) ClassFactory(isMic);
    if (factory == nullptr) return E_OUTOFMEMORY;
    const HRESULT hr = factory->QueryInterface(riid, ppv);
    factory->Release();
    return hr;
}

STDAPI DllRegisterServer() {
    HRESULT hr = RegisterClsid(STFU_CLSID_MIC_STR, L"STFU Noise Canceller (Mic)");
    if (FAILED(hr)) return hr;
    return RegisterClsid(STFU_CLSID_SPK_STR, L"STFU Noise Canceller (Speaker)");
}

STDAPI DllUnregisterServer() {
    UnregisterClsid(STFU_CLSID_MIC_STR);
    UnregisterClsid(STFU_CLSID_SPK_STR);
    return S_OK;
}
