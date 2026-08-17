from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, room_io
from livekit.plugins import google

from alerts import AlertMonitor
from tools import INSTRUCTIONS, InventoryAssistant
from video import FrameBuffer

load_dotenv(".env.local")

# Explicit, rather than relying on whatever level the livekit-agents CLI
# happens to configure - ensures our own speech.* loggers (tools.py,
# vision.py, alerts.py) are always visible regardless of CLI flags.
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("speech.agent")

server = AgentServer()


@server.rtc_session(agent_name="inventory-assistant")
async def inventory_assistant_session(ctx: agents.JobContext) -> None:
    frame_buffer = FrameBuffer()

    def _on_track_subscribed(track: rtc.Track, publication, participant) -> None:
        if track.kind == rtc.TrackKind.KIND_VIDEO:
            frame_buffer.attach(track)

    ctx.room.on("track_subscribed", _on_track_subscribed)

    # Attach to a video track that was already published before we joined.
    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            if publication.track is not None and publication.track.kind == rtc.TrackKind.KIND_VIDEO:
                frame_buffer.attach(publication.track)

    session = AgentSession(
        llm=google.realtime.RealtimeModel(
            voice="Puck",
            instructions=INSTRUCTIONS,
            temperature=0.7,
            modalities=["AUDIO"],
        )
    )

    # video_input intentionally disabled - frames are captured on-demand only,
    # inside InventoryAssistant.identify_product(), never streamed continuously
    # into the realtime model.
    await session.start(
        room=ctx.room,
        agent=InventoryAssistant(frame_buffer, ctx.room),
        room_options=room_io.RoomOptions(video_input=False),
    )

    alert_monitor = AlertMonitor(session)
    alert_monitor.start()

    async def _on_shutdown() -> None:
        frame_buffer.close()
        await alert_monitor.stop()

    ctx.add_shutdown_callback(_on_shutdown)

    # Defensive fallback: if the shutdown-callback path doesn't fire for some
    # reason, this ensures the poll task still gets cancelled on session close
    # rather than leaking. stop() is idempotent, so both firing is harmless.
    def _on_session_close(*_args, **_kwargs) -> None:
        try:
            asyncio.get_running_loop().create_task(alert_monitor.stop())
        except Exception:
            logger.exception("fallback alert-monitor stop on session close failed")

    session.on("close", _on_session_close)

    await session.generate_reply(
        instructions=(
            "Greet the user, briefly mention you can identify a product shown "
            "to the camera, check stock or expiration by name, and record a sale."
        )
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
