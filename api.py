from __future__ import annotations

import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from livekit.api import (
    AccessToken,
    RoomAgentDispatch,
    RoomConfiguration,
    VideoGrants,
)
from pydantic import BaseModel

load_dotenv(".env.local")

AGENT_NAME = "inventory-assistant"

app = FastAPI(title="Voice Inventory Connection API")

# Open for now (demo stage, no frontend origin locked in yet) - tighten to a
# specific origin once a real frontend exists.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConnectionDetails(BaseModel):
    serverUrl: str
    roomName: str
    participantName: str
    participantToken: str


@app.get("/token", response_model=ConnectionDetails)
def create_token(participant_name: str | None = None) -> ConnectionDetails:
    """Mint a LiveKit access token for a fresh room, with the inventory
    assistant agent dispatched into it. A frontend calls this once per
    session, then joins the returned room with any LiveKit client SDK -
    the same flow the LiveKit Playground uses under the hood."""
    room_name = f"inventory-{uuid.uuid4().hex[:12]}"
    identity = participant_name or f"user-{uuid.uuid4().hex[:8]}"

    token = (
        AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_name(identity)
        .with_grants(VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True))
        .with_room_config(
            RoomConfiguration(agents=[RoomAgentDispatch(agent_name=AGENT_NAME)]),
        )
        .to_jwt()
    )

    return ConnectionDetails(
        serverUrl=os.environ["LIVEKIT_URL"],
        roomName=room_name,
        participantName=identity,
        participantToken=token,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
