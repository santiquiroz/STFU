import { useState } from "react";
import { useDevices } from "../hooks/useDevices";
import { usePipelineStatus } from "../hooks/usePipeline";

function Toggle({
  on,
  onChange,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      onClick={() => onChange(!on)}
      className={`w-12 h-6 rounded-full transition-colors ${on ? "bg-green-500" : "bg-zinc-600"}`}
    >
      <div
        className={`w-5 h-5 bg-white rounded-full shadow transition-transform mx-0.5 ${on ? "translate-x-6" : ""}`}
      />
    </button>
  );
}

export function Simple() {
  const [micOn, setMicOn] = useState(false);
  const [speakerOn, setSpeakerOn] = useState(false);
  const [strength, setStrength] = useState(85);
  const [selectedInput, setSelectedInput] = useState<number | undefined>(undefined);
  const [selectedOutput, setSelectedOutput] = useState<number | undefined>(undefined);
  const { data: devices = [] } = useDevices();
  const { data: status } = usePipelineStatus();

  const inputs = devices.filter((d) => d.channels_in > 0);
  const outputs = devices.filter((d) => d.channels_out > 0);

  return (
    <div className="min-h-screen bg-zinc-900 text-white p-6 flex flex-col gap-5 select-none">
      <div>
        <h1 className="text-xl font-bold tracking-tight">STFU</h1>
        <p className="text-zinc-500 text-xs">
          Suppress The Frustrating Unwanted noise
        </p>
      </div>

      <div className="bg-zinc-800 rounded-xl p-5 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="font-medium text-sm">🎙 Micrófono</p>
            <select
              className="mt-1 text-xs bg-zinc-700 rounded px-2 py-1 text-zinc-300 w-48 truncate"
              value={selectedInput ?? inputs[0]?.id}
              onChange={(e) => setSelectedInput(Number(e.target.value))}
            >
              {inputs.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>
          <Toggle on={micOn} onChange={setMicOn} />
        </div>
        <div>
          <p className="text-xs text-zinc-400 mb-1">
            Intensidad — {strength}%
          </p>
          <input
            type="range"
            min={0}
            max={100}
            value={strength}
            onChange={(e) => setStrength(Number(e.target.value))}
            className="w-full accent-green-500"
          />
        </div>
      </div>

      <div className="bg-zinc-800 rounded-xl p-5 flex items-center justify-between">
        <div>
          <p className="font-medium text-sm">🔊 Altavoces</p>
          <select
            className="mt-1 text-xs bg-zinc-700 rounded px-2 py-1 text-zinc-300 w-48 truncate"
            value={selectedOutput ?? outputs[0]?.id}
            onChange={(e) => setSelectedOutput(Number(e.target.value))}
          >
            {outputs.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
        <Toggle on={speakerOn} onChange={setSpeakerOn} />
      </div>

      {status && (
        <p className="text-center text-zinc-600 text-xs">
          Latencia: {status.latency_ms.toFixed(0)}ms
        </p>
      )}
    </div>
  );
}
