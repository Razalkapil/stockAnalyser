"""The FastAPI application.

``create_app`` takes the paths it serves from, so tests build one against a temp database and
lake and the CLI builds one from settings. Every route except ``/api/health`` requires a bearer
token. Reads only; the two writes (approve / retire a strategy) go through the audited
``strategies.repo.set_status``.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query

from stk.api import playground_routes, services
from stk.api import schemas as s
from stk.api.deps import ApiContext, Conn, Ctx, require_token
from stk.backtest.setup import make_rates_fn
from stk.config.backtest import BacktestConfig, load_backtest_config
from stk.playground.context import PlayCtx
from stk.strategies.proposals import ProposalError
from stk.strategies.proposals import approve as approve_proposal
from stk.strategies.proposals import dismiss as dismiss_proposal
from stk.strategies.repo import get_strategy, set_status

open_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_token)])


def _day(day: str) -> str:
    """A path date, validated. A bad one is the caller's error, not a 500 three layers down."""
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(422, "date must be YYYY-MM-DD") from exc
    return day


@open_router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/status", response_model=s.Status)
def status(conn: Conn, ctx: Ctx) -> s.Status:
    return services.build_status(conn, ctx.parquet_root)


@router.get("/api/picks", response_model=list[s.Pick])
def picks(conn: Conn, on: Annotated[str | None, Query(alias="date")] = None,
          horizon: str | None = None) -> list[s.Pick]:
    return services.list_picks(conn, on, horizon)


@router.get("/api/previews", response_model=list[s.PreviewPick])
def previews(conn: Conn, on: Annotated[str | None, Query(alias="date")] = None,
             slug: str | None = None) -> list[s.PreviewPick]:
    """What NOT-promoted strategies would pick. Informational: these are not recommendations."""
    return services.list_previews(conn, on, slug)


@router.get("/api/strategies", response_model=list[s.StrategySummary])
def strategies(conn: Conn) -> list[s.StrategySummary]:
    return services.list_strategy_summaries(conn)


@router.get("/api/strategies/{slug}", response_model=s.StrategyDetail)
def strategy(slug: str, conn: Conn) -> s.StrategyDetail:
    detail = services.strategy_detail(conn, slug)
    if detail is None:
        raise HTTPException(404, f"no strategy {slug!r}")
    return detail


@router.post("/api/strategies/{slug}/approve", response_model=s.StrategySummary)
def approve(slug: str, conn: Conn) -> s.StrategySummary:
    """Take a gated candidate live. Refuses anything that has not passed the gate."""
    row = get_strategy(conn, slug)
    if row is None:
        raise HTTPException(404, f"no strategy {slug!r}")
    if row.status != "candidate":
        raise HTTPException(409, f"only a candidate can be approved; this one is {row.status}")
    gate_ok = conn.execute(
        "SELECT 1 FROM backtest_runs WHERE strategy_ref=? AND gate_verdict='pass' LIMIT 1",
        (slug,)).fetchone()
    if gate_ok is None:
        raise HTTPException(409, "this strategy has not passed the promotion gate -- no "
                                 "exceptions, including for a person")
    set_status(conn, row.strategy_id, "live", actor="user", reason="approved in the UI")
    return next(x for x in services.list_strategy_summaries(conn) if x.id == slug)


@router.post("/api/strategies/{slug}/retire", response_model=s.StrategySummary)
def retire(slug: str, body: s.DemoteRequest, conn: Conn) -> s.StrategySummary:
    """Take a strategy out of service. Requires explicit confirmation."""
    if not body.confirm:
        raise HTTPException(422, "retiring a strategy requires confirm=true")
    row = get_strategy(conn, slug)
    if row is None:
        raise HTTPException(404, f"no strategy {slug!r}")
    set_status(conn, row.strategy_id, "retired", actor="user",
               reason=body.reason or "retired in the UI")
    return next(x for x in services.list_strategy_summaries(conn) if x.id == slug)


