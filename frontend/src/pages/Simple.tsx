import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useDevices } from "../hooks/useDevices";
import { usePipelineStatus } from "../hooks/usePipeline";
import { useBypass } from "../hooks/useBypass";
import { api } from "../services/api";
import { extractError, Badge, Toggle, Button } from "../components/ui";

export function Simple() {
  const queryClient = useQueryClient();
  const [micOn, setMicOn] = useState(false);
  const [micBusy, setMicBusy] = useState(false);
  const [strength, setStrength] = useState(85);
  const [selectedInput, setSelectedInput] = useState<number | undefined>(undefined);
  const [selectedTestOut, setSelectedTestOut] = useState<number | undefined>(undefined);
  const [micError, setMicError] = useState<string | null>(null);
  const [musicMode, setMusicMode] = useState(false);
  // Una vez que el usuario toca el slider/picker en esta sesión, su elección
  // manda: el poll de feeder-status ya no debe pisarla con el valor del
  // backend (evita pelear un drag activo o revertir una elección explícita).
  // Antes de eso, reconciliamos libremente para reflejar un feeder que
  // arrancó fuera de sesión (reload, otro cliente, DefaultDeviceWatcher).
  const userTouchedStrengthRef = useRef(false);
  const userTouchedInputRef = useRef(false);

  const { data: devices = [] } = useDevices();
  const { data: status } = usePipelineStatus();
  const bypassMutation = useBypass();
  const { data: feeder, isError: backendDown } = useQuery({
    queryKey: ["feeder-status"],
    queryFn: api.getFeederStatus,
    refetchInterval: 2000,
  });

  // Reconciliación con el estado real del backend
  useEffect(() => {
    if (feeder && !micBusy) {
      setMicOn(feeder.active);
      if (!feeder.active) setMusicMode(false);
      if (feeder.strength != null && !userTouchedStrengthRef.current) {
        setStrength(Math.round(feeder.strength * 100));
      }
      if (feeder.input_device_id != null && !userTouchedInputRef.current) {
        setSelectedInput(feeder.input_device_id);
      }
    }
  }, [feeder, micBusy]);

  const inputs = devices.filter((d) => d.channels_in > 0);
  const outputs = devices.filter((d) => d.channels_out > 0);
  const hasInput = inputs.length > 0;
  // Sin fallback a id 0: un id inventado arranca el feeder contra un device
  // inexistente. undefined => el toggle queda deshabilitado.
  const effectiveInput = selectedInput ?? inputs[0]?.id;
  const effectiveTestOut = selectedTestOut ?? outputs[0]?.id;
  const bridgePresent = feeder?.bridge_present ?? false;
  const isBypassed = status?.streams?.feeder?.bypass ?? false;

  async function handleMicToggle(next: boolean) {
    setMicError(null);
    if (next && effectiveInput === undefined) {
      setMicError("No se detectó ningún micrófono.");
      return;
    }
    if (next && !bridgePresent && effectiveTestOut === undefined) {
      setMicError("No hay dispositivo de salida para la prueba.");
      return;
    }
    setMicBusy(true);
    try {
      if (next) {
        // Con driver: sale al STFU Audio Bridge. Sin driver: modo prueba por parlantes.
        await api.startFeeder(
          effectiveInput!,
          [{ plugin_id: "deepfilternet3", parameters: { strength: strength / 100 } }],
          bridgePresent ? undefined : effectiveTestOut,
        );
        setMicOn(true);
        setMusicMode(false);
      } else {
        await api.stopFeeder();
        setMicOn(false);
        setMusicMode(false);
      }
      // Refresca el estado real sin esperar al poll de 2s.
      queryClient.invalidateQueries({ queryKey: ["feeder-status"] });
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
    } catch (e) {
      setMicError(extractError(e));
    }
  }

  async function toggleBypass() {
    try {
      await bypassMutation.mutateAsync(!isBypassed);
    } catch (e) {
      setMicError(extractError(e));
    }
  }

  async function handleMusicMode() {
    setMicError(null);
    if (effectiveInput === undefined) {
      setMicError("No se detectó ningún micrófono.");
      return;
    }
    if (!bridgePresent && effectiveTestOut === undefined) {
      setMicError("No hay dispositivo de salida para la prueba.");
      return;
    }
    setMicBusy(true);
    try {
      const preset = await api.getPreset("Música");
      await api.startFeeder(
        effectiveInput,
        preset.plugins,
        bridgePresent ? undefined : effectiveTestOut,
      );
      setMicOn(true);
      setMusicMode(true);
      const s = preset.plugins[0]?.parameters?.strength;
      if (typeof s === "number") setStrength(Math.round(s * 100));
      queryClient.invalidateQueries({ queryKey: ["feeder-status"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    } catch (e) {
      setMicError(extractError(e));
    } finally {
      setMicBusy(false);
    }
  }

  function isTypingTarget(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false;
    return ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName);
  }

  useEffect(() => {
    if (!micOn) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.code !== "Space" || e.repeat) return;
      if (isTypingTarget(document.activeElement)) return;
      if (bypassMutation.isPending) return;
      e.preventDefault();
      toggleBypass();
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [micOn, isBypassed, bypassMutation.isPending]);

  const latency = status?.latency_ms ?? 0;

  return (
    <div className="min-h-screen bg-zinc-900 text-white p-6 flex flex-col gap-5 select-none">
      <div>
        <h1 className="text-xl font-bold tracking-tight">STFU</h1>
        <p className="text-zinc-500 text-xs">Suppress The Frustrating Unwanted noise</p>
      </div>

      {/* Estado del backend / driver */}
      {backendDown ? (
        <div className="rounded-lg px-3 py-2 text-xs bg-red-950 text-red-300">
          ⚠ Sin conexión con el backend de STFU. Verifica que el servicio esté corriendo.
        </div>
      ) : (
        <div
          className={`rounded-lg px-3 py-2 text-xs ${
            bridgePresent ? "bg-green-950 text-green-300" : "bg-amber-950 text-amber-300"
          }`}
        >
          {bridgePresent
            ? "✓ STFU Microphone instalado — selecciónalo en Discord/Zoom para recibir audio limpio."
            : "⚠ Driver STFU no instalado — modo prueba: te escuchas limpio por los parlantes."}
        </div>
      )}

      {/* Mic */}
      <div className="bg-zinc-800 rounded-xl p-5 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="font-medium text-sm">🎙 Micrófono</p>
            {hasInput ? (
              <select
                className="mt-1 text-xs bg-zinc-700 rounded px-2 py-1 text-zinc-300 w-48 truncate"
                value={effectiveInput}
                onChange={(e) => {
                  userTouchedInputRef.current = true;
                  setSelectedInput(Number(e.target.value));
                }}
              >
                {inputs.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            ) : (
              <p className="mt-1 text-xs text-amber-400">No se detectó ningún micrófono.</p>
            )}
          </div>
          <Toggle on={micOn} loading={micBusy} disabled={!hasInput && !micOn} onChange={handleMicToggle} />
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
            onChange={(e) => {
              userTouchedStrengthRef.current = true;
              setStrength(Number(e.target.value));
            }}
            onMouseUp={handleStrengthRelease}
            onTouchEnd={handleStrengthRelease}
            className="w-full accent-green-500"
          />
        </div>

        {micOn && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <p className="text-xs text-zinc-400">A/B — Original ⇄ Limpio</p>
              <p className="text-[10px] text-zinc-600">barra espaciadora</p>
            </div>
            <div className="flex rounded-lg overflow-hidden border border-zinc-700">
              <button
                onClick={() => !isBypassed && toggleBypass()}
                disabled={bypassMutation.isPending}
                className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                  isBypassed
                    ? "bg-amber-600 text-white"
                    : "bg-zinc-700 text-zinc-400 hover:bg-zinc-600"
                }`}
              >
                Original
              </button>
              <button
                onClick={() => isBypassed && toggleBypass()}
                disabled={bypassMutation.isPending}
                className={`flex-1 px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                  !isBypassed
                    ? "bg-green-600 text-white"
                    : "bg-zinc-700 text-zinc-400 hover:bg-zinc-600"
                }`}
              >
                Limpio
              </button>
            </div>
          </div>
        )}

        {!bridgePresent && !backendDown && (
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

      {/* Modo música */}
      <Button
        variant={musicMode ? "primary" : "ghost"}
        onClick={handleMusicMode}
        disabled={micBusy || effectiveInput === undefined}
        className="w-full flex items-center justify-center gap-2"
      >
        🎵 Modo música
        {musicMode && <Badge label="activo" tone="green" />}
      </Button>

      <div className="flex flex-col items-center gap-2">
        <p className="text-center text-zinc-600 text-xs">
          {latency > 0 ? `Latencia: ${latency.toFixed(1)} ms` : "Latencia: —"}
        </p>

        {micOn && status?.streams?.feeder?.inference && (
          <div className="flex gap-2">
            {status.streams.feeder.inference.device && (
              <Badge
                label={status.streams.feeder.inference.device}
                tone="blue"
              />
            )}
            {status.streams.feeder.inference.degraded && (
              <Badge label="degradado" tone="red" />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
