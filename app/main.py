"""Main FastAPI application for CUCM Live Monitor."""

import logging
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from .config import settings
from .background import BackgroundPoller
from .models import ConnectionStatus
from pydantic import BaseModel
import os

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


# Pydantic models for settings
class CUCMSettings(BaseModel):
    cucm_host: str
    cucm_username: str
    cucm_password: str
    poll_interval: int = 5


# Initialize background poller
poller = BackgroundPoller(poll_interval=settings.poll_interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.

    Args:
        app: FastAPI application instance.
    """
    # Startup
    logger.info("Starting CUCM Live Monitor...")
    logger.info(f"Connecting to CUCM: {settings.cucm_host}")
    await poller.start()

    yield

    # Shutdown
    logger.info("Shutting down CUCM Live Monitor...")
    await poller.stop()


# Create FastAPI app
app = FastAPI(
    title="CUCM Live Monitor",
    description="Real-time call monitoring for Cisco CUCM",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """
    Serve the main dashboard HTML page.

    Returns:
        HTMLResponse: Dashboard HTML content.
    """
    html_file = static_dir / "index.html"
    with open(html_file, "r") as f:
        return HTMLResponse(content=f.read())


@app.get("/settings", response_class=HTMLResponse)
async def get_settings_page():
    """
    Serve the settings page.

    Returns:
        HTMLResponse: Settings page HTML content.
    """
    html_file = static_dir / "settings.html"
    with open(html_file, "r") as f:
        return HTMLResponse(content=f.read())


@app.get("/health")
async def health_check():
    """
    Health check endpoint.

    Returns:
        dict: Health status.
    """
    return {"status": "healthy", "cucm_host": settings.cucm_host}


@app.get("/api/status")
async def get_status():
    """
    Get current cluster status (REST endpoint).

    Returns:
        JSONResponse: Current status or error.
    """
    status = poller.get_current_status()

    if status:
        return JSONResponse(content=status.model_dump(mode='json'))
    else:
        connection_status = poller.get_connection_status()
        return JSONResponse(
            status_code=503,
            content={
                "error": "Not connected to CUCM",
                "connection_status": connection_status,
            },
        )


@app.get("/api/connection")
async def get_connection():
    """
    Get connection status.

    Returns:
        dict: Connection status information.
    """
    return poller.get_connection_status()


@app.get("/api/settings")
async def get_settings():
    """
    Get current CUCM settings (password masked).

    Returns:
        dict: Current settings with masked password.
    """
    return {
        "cucm_host": settings.cucm_host,
        "cucm_username": settings.cucm_username,
        "cucm_password": "********" if settings.cucm_password else "",
        "poll_interval": settings.poll_interval,
    }


@app.post("/api/settings")
async def update_settings(new_settings: CUCMSettings):
    """
    Update CUCM settings and reconnect.

    Args:
        new_settings: New CUCM configuration.

    Returns:
        dict: Success message or error.
    """
    try:
        # Update environment variables
        os.environ["CUCM_HOST"] = new_settings.cucm_host
        os.environ["CUCM_USERNAME"] = new_settings.cucm_username
        os.environ["CUCM_PASSWORD"] = new_settings.cucm_password
        os.environ["POLL_INTERVAL"] = str(new_settings.poll_interval)

        # Update settings object
        settings.cucm_host = new_settings.cucm_host
        settings.cucm_username = new_settings.cucm_username
        settings.cucm_password = new_settings.cucm_password
        settings.poll_interval = new_settings.poll_interval

        # Update .env file for persistence
        env_path = Path("/app/.env")
        if env_path.exists():
            with open(env_path, "r") as f:
                lines = f.readlines()

            # Update or add settings
            settings_map = {
                "CUCM_HOST": new_settings.cucm_host,
                "CUCM_USERNAME": new_settings.cucm_username,
                "CUCM_PASSWORD": new_settings.cucm_password,
                "POLL_INTERVAL": str(new_settings.poll_interval),
            }

            updated_lines = []
            updated_keys = set()

            for line in lines:
                key = line.split("=")[0].strip()
                if key in settings_map:
                    updated_lines.append(f"{key}={settings_map[key]}\n")
                    updated_keys.add(key)
                else:
                    updated_lines.append(line)

            # Add any missing keys
            for key, value in settings_map.items():
                if key not in updated_keys:
                    updated_lines.append(f"{key}={value}\n")

            with open(env_path, "w") as f:
                f.writelines(updated_lines)

        # Restart poller with new settings
        await poller.stop()
        poller.ris_client.cucm_host = new_settings.cucm_host
        poller.ris_client.username = new_settings.cucm_username
        poller.ris_client.password = new_settings.cucm_password
        poller.poll_interval = new_settings.poll_interval
        await poller.start()

        logger.info(f"Settings updated - new CUCM host: {new_settings.cucm_host}")

        return {
            "success": True,
            "message": "Settings updated successfully. Reconnecting to CUCM...",
        }

    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": str(e)},
        )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.

    Args:
        websocket: WebSocket connection.
    """
    await websocket.accept()
    logger.info("WebSocket client connected")

    # Add client to poller
    poller.add_websocket_client(websocket)

    try:
        # Send initial status if available
        current_status = poller.get_current_status()
        if current_status:
            await websocket.send_text(current_status.model_dump_json())

        # Keep connection alive and handle incoming messages
        while True:
            # Wait for messages from client (ping/pong for keep-alive)
            data = await websocket.receive_text()
            logger.debug(f"Received from client: {data}")

            # Handle client requests
            if data == "ping":
                await websocket.send_text("pong")
            elif data == "status":
                status = poller.get_current_status()
                if status:
                    await websocket.send_text(status.model_dump_json())

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Remove client from poller
        poller.remove_websocket_client(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level=settings.log_level.lower(),
    )
