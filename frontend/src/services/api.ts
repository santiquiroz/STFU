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

  getFeederStatus: (): Promise<{
    bridge_present: boolean;
    bridge_name: string;
    bridge_device_id: number | null;
    active: boolean;
  }> => client.get("/feeder/status").then((r) => r.data),

  startFeeder: (
    inputDeviceId: number,
    strength: number,
    testOutputDeviceId?: number,
  ): Promise<{ ok: boolean; using_bridge: boolean; output_device_id: number }> =>
    client
      .post("/feeder/start", {
        input_device_id: inputDeviceId,
        plugins: [
          { plugin_id: "deepfilternet3", parameters: { strength } },
        ],
        test_output_device_id: testOutputDeviceId ?? null,
      })
      .then((r) => r.data),

  stopFeeder: (): Promise<{ ok: boolean }> =>
    client.delete("/feeder/stop").then((r) => r.data),

  setFeederParameter: (
    pluginIndex: number,
    parameterId: string,
    value: number,
  ): Promise<{ ok: boolean }> =>
    client
      .post(
        `/feeder/parameter?plugin_index=${pluginIndex}&parameter_id=${parameterId}&value=${value}`,
      )
      .then((r) => r.data),

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

  getUnsignedApoEnabled: (): Promise<{ enabled: boolean }> =>
    client.get("/apo/unsigned").then((r) => r.data),

  enableUnsignedApos: (): Promise<{ ok: boolean }> =>
    client.post("/apo/unsigned").then((r) => r.data),

  getBridgeStatus: (): Promise<{ active: Record<string, boolean> }> =>
    client.get("/apo/bridge").then((r) => r.data),

  startBridge: (
    flow: "Capture" | "Render",
    plugins: PluginConfig[],
  ): Promise<{ ok: boolean }> =>
    client.post(`/apo/bridge/${flow}`, { plugins }).then((r) => r.data),

  stopBridge: (flow: "Capture" | "Render"): Promise<{ ok: boolean }> =>
    client.delete(`/apo/bridge/${flow}`).then((r) => r.data),

  setBridgeParameter: (
    flow: "Capture" | "Render",
    pluginIndex: number,
    parameterId: string,
    value: number,
  ): Promise<{ ok: boolean }> =>
    client
      .post(`/apo/bridge/${flow}/parameter`, {
        plugin_index: pluginIndex,
        parameter_id: parameterId,
        value,
      })
      .then((r) => r.data),
};
