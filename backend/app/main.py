from fastapi import FastAPI, HTTPException

from app.api.routes.accounts import router as accounts_router
from app.infrastructure.database.session import check_database_connection


app = FastAPI(
    title="XAU Trading Platform API",
    description="Backend API for the XAU trading platform.",
    version="0.1.0",
)

app.include_router(accounts_router)


@app.get("/health/live", tags=["Health"])
async def liveness_check():
    return {"status": "alive"}


@app.get("/health", tags=["Health"])
async def health_check():
    if not await check_database_connection():
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        )

    return {
        "status": "ok",
        "application": "XAU Trading Platform",
        "version": "0.1.0",
        "database": "connected",
    }


@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "Welcome to XAU Trading Platform API",
        "docs": "/docs",
    }
