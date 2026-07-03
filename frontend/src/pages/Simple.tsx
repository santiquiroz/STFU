import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDevices } from "../hooks/useDevices";
import { usePipelineStatus } from "../hooks/usePipeline";
import { api } from "../services/api";

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
  const [micBusy, setMicBusy] = useState(false);
  const [strength, setStrength] = useState(85);
  const [selectedInput, setSelectedInput] = useState<number | undefined>(undefined);
  const [selectedTestOut, setSelectedTestOut] = useState<number | undefined>(undefined);
  const [micError, setMicError] = useState<string | null>(null);

  const { data: devices = [] } = useDevices();
  const { data: status } = usePipelineStatus();
  const { data: feeder } = useQuery({
    queryKey: ["feeder-status"],
    queryFn: api.getFeederStatus,
    refetchInterval: 2000,
  });

  // Reconciliación con el estado real del backend
  useEffect(() => {
    if (feeder && !micBusy) setMicOn(feeder.active);
  }, [feeder, micBusy]);

  const inputs = devices.filter((d) => d.channels_in > 0);
  const outputs = devices.filter((d) => d.channels_out > 0);
  const effectiveInput = selectedInput ?? inputs[0]?.id ?? 0;
  const effectiveTestOut = selectedTestOut ?? outputs[0]?.id ?? 0;
  const bridgePresent = feeder?.bridge_present ?? false;

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
      if (next) {
        // Con driver: sale al STFU Audio Bridge. Sin driver: modo prueba por parlantes.
        await api.startFeeder(effectiveInput, strength / 100, bridgePresent ? undefined : effectiveTestOut);
        setMicOn(true);
      } else {
        await api.stopFeeder();
        setMicOn(false);
      }
    } catch (e) {
      setMicOn(false);
      setMicError(extractError(e));
    } finally {
      setMicBusy(false);
    }
  }

  async function handleStrengthRelease() {
    if (!micOn) return;
    try {
      await api.setFeederParameter(0, "strength", strength / 100);
    } catch {
      /* reintenta al re-activar */
    }
  }

  const latency = status?.latency_ms ?? 0;

  return (
    <div className="min-h-screen bg-zinc-900 text-white p-6 flex flex-col gap-5 select-none">
      <div>
        <h1 className="text-xl font-bold tracking-tight">STFU</h1>
        <p className="text-zinc-500 text-xs">Suppress The Frustrating Unwanted noise</p>
      </div>

      {/* Estado del driver */}
      <div
        className={`rounded-lg px-3 py-2 text-xs ${
          bridgePresent ? "bg-green-950 text-green-300" : "bg-amber-950 text-amber-300"
        }`}
      >
        {bridgePresent
          ? "✓ STFU Microphone instalado — selecciónalo en Discord/Zoom para recibir audio limpio."
          : "⚠ Driver STFU no instalado — modo prueba: te escuchas limpio por los parlantes."}
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
          <Toggle on={micOn} loading={micBusy} onChange={handleMicToggle} />
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

        {!bridgePresent && (
          <div>
            <p className="text-xs text-zinc-400 mb-1">Escuchar prueba en:</p>
            <select
              className="text-xs bg-zinc-700 rounded px-2 py-1 text-zinc-300 w-48 truncate"
              value={effectiveTestOut}
              onChange={(e) => setSelectedTestOut(Number(e.target.value))}
            >
              {outputs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <p className="text-[11px] text-zinc-500 leading-snug">
          {bridgePresent
            ? "Con esto activo, cualquier app que use STFU Microphone recibe tu voz sin ruido."
            : "Modo prueba sin driver: capturamos tu mic, quitamos el ruido y lo reproducimos por la salida elegida para que oigas el resultado."}
        </p>
      </div>

      <p className="text-center text-zinc-600 text-xs">
        {latency > 0 ? `Latencia: ${latency.toFixed(1)} ms` : "Latencia: —"}
      </p>
    </div>
  );
}
