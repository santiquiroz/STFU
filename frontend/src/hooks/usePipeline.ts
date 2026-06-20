import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApoRegisterRequest, PipelineRequest } from "../services/api";

export function usePipelineStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: api.getStatus,
    refetchInterval: 500,
  });
}

export function useActivePipelines() {
  return useQuery({
    queryKey: ["pipeline/active"],
    queryFn: api.getActivePipelines,
    refetchInterval: 1000,
  });
}

export function useStartPipeline(target: "mic" | "speaker") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (req: PipelineRequest) => api.startPipeline(target, req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["status"] });
      queryClient.invalidateQueries({ queryKey: ["pipeline/active"] });
    },
  });
}

export function useStopPipeline(target: "mic" | "speaker") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.stopPipeline(target),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["status"] });
      queryClient.invalidateQueries({ queryKey: ["pipeline/active"] });
    },
  });
}

export function useApoStatus(flow: string, deviceName: string) {
  return useQuery({
    queryKey: ["apo/status", flow, deviceName],
    queryFn: () => api.getApoStatus(flow, deviceName),
    enabled: !!deviceName,
    refetchInterval: 5000,
  });
}

export function useApoRegister() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (req: ApoRegisterRequest) => api.registerApo(req),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["apo/status"] }),
  });
}
