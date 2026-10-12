"""REST API (FastAPI): ``uvicorn ecoops.api:app``.

Read-only by design — there are no endpoints that change infrastructure.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query

from . import __version__
from .generator import generate
from .ingest import load_csv_dir
from .pipeline import AnalysisResult, run
from .settings import load_settings
from .utils import to_jsonable


def create_app(seed: int = 42, data_dir: str | None = None, config_dir: str | None = None) -> FastAPI:
    settings = load_settings(config_dir)
    data = load_csv_dir(data_dir) if data_dir else generate(seed)
    result: AnalysisResult = run(data, settings)

    app = FastAPI(title="EcoOps Navigator API", version=__version__,
                  description="Read-only decision-support API. It never changes infrastructure.")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, "opportunities": len(result.opportunities)}

    @app.get("/summary")
    def summary() -> dict:
        return to_jsonable(result.summary)

    @app.get("/opportunities")
    def opportunities(domain: str | None = Query(None, pattern="^(digital|physical)$"),
                      status: str | None = Query(None, pattern="^(clear|conditional|blocked)$"),
                      min_score: float = 0.0) -> list[dict]:
        items = [o for o in result.opportunities
                 if (domain is None or o.domain == domain)
                 and (status is None or o.constraint_status == status)
                 and o.score >= min_score]
        return to_jsonable([o.to_row() for o in items])

    @app.get("/opportunities/{opp_id}")
    def opportunity(opp_id: str) -> dict:
        o = result.get(opp_id)
        if o is None:
            raise HTTPException(status_code=404, detail=f"Unknown opportunity {opp_id}")
        return to_jsonable(o.to_dict())

    @app.get("/pathways")
    def pathways() -> list[dict]:
        return to_jsonable([p.to_dict() for p in result.pathways])

    @app.get("/footprint")
    def footprint() -> list[dict]:
        return to_jsonable(result.footprint.to_dict("records"))

    @app.get("/assumptions")
    def assumptions() -> dict:
        return {"register": result.assumption_register, "data_issues": result.data_issues}

    return app


app = create_app(seed=int(os.environ.get("ECOOPS_SEED", "42")), data_dir=os.environ.get("ECOOPS_DATA_DIR"))
