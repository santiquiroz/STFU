import { useQuery } from "@tanstack/react-query";
import { api } from "../services/api";

export function usePlugins() {
  return useQuery({
    queryKey: ["plugins"],
    queryFn: api.getPlugins,
    staleTime: Infinity,
  });
}
