"""One bounded model request with explicit provenance; no hidden rule fallback."""
import hashlib
import json
import time
from contextvars import ContextVar

progress_listener = ContextVar("llm_progress_listener", default=None)
response_usage = ContextVar("llm_response_usage", default=None)
response_metadata = ContextVar("llm_response_metadata", default=None)


class OutputTruncatedError(ValueError):
    pass


class RoleCallError(RuntimeError):
    pass


def role_call(client, *, role, model, system, payload, audit, validate=None, schema=None):
    prompt = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    row = {"role": role, "model": model, "backend": type(client).__name__, "status": "started", "fallback_used": False,
           "input_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
    audit.append(row)
    listener = progress_listener.get()
    if listener:
        listener({"role": role, "model": model, "status": "started"})
    started = time.monotonic()
    usage_token = response_usage.set(None)
    metadata_token = response_metadata.set(None)
    try:
        if validate and callable(getattr(type(client), "chat_json", None)):
            response = client.chat_json(system, prompt, model=model, schema=schema).strip()
        else:
            response = client.chat(system, prompt, model=model).strip()
        if (response_metadata.get() or {}).get("finish_reason") == "length":
            raise OutputTruncatedError("Model output reached its token limit before completion")
        if not response:
            raise ValueError("Empty model response")
        value = validate(response) if validate else response
        row["status"] = "success"
        return value
    except Exception as exc:
        row.update(status="error", error_type=type(exc).__name__)
        row["failure_category"] = ("output_truncated" if isinstance(exc, OutputTruncatedError)
            else "invalid_json" if isinstance(exc, json.JSONDecodeError)
            else "schema_validation" if isinstance(exc, ValueError)
            else "timeout" if "timeout" in type(exc).__name__.casefold() else "model_call_error")
        if isinstance(exc, ValueError):
            row["validation_error"] = str(exc)[:240]
        # Do not put server URLs, keys, or raw SDK exceptions in public reports.
        raise RoleCallError(f"{role} model call failed ({type(exc).__name__}); see llm_audit") from exc
    finally:
        usage = response_usage.get()
        row["usage"] = usage
        row["usage_status"] = "reported" if usage is not None else "unavailable"
        response_usage.reset(usage_token)
        row["response_metadata"] = response_metadata.get()
        response_metadata.reset(metadata_token)
        row["latency_seconds"] = round(time.monotonic() - started, 4)
        if listener:
            listener({"role": role, "model": model, "status": row["status"]})
