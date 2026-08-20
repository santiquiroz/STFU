import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useDevices } from "../hooks/useDevices";
import { SpectrumVisualizer } from "../components/SpectrumVisualizer";
import { ReductionMeter } from "../components/ReductionMeter";
import { ChainEditor } from "../components/ChainEditor";
import { PresetPicker } from "../components/PresetPicker";
import { api } from "../services/api";
import type { PluginConfig } from "../services/api";
import { extractError } from "../components/ui";

export function Studio() {
  const queryClient = useQueryClient();
  const [chain, setChain] = useState<PluginConfig[]>([]);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  const { data: devices = [] } = useDevices();
  const { data: feeder } = useQuery({
    queryKey: ["feeder-status"],
    queryFn: api.getFeederStatus,
    refetchInterval: 2000,
  });

  const inputs = devices.filter((d) => d.channels_in > 0);
  const outputs = devices.filter((d) => d.channels_out > 0);
  const effectiveInput = inputs[0]?.id;
  const effectiveTestOut = outputs[0]?.id;
  const bridgePresent = feeder?.bridge_present ?? false;
  const canApply = effectiveInput !== undefined;

  async function handleApply() {
    if (effectiveInput === undefined) return;
    setApplyError(null);
    setApplying(true);
    try {
      await api.startFeeder(
        effectiveInput,
        chain,
        bridgePresent ? undefined : effectiveTestOut,
      );
      queryClient.invalidateQueries({ queryKey: ["feeder-status"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    } catch (e) {
      setApplyError(extractError(e));
    } finally {
      setApplying(false);
    }
  }

  return (
    <div className="min-h-screen bg-zinc-900 text-white p-6 flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Estudio de voz</h1>
        <p className="text-zinc-500 text-xs">
          Ajustá la cadena de efectos y observá el resultado en vivo
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <SpectrumVisualizer />
        <ReductionMeter />
      </div>

      <PresetPicker currentChain={chain} onLoadChain={setChain} />

      {applyError && (
        <p className="text-red-400 text-xs truncate" title={applyError}>
          ⚠ {applyError}
        </p>
      )}

      <ChainEditor
        chain={chain}
        onChange={setChain}
        onApply={handleApply}
        applying={applying}
        canApply={canApply}
      />
    </div>
  );
}
