import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../services/api";

export function useBypass() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (on: boolean) => api.feederBypass(on),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["feeder-status"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });
}
