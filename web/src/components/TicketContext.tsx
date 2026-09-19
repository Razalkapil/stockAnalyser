import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

/** What "Paper trade this" (or "New order") pre-fills into the ticket. */
export interface TicketPrefill {
  symbol?: string;
  side?: "buy" | "sell";
  ref?: number | null;
  stop?: number | null;
  target?: number | null;
  pickId?: number | null;
  note?: string;
}

interface Ctx {
  open: boolean;
  prefill: TicketPrefill;
  openTicket: (p?: TicketPrefill) => void;
  closeTicket: () => void;
}

const TicketCtx = createContext<Ctx | null>(null);

export function TicketProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [prefill, setPrefill] = useState<TicketPrefill>({});
  const openTicket = useCallback((p: TicketPrefill = {}) => {
    setPrefill(p);
    setOpen(true);
  }, []);
  const closeTicket = useCallback(() => setOpen(false), []);
  const value = useMemo(() => ({ open, prefill, openTicket, closeTicket }), [open, prefill, openTicket, closeTicket]);
  return <TicketCtx.Provider value={value}>{children}</TicketCtx.Provider>;
}

export function useTicket(): Ctx {
  const c = useContext(TicketCtx);
  if (!c) throw new Error("useTicket must be used inside <TicketProvider>");
  return c;
}
