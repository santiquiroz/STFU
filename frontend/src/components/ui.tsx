export function Spinner() {
  return (
    <div className="w-5 h-5 mx-auto rounded-full border-2 border-white/40 border-t-white animate-spin" />
  );
}

export function ProgressBar({ pct }: { pct: number | null }) {
  const determinate = pct !== null;
  const clamped = determinate ? Math.min(100, Math.max(0, pct)) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-700">
      <div
        className={`h-full rounded-full bg-green-500 transition-[width] duration-200 ${
          determinate ? "" : "w-1/3 animate-pulse"
        }`}
        style={determinate ? { width: `${clamped}%` } : undefined}
      />
    </div>
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

export function Toggle({
  on,
  loading,
  disabled,
  onChange,
}: {
  on: boolean;
  loading: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  const blocked = loading || disabled;
  return (
    <button
      onClick={() => !blocked && onChange(!on)}
      disabled={blocked}
      className={`w-12 h-6 rounded-full transition-colors ${
        loading
          ? "bg-zinc-500 cursor-wait"
          : disabled
            ? "bg-zinc-700 cursor-not-allowed opacity-50"
            : on
              ? "bg-green-500"
              : "bg-zinc-600"
      }`}
    >
      {loading ? (
        <Spinner />
      ) : (
        <div
          className={`w-5 h-5 bg-white rounded-full shadow transition-transform mx-0.5 ${
            on ? "translate-x-6" : ""
          }`}
        />
      )}
    </button>
  );
}

export function Button({
  variant = "primary",
  children,
  className,
  ...props
}: {
  variant?: "primary" | "ghost" | "destructive";
  children: React.ReactNode;
  className?: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const variantClasses: Record<string, string> = {
    primary: "bg-green-600 hover:bg-green-500 text-white",
    ghost: "bg-zinc-700 hover:bg-zinc-600 text-zinc-200",
    destructive: "bg-red-800 hover:bg-red-700 text-red-100",
  };

  const baseClasses = "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
  const variantClass = variantClasses[variant] || variantClasses.primary;

  return (
    <button
      className={`${baseClasses} ${variantClass} ${className ?? ""}`}
      {...props}
    >
      {children}
    </button>
  );
}
