import { useState } from "react";
import { usePlugins } from "../hooks/usePlugins";
import { api } from "../services/api";
import type { PluginCatalogEntry, PluginConfig } from "../services/api";
import { PluginRow } from "./PluginRow";
import { Button, Card, Spinner, extractError } from "./ui";

interface ChainEditorProps {
  chain: PluginConfig[];
  onChange: (chain: PluginConfig[]) => void;
  onApply: () => void;
  applying?: boolean;
  canApply?: boolean;
  liveEditable?: boolean;
  onLiveApplied?: (chain: PluginConfig[]) => void;
}

const selectClasses =
  "flex-1 rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-xs text-zinc-200 transition-colors focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500/50";

function swapAt<T>(items: T[], a: number, b: number): T[] {
  const next = [...items];
  const temp = next[a];
  next[a] = next[b];
  next[b] = temp;
  return next;
}

function isNumericValue(value: number | string | boolean): value is number {
  return typeof value === "number";
}

function buildCatalogMap(catalog: PluginCatalogEntry[]): Map<string, PluginCatalogEntry> {
  return new Map(catalog.map((entry) => [entry.plugin_id, entry]));
}

function ModelNodeRow({ pluginId }: { pluginId: string }) {
  return (
    <Card className="flex flex-col gap-1 border border-dashed border-zinc-700/70 bg-zinc-800/60">
      <div className="flex items-center gap-2">
        <span className="text-sm font-bold tracking-tight text-white">
          🧠 Cancelación de ruido (modelo)
        </span>
        <span className="rounded-full bg-zinc-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-zinc-400">
          {pluginId}
        </span>
      </div>
      <p className="text-[11px] text-zinc-500">
        Se gestiona desde la pestaña Modelos — no editable acá.
      </p>
    </Card>
  );
}

function EmptyChainNotice() {
  return (
    <Card className="border border-dashed border-zinc-700/70 text-center text-sm text-zinc-500">
      Cadena vacía — agregá un plugin para empezar a procesar tu audio.
    </Card>
  );
}

export function ChainEditor({
  chain,
  onChange,
  onApply,
  applying = false,
  canApply = false,
  liveEditable = false,
  onLiveApplied,
}: ChainEditorProps) {
  const { data: catalog, isLoading, isError, error } = usePlugins();
  const [selectedToAdd, setSelectedToAdd] = useState("");

  function updateParam(index: number, paramId: string, value: number | string | boolean) {
    const nextChain = chain.map((config, i) =>
      i === index
        ? { ...config, parameters: { ...config.parameters, [paramId]: value } }
        : config,
    );
    onChange(nextChain);

    if (liveEditable && isNumericValue(value)) {
      api.setFeederParameter(index, paramId, value).catch(() => {});
    }
  }

  function removePlugin(index: number) {
    const nextChain = chain.filter((_, i) => i !== index);
    onChange(nextChain);

    if (liveEditable) {
      api
        .removeFeederPlugin(index)
        .then(() => onLiveApplied?.(nextChain))
        .catch(() => {});
    }
  }

  function movePlugin(index: number, direction: -1 | 1) {
    onChange(swapAt(chain, index, index + direction));
  }

  function addPlugin(pluginId: string) {
    if (!pluginId) return;
    const index = chain.length;
    const nextChain = [...chain, { plugin_id: pluginId, parameters: {} }];
    onChange(nextChain);
    setSelectedToAdd("");

    if (liveEditable) {
      api
        .insertFeederPlugin(index, pluginId)
        .then(() => onLiveApplied?.(nextChain))
        .catch(() => {});
    }
  }

  if (isLoading) {
    return (
      <Card className="flex items-center justify-center gap-2 py-8 text-sm text-zinc-400">
        <Spinner /> Cargando catálogo de plugins…
      </Card>
    );
  }

  if (isError) {
    return (
      <Card className="text-sm text-red-400">
        ⚠ No se pudo cargar el catálogo de plugins: {extractError(error)}
      </Card>
    );
  }

  const availablePlugins = catalog ?? [];
  const catalogMap = buildCatalogMap(availablePlugins);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3">
        {chain.length === 0 && <EmptyChainNotice />}

        {chain.map((config, index) => {
          const entry = catalogMap.get(config.plugin_id);
          if (!entry) {
            return <ModelNodeRow key={`${config.plugin_id}-${index}`} pluginId={config.plugin_id} />;
          }
          return (
            <PluginRow
              key={`${config.plugin_id}-${index}`}
              entry={entry}
              config={config}
              index={index}
              total={chain.length}
              onParamChange={(paramId, value) => updateParam(index, paramId, value)}
              onRemove={() => removePlugin(index)}
              onMoveUp={() => movePlugin(index, -1)}
              onMoveDown={() => movePlugin(index, 1)}
            />
          );
        })}
      </div>

      <Card className="flex flex-col gap-3 border border-zinc-700/60">
        <div className="flex items-center gap-2">
          <label className="text-xs text-zinc-400" htmlFor="chain-editor-add-plugin">
            Agregar plugin
          </label>
          <select
            id="chain-editor-add-plugin"
            value={selectedToAdd}
            onChange={(e) => addPlugin(e.target.value)}
            className={selectClasses}
          >
            <option value="">Elegí un plugin…</option>
            {availablePlugins.map((entry) => (
              <option key={entry.plugin_id} value={entry.plugin_id}>
                {entry.name}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1 border-t border-zinc-700/60 pt-3">
          <Button
            variant="primary"
            onClick={onApply}
            disabled={!canApply || applying || chain.length === 0}
          >
            {applying ? <Spinner /> : "Aplicar cadena"}
          </Button>
          <p className="text-[11px] text-zinc-500">
            {!canApply
              ? "Activá el micrófono en Control para aplicar."
              : liveEditable
                ? "Cadena activa: parámetros, agregar y quitar plugins se aplican en vivo sin cortar el audio; reordenar requiere volver a aplicar."
                : "Los parámetros numéricos se aplican en vivo mientras la cadena está activa; agregar, quitar o reordenar plugins requiere volver a aplicar."}
          </p>
        </div>
      </Card>
    </div>
  );
}
