import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../services/api";

export function useModels() {
  return useQuery({ queryKey: ["models"], queryFn: api.listModels, staleTime: 30_000 });
}

export function useDownloadModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.downloadModel(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
}

export function useActivateModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; target: string; device: string }) =>
      api.activateModel(v.id, v.target, v.device),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["models"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });
}

export function useDeleteModel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteModel(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });
}
