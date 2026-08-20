import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, PluginConfig } from "../services/api";

export function usePresets() {
  return useQuery({
    queryKey: ["presets"],
    queryFn: api.listPresets,
  });
}

export function useSavePreset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, plugins }: { name: string; plugins: PluginConfig[] }) =>
      api.savePreset(name, plugins),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["presets"] });
    },
  });
}

export function useDeletePreset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.deletePreset(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["presets"] });
    },
  });
}