@router.get("/api/proposals", response_model=list[s.ProposalOut])
def proposals(conn: Conn) -> list[s.ProposalOut]:
    return services.proposal_list(conn)


@router.post("/api/proposals/{pid}/approve", response_model=list[s.ProposalOut])
def proposal_approve(pid: int, conn: Conn, body: s.DecisionRequest | None = None
                     ) -> list[s.ProposalOut]:
    """Approve a proposal. A NEW strategy must have passed the gate; a demotion needs confirm."""
    try:
        approve_proposal(conn, pid, confirm=bool(body and body.confirm))
    except ProposalError as exc:
        raise HTTPException(409, str(exc)) from exc
    return services.proposal_list(conn)


@router.post("/api/proposals/{pid}/dismiss", response_model=list[s.ProposalOut])
def proposal_dismiss(pid: int, conn: Conn) -> list[s.ProposalOut]:
    try:
        dismiss_proposal(conn, pid)
    except ProposalError as exc:
        raise HTTPException(409, str(exc)) from exc
    return services.proposal_list(conn)


@router.get("/api/stocks/search", response_model=list[s.StockHit])
def stock_search(conn: Conn, q: str = "") -> list[s.StockHit]:
    return services.search_stocks(conn, q)


@router.get("/api/stocks/{symbol}", response_model=s.StockDetail)
def stock(symbol: str, conn: Conn, ctx: Ctx) -> s.StockDetail:
    detail = services.stock_detail(conn, ctx.parquet_root, ctx.cfg, symbol)
    if detail is None:
        raise HTTPException(404, f"no security {symbol!r}")
    return detail


@router.get("/api/stocks/{symbol}/bars", response_model=list[s.Bar])
def bars(symbol: str, ctx: Ctx, start: Annotated[date | None, Query(alias="from")] = None,
         end: Annotated[date | None, Query(alias="to")] = None) -> list[s.Bar]:
    last = services.latest_bar_date(ctx.parquet_root)
    if last is None:
        return []
    stop = end or last
    return services.stock_bars(ctx.parquet_root, ctx.cfg, symbol,
                               start or stop - timedelta(days=400), stop)


@router.get("/api/briefs", response_model=list[s.BriefListItem])
def briefs(conn: Conn) -> list[s.BriefListItem]:
    return services.list_briefs(conn)


@router.get("/api/briefs/{day}", response_model=s.Brief)
def brief(day: str, conn: Conn) -> s.Brief:
    return services.get_brief(conn, _day(day))


@router.post("/api/briefs/{day}/generate", response_model=s.Brief)
def generate_brief(day: str, conn: Conn, force: bool = False) -> s.Brief:
    """Queue an evening review for a day.

    The only thing this writes is a row in ``ai_requests``; ``stk ai worker`` does the work.
    The API cannot call a model -- an import-linter contract keeps ``stk.ai`` out of
    ``stk.api`` -- and this route is what makes that restriction bearable rather than a dead
    end. Idempotent: a day already queued or running is returned as-is, not queued twice.
    """
    return services.request_brief(conn, _day(day), force=force)


def create_app(*, sqlite_path: Path, parquet_root: Path, cfg: BacktestConfig | None = None
               ) -> FastAPI:
    app = FastAPI(title="stk", docs_url="/api/docs", openapi_url="/api/openapi.json")
    resolved = cfg or load_backtest_config()
    app.state.ctx = ApiContext(sqlite_path, parquet_root, resolved)
    app.state.play_ctx = PlayCtx(parquet_root, resolved, make_rates_fn())
    app.include_router(open_router)
    app.include_router(router)
    app.include_router(playground_routes.router)
    return app


def openapi_document() -> str:
    """The OpenAPI JSON, deterministic, with no database or lake needed to produce it."""
    import json  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(sqlite_path=Path(tmp) / "x.db", parquet_root=Path(tmp),
                         cfg=load_backtest_config())
        return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
