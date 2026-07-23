from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config.settings import settings
from app.core.logging import setup_logging
from app.middleware.logging_middleware import LoggingMiddleware
from app.api.api import api_router
from loguru import logger

# Initialize logging system using loguru interceptors
setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc",
)

# Configure request tracking logging middleware
app.add_middleware(LoggingMiddleware)

# Configure Cross-Origin Resource Sharing (CORS)
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Include application route aggregates
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["healthcheck"])
def healthcheck() -> dict:
    """Basic healthcheck endpoint to verify FastAPI online status."""
    return {"status": "ok", "project": settings.PROJECT_NAME}


if __name__ == "__main__":
    import uvicorn

    logger.info("Booting Uvicorn backend dev-server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
