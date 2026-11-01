"""Market Scanner UI: FastAPI server-rendered shell with vanilla JS SPA."""

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from ui.app import api

app = FastAPI(title="Market Scanner UI", docs_url=None, redoc_url=None, openapi_url=None)

# Mount static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include API routes
app.include_router(api.router, prefix="/api")

# Health check
@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}

# Serve index.html for all non-API routes (SPA mode)
@app.get("/")
@app.get("/{path:path}")
async def serve_spa(path: str = ""):
    """Serve the SPA index.html for all non-API routes."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    # Fallback if static files not mounted
    return {"error": "UI not found"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )
