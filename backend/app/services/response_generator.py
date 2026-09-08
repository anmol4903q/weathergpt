"""
Phase 5G — Gemini's grounded-answer call.

Gemini is NOT the weather-data source here. It only phrases an answer
using the structured context we hand it, under an explicit system
instruction not to invent facts and not to conflate "couldn't check" with
"confirmed clear".
"""

import json

from google import genai
from google.genai import types

_SYSTEM_INSTRUCTION = (
    "You are WeatherGPT's assistant. You will be given a user's question and "
    "a JSON block of verified weather facts. Follow these rules strictly:\n"
    "- Use only the facts in the JSON. Never invent temperature, rainfall, "
    "probability, timing, or warnings.\n"
    "- The JSON's official_alerts_status field distinguishes 'ok' (an "
    "official alert was matched), 'no_active_warning' (checked, nothing "
    "found), and 'unavailable' (could not be checked at all). NEVER say "
    "'there is no warning' when the status is 'unavailable' — say the "
    "official warning data could not be checked right now.\n"
    "- Clearly distinguish official IMD alerts (state this is from IMD) "
    "from your own interpretation of the weather figures.\n"
    "- If a value needed to answer is missing or marked unavailable, say so "
    "plainly instead of guessing.\n"
    "- Be concise and in plain language for a general user, not a "
    "meteorologist.\n"
    "- Answer the user's actual question — do not dump all supplied data.\n"
    "- Mention an official IMD alert if one is present and relevant.\n"
    "- Keep the stated location and time period consistent with what was "
    "supplied in the JSON."
)


class ResponseGenerationError(Exception):
    """Gemini's answer call itself failed (network/auth/rate-limit)."""


async def generate_answer(question: str, context: dict, api_key: str, model: str) -> str:
    client = genai.Client(api_key=api_key)
    prompt = f"User question: {question}\n\nVerified weather context (JSON):\n{json.dumps(context, default=str)}"

    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=_SYSTEM_INSTRUCTION),
        )
    except Exception as exc:
        raise ResponseGenerationError(f"Gemini answer generation failed: {exc}")

    if not response.text:
        raise ResponseGenerationError("Gemini returned an empty answer")

    return response.text.strip()
