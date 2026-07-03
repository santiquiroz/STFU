import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDevices } from "../hooks/useDevices";
import {
  usePipelineStatus,
  useStartPipeline,
  useStopPipeline,
} from "../hooks/usePipeline";
import { api, ApoRegisterRequest, STFU_APO_SFX_CLSID } from "../services/api";

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

  const [speakerBusy, setSpeakerBusy] = useState(false);
  const { data: devices = [] } = useDevices();
  const { data: status } = usePipelineStatus();
  const { data: bridge } = useQuery({
    queryKey: ["apo-bridge"],
    queryFn: api.getBridgeStatus,
    refetchInterval: 2000,
  });
  const startMic = useStartPipeline("mic");
  const stopMic = useStopPipeline("mic");

  // Reconciliación: los toggles reflejan el estado real del backend
  // (reinicios, pipelines ya activos al abrir la UI, streams caídos)
  useEffect(() => {
    if (status && !startMic.isPending && !stopMic.isPending) {
      setMicOn(status.active.includes("mic"));
    }
  }, [status, startMic.isPending, stopMic.isPending]);

  useEffect(() => {
    if (bridge && !speakerBusy) {
      setSpeakerOn(Boolean(bridge.active["Render"]));
    }
  }, [bridge, speakerBusy]);

  const inputs = devices.filter((d) => d.channels_in > 0);
  const outputs = devices.filter((d) => d.channels_out > 0);
  const effectiveInput = selectedInput ?? inputs[0]?.id ?? 0;
  const effectiveOutput = selectedOutput ?? outputs[0]?.id ?? 0;

  function buildMicRequest(s: number) {
    return {
      plugins: [
        {
          plugin_id: "deepfilternet3",
          parameters: { strength: s / 100 },
        },
      ],
      input_device_id: effectiveInput,
      output_device_id: effectiveOutput,
    };
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
    if (next) {
      setMicOn(true);
      try {
        await startMic.mutateAsync(buildMicRequest(strength));
      } catch (e: unknown) {
        setMicOn(false);
        setMicError(extractError(e));
      }
    } else {
      setMicOn(false);
      await stopMic.mutateAsync();
    }
  }

  async function ensureApoRegistered(deviceName: string): Promise<void> {
    const unsigned = await api.getUnsignedApoEnabled();
    if (!unsigned.enabled) {
      setSpeakerError(
        "Requiere habilitar APOs sin firma (una sola vez, admin). " +
          "Ejecuta el backend como administrador y reintenta.",
      );
      await api.enableUnsignedApos();
      setSpeakerError(null);
    }
    const apoStatus = await api.getApoStatus("Render", deviceName);
    if (apoStatus.registered && apoStatus.clsid === STFU_APO_SFX_CLSID) return;
    setSpeakerError(
      "Registrando STFU APO en el dispositivo (requiere admin; " +
        "el audio del sistema se reinicia ~2s)...",
    );
    const req: ApoRegisterRequest = {
      flow: "Render",
      device_name: deviceName,
      apo_clsid: STFU_APO_SFX_CLSID,
    };
    await api.registerApo(req);
    setSpeakerError(null);
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
        await ensureApoRegistered(outputDevice.name);
        // pipeline del APO: audiodg → pipe → DFN3 → de vuelta al endpoint
        await api.startBridge("Render", [
          { plugin_id: "deepfilternet3", parameters: { strength: strength / 100 } },
        ]);
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
    // Parámetro en vivo: sin reiniciar streams (sin glitch audible)
    if (micOn) {
      try {
        await api.setParameter("mic", 0, "strength", strength / 100);
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
  const micLoading = startMic.isPending || stopMic.isPending;
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
