import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDevices } from "../hooks/useDevices";
import { usePipelineStatus } from "../hooks/usePipeline";
import {
  api,
  ApoRegisterRequest,
  STFU_APO_MFX_CLSID,
  STFU_APO_SFX_CLSID,
} from "../services/api";

function Toggle({
  on,
  loading,
  onChange,
}: {
  on: boolean;
  loading: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      onClick={() => !loading && onChange(!on)}
      disabled={loading}
      className={`w-12 h-6 rounded-full transition-colors ${
        loading ? "bg-zinc-500 cursor-wait" : on ? "bg-green-500" : "bg-zinc-600"
      }`}
    >
      {loading ? (
        <div className="w-5 h-5 mx-auto rounded-full border-2 border-white/40 border-t-white animate-spin" />
      ) : (
        <div
          className={`w-5 h-5 bg-white rounded-full shadow transition-transform mx-0.5 ${
            on ? "translate-x-6" : ""
          }`}
        />
      )}
    </button>
  );
}

export function Simple() {
  const [micOn, setMicOn] = useState(false);
  const [speakerOn, setSpeakerOn] = useState(false);
  const [strength, setStrength] = useState(85);
  const [selectedInput, setSelectedInput] = useState<number | undefined>(
    undefined,
  );
  const [selectedOutput, setSelectedOutput] = useState<number | undefined>(
    undefined,
  );
  const [micError, setMicError] = useState<string | null>(null);
  const [speakerError, setSpeakerError] = useState<string | null>(null);

  const [micBusy, setMicBusy] = useState(false);
  const [speakerBusy, setSpeakerBusy] = useState(false);
  const { data: devices = [] } = useDevices();
  const { data: status } = usePipelineStatus();
  const { data: bridge } = useQuery({
    queryKey: ["apo-bridge"],
    queryFn: api.getBridgeStatus,
    refetchInterval: 2000,
  });

  // Reconciliación: los toggles reflejan el estado real del bridge APO
  // (reinicios del backend, o ya activos al abrir la UI)
  useEffect(() => {
    if (bridge && !micBusy) {
      setMicOn(Boolean(bridge.active["Capture"]));
    }
  }, [bridge, micBusy]);

  useEffect(() => {
    if (bridge && !speakerBusy) {
      setSpeakerOn(Boolean(bridge.active["Render"]));
    }
  }, [bridge, speakerBusy]);

  const inputs = devices.filter((d) => d.channels_in > 0);
  const outputs = devices.filter((d) => d.channels_out > 0);
  const effectiveInput = selectedInput ?? inputs[0]?.id ?? 0;
  const effectiveOutput = selectedOutput ?? outputs[0]?.id ?? 0;

  function dfn3Plugins(s: number) {
    return [{ plugin_id: "deepfilternet3", parameters: { strength: s / 100 } }];
  }

  function extractError(e: unknown): string {
    if (e && typeof e === "object" && "response" in e) {
      const resp = (e as { response?: { data?: { detail?: string } } }).response;
      if (resp?.data?.detail) return resp.data.detail;
    }
    return e instanceof Error ? e.message : String(e);
  }

  async function handleMicToggle(next: boolean) {
    setMicError(null);
    setMicBusy(true);
    try {
      await doMicToggle(next);
    } finally {
      setMicBusy(false);
    }
  }

  async function doMicToggle(next: boolean) {
    if (next) {
      const micDevice = inputs.find((d) => d.id === effectiveInput);
      if (!micDevice) return;
      try {
        await ensureApoRegistered("Capture", micDevice.name, STFU_APO_MFX_CLSID, setMicError);
        // APO de captura: Discord/Zoom que usen el MISMO micrófono reciben
        // audio ya limpio — no aparece ningún dispositivo nuevo
        await api.startBridge("Capture", dfn3Plugins(strength));
        setMicOn(true);
      } catch (e) {
        setMicOn(false);
        setMicError(extractError(e));
      }
    } else {
      setMicOn(false);
      try {
        await api.stopBridge("Capture");
      } catch {
        /* bridge ya detenido */
      }
    }
  }

  async function handleMicUnregister() {
    const micDevice = inputs.find((d) => d.id === effectiveInput);
    if (!micDevice) return;
    setMicError(null);
    try {
      await api.stopBridge("Capture");
      await api.unregisterApo("Capture", micDevice.name);
      setMicOn(false);
    } catch (e) {
      setMicError(extractError(e));
    }
  }

  async function ensureApoRegistered(
    flow: "Capture" | "Render",
    deviceName: string,
    clsid: string,
    setError: (m: string | null) => void,
  ): Promise<void> {
    const unsigned = await api.getUnsignedApoEnabled();
    if (!unsigned.enabled) {
      setError("Habilitando STFU en el motor de audio (pedirá permisos de administrador)...");
      await api.enableUnsignedApos();
      setError(null);
    }
    const apoStatus = await api.getApoStatus(flow, deviceName);
    if (apoStatus.registered && apoStatus.clsid === clsid) return;
    setError("Instalando STFU en el dispositivo (admin; el audio se reinicia ~2s)...");
    const req: ApoRegisterRequest = {
      flow,
      device_name: deviceName,
      apo_clsid: clsid,
    };
    await api.registerApo(req);
    setError(null);
  }

  async function handleSpeakerToggle(next: boolean) {
    setSpeakerError(null);
    setSpeakerBusy(true);
    try {
      await doSpeakerToggle(next);
    } finally {
      setSpeakerBusy(false);
    }
  }

  async function doSpeakerToggle(next: boolean) {
    if (next) {
      const outputDevice = outputs.find((d) => d.id === effectiveOutput);
      if (!outputDevice) return;
      try {
        await ensureApoRegistered("Render", outputDevice.name, STFU_APO_SFX_CLSID, setSpeakerError);
        // pipeline del APO: audiodg → pipe → DFN3 → de vuelta al endpoint
        await api.startBridge("Render", dfn3Plugins(strength));
        setSpeakerOn(true);
      } catch (e) {
        setSpeakerOn(false);
        setSpeakerError(extractError(e));
      }
    } else {
      setSpeakerOn(false);
      try {
        await api.stopBridge("Render");
      } catch {
        /* bridge ya detenido */
      }
    }
  }

  async function handleSpeakerUnregister() {
    const outputDevice = outputs.find((d) => d.id === effectiveOutput);
    if (!outputDevice) return;
    setSpeakerError(null);
    try {
      await api.stopBridge("Render");
      await api.unregisterApo("Render", outputDevice.name);
      setSpeakerOn(false);
    } catch (e) {
      setSpeakerError(extractError(e));
    }
  }

  async function handleStrengthRelease() {
    // Parámetro en vivo: sin reiniciar el bridge (sin glitch audible)
    if (micOn) {
      try {
        await api.setBridgeParameter("Capture", 0, "strength", strength / 100);
      } catch {
        /* leave on, retry on next toggle */
      }
    }
    if (speakerOn) {
      try {
        await api.setBridgeParameter("Render", 0, "strength", strength / 100);
      } catch {
        /* leave on, retry on next toggle */
      }
    }
  }

  const latency = status?.latency_ms ?? 0;
  const micLoading = micBusy;
  const speakerLoading = speakerBusy;

  return (
    <div className="min-h-screen bg-zinc-900 text-white p-6 flex flex-col gap-5 select-none">
      <div>
        <h1 className="text-xl font-bold tracking-tight">STFU</h1>
        <p className="text-zinc-500 text-xs">
          Suppress The Frustrating Unwanted noise
        </p>
      </div>

      {/* Mic */}
      <div className="bg-zinc-800 rounded-xl p-5 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="font-medium text-sm">🎙 Micrófono</p>
            <select
              className="mt-1 text-xs bg-zinc-700 rounded px-2 py-1 text-zinc-300 w-48 truncate"
              value={effectiveInput}
              onChange={(e) => setSelectedInput(Number(e.target.value))}
            >
              {inputs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>
          <Toggle on={micOn} loading={micLoading} onChange={handleMicToggle} />
        </div>
        {micError && (
          <p className="text-red-400 text-xs truncate" title={micError}>
            ⚠ {micError}
          </p>
        )}
        <div>
          <p className="text-xs text-zinc-400 mb-1">Intensidad — {strength}%</p>
          <input
            type="range"
            min={0}
            max={100}
            value={strength}
            onChange={(e) => setStrength(Number(e.target.value))}
            onMouseUp={handleStrengthRelease}
            onTouchEnd={handleStrengthRelease}
            className="w-full accent-green-500"
          />
        </div>
        <p className="text-[11px] text-zinc-500 leading-snug">
          Con esto activo, cualquier app (Discord, Zoom…) que use{" "}
          <span className="text-zinc-400">este mismo micrófono</span> recibe el
          audio ya limpio. No aparece ningún micrófono nuevo — es el diseño.
        </p>
        {micOn && (
          <button
            onClick={handleMicUnregister}
            className="self-start text-xs text-zinc-500 hover:text-zinc-300 underline"
          >
            Desinstalar STFU APO de este micrófono
          </button>
        )}
      </div>

      {/* Speaker */}
      <div className="bg-zinc-800 rounded-xl p-5 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="font-medium text-sm">🔊 Altavoces</p>
            <select
              className="mt-1 text-xs bg-zinc-700 rounded px-2 py-1 text-zinc-300 w-48 truncate"
              value={effectiveOutput}
              onChange={(e) => setSelectedOutput(Number(e.target.value))}
            >
              {outputs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>
          <Toggle
            on={speakerOn}
            loading={speakerLoading}
            onChange={handleSpeakerToggle}
          />
        </div>
        {speakerError && (
          <p className="text-red-400 text-xs truncate" title={speakerError}>
            ⚠ {speakerError}
          </p>
        )}
        <button
          onClick={handleSpeakerUnregister}
          className="self-start text-xs text-zinc-500 hover:text-zinc-300 underline"
        >
          Desinstalar STFU APO de este dispositivo
        </button>
      </div>

      {/* Latency */}
      <p className="text-center text-zinc-600 text-xs">
        {latency > 0
          ? `Latencia: ${latency.toFixed(1)} ms`
          : "Latencia: —"}
      </p>
    </div>
  );
}
