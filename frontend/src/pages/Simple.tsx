import { useState } from "react";
import { useDevices } from "../hooks/useDevices";
import {
  usePipelineStatus,
  useStartPipeline,
  useStopPipeline,
} from "../hooks/usePipeline";

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

  const { data: devices = [] } = useDevices();
  const { data: status } = usePipelineStatus();
  const startMic = useStartPipeline("mic");
  const stopMic = useStopPipeline("mic");
  const startSpeaker = useStartPipeline("speaker");
  const stopSpeaker = useStopPipeline("speaker");

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

  function buildSpeakerRequest(s: number) {
    return {
      plugins: [
        {
          plugin_id: "deepfilternet3",
          parameters: { strength: s / 100 },
        },
      ],
      input_device_id: effectiveOutput,
      output_device_id: effectiveOutput,
    };
  }

  async function handleMicToggle(next: boolean) {
    setMicError(null);
    if (next) {
      setMicOn(true);
      try {
        await startMic.mutateAsync(buildMicRequest(strength));
      } catch (e: unknown) {
        setMicOn(false);
        const msg = e instanceof Error ? e.message : String(e);
        setMicError(msg);
      }
    } else {
      setMicOn(false);
      await stopMic.mutateAsync();
    }
  }

  async function handleSpeakerToggle(next: boolean) {
    setSpeakerError(null);
    if (next) {
      setSpeakerOn(true);
      try {
        await startSpeaker.mutateAsync(buildSpeakerRequest(strength));
      } catch (e: unknown) {
        setSpeakerOn(false);
        const msg = e instanceof Error ? e.message : String(e);
        setSpeakerError(msg);
      }
    } else {
      setSpeakerOn(false);
      await stopSpeaker.mutateAsync();
    }
  }

  async function handleStrengthRelease() {
    if (micOn) {
      try {
        await startMic.mutateAsync(buildMicRequest(strength));
      } catch {
        /* leave on, retry on next toggle */
      }
    }
    if (speakerOn) {
      try {
        await startSpeaker.mutateAsync(buildSpeakerRequest(strength));
      } catch {
        /* leave on, retry on next toggle */
      }
    }
  }

  const latency = status?.latency_ms ?? 0;
  const micLoading = startMic.isPending || stopMic.isPending;
  const speakerLoading = startSpeaker.isPending || stopSpeaker.isPending;

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
