import { useState } from "react";
import { usePresets, useSavePreset, useDeletePreset } from "../hooks/usePresets";
import { api } from "../services/api";
import type { PluginConfig } from "../services/api";
import { Button, Card, Badge, Spinner, extractError } from "./ui";

interface PresetPickerProps {
  currentChain: PluginConfig[];
  onLoadChain: (plugins: PluginConfig[]) => void;
}

export function PresetPicker({ currentChain, onLoadChain }: PresetPickerProps) {
  const { data: presets, isLoading } = usePresets();
  const savePresetMutation = useSavePreset();
  const deletePresetMutation = useDeletePreset();

  const [presetName, setPresetName] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [loadingPreset, setLoadingPreset] = useState<string | null>(null);

  const handleLoadPreset = async (name: string) => {
    setLoadingPreset(name);
    try {
      const preset = await api.getPreset(name);
      onLoadChain(preset.plugins);
    } catch (e) {
      setSaveError(extractError(e));
    } finally {
      setLoadingPreset(null);
    }
  };

  const handleSavePreset = async () => {
    setSaveError(null);
    try {
      await savePresetMutation.mutateAsync({
        name: presetName,
        plugins: currentChain,
      });
      setPresetName("");
    } catch (e) {
      setSaveError(extractError(e));
    }
  };

  const handleDeletePreset = async (name: string) => {
    setDeleteError(null);
    try {
      await deletePresetMutation.mutateAsync(name);
    } catch (e) {
      setDeleteError(extractError(e));
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Save section */}
      <Card className="flex flex-col gap-3">
        <div className="text-sm font-semibold text-white">Guardar escena</div>
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="Nombre de la escena"
            value={presetName}
            onChange={(e) => {
              setPresetName(e.target.value);
              setSaveError(null);
            }}
            className="flex-1 rounded-md border border-zinc-700 bg-zinc-800 px-2 py-1.5 text-sm text-zinc-200 placeholder-zinc-500 transition-colors focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500/50"
          />
          <Button
            variant="primary"
            onClick={handleSavePreset}
            disabled={!presetName.trim() || savePresetMutation.isPending}
          >
            {savePresetMutation.isPending ? "Guardando..." : "Guardar"}
          </Button>
        </div>
        {saveError && <div className="text-xs text-red-300">{saveError}</div>}
      </Card>

      {/* Presets list section */}
      <Card className="flex flex-col gap-3">
        <div className="text-sm font-semibold text-white">Escenas</div>

        {isLoading ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : !presets || presets.length === 0 ? (
          <div className="text-xs text-zinc-400">No hay presets guardados.</div>
        ) : (
          <div className="flex flex-col gap-2">
            {presets.map((preset) => (
              <div
                key={preset.name}
                className="flex items-center justify-between gap-2 rounded-lg bg-zinc-700/40 p-2.5 transition-colors hover:bg-zinc-700/60"
              >
                <div className="flex items-center gap-2 flex-1 min-w-0">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-white truncate">
                      {preset.name}
                    </div>
                  </div>
                  {preset.builtin && (
                    <Badge label="Predefinido" tone="blue" />
                  )}
                </div>

                <div className="flex gap-1.5 flex-shrink-0">
                  <Button
                    variant="ghost"
                    onClick={() => handleLoadPreset(preset.name)}
                    disabled={loadingPreset === preset.name}
                    className="text-xs"
                  >
                    {loadingPreset === preset.name ? (
                      <div className="w-3 h-3 border-2 border-zinc-400 border-t-zinc-200 rounded-full animate-spin" />
                    ) : (
                      "Cargar"
                    )}
                  </Button>

                  {!preset.builtin && (
                    <Button
                      variant="destructive"
                      onClick={() => handleDeletePreset(preset.name)}
                      disabled={deletePresetMutation.isPending}
                      className="text-xs"
                    >
                      {deletePresetMutation.isPending ? "..." : "Borrar"}
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {deleteError && (
          <div className="text-xs text-red-300">{deleteError}</div>
        )}
      </Card>
    </div>
  );
}
