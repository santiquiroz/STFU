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

export interface ModelInfo {
  id: string;
  name: string;
  version: string;
  tier: "floor" | "default" | "quality" | "legacy";
  size_mb: number;
  algorithmic_latency_ms: number;
  license: string;
  supported_devices: string[];
  tags: string[];
  installed: boolean;
}

export interface InferenceStatus {
  device: string | null;
  degraded: boolean;
  model_id?: string | null;
}

export interface AudioTelemetry {
  pre_db: number;
  post_db: number;
  reduction_db: number;
  spectrum_pre: number[];
  spectrum_post: number[];
}

export interface StreamStats {
  playback_active: boolean;
  pipeline_failed: boolean;
  worker_failed: boolean;
  total_latency_ms: number;
  stages: {
    stage: string;
    ema_ms: number;
    p95_ms: number;
    budget_ms: number;
    overbudget: number;
  }[];
  inference?: InferenceStatus | null;
  audio?: AudioTelemetry;
  bypass?: boolean;
}

export interface ApoHealthEndpoint {
  endpoint_guid: string;
  flow: "Capture" | "Render";
  state: "ok" | "deactivated" | "endpoint-missing";
}

export interface ApoHealth {
  needs_repair: boolean;
  endpoints: ApoHealthEndpoint[];
}

export interface StatusResponse {
  status: string;
  latency_ms: number;
  active: string[];
  streams?: Record<string, StreamStats>;
  apo?: Record<string, boolean>;
  apo_health?: ApoHealth;
}

export interface PluginConfig {
  plugin_id: string;
  parameters?: Record<string, number | string | boolean>;
}

export interface Parameter {
  id: string;
  label: string;
  type: "float" | "int" | "bool" | "enum";
  default: unknown;
  min?: number;
  max?: number;
  options?: string[];
}

export interface PluginCatalogEntry {
  plugin_id: string;
  name: string;
  version: string;
  parameters: Parameter[];
}

export interface PresetInfo {
  name: string;
  plugins: PluginConfig[];
  builtin: boolean;
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
    plugins: PluginConfig[],
    testOutputDeviceId?: number,
  ): Promise<{ ok: boolean; using_bridge: boolean; output_device_id: number }> =>
    client
      .post("/feeder/start", {
        input_device_id: inputDeviceId,
        plugins,
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
      .post("/feeder/parameter", {
        plugin_index: pluginIndex,
        parameter_id: parameterId,
        value,
      })
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

  listModels: (): Promise<ModelInfo[]> =>
    client.get("/models").then((r) => r.data),

  downloadModel: (id: string): Promise<{ installed: boolean; path: string }> =>
    client.post(`/models/${encodeURIComponent(id)}/download`).then((r) => r.data),

  activateModel: (
    id: string,
    target: string,
    device: string,
  ): Promise<{ activated: string; target: string }> =>
    client
      .post(`/models/${encodeURIComponent(id)}/activate`, null, {
        params: { target, device },
      })
      .then((r) => r.data),

  deleteModel: (id: string): Promise<{ deleted: boolean }> =>
    client.delete(`/models/${encodeURIComponent(id)}`).then((r) => r.data),

  getApoHealth: (): Promise<ApoHealth> =>
    client.get("/apo/health").then((r) => r.data),

  repairApo: (): Promise<{ ok: boolean }> =>
    client.post("/apo/repair").then((r) => r.data),

  getPlugins: (): Promise<PluginCatalogEntry[]> =>
    client.get("/plugins").then((r) => r.data),

  listPresets: (): Promise<PresetInfo[]> =>
    client.get("/presets").then((r) => r.data),

  getPreset: (name: string): Promise<PresetInfo> =>
    client.get(`/presets/${encodeURIComponent(name)}`).then((r) => r.data),

  savePreset: (
    name: string,
    plugins: PluginConfig[],
  ): Promise<{ name: string; plugins: PluginConfig[]; builtin: boolean }> =>
    client
      .post(`/presets/${encodeURIComponent(name)}`, { plugins })
      .then((r) => r.data),

  deletePreset: (name: string): Promise<{ deleted?: boolean } | unknown> =>
    client.delete(`/presets/${encodeURIComponent(name)}`).then((r) => r.data),

  feederBypass: (on: boolean): Promise<{ ok: boolean; bypass: boolean }> =>
    client.post("/feeder/bypass", { on }).then((r) => r.data),
};
