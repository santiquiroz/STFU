export function Spinner() {
  return (
    <div className="w-5 h-5 mx-auto rounded-full border-2 border-white/40 border-t-white animate-spin" />
  );
}

export function extractError(e: unknown): string {
  if (e && typeof e === "object" && "response" in e) {
    const resp = (e as { response?: { data?: { detail?: string } } }).response;
    if (resp?.data?.detail) return resp.data.detail;
  }
  return e instanceof Error ? e.message : String(e);
}

export function Card({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`bg-zinc-800 rounded-xl p-4 ${className ?? ""}`}>
      {children}
    </div>
  );
}

type BadgeTone = "neutral" | "green" | "amber" | "red" | "blue";

const toneClasses: Record<BadgeTone, string> = {
  green: "bg-green-950 text-green-300",
  amber: "bg-amber-950 text-amber-300",
  red: "bg-red-950 text-red-300",
  blue: "bg-blue-950 text-blue-300",
  neutral: "bg-zinc-700 text-zinc-300",
};

export function Badge({
  label,
  tone,
}: {
  label: string;
  tone: BadgeTone;
}) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${toneClasses[tone]}`}>
      {label}
    </span>
  );
}

type Tier = "floor" | "default" | "quality" | "legacy";

const tierMap: Record<
  Tier,
  { tone: BadgeTone; label: string }
> = {
  floor: { tone: "blue", label: "Ligero" },
  default: { tone: "green", label: "Estándar" },
  quality: { tone: "amber", label: "Calidad" },
  legacy: { tone: "neutral", label: "Legacy" },
};

export function TierBadge({ tier }: { tier: Tier }) {
  const { tone, label } = tierMap[tier];
  return <Badge label={label} tone={tone} />;
}
