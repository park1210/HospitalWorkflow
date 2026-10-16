"""Native Ollama client for bounded CPU-capable offline routing probes."""
import json
from urllib.request import Request, urlopen
from app.llm.role_call import response_usage, response_metadata


class OllamaProbeClient:
    def __init__(self, endpoint, *, cpu=False, timeout=120, max_tokens=192):
        self.endpoint, self.cpu, self.timeout, self.max_tokens = endpoint, cpu, timeout, max_tokens

    def chat_json(self, system, user, model=None, schema=None):
        options = {"temperature": 0, "num_predict": self.max_tokens}
        if self.cpu:
            options["num_gpu"] = 0
        body = {"model": model, "stream": False, "format": schema or "json", "options": options,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        request = Request(self.endpoint.rstrip("/") + "/api/chat", data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=self.timeout) as response:
            result = json.load(response)
        prompt, completion = result.get("prompt_eval_count"), result.get("eval_count")
        if type(prompt) is int and type(completion) is int and min(prompt, completion) >= 0:
            response_usage.set({"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion})
        content = result["message"]["content"]
        response_metadata.set({"finish_reason": result.get("done_reason"), "output_characters": len(content)})
        return content
