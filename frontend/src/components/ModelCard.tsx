import { useState } from "react";
import type { ModelInfo } from "../services/api";
import { Badge, Card, Spinner, TierBadge } from "./ui";

interface ModelCardProps {
  model: ModelInfo;
  active: boolean;
  downloading: boolean;
  activating: boolean;
  deleting: boolean;
  downloadError?: string | null;
  activateError?: string | null;
  deleteError?: string | null;
  onDownload: () => void;
  onActivate: (target: string, device: string) => void;
  onDelete: () => void;
}

const tierAccentClasses: Record<ModelInfo["tier"], string> = {
  floor: "border-l-blue-500",
  default: "border-l-green-500",
  quality: "border-l-amber-500",
  legacy: "border-l-zinc-600",
};

const primaryButtonClasses =
  "inline-flex items-center justify-center gap-2 rounded-lg bg-green-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-green-500 hover:shadow-green-900/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-green-400 active:scale-[0.98] active:bg-green-700 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-500 disabled:shadow-none disabled:active:scale-100";

const ghostButtonClasses =
  "inline-flex items-center justify-center gap-2 rounded-lg border border-zinc-700 px-3 py-1.5 text-sm font-medium text-zinc-300 transition-all hover:border-zinc-600 hover:bg-zinc-800 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-400 active:scale-[0.98]";

const destructiveButtonClasses =
  "inline-flex items-center justify-center gap-2 rounded-lg border border-red-900/50 bg-red-950/30 px-3 py-1.5 text-sm font-medium text-red-300 transition-all hover:border-red-700 hover:bg-red-900/40 hover:text-red-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-500 active:scale-[0.98] active:bg-red-900/60 disabled:cursor-not-allowed disabled:border-zinc-800 disabled:bg-transparent disabled:text-zinc-600 disabled:active:scale-100";

const selectClasses =
  "rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-200 transition-colors focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500/50 disabled:cursor-not-allowed disabled:text-zinc-500";

function DeviceChip({ label }: { label: string }) {
  return (
    <span className="rounded-md border border-zinc-700 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
      {label}
    </span>
  );
}

function ActiveIndicator() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-green-950 px-2 py-0.5 text-xs font-medium text-green-300 ring-1 ring-green-500/40">
      <span className="h-1.5 w-1.5 rounded-full bg-green-400 animate-pulse" />
      Activo
    </span>
  );
}

function ErrorText({ message }: { message: string }) {
  return (
    <p className="text-xs leading-snug text-red-400" title={message}>
      {message}
    </p>
  );
}

function ModelMeta({ model }: { model: ModelInfo }) {
  return (
    <dl className="grid grid-cols-3 gap-2 text-xs">
      <div>
        <dt className="text-zinc-500">Tamaño</dt>
        <dd className="font-medium text-zinc-300">{model.size_mb} MB</dd>
      </div>
      <div>
        <dt className="text-zinc-500">Latencia</dt>
        <dd className="font-medium text-zinc-300">{model.algorithmic_latency_ms} ms</dd>
      </div>
      <div className="min-w-0">
        <dt className="text-zinc-500">Licencia</dt>
        <dd className="truncate font-medium text-zinc-300" title={model.license}>
          {model.license}
        </dd>
      </div>
    </dl>
  );
}

function ActivatePanel({
  model,
  activating,
  onConfirm,
}: {
  model: ModelInfo;
  activating: boolean;
  onConfirm: (device: string) => void;
}) {
  const [device, setDevice] = useState("auto");

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-zinc-700 bg-zinc-900/60 p-3">
      <label className="flex flex-col gap-1 text-xs text-zinc-400">
        Destino
        <select disabled value="mic" className={selectClasses}>
          <option value="mic">Micrófono</option>
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-zinc-400">
        Device
        <select
          value={device}
          onChange={(e) => setDevice(e.target.value)}
          className={selectClasses}
        >
          <option value="auto">Auto</option>
          {model.supported_devices.map((d) => (
            <option key={d} value={d}>
              {d.toUpperCase()}
            </option>
          ))}
        </select>
      </label>
      <button
        onClick={() => onConfirm(device)}
        disabled={activating}
        className={`${primaryButtonClasses} w-full`}
      >
        {activating ? <Spinner /> : "Confirmar activación"}
      </button>
    </div>
  );
}

export function ModelCard({
  model,
  active,
  downloading,
  activating,
  deleting,
  downloadError,
  activateError,
  deleteError,
  onDownload,
  onActivate,
  onDelete,
}: ModelCardProps) {
  const [panelOpen, setPanelOpen] = useState(false);

  function handleConfirmActivate(device: string) {
    onActivate("mic", device);
  }

  return (
    <Card
      className={`flex flex-col gap-4 border-l-4 ${tierAccentClasses[model.tier]} transition-transform duration-150 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-black/30`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-lg font-bold tracking-tight text-white" title={model.name}>
            {model.name}
          </h3>
          <p className="text-xs text-zinc-500">v{model.version}</p>
        </div>
        <TierBadge tier={model.tier} />
      </div>

      <ModelMeta model={model} />

      {model.supported_devices.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {model.supported_devices.map((d) => (
            <DeviceChip key={d} label={d} />
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1.5">
        <Badge
          label={model.installed ? "Instalado" : "Disponible"}
          tone={model.installed ? "green" : "neutral"}
        />
        {active && <ActiveIndicator />}
      </div>

      <div className="mt-auto flex flex-col gap-2 border-t border-zinc-700/60 pt-3">
        {!model.installed ? (
          <>
            <button onClick={onDownload} disabled={downloading} className={primaryButtonClasses}>
              {downloading ? <Spinner /> : "Descargar"}
            </button>
            {downloadError && <ErrorText message={downloadError} />}
          </>
        ) : (
          <>
            <div className="flex gap-2">
              <button
                onClick={() => setPanelOpen((open) => !open)}
                className={`flex-1 ${panelOpen ? ghostButtonClasses : primaryButtonClasses}`}
              >
                {panelOpen ? "Cancelar" : "Activar"}
              </button>
              <button
                onClick={onDelete}
                disabled={active || deleting}
                title={active ? "No se puede borrar el modelo activo" : undefined}
                className={destructiveButtonClasses}
              >
                {deleting ? <Spinner /> : "Borrar"}
              </button>
            </div>

            {panelOpen && (
              <ActivatePanel model={model} activating={activating} onConfirm={handleConfirmActivate} />
            )}

            {activateError && <ErrorText message={activateError} />}
            {deleteError && <ErrorText message={deleteError} />}
          </>
        )}
      </div>
    </Card>
  );
}
