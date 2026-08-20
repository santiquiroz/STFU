import { useEffect, useRef } from "react";
import type { RefObject } from "react";
import { usePipelineStatus } from "../hooks/usePipeline";
import type { AudioTelemetry } from "../services/api";
import { Card } from "./ui";

const BIN_COUNT = 48;
const DB_FLOOR = -120;
const DB_CEIL = 0;
const CANVAS_HEIGHT_PX = 180;
const BAR_GAP_PX = 2;
const IDLE_BAR_HEIGHT = 0.035;
const SMOOTHING_FACTOR = 0.15;
const GUIDE_LINE_COUNT = 3;

const GRID_LINE_COLOR = "rgba(63, 63, 70, 0.25)";
const BASELINE_COLOR = "rgba(82, 82, 91, 0.5)";
const POST_COLOR_ACTIVE = "rgba(74, 222, 128, 0.92)";
const PRE_COLOR_ACTIVE = "rgba(161, 161, 170, 0.28)";
const POST_COLOR_IDLE = "rgba(113, 113, 122, 0.5)";
const PRE_COLOR_IDLE = "rgba(63, 63, 70, 0.4)";

interface SpectrumBars {
  pre: Float32Array;
  post: Float32Array;
}

interface CanvasSize {
  width: number;
  height: number;
  dpr: number;
}

function createEmptyBars(): SpectrumBars {
  return { pre: new Float32Array(BIN_COUNT), post: new Float32Array(BIN_COUNT) };
}

function normalizeDb(db: number): number {
  return Math.min(1, Math.max(0, (db - DB_FLOOR) / (DB_CEIL - DB_FLOOR)));
}

function buildNormalizedSpectrum(spectrum: number[]): Float32Array {
  const result = new Float32Array(BIN_COUNT);
  for (let i = 0; i < BIN_COUNT; i++) {
    result[i] = normalizeDb(spectrum[i] ?? DB_FLOOR);
  }
  return result;
}

function lerp(current: number, target: number, factor: number): number {
  return current + (target - current) * factor;
}

function lerpBarsToward(bars: SpectrumBars, targetPre: Float32Array, targetPost: Float32Array, factor: number) {
  for (let i = 0; i < BIN_COUNT; i++) {
    bars.pre[i] = lerp(bars.pre[i], targetPre[i], factor);
    bars.post[i] = lerp(bars.post[i], targetPost[i], factor);
  }
}

function lerpBarsTowardIdle(bars: SpectrumBars, factor: number) {
  for (let i = 0; i < BIN_COUNT; i++) {
    bars.pre[i] = lerp(bars.pre[i], IDLE_BAR_HEIGHT, factor);
    bars.post[i] = lerp(bars.post[i], IDLE_BAR_HEIGHT, factor);
  }
}

function resolveSmoothingFactor(): number {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return reducedMotion ? 1 : SMOOTHING_FACTOR;
}

