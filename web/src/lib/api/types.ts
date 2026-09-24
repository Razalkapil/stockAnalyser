/** Friendly names for the generated OpenAPI types (schema.d.ts is regenerated, never edited). */
import type { components } from "./schema";

type S = components["schemas"];
export type Status = S["Status"];
export type Pick = S["Pick"];
export type PreviewPick = S["PreviewPick"];
export type StrategySummary = S["StrategySummary"];
export type StrategyDetail = S["StrategyDetail"];
export type GateCheck = S["GateCheckOut"];
export type StockHit = S["StockHit"];
export type StockDetail = S["StockDetail"];
export type Bar = S["Bar"];
export type BriefListItem = S["BriefListItem"];
export type Brief = S["Brief"];
export type LabRun = S["LabRun"];
export type BriefState = Brief["state"];
export type BriefCoverage = NonNullable<Brief["coverage"]>;
export type PortfolioSummary = S["PortfolioSummary"];
export type PortfolioDetail = S["PortfolioDetail"];
export type OrderOut = S["OrderOut"];
export type TradeOut = S["TradeOut"];
export type CostPreview = S["CostPreview"];
export type NewOrder = S["NewOrder"];
export type ProposalOut = S["ProposalOut"];
