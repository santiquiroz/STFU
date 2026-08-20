interface NavProps {
  active: "control" | "estudio" | "modelos" | "sistema";
  onChange: (tab: "control" | "estudio" | "modelos" | "sistema") => void;
}

export function Nav({ active, onChange }: NavProps) {
  const tabs = [
    { id: "control", label: "Control" },
    { id: "estudio", label: "Estudio" },
    { id: "modelos", label: "Modelos" },
    { id: "sistema", label: "Sistema" },
  ] as const;

  return (
    <nav className="border-b border-zinc-700 bg-zinc-900">
      <div className="flex gap-8 px-6 py-4">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            className={`text-sm font-medium transition-colors pb-2 ${
              active === tab.id
                ? "text-green-400 border-b-2 border-green-500"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
    </nav>
  );
}
