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

export interface ApoStatus {
  registered: boolean;
  clsid: string | null;
}

export interface ApoRegisterRequest {
  flow: "Capture" | "Render";
  device_name: string;
  apo_clsid: string;
}

// CLSIDs reales — deben coincidir con apo/src/guids.h y backend constants.py
export const STFU_APO_MFX_CLSID = "{A5C595A5-CE9C-41DE-B555-82867799E74B}";
export const STFU_APO_SFX_CLSID = "{BD92FF05-2825-4D63-919B-D89FAF679713}";

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

  setParameter: (
    target: "mic" | "speaker",
    pluginIndex: number,
    parameterId: string,
    value: number,
  ): Promise<{ ok: boolean }> =>
    client
      .post(`/pipeline/${target}/parameter`, {
        plugin_index: pluginIndex,
        parameter_id: parameterId,
        value,
      })
      .then((r) => r.data),

  getApoStatus: (flow: string, deviceName: string): Promise<ApoStatus> =>
    client
      .get(`/apo/status/${flow}`, { params: { device_name: deviceName } })
      .then((r) => r.data),

  registerApo: (req: ApoRegisterRequest): Promise<{ ok: boolean }> =>
    client.post("/apo/register", req).then((r) => r.data),

  unregisterApo: (
    flow: string,
    deviceName: string,
  ): Promise<{ ok: boolean }> =>
    client
      .delete(`/apo/register/${flow}`, { params: { device_name: deviceName } })
      .then((r) => r.data),
};
