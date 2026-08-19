import { useState } from "react";
import {
  useActivateModel,
  useDeleteModel,
  useDownloadModel,
  useModels,
} from "../hooks/useModels";
import { extractError, Spinner } from "../components/ui";
import { ModelCard } from "../components/ModelCard";

export function Models() {
  const { data: models, isLoading, isError, error } = useModels();
  const downloadMutation = useDownloadModel();
  const activateMutation = useActivateModel();
  const deleteMutation = useDeleteModel();
  const [activeModelId, setActiveModelId] = useState<string | null>(null);

  function handleActivate(id: string, target: string, device: string) {
    activateMutation.mutate(
      { id, target, device },
      { onSuccess: () => setActiveModelId(id) },
    );
  }

  return (
    <div className="min-h-screen bg-zinc-900 text-white p-6 flex flex-col gap-5">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Modelos</h1>
        <p className="text-zinc-500 text-xs">
          Descargá y activá modelos de cancelación de ruido. Los modelos corren en CPU o GPU.
        </p>
      </div>

      {isLoading && (
        <div className="flex justify-center py-12">
          <Spinner />
        </div>
      )}

      {isError && (
        <div className="rounded-lg bg-red-950 px-3 py-2 text-xs text-red-300">
          {extractError(error)}
        </div>
      )}

      {!isLoading && !isError && models?.length === 0 && (
        <p className="text-sm text-zinc-500">No hay modelos disponibles en el catálogo.</p>
      )}

      {!isLoading && !isError && models && models.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {models.map((model) => (
            <ModelCard
              key={model.id}
              model={model}
              active={activeModelId === model.id}
              downloading={downloadMutation.isPending && downloadMutation.variables === model.id}
              activating={
                activateMutation.isPending && activateMutation.variables?.id === model.id
              }
              deleting={deleteMutation.isPending && deleteMutation.variables === model.id}
              downloadError={
                downloadMutation.isError && downloadMutation.variables === model.id
                  ? extractError(downloadMutation.error)
                  : null
              }
              activateError={
                activateMutation.isError && activateMutation.variables?.id === model.id
                  ? extractError(activateMutation.error)
                  : null
              }
              deleteError={
                deleteMutation.isError && deleteMutation.variables === model.id
                  ? extractError(deleteMutation.error)
                  : null
              }
              onDownload={() => downloadMutation.mutate(model.id)}
              onActivate={(target, device) => handleActivate(model.id, target, device)}
              onDelete={() => deleteMutation.mutate(model.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
