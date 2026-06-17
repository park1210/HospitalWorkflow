from typing import Optional

from app.config import settings

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class OllamaClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.client = None
        if OpenAI is not None:
            self.client = OpenAI(
                base_url=base_url or settings.OLLAMA_BASE_URL,
                api_key=api_key or settings.OLLAMA_API_KEY,
            )

    def chat(self, system_prompt: str, user_prompt: str, model: Optional[str] = None) -> str:
        if self.client is None:
            raise RuntimeError("OpenAI package is not installed. Falling back to rule-based agent behavior.")

        response = self.client.chat.completions.create(
            model=model or settings.OLLAMA_MODEL,
            temperature=settings.TEMPERATURE,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""