function drawGuideLines(ctx: CanvasRenderingContext2D, width: number, height: number) {
  ctx.strokeStyle = GRID_LINE_COLOR;
  ctx.lineWidth = 1;
  for (let i = 1; i <= GUIDE_LINE_COUNT; i++) {
    const y = Math.round((height * i) / (GUIDE_LINE_COUNT + 1)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
  ctx.strokeStyle = BASELINE_COLOR;
  ctx.beginPath();
  ctx.moveTo(0, height - 0.5);
  ctx.lineTo(width, height - 0.5);
  ctx.stroke();
}

function drawBar(
  ctx: CanvasRenderingContext2D,
  x: number,
  width: number,
  containerHeight: number,
  normalizedValue: number,
  color: string,
) {
  const barHeight = normalizedValue * containerHeight;
  if (barHeight <= 0.5 || width <= 0) return;
  const y = containerHeight - barHeight;
  const radius = Math.min(2, width / 2);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.roundRect(x, y, width, barHeight, [radius, radius, 0, 0]);
  ctx.fill();
}

function drawSpectrumBars(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  bars: SpectrumBars,
  active: boolean,
) {
  if (width <= 0) return;
  const barWidth = Math.max(0, (width - BAR_GAP_PX * (BIN_COUNT - 1)) / BIN_COUNT);
  const preColor = active ? PRE_COLOR_ACTIVE : PRE_COLOR_IDLE;
  const postColor = active ? POST_COLOR_ACTIVE : POST_COLOR_IDLE;

  for (let i = 0; i < BIN_COUNT; i++) {
    const x = i * (barWidth + BAR_GAP_PX);
    drawBar(ctx, x, barWidth, height, bars.pre[i], preColor);
    drawBar(ctx, x, barWidth, height, bars.post[i], postColor);
  }
}

function SpectrumLegend() {
  return (
    <div className="flex items-center gap-3 text-[10px] uppercase tracking-wide text-zinc-500">
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-sm bg-green-400" />
        Limpio
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-sm bg-zinc-500/50" />
        Removido
      </span>
    </div>
  );
}

function SpectrumPlaceholder() {
  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-6">
      <p className="rounded-full bg-zinc-900/70 px-4 py-1.5 text-center text-xs text-zinc-400 backdrop-blur-sm">
        Activá el micrófono para ver el espectro en vivo
      </p>
    </div>
  );
}

function BypassBadge() {
  return (
    <div className="pointer-events-none absolute right-2 top-2">
      <span className="rounded-full bg-zinc-900/80 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-300 ring-1 ring-amber-500/30">
        Bypass
      </span>
    </div>
  );
}

function useSpectrumCanvas(
  containerRef: RefObject<HTMLDivElement | null>,
  audioRef: RefObject<AudioTelemetry | undefined>,
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!canvasRef.current || !containerRef.current) return;
    const canvasEl: HTMLCanvasElement = canvasRef.current;
    const containerEl: HTMLDivElement = containerRef.current;
    const ctx2d = canvasEl.getContext("2d");
    if (!ctx2d) return;
    const ctx: CanvasRenderingContext2D = ctx2d;

    const bars = createEmptyBars();
    const sizeRef: { current: CanvasSize } = { current: { width: 0, height: CANVAS_HEIGHT_PX, dpr: 1 } };

    function syncCanvasSize() {
      const dpr = window.devicePixelRatio || 1;
      const width = containerEl.clientWidth;
      sizeRef.current = { width, height: CANVAS_HEIGHT_PX, dpr };
      canvasEl.width = width * dpr;
      canvasEl.height = CANVAS_HEIGHT_PX * dpr;
      canvasEl.style.height = `${CANVAS_HEIGHT_PX}px`;
    }

    syncCanvasSize();
    const resizeObserver = new ResizeObserver(syncCanvasSize);
    resizeObserver.observe(containerEl);

    const smoothingFactor = resolveSmoothingFactor();
    let rafId: number;

    function renderFrame() {
      const { width, height, dpr } = sizeRef.current;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const audio = audioRef.current;
      const active = !!audio;

      if (audio) {
        const targetPre = buildNormalizedSpectrum(audio.spectrum_pre);
        const targetPost = buildNormalizedSpectrum(audio.spectrum_post);
        lerpBarsToward(bars, targetPre, targetPost, smoothingFactor);
      } else {
        lerpBarsTowardIdle(bars, smoothingFactor);
      }

      drawGuideLines(ctx, width, height);
      drawSpectrumBars(ctx, width, height, bars, active);

      rafId = requestAnimationFrame(renderFrame);
    }

    rafId = requestAnimationFrame(renderFrame);

    return () => {
      cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
    };
  }, [containerRef, audioRef]);

  return canvasRef;
}

export function SpectrumVisualizer() {
  const { data: status } = usePipelineStatus();
  const audio = status?.streams?.feeder?.audio;
  const bypass = status?.streams?.feeder?.bypass ?? false;

  const containerRef = useRef<HTMLDivElement | null>(null);
  const audioRef = useRef<AudioTelemetry | undefined>(audio);
  audioRef.current = audio;

  const canvasRef = useSpectrumCanvas(containerRef, audioRef);

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-300">Espectro en vivo</h3>
        <SpectrumLegend />
      </div>
      <div ref={containerRef} className="relative w-full" style={{ height: CANVAS_HEIGHT_PX }}>
        <canvas ref={canvasRef} className="block h-full w-full" />
        {!audio && <SpectrumPlaceholder />}
        {audio && bypass && <BypassBadge />}
      </div>
    </Card>
  );
}
