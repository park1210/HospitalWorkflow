from typing import Optional

from app.config import settings
from app.llm.role_call import response_usage, response_metadata

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
                timeout=settings.LLM_TIMEOUT_SECONDS,
                max_retries=0,
            )

    def chat_json(self, system_prompt: str, user_prompt: str, model: Optional[str] = None, *, schema=None) -> str:
        return self.chat(system_prompt, user_prompt, model=model, json_mode=True, json_schema=schema)

    def chat(self, system_prompt: str, user_prompt: str, model: Optional[str] = None, *, json_mode: bool = False, json_schema=None) -> str:
        if self.client is None:
            raise RuntimeError("OpenAI package is not installed. Falling back to rule-based agent behavior.")

        options = {"response_format": {"type": "json_object"}} if json_mode else {}
        if json_schema:
            options = {"response_format": {"type": "json_schema", "json_schema": {
                "name": "clinical_decision", "strict": True, "schema": json_schema}}}
        response = self.client.chat.completions.create(
            model=model or settings.OLLAMA_MODEL,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            **options,
        )
        usage = getattr(response, "usage", None)
        if usage is not None:
            values = {key: getattr(usage, key, None) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
            if all(type(v) is int and v >= 0 for v in values.values()):
                response_usage.set(values)
        choice = response.choices[0]
        content = choice.message.content or ""
        response_metadata.set({"finish_reason": getattr(choice, "finish_reason", None),
                               "output_characters": len(content)})
        return content
