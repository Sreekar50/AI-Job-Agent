"""
Terminal HITL Client

Connect to the agent's WebSocket and respond to human-in-the-loop requests
from the terminal. Shows a 30-second countdown.

Usage: python scripts/hitl_client.py [ws_url]
"""
import asyncio
import json
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets
from loguru import logger


WS_URL = "ws://localhost:8000/ws/agent"


def countdown(seconds: int, label: str):
    """Print a visible countdown timer."""
    for i in range(seconds, 0, -1):
        print(f"\r  ⏰ [{label}] — {i}s remaining...  ", end="", flush=True)
        time.sleep(1)
    print()


async def handle_hitl_request(ws, request: dict):
    """Handle an incoming HITL request interactively."""
    print("\n" + "=" * 60)
    print("🚨  HUMAN INPUT REQUIRED")
    print("=" * 60)
    print(f"  Job ID:   {request['job_id']}")
    print(f"  Field:    {request['field_label']}")
    print(f"  Type:     {request['field_type']}")
    if request.get("field_options"):
        print(f"  Options:  {', '.join(request['field_options'])}")
    if request.get("context"):
        print(f"\n  Context:\n  {request['context']}")
    print(f"\n  You have {request['timeout_seconds']} seconds to respond.")
    print("-" * 60)

    timeout = request["timeout_seconds"]

    async def get_input():
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: input("  Your answer: ").strip())

    try:
        answer = await asyncio.wait_for(get_input(), timeout=timeout - 1)
    except asyncio.TimeoutError:
        print("\n  ⌛ Timeout — job will move to backlog.")
        return

    if answer:
        payload = json.dumps({
            "type": "hitl_answer",
            "job_id": request["job_id"],
            "answer": answer,
        })
        await ws.send(payload)
        print(f"  ✅ Answer submitted: '{answer}'")
    else:
        print("  ❌ Empty answer — job will move to backlog.")


async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else WS_URL
    print(f"Connecting to agent at {url}...")

    try:
        async with websockets.connect(url) as ws:
            print("✅ Connected! Waiting for HITL requests...\n")
            print("(Press Ctrl+C to disconnect)\n")

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")

                if msg_type == "hitl_request":
                    await handle_hitl_request(ws, msg)

                elif msg_type == "pending_hitl":
                    requests = msg.get("requests", [])
                    if requests:
                        print(f"📋 {len(requests)} pending HITL request(s) found:")
                        for r in requests:
                            await handle_hitl_request(ws, r)

                elif msg_type == "hitl_answer_ack":
                    status = "✅ Accepted" if msg.get("success") else "❌ Failed"
                    print(f"  Answer ack for job {msg.get('job_id')}: {status}")

                elif msg_type == "job_update":
                    print(f"📊 Job update: {msg.get('job_id')} → {msg.get('status')}")

                elif msg_type == "pong":
                    pass  # keepalive

    except KeyboardInterrupt:
        print("\nDisconnected.")
    except Exception as e:
        print(f"Connection error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
