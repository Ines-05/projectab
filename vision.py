from __future__ import annotations

import logging
import os
from functools import lru_cache

from google import genai
from google.genai import types

logger = logging.getLogger("speech.vision")

IDENTIFY_PROMPT = (
    "Identify this single retail product by name and brand. "
    "Respond with only the product name, no extra commentary."
)


class VisionIdentifyError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    return genai.Client(api_key=os.environ["GOOGLE_API_KEY"])


def identify_product_from_image(image_bytes: bytes) -> str:
    """One-shot Gemini call — deliberately NOT the ongoing realtime session/transcript."""
    logger.info("identify_product_from_image: calling gemini-2.5-flash with %d bytes", len(image_bytes))
    response = _client().models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            IDENTIFY_PROMPT,
        ],
    )
    logger.info("identify_product_from_image: raw response.text = %r", response.text)
    text = (response.text or "").strip()
    if not text:
        raise VisionIdentifyError("the vision model returned an empty description")
    return text
