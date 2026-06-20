import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Simple } from "./pages/Simple";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Simple />
    </QueryClientProvider>
  );
}
