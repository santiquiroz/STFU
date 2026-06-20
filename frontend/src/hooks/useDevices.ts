import { useQuery } from "@tanstack/react-query";
import { api } from "../services/api";

export function useDevices() {
  return useQuery({
    queryKey: ["devices"],
    queryFn: api.getDevices,
    staleTime: 30_000,
  });
}
