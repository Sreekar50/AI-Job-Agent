"""
WebSocket Routes — Real-time HITL notifications and agent status updates.

Clients connect to /ws/agent to receive:
- hitl_request: A field needs human input (30s countdown)
- hitl_timeout: The HITL window expired
- job_update: Status change on a job

Clients send:
- {"type": "hitl_answer", "job_id": "...", "answer": "..."}
"""
import asyncio
import json
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from backend.utils.hitl_manager import hitl_manager

router = APIRouter()

# All connected WebSocket clients
_connected_clients: Set[WebSocket] = set()


async def broadcast(payload: dict):
    """Send a message to all connected WebSocket clients."""
    message = json.dumps(payload)
    dead = set()
    for ws in list(_connected_clients):
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    for ws in dead:
        _connected_clients.discard(ws)


# Inject broadcaster into HITL manager
hitl_manager.set_broadcaster(broadcast)


@router.websocket("/agent")
async def agent_ws(websocket: WebSocket):
    await websocket.accept()
    _connected_clients.add(websocket)
    logger.info(f"WebSocket client connected. Total: {len(_connected_clients)}")

    # Send any currently pending HITL requests
    pending = hitl_manager.get_all_pending()
    if pending:
        await websocket.send_text(json.dumps({
            "type": "pending_hitl",
            "requests": pending,
        }))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "message": "Invalid JSON"}))
                continue

            msg_type = data.get("type")

            if msg_type == "hitl_answer":
                job_id = data.get("job_id")
                answer = data.get("answer", "")
                success = hitl_manager.submit_answer(job_id, answer)
                await websocket.send_text(json.dumps({
                    "type": "hitl_answer_ack",
                    "job_id": job_id,
                    "success": success,
                }))

            elif msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

            elif msg_type == "list_pending":
                pending = hitl_manager.get_all_pending()
                await websocket.send_text(json.dumps({
                    "type": "pending_hitl",
                    "requests": pending,
                }))

            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                }))

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        _connected_clients.discard(websocket)
