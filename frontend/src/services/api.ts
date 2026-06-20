import axios from "axios";

const client = axios.create({ baseURL: "http://localhost:8765" });

export interface DeviceInfo {
  id: number;
  name: string;
  channels_in: number;
  channels_out: number;
  is_default_input: boolean;
  is_default_output: boolean;
}

export interface StatusResponse {
  status: string;
  latency_ms: number;
  active: string[];
}

export interface PluginConfig {
  plugin_id: string;
  parameters?: Record<string, number | string | boolean>;
}

export interface PipelineRequest {
  plugins: PluginConfig[];
  input_device_id: number;
  output_device_id: number;
}

export interface PipelineResponse {
  ok: boolean;
  target: string;
  active: boolean;
  latency_ms?: number;
}

export const api = {
  getStatus: (): Promise<StatusResponse> =>
    client.get("/status").then((r) => r.data),

  getDevices: (): Promise<DeviceInfo[]> =>
    client.get("/devices").then((r) => r.data),

  startPipeline: (
    target: "mic" | "speaker",
    req: PipelineRequest,
  ): Promise<PipelineResponse> =>
    client.post(`/pipeline/${target}`, req).then((r) => r.data),

  stopPipeline: (target: "mic" | "speaker"): Promise<PipelineResponse> =>
    client.delete(`/pipeline/${target}`).then((r) => r.data),

  getActivePipelines: (): Promise<{ active: string[] }> =>
    client.get("/pipeline/active").then((r) => r.data),
};
