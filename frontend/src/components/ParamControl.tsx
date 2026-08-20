import type { Parameter } from "../services/api";
import { Toggle } from "./ui";

export function ParamControl({
  param,
  value,
  onChange,
}: {
  param: Parameter;
  value: number | string | boolean;
  onChange: (value: number | string | boolean) => void;
}) {
  if (param.type === "float" || param.type === "int") {
    const min = param.min ?? 0;
    const max = param.max ?? 1;
    const step = param.type === "int" ? 1 : 0.01;
    const numValue = typeof value === "number" ? value : 0;

    return (
      <div className="flex flex-col gap-2">
        <div className="flex justify-between items-center">
          <label className="text-xs text-zinc-400">{param.label}</label>
          <span className="text-xs text-zinc-400">
            {typeof numValue === "number" ? numValue.toFixed(param.type === "int" ? 0 : 2) : numValue}
          </span>
        </div>
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={numValue}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-full accent-green-500"
        />
      </div>
    );
  }

  if (param.type === "bool") {
    return (
      <div className="flex items-center justify-between">
        <label className="text-xs text-zinc-400">{param.label}</label>
        <Toggle
          on={Boolean(value)}
          loading={false}
          onChange={onChange}
        />
      </div>
    );
  }

  if (param.type === "enum") {
    return (
      <div className="flex flex-col gap-2">
        <label className="text-xs text-zinc-400">{param.label}</label>
        <select
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
          className="text-xs bg-zinc-700 rounded px-2 py-1 text-zinc-300"
        >
          {(param.options ?? []).map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      </div>
    );
  }

  return null;
}
