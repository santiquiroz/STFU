import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type DownloadProgress } from "../services/api";
import { extractError } from "../components/ui";

export function useModels() {
  return useQuery({ queryKey: ["models"], queryFn: api.listModels, staleTime: 30_000 });
}

export interface DownloadState {
  modelId: string;
  progress: DownloadProgress | null;
  error: string | null;
}

// El backend corre un solo job de descarga trackeado por vez desde esta UI
// (misma limitación que tenía el useMutation anterior); una segunda
// descarga simplemente reemplaza el socket de progreso de la primera.
export function useDownloadModel() {
  const qc = useQueryClient();
  const [state, setState] = useState<DownloadState | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

  const closeSocket = useCallback(() => {
    socketRef.current?.close();
    socketRef.current = null;
  }, []);

  useEffect(() => closeSocket, [closeSocket]);

  const handleProgressMessage = useCallback(
    (modelId: string, payload: DownloadProgress) => {
      if (payload.status === "done") {
        closeSocket();
        setState(null);
        qc.invalidateQueries({ queryKey: ["models"] });
        return;
      }
      if (payload.status === "error") {
        closeSocket();
        setState({ modelId, progress: payload, error: payload.error ?? "La descarga falló." });
        return;
      }
      setState({ modelId, progress: payload, error: null });
    },
    [closeSocket, qc],
  );

  const trackProgress = useCallback(
    (modelId: string, jobId: string) => {
      const socket = new WebSocket(api.downloadProgressWsUrl(jobId));
      socketRef.current = socket;
      socket.onmessage = (event) => handleProgressMessage(modelId, JSON.parse(event.data));
      socket.onerror = () =>
        setState({ modelId, progress: null, error: "Se perdió la conexión de progreso." });
    },
    [handleProgressMessage],
  );

  const mutation = useMutation({
    mutationFn: (id: string) => api.downloadModel(id),
    onMutate: (id) => {
      closeSocket();
      setState({ modelId: id, progress: null, error: null });
    },
    onSuccess: (data, id) => trackProgress(id, data.job_id),
    onError: (error, id) => setState({ modelId: id, progress: null, error: extractError(error) }),
  });

  return { download: (id: string) => mutation.mutate(id), state };
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
