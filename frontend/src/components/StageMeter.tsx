import type { StreamStats } from "../services/api";

type Stage = StreamStats["stages"][number];

function isOverBudget(stage: Stage): boolean {
  return stage.overbudget > 0;
}

function BudgetDot({ overBudget }: { overBudget: boolean }) {
  return (
    <span
      className={`inline-block h-1.5 w-1.5 rounded-full ${
        overBudget ? "bg-red-500" : "bg-green-500/70"
      }`}
    />
  );
}

function StageRow({ stage }: { stage: Stage }) {
  const overBudget = isOverBudget(stage);
  return (
    <div className="grid grid-cols-[auto_1fr_auto] items-center gap-x-2 text-xs">
      <BudgetDot overBudget={overBudget} />
      <span
        className={`truncate ${overBudget ? "text-red-300" : "text-zinc-300"}`}
      >
        {stage.stage}
      </span>
      <span className="tabular-nums text-zinc-400">
        {stage.ema_ms.toFixed(1)} ms
        <span className="ml-1 text-zinc-600">
          p95 {stage.p95_ms.toFixed(1)} · bgt {stage.budget_ms.toFixed(1)}
        </span>
      </span>
    </div>
  );
}

export function StageMeter({ stages }: { stages: StreamStats["stages"] }) {
  if (!stages?.length) return null;

  return (
    <div className="w-full max-w-xs rounded-lg bg-zinc-800/60 px-3 py-2">
      <p className="mb-1 text-[10px] uppercase tracking-wide text-zinc-600">
        Latencia por etapa
      </p>
      <div className="flex flex-col gap-0.5">
        {stages.map((stage) => (
          <StageRow key={stage.stage} stage={stage} />
        ))}
      </div>
    </div>
  );
}
