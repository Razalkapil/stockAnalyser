"""web/openapi.json is what the frontend's TypeScript types are generated from. If the API
changes and this file does not, the UI would be compiled against a contract that no longer
exists -- so a stale copy fails the build."""

from __future__ import annotations

from pathlib import Path

from stk.api.app import openapi_document

COMMITTED = Path(__file__).parent.parent.parent / "web" / "openapi.json"


def test_committed_openapi_matches_the_api():
    assert COMMITTED.read_text() == openapi_document(), (
        "web/openapi.json is stale. Regenerate: `uv run stk api openapi --out web/openapi.json` "
        "then `cd web && npm run gen:api` and commit both (plus src/lib/api/schema.d.ts)."
    )
