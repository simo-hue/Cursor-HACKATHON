"""Al Dente Company Brain backend entry point."""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.graph import GraphBuilder
from app.orchestrator import Orchestrator
from app.schemas import AskRequest, AskResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_STATIC = Path(__file__).resolve().parent / "static"
_FILES = _STATIC / "files"
_FILES.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Al Dente Company Brain", version="1.0.0")
app.mount("/files", StaticFiles(directory=_FILES), name="files")
app.mount("/static", StaticFiles(directory=_STATIC), name="static")
orchestrator = Orchestrator()
graph_builder = GraphBuilder(
    orchestrator.api,
    orchestrator.kb,
    orchestrator.graph_cache,
)


@app.exception_handler(RequestValidationError)
def validation_error(_request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content=AskResponse(
            answer="Not available: the request must contain a non-empty string field named 'question'.",
            sources=[],
            verticale="crm",
            artifact_url=None,
        ).model_dump(),
    )


@app.get("/", include_in_schema=False)
def ui() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    try:
        return orchestrator.answer(request.question)
    except Exception:
        logger.exception("Unhandled /ask failure")
        return AskResponse(
            answer=(
                "I could not answer reliably because an internal error occurred "
                "while checking the available Al Dente sources."
            ),
            sources=[],
            verticale="crm",
            artifact_url=None,
        )


@app.get("/graph-data")
def graph_data() -> dict:
    try:
        return graph_builder.build()
    except Exception:
        logger.exception("Graph construction failed")
        return {
            "nodes": [],
            "edges": [],
            "warnings": ["The knowledge graph could not be built from the available sources."],
        }
