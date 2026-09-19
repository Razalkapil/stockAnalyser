import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { OrderDrawer } from "./components/OrderDrawer";
import { StaleBanner } from "./components/StaleBanner";
import { TicketProvider } from "./components/TicketContext";
import { TopBar } from "./components/TopBar";
import { getToken } from "./lib/api/client";
import { useStatus } from "./lib/api/hooks";
import { color } from "./lib/theme";
import { Brief } from "./screens/Brief";
import { Login } from "./screens/Login";
import { Playground } from "./screens/Playground";
import { Stocks } from "./screens/Stocks";
import { StrategyLab } from "./screens/StrategyLab";
import { Today } from "./screens/Today";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 } },
});

function Shell() {
  const { data: status } = useStatus();
  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        background: color.page,
        color: color.text,
        overflow: "hidden",
      }}
    >
      <TopBar />
      <StaleBanner warning={status?.staleWarning ?? null} alerts={status?.jobAlerts ?? []} />
      <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
        <Routes>
          <Route path="/" element={<Today />} />
          <Route path="/stocks" element={<Stocks />} />
          <Route path="/stocks/:symbol" element={<Stocks />} />
          <Route path="/strategy" element={<StrategyLab />} />
          <Route path="/brief" element={<Brief />} />
          <Route path="/playground" element={<Playground />} />
        </Routes>
      </div>
    </div>
  );
}

export default function App() {
  const [token, setTokenState] = useState(getToken());
  useEffect(() => {
    const sync = () => {
      setTokenState(getToken());
      queryClient.clear(); // never show one session's data to the next
    };
    window.addEventListener("stk-auth-changed", sync);
    return () => window.removeEventListener("stk-auth-changed", sync);
  }, []);
  if (!token) return <Login />;
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <TicketProvider>
          <Shell />
          <OrderDrawer />
        </TicketProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
