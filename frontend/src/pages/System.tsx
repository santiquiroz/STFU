import { useApoHealth, useRepairApo } from "../hooks/useSystemHealth";
import { usePipelineStatus } from "../hooks/usePipeline";
import type { ApoHealthEndpoint, StreamStats } from "../services/api";
import { Badge, Card, Spinner, extractError } from "../components/ui";

const repairButtonClasses =
  "inline-flex items-center justify-center gap-2 rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm transition-all hover:bg-amber-500 hover:shadow-amber-900/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-400 active:scale-[0.98] active:bg-amber-700 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-500 disabled:shadow-none disabled:active:scale-100";

const endpointStateTone: Record<ApoHealthEndpoint["state"], "green" | "amber" | "red"> = {
  ok: "green",
  deactivated: "amber",
  "endpoint-missing": "red",
};

const endpointStateLabel: Record<ApoHealthEndpoint["state"], string> = {
  ok: "OK",
  deactivated: "Desactivado",
  "endpoint-missing": "Falta el endpoint",
};

function RepairBanner() {
  const repairMutation = useRepairApo();

  return (
    <div className="rounded-lg bg-amber-950 px-3 py-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-xs text-amber-300">
        ⚠ El APO fue desactivado (probablemente una actualización de Windows)
      </p>
      <div className="flex flex-col items-start gap-1 sm:items-end">
        <button
          onClick={() => repairMutation.mutate()}
          disabled={repairMutation.isPending}
          className={repairButtonClasses}
        >
          {repairMutation.isPending ? <Spinner /> : "Reparar"}
        </button>
        {repairMutation.isError && (
          <p className="text-xs text-red-400" title={extractError(repairMutation.error)}>
            {extractError(repairMutation.error)}
          </p>
        )}
      </div>
    </div>
  );
}

function OkBanner() {
  return (
    <div className="rounded-lg bg-green-950 px-3 py-2 text-xs text-green-300">
      ✓ APO OK
    </div>
  );
}

function EndpointList({ endpoints }: { endpoints: ApoHealthEndpoint[] }) {
  if (endpoints.length === 0) {
    return <p className="text-xs text-zinc-500">No hay APOs registrados en este equipo.</p>;
  }

  return (
    <ul className="flex flex-col gap-1.5">
      {endpoints.map((endpoint) => (
        <li
          key={endpoint.endpoint_guid}
          className="flex items-center justify-between gap-3 rounded-lg border border-zinc-700/60 px-3 py-1.5"
        >
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-zinc-300" title={endpoint.endpoint_guid}>
              {endpoint.flow}
            </p>
            <p className="truncate text-[10px] text-zinc-500" title={endpoint.endpoint_guid}>
              {endpoint.endpoint_guid}
            </p>
          </div>
          <Badge label={endpointStateLabel[endpoint.state]} tone={endpointStateTone[endpoint.state]} />
        </li>
      ))}
    </ul>
  );
}

function ApoHealthSection() {
  const { data: health, isLoading, isError, error } = useApoHealth();

  return (
    <Card className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold text-white">Salud del APO</h2>

      {isLoading && (
        <div className="flex justify-center py-4">
          <Spinner />
        </div>
      )}

      {isError && (
        <p className="rounded-lg bg-red-950 px-3 py-2 text-xs text-red-300">{extractError(error)}</p>
      )}

      {!isLoading && !isError && health && (
        <>
          {health.needs_repair ? <RepairBanner /> : <OkBanner />}
          <EndpointList endpoints={health.endpoints} />
        </>
      )}
    </Card>
  );
}

function StreamStatusBadges({ stats }: { stats: StreamStats }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {stats.inference?.device && <Badge label={stats.inference.device} tone="blue" />}
      {stats.inference?.degraded && (
        <Badge label="Degradado — cayó a passthrough" tone="red" />
      )}
      {stats.pipeline_failed && <Badge label="Pipeline falló" tone="red" />}
      {stats.worker_failed && <Badge label="Worker falló" tone="red" />}
    </div>
  );
}

function InferenceSection() {
  const { data: status } = usePipelineStatus();
  const streams = status?.streams ?? {};
  const targets = Object.entries(streams);

  return (
    <Card className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold text-white">Inferencia</h2>

      {targets.length === 0 ? (
        <p className="text-xs text-zinc-500">No hay procesamiento de audio activo.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {targets.map(([target, stats]) => (
            <li
              key={target}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-zinc-700/60 px-3 py-1.5"
            >
              <p className="text-xs font-medium capitalize text-zinc-300">{target}</p>
              <StreamStatusBadges stats={stats} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function System() {
  return (
    <div className="min-h-screen bg-zinc-900 text-white p-6 flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Sistema</h1>
        <p className="text-zinc-500 text-xs">Configuración del sistema</p>
      </div>

      <ApoHealthSection />
      <InferenceSection />
    </div>
  );
}
