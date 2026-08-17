from __future__ import annotations

import asyncio
import logging
import os

from livekit import rtc
from livekit.agents import Agent, RunContext, function_tool
from livekit.agents.llm import ToolError
from livekit.agents.utils.images import EncodeOptions, ResizeOptions, encode

import db
import nl2sql
import vision
from video import FrameBuffer

logger = logging.getLogger("speech.tools")

MATCH_THRESHOLD = float(os.getenv("PRODUCT_MATCH_THRESHOLD", "0.3"))
AMBIGUITY_MARGIN = float(os.getenv("PRODUCT_MATCH_AMBIGUITY_MARGIN", "0.05"))

# Topic the mobile client listens on to know when to turn its camera on -
# see speech/mobile/src/ConnectionScreen.tsx's useDataChannel call. The
# camera is off by default (mic-only UI); this is the only trigger that
# turns it on, folded into identify_product rather than a separate voice
# command, so "what is this" does both in one step.
CAMERA_CONTROL_TOPIC = "camera-control"
CAMERA_WARMUP_TIMEOUT_SECONDS = 3.0
CAMERA_WARMUP_POLL_INTERVAL_SECONDS = 0.2

INSTRUCTIONS = (
    "You are a friendly, concise voice assistant helping a blind retail-store "
    "staff member manage shelf inventory entirely by voice. Never ask the user "
    "to look at a screen. When you report stock or expiration, speak the "
    "matched product's full name once so the user knows what was found, then "
    "answer their question plainly."
)


class InventoryAssistant(Agent):
    def __init__(self, frame_buffer: FrameBuffer, room: rtc.Room) -> None:
        super().__init__(instructions=INSTRUCTIONS)
        self._frames = frame_buffer
        self._room = room

    def _resolve_single_match(self, search_term: str) -> db.ProductMatch:
        matches = db.match_product(search_term, threshold=MATCH_THRESHOLD)
        logger.info(
            "match_product(%r) -> %s",
            search_term,
            [(m["name"], round(m["similarity"], 3)) for m in matches],
        )
        if not matches:
            raise ToolError(
                f"I couldn't find any product matching '{search_term}' in the inventory."
            )
        if len(matches) > 1 and (matches[0]["similarity"] - matches[1]["similarity"]) < AMBIGUITY_MARGIN:
            names = ", ".join(m["name"] for m in matches[:3])
            raise ToolError(
                f"I found more than one close match for '{search_term}': {names}. "
                "Could you say the product name more precisely?"
            )
        return matches[0]

    @function_tool()
    async def identify_product(self, context: RunContext) -> dict:
        """Identify the retail product the user is currently showing to the camera.
        Use this when the user asks what they are holding or looking at, e.g.
        "what is this", "what am I holding", "what product is this".
        Captures the latest camera frame, asks a vision model for a plain-text
        description, matches it against the store inventory, and returns its
        current stock and expiration. The user's camera is off by default and
        turns on automatically the first time this is called - there is no
        separate "turn on the camera" step for the user to do.
        """
        if self._frames.latest_frame is None:
            await self._room.local_participant.publish_data(
                "enable_camera", topic=CAMERA_CONTROL_TOPIC
            )
            elapsed = 0.0
            while self._frames.latest_frame is None and elapsed < CAMERA_WARMUP_TIMEOUT_SECONDS:
                await asyncio.sleep(CAMERA_WARMUP_POLL_INTERVAL_SECONDS)
                elapsed += CAMERA_WARMUP_POLL_INTERVAL_SECONDS

        frame = self._frames.latest_frame
        if frame is None:
            raise ToolError(
                "I couldn't access the camera just now. Please check the app "
                "has camera permission and try again."
            )
        logger.info("identify_product: captured frame %sx%s", frame.width, frame.height)

        image_bytes = encode(
            frame,
            EncodeOptions(
                format="JPEG",
                resize_options=ResizeOptions(width=512, height=512, strategy="scale_aspect_fit"),
            ),
        )
        logger.info("identify_product: encoded JPEG, %d bytes", len(image_bytes))

        try:
            description = await asyncio.to_thread(vision.identify_product_from_image, image_bytes)
        except vision.VisionIdentifyError as exc:
            logger.warning("identify_product: vision model call failed: %s", exc)
            raise ToolError(f"I couldn't make out the product in the image: {exc}") from exc
        logger.info("identify_product: vision model description: %r", description)

        match = self._resolve_single_match(description)
        return {
            "matched_name": match["name"],
            "category": match["category"],
            "stock_quantity": match["stock_quantity"],
            "expiration_date": match["expiration_date"],
        }

    @function_tool()
    async def get_product_stock(self, context: RunContext, product_name: str) -> dict:
        """Look up the current stock quantity and expiration date of a product by name.
        Args:
            product_name: The product name or description as spoken by the user,
                e.g. "Coca-Cola" or "the Snickers bar".
        """
        match = self._resolve_single_match(product_name)
        return {
            "matched_name": match["name"],
            "category": match["category"],
            "stock_quantity": match["stock_quantity"],
            "expiration_date": match["expiration_date"],
        }

    @function_tool()
    async def record_sale(self, context: RunContext, product_name: str, quantity: int) -> dict:
        """Record the sale of a product and decrement its stock accordingly.
        Args:
            product_name: The product name or description as spoken by the user.
            quantity: The number of units sold. Must be a positive whole number.
        """
        if quantity <= 0:
            raise ToolError("The quantity sold must be a positive whole number.")

        match = self._resolve_single_match(product_name)
        try:
            result = db.record_sale(match["id"], quantity)
        except db.InsufficientStockError as exc:
            raise ToolError(str(exc)) from exc
        except db.ProductNotFoundError as exc:
            raise ToolError(str(exc)) from exc
        except db.DbError as exc:
            logger.exception("record_sale failed unexpectedly")
            raise ToolError("Something went wrong recording that sale, please try again.") from exc

        return {"matched_name": result["name"], "remaining_stock": result["stock_quantity"]}

    @function_tool()
    async def query_inventory(self, context: RunContext, question: str) -> dict:
        """Answer an open-ended inventory question that isn't a single-product
        lookup or a sale, e.g. counts, aggregates, or "which products..."
        questions ("how many products are low on stock", "what expires this
        month", "what did we sell this week").
        Args:
            question: The user's question, as spoken, in natural language.
        """
        try:
            sql = await asyncio.to_thread(nl2sql.translate_to_sql, question)
        except nl2sql.Nl2SqlError as exc:
            raise ToolError(f"I couldn't figure out how to look that up: {exc}") from exc

        if not nl2sql.is_safe_select(sql):
            raise ToolError(
                "I can only answer that kind of question with a lookup, not a "
                "change to the data, so I can't run that one."
            )

        try:
            rows = await asyncio.to_thread(db.execute_readonly_query, sql)
        except db.DbError as exc:
            raise ToolError(f"I couldn't complete that lookup: {exc}") from exc

        return {"rows": rows}
