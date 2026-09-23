"""
Phase 5G — the AI's grounded-answer call.

Provider: Groq (migrated from Gemini). The AI is NOT the weather-data
source here. It only phrases an answer using the structured context we
hand it, under an explicit system instruction not to invent facts and
not to conflate "couldn't check" with "confirmed clear".
"""

import json

from groq import AsyncGroq

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
    "from your own interpretation of the weather figures. Never claim "
    "WeatherGPT itself issued an official warning.\n"
    "- If a value needed to answer is missing or marked unavailable, say so "
    "plainly instead of guessing.\n"
    "- Be concise and in plain language for a general user, not a "
    "meteorologist.\n"
    "- Answer the user's actual question — do not dump all supplied data.\n"
    "- Mention an official IMD alert if one is present and relevant. "
    "Official warnings take priority over WeatherGPT's own risk assessment "
    "if the two would otherwise seem to disagree.\n"
    "- Keep the stated location and time period consistent with what was "
    "supplied in the JSON.\n"
    "- The JSON may include a 'weathergpt_risk_assessment' field with a "
    "'level' (LOW/MODERATE/HIGH/UNKNOWN) and 'reasons' list. This is "
    "WeatherGPT's own computed assessment, NOT an official IMD warning — "
    "never call it official. If present, state this risk level and weave "
    "in its reasons naturally; do not invent a different level or perform "
    "your own risk calculation, and do not omit it when it's present and "
    "relevant to the question. If its level is UNKNOWN, say the risk "
    "couldn't be assessed rather than guessing a level yourself."
)


class ResponseGenerationError(Exception):
    """Groq's answer call itself failed (network/auth/rate-limit)."""


async def generate_answer(question: str, context: dict, api_key: str, model: str) -> str:
    client = AsyncGroq(api_key=api_key)
    prompt = f"User question: {question}\n\nVerified weather context (JSON):\n{json.dumps(context, default=str)}"

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        raise ResponseGenerationError(f"Groq answer generation failed: {exc}")

    content = response.choices[0].message.content if response.choices else None
    if not content:
        raise ResponseGenerationError("Groq returned an empty answer")

    return content.strip()
