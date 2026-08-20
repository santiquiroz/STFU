import type { Parameter, PluginCatalogEntry, PluginConfig } from "../services/api";
import { ParamControl } from "./ParamControl";
import { Card } from "./ui";

const moveButtonClasses =
  "inline-flex h-7 w-7 items-center justify-center rounded-md border border-zinc-700 text-xs font-medium text-zinc-300 transition-all hover:border-zinc-600 hover:bg-zinc-700 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-400 active:scale-95 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:border-zinc-700";

const removeButtonClasses =
  "inline-flex h-7 items-center justify-center gap-1 rounded-md border border-red-900/50 px-2 text-xs font-medium text-red-300 transition-all hover:border-red-700 hover:bg-red-900/30 hover:text-red-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-500 active:scale-95";

function readParamValue(config: PluginConfig, param: Parameter): number | string | boolean {
  const stored = config.parameters?.[param.id];
  if (stored !== undefined) return stored;
  return param.default as number | string | boolean;
}

interface PluginRowProps {
  entry: PluginCatalogEntry;
  config: PluginConfig;
  index: number;
  total: number;
  onParamChange: (paramId: string, value: number | string | boolean) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}

export function PluginRow({
  entry,
  config,
  index,
  total,
  onParamChange,
  onRemove,
  onMoveUp,
  onMoveDown,
}: PluginRowProps) {
  return (
    <Card className="flex flex-col gap-3 border border-zinc-700/60 transition-colors hover:border-zinc-600">
      <div className="flex items-start justify-between gap-3 border-b border-zinc-700/60 pb-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-zinc-700 text-[11px] font-semibold text-zinc-300">
            {index + 1}
          </span>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-bold tracking-tight text-white" title={entry.name}>
              {entry.name}
            </h3>
            <p className="text-[11px] text-zinc-500">v{entry.version}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            onClick={onMoveUp}
            disabled={index === 0}
            className={moveButtonClasses}
            title="Subir"
            aria-label="Subir en la cadena"
          >
            ↑
          </button>
          <button
            onClick={onMoveDown}
            disabled={index === total - 1}
            className={moveButtonClasses}
            title="Bajar"
            aria-label="Bajar en la cadena"
          >
            ↓
          </button>
          <button onClick={onRemove} className={removeButtonClasses} title="Quitar" aria-label="Quitar plugin">
            Quitar
          </button>
        </div>
      </div>

      {entry.parameters.length > 0 ? (
        <div className="grid grid-cols-1 gap-x-4 gap-y-3 sm:grid-cols-2">
          {entry.parameters.map((param) => (
            <ParamControl
              key={param.id}
              param={param}
              value={readParamValue(config, param)}
              onChange={(value) => onParamChange(param.id, value)}
            />
          ))}
        </div>
      ) : (
        <p className="text-xs text-zinc-500">Sin parámetros configurables.</p>
      )}
    </Card>
  );
}
