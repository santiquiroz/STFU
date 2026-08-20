import { useEffect, useRef, useState } from "react";
import { usePipelineStatus } from "../hooks/usePipeline";
import { Card } from "./ui";

const MAX_REDUCTION_DB = 40;
const REDUCTION_ACTIVE_THRESHOLD_DB = 1;
const SMOOTHING_FACTOR = 0.25;
const CONVERGENCE_EPSILON_DB = 0.02;

function clampReductionRatio(reductionDb: number): number {
  return Math.min(1, Math.max(0, reductionDb / MAX_REDUCTION_DB));
}

function resolveSmoothingFactor(): number {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  return reducedMotion ? 1 : SMOOTHING_FACTOR;
}

function useSmoothedReduction(targetDb: number | undefined): number {
  const target = targetDb ?? 0;
  const [displayedDb, setDisplayedDb] = useState(target);
  const currentRef = useRef(target);
  const targetRef = useRef(target);
  const rafRef = useRef<number | undefined>(undefined);
  const smoothingRef = useRef(1);

  useEffect(() => {
    smoothingRef.current = resolveSmoothingFactor();
  }, []);

  useEffect(() => {
    targetRef.current = target;
    startSmoothingLoop();

    function startSmoothingLoop() {
      if (rafRef.current !== undefined) return;

      function tick() {
        const smoothing = smoothingRef.current;
        const next = currentRef.current + (targetRef.current - currentRef.current) * smoothing;
        const converged = Math.abs(targetRef.current - next) < CONVERGENCE_EPSILON_DB;
        currentRef.current = converged ? targetRef.current : next;
        setDisplayedDb(currentRef.current);

        if (converged) {
          rafRef.current = undefined;
          return;
        }
        rafRef.current = requestAnimationFrame(tick);
      }

      rafRef.current = requestAnimationFrame(tick);
    }

    return () => {
      if (rafRef.current !== undefined) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = undefined;
      }
    };
  }, [target]);

  return displayedDb;
}

function ReductionHeadline({ reductionDb, active }: { reductionDb: number; active: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
        Ruido reducido
      </span>
      <span
        className={`text-4xl font-bold tabular-nums transition-colors duration-300 ${
          active ? "text-green-400" : "text-zinc-400"
        }`}
      >
        −{reductionDb.toFixed(1)} dB
      </span>
    </div>
  );
}

function ReductionBar({ ratio, active }: { ratio: number; active: boolean }) {
  return (
    <div className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-700">
      <div
        className={`h-full rounded-full transition-[width] duration-500 ease-out ${
          active ? "bg-green-500" : "bg-zinc-500"
        }`}
        style={{ width: `${ratio * 100}%` }}
      />
    </div>
  );
}

function ReductionContext({ preDb, postDb }: { preDb: number; postDb: number }) {
  return (
    <p className="text-xs text-zinc-400">
      entrada {preDb.toFixed(0)} dB → salida {postDb.toFixed(0)} dB
    </p>
  );
}

function ReductionPlaceholder() {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
        Ruido reducido
      </span>
      <span className="text-4xl font-bold text-zinc-600">— dB</span>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-800">
        <div className="h-full w-0 rounded-full border border-dashed border-zinc-700" />
      </div>
      <p className="text-xs text-zinc-500">Sin stream activo</p>
    </div>
  );
}

export function ReductionMeter() {
  const { data: status } = usePipelineStatus();
  const audio = status?.streams?.feeder?.audio;
  const bypass = status?.streams?.feeder?.bypass ?? false;
  const displayedReductionDb = useSmoothedReduction(audio?.reduction_db);

  if (!audio) {
    return (
      <Card>
        <ReductionPlaceholder />
      </Card>
    );
  }

  const isReducing = !bypass && audio.reduction_db > REDUCTION_ACTIVE_THRESHOLD_DB;
  const ratio = clampReductionRatio(displayedReductionDb);

  return (
    <Card className="flex flex-col gap-3">
      <ReductionHeadline reductionDb={displayedReductionDb} active={isReducing} />
      <ReductionBar ratio={ratio} active={isReducing} />
      <ReductionContext preDb={audio.pre_db} postDb={audio.post_db} />
    </Card>
  );
}
