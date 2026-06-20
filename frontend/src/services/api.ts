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
}

export const api = {
  getStatus: (): Promise<StatusResponse> =>
    client.get("/status").then((r) => r.data),
  getDevices: (): Promise<DeviceInfo[]> =>
    client.get("/devices").then((r) => r.data),
  configurePipeline: (
    target: "mic" | "speaker",
    config: object,
  ): Promise<void> =>
    client.post(`/pipeline/${target}`, config).then((r) => r.data),
};
