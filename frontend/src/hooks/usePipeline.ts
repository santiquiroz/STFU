import { useQuery } from "@tanstack/react-query";
import { api } from "../services/api";

export function usePipelineStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: api.getStatus,
    refetchInterval: 500,
  });
}
