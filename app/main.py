import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .database import Base, SessionLocal, engine
from .errors import AppError, envelope
from .logging_config import configure_logging
from .routers import patients, vapi_tools
from .seed import seed_if_empty

configure_logging()
logger = logging.getLogger("app.main")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    logger.info("app_startup_complete")
    yield


app = FastAPI(
    title="Patient Registration API",
    description="Backend for the Voice AI patient-registration agent (Vapi tool-calls + REST API).",
    version="1.0.0",
    lifespan=lifespan,
)

# Dashboard is a static page fetching this same API from the browser; open CORS
# is fine here since there is no auth/session state to protect in this demo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(data=None, error={"message": exc.message, "details": exc.details}),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=envelope(data=None, error={"message": "Validation failed", "details": errors}),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("unhandled_error")
    return JSONResponse(
        status_code=500,
        content=envelope(data=None, error={"message": "Internal server error"}),
    )


app.include_router(patients.router)
app.include_router(vapi_tools.router)


@app.get("/")
async def root():
    return envelope(data={"service": "patient-registration-api", "status": "ok", "dashboard": "/dashboard"})


@app.get("/health")
async def health():
    return envelope(data={"status": "ok"})


@app.get("/dashboard")
async def dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html")
