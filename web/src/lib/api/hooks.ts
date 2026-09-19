import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPatch, apiPost } from "./client";
import type {
  Bar,
  Brief,
  BriefListItem,
  CostPreview,
  NewOrder,
  Pick,
  PortfolioDetail,
  PortfolioSummary,
  Status,
  StockDetail,
  StockHit,
  StrategyDetail,
  StrategySummary,
} from "./types";

const enc = encodeURIComponent;

/** Polled: the market status and stale banner must not go quietly out of date. */
export const useStatus = () =>
  useQuery({
    queryKey: ["status"],
    queryFn: () => apiGet<Status>("/api/status"),
    refetchInterval: 60_000,
  });

export const usePicks = (date?: string) =>
  useQuery({
    queryKey: ["picks", date ?? "latest"],
    queryFn: () => apiGet<Pick[]>(`/api/picks${date ? `?date=${enc(date)}` : ""}`),
  });

export const useStrategies = () =>
  useQuery({ queryKey: ["strategies"], queryFn: () => apiGet<StrategySummary[]>("/api/strategies") });

export const useStrategy = (slug: string | null) =>
  useQuery({
    queryKey: ["strategy", slug],
    queryFn: () => apiGet<StrategyDetail>(`/api/strategies/${enc(slug ?? "")}`),
    enabled: !!slug,
  });

export const useStockSearch = (q: string) =>
  useQuery({
    queryKey: ["stock-search", q],
    queryFn: () => apiGet<StockHit[]>(`/api/stocks/search?q=${enc(q)}`),
    enabled: q.trim().length > 0,
    staleTime: 30_000,
  });

export const useStock = (symbol: string | null) =>
  useQuery({
    queryKey: ["stock", symbol],
    queryFn: () => apiGet<StockDetail>(`/api/stocks/${enc(symbol ?? "")}`),
    enabled: !!symbol,
    retry: false,
  });

export const useBars = (symbol: string | null) =>
  useQuery({
    queryKey: ["bars", symbol],
    queryFn: () => apiGet<Bar[]>(`/api/stocks/${enc(symbol ?? "")}/bars`),
    enabled: !!symbol,
  });

export const useBriefs = () =>
  useQuery({ queryKey: ["briefs"], queryFn: () => apiGet<BriefListItem[]>("/api/briefs") });

export const useBrief = (day: string | null) =>
  useQuery({
    queryKey: ["brief", day],
    queryFn: () => apiGet<Brief>(`/api/briefs/${enc(day ?? "")}`),
    enabled: !!day,
  });

export function useStrategyAction(slug: string) {
  const qc = useQueryClient();
  const done = () => {
    void qc.invalidateQueries({ queryKey: ["strategies"] });
    void qc.invalidateQueries({ queryKey: ["strategy", slug] });
  };
  return {
    approve: useMutation({
      mutationFn: () => apiPost(`/api/strategies/${enc(slug)}/approve`),
      onSuccess: done,
    }),
    retire: useMutation({
      mutationFn: (reason: string) =>
        apiPost(`/api/strategies/${enc(slug)}/retire`, { confirm: true, reason }),
      onSuccess: done,
    }),
  };
}

// --- playground ----------------------------------------------------------------------------

export const usePortfolios = () =>
  useQuery({ queryKey: ["portfolios"], queryFn: () => apiGet<PortfolioSummary[]>("/api/portfolios") });

/** Polled while the tab is open: fills happen server-side, between page loads. */
export const usePortfolio = (id: number | null) =>
  useQuery({
    queryKey: ["portfolio", id],
    queryFn: () => apiGet<PortfolioDetail>(`/api/portfolios/${id}`),
    enabled: id != null,
    refetchInterval: 30_000,
  });

function usePortfolioInvalidation() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: ["portfolios"] });
    void qc.invalidateQueries({ queryKey: ["portfolio"] });
  };
}

export function useCreatePortfolio() {
  const done = usePortfolioInvalidation();
  return useMutation({
    mutationFn: (b: { name: string; startCapital: string }) =>
      apiPost<PortfolioSummary>("/api/portfolios", b),
    onSuccess: done,
  });
}

export function usePlaceOrder() {
  const done = usePortfolioInvalidation();
  return useMutation({
    mutationFn: (b: NewOrder) => apiPost<{ id: number }>("/api/orders", b),
    onSuccess: done,
  });
}

export function useCancelOrder() {
  const done = usePortfolioInvalidation();
  return useMutation({
    mutationFn: (id: number) => apiDelete(`/api/orders/${id}`),
    onSuccess: done,
  });
}

export function useJournal() {
  const done = usePortfolioInvalidation();
  return useMutation({
    mutationFn: (v: { id: number; note: string }) => apiPatch(`/api/trades/${v.id}`, { note: v.note }),
    onSuccess: done,
  });
}

export const useCostPreview = (req: { symbol: string; side: string; qty: number; price: number } | null) =>
  useQuery({
    queryKey: ["preview", req],
    queryFn: () =>
      apiPost<CostPreview>("/api/orders/preview", {
        symbol: req!.symbol,
        side: req!.side,
        qty: req!.qty,
        price: String(req!.price),
      }),
    enabled: req != null,
    placeholderData: keepPreviousData,
    staleTime: 10_000,
    retry: false,
  });
