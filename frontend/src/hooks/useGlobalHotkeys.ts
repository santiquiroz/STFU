import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { register, unregisterAll, type ShortcutEvent } from "@tauri-apps/plugin-global-shortcut";
import { api, DeviceInfo, StatusResponse } from "../services/api";

export const HOTKEY_BYPASS = "CommandOrControl+Alt+M";
export const HOTKEY_MUSIC = "CommandOrControl+Alt+N";

interface FeederStatusCache {
  active: boolean;
  bridge_present: boolean;
  input_device_id: number | null;
}

function wasPressed(event: ShortcutEvent): boolean {
  return event.state === "Pressed";
}

// Registra atajos OS-wide una sola vez por sesión de la app; los handlers
// leen el cache de TanStack Query en el momento del press en vez de cerrar
// sobre estado del render (así no hace falta re-registrar el shortcut cada
// vez que cambia el estado del feeder).
export function useGlobalHotkeys() {
  const queryClient = useQueryClient();

  // GlobalHotkeys es el único componente montado durante toda la vida de la
  // app (a diferencia de Simple/Studio, que solo observan feeder-status
  // mientras su tab está activo). Sin este observer propio, gcTime por
  // defecto de TanStack Query puede purgar la cache de ["feeder-status"]
  // si el usuario deja STFU en Modelos/Sistema (o minimizado) más de 5 min,
  // y el guard de actividad de abajo dejaría de disparar el atajo global.
  // Mismo queryKey/queryFn/refetchInterval que Simple.tsx: dedupe, no pega
  // dos veces al backend.
  useQuery({
    queryKey: ["feeder-status"],
    queryFn: api.getFeederStatus,
    refetchInterval: 2000,
  });

  useEffect(() => {
    let bypassBusy = false;
    let musicBusy = false;

    async function toggleBypassFromHotkey() {
      if (bypassBusy) return;
      const feeder = queryClient.getQueryData<FeederStatusCache>(["feeder-status"]);
      if (!feeder?.active) return;
      const status = queryClient.getQueryData<StatusResponse>(["status"]);
      const isBypassed = status?.streams?.feeder?.bypass ?? false;
      bypassBusy = true;
      try {
        await api.feederBypass(!isBypassed);
        queryClient.invalidateQueries({ queryKey: ["feeder-status"] });
        queryClient.invalidateQueries({ queryKey: ["status"] });
      } catch {
        // el feeder pudo dejar de estar activo entre la lectura del cache y la llamada
      } finally {
        bypassBusy = false;
      }
    }

    async function startMusicModeFromHotkey() {
      if (musicBusy) return;
      const feeder = queryClient.getQueryData<FeederStatusCache>(["feeder-status"]);
      const devices = queryClient.getQueryData<DeviceInfo[]>(["devices"]) ?? [];
      const inputs = devices.filter((d) => d.channels_in > 0);
      const outputs = devices.filter((d) => d.channels_out > 0);
      const inputDeviceId = feeder?.input_device_id ?? inputs[0]?.id;
      if (inputDeviceId === undefined) return;
      const bridgePresent = feeder?.bridge_present ?? false;
      const outputDeviceId = outputs[0]?.id;
      if (!bridgePresent && outputDeviceId === undefined) return;
      musicBusy = true;
      try {
        const preset = await api.getPreset("Música");
        await api.startFeeder(
          inputDeviceId,
          preset.plugins,
          bridgePresent ? undefined : outputDeviceId,
        );
        queryClient.invalidateQueries({ queryKey: ["feeder-status"] });
        queryClient.invalidateQueries({ queryKey: ["status"] });
      } catch {
        // dispositivo desconectado o backend caído; el usuario lo ve reflejado en la UI
      } finally {
        musicBusy = false;
      }
    }

    register(HOTKEY_BYPASS, (event) => {
      if (wasPressed(event)) void toggleBypassFromHotkey();
    }).catch((e) => console.error("no se pudo registrar el atajo de bypass", e));

    register(HOTKEY_MUSIC, (event) => {
      if (wasPressed(event)) void startMusicModeFromHotkey();
    }).catch((e) => console.error("no se pudo registrar el atajo de modo música", e));

    return () => {
      void unregisterAll();
    };
  }, [queryClient]);
}
