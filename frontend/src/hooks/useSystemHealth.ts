import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../services/api";

export function useApoHealth() {
  return useQuery({ queryKey: ["apo/health"], queryFn: api.getApoHealth, refetchInterval: 10_000 });
}

export function useRepairApo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.repairApo(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["apo/health"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    },
  });
}
