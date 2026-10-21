"""One bounded model request with explicit provenance; no hidden rule fallback."""
import hashlib
import json
import time
from contextvars import ContextVar
from copy import deepcopy

progress_listener = ContextVar("llm_progress_listener", default=None)
response_usage = ContextVar("llm_response_usage", default=None)
response_metadata = ContextVar("llm_response_metadata", default=None)


class OutputTruncatedError(ValueError):
    pass


class RoleCallError(RuntimeError):
    pass


class ContractValidationError(ValueError):
    """A known output-contract error with bounded, inspectable field details."""
    def __init__(self, message, *, code, field, value):
        super().__init__(message)
        self.details = {"code": code, "field": field, "value_type": type(value).__name__,
                        "value_repr": repr(value)[:240]}


def role_call(client, *, role, model, system, payload, audit, validate=None, schema=None, repair_codes=()):
    """At most one explicit contract repair; never retry network/timeout failures."""
    try:
        return _role_call_once(client, role=role, model=model, system=system, payload=payload,
                               audit=audit, validate=validate, schema=schema)
    except RoleCallError:
        failed_index = len(audit) - 1
        detail = audit[-1].get("validation_detail", {})
        if detail.get("code") not in repair_codes:
            raise
        repaired_payload = deepcopy(payload)
        repaired_payload["output_contract_repair"] = {
            "error": deepcopy(detail), "message": audit[-1]["validation_error"],
            "instruction": "The previous output was rejected. Return a complete new JSON response following the original contract. Use only the original observations; do not invent facts or confirmation. This is the only correction attempt."}
        audit[-1]["repair_requested"] = True
        retry_index = len(audit)
        try:
            result = _role_call_once(client, role=role, model=model, system=system,
                                    payload=repaired_payload, audit=audit, validate=validate, schema=schema)
            audit[failed_index]["repaired_by_audit_index"] = retry_index
            return result
        finally:
            if len(audit) > retry_index:
                audit[retry_index]["repair_of_audit_index"] = failed_index


def _role_call_once(client, *, role, model, system, payload, audit, validate=None, schema=None):
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
    response = None
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
            if response is not None:
                row["invalid_response"] = response[:4096]
                row["invalid_response_truncated"] = len(response) > 4096
                row["response_sha256"] = hashlib.sha256(response.encode()).hexdigest()
            if isinstance(exc, ContractValidationError):
                row["validation_detail"] = deepcopy(exc.details)
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
