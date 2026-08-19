import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Simple } from "./pages/Simple";
import { Models } from "./pages/Models";
import { System } from "./pages/System";
import { Nav } from "./components/Nav";

const queryClient = new QueryClient();

export default function App() {
  const [activeTab, setActiveTab] = useState<"control" | "modelos" | "sistema">(
    "control"
  );

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex flex-col min-h-screen">
        <Nav active={activeTab} onChange={setActiveTab} />
        <div className="flex-1">
          {activeTab === "control" && <Simple />}
          {activeTab === "modelos" && <Models />}
          {activeTab === "sistema" && <System />}
        </div>
      </div>
    </QueryClientProvider>
  );
}
