from dataclasses import dataclass
from pathlib import Path
import os


def load_local_env_file() -> None:
    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'").strip()
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env_file()


@dataclass
class Settings:
    PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
    PROMPTS_DIR: Path = PROJECT_ROOT / "prompts"
    RAW_DATA_PATH: Path = Path(os.getenv("RAW_DATA_PATH", str(PROJECT_ROOT / "data" / "raw" / "_medqa.jsonl")))
    PROCESSED_DATA_PATH: Path = PROJECT_ROOT / "data" / "processed" / "cases.jsonl"
    RESULTS_DIR: Path = PROJECT_ROOT / "outputs" / "results"
    TRANSCRIPTS_DIR: Path = PROJECT_ROOT / "outputs" / "transcripts"
    LOGS_DIR: Path = PROJECT_ROOT / "outputs" / "logs"
    TRAJECTORIES_DIR: Path = PROJECT_ROOT / "outputs" / "trajectories"
    WHAT_IF_DIR: Path = PROJECT_ROOT / "outputs" / "what_if"
    DATASETS_DIR: Path = PROJECT_ROOT / "outputs" / "datasets"
    REFLECTIONS_DIR: Path = PROJECT_ROOT / "outputs" / "reflections"
    REPORTS_DIR: Path = PROJECT_ROOT / "outputs" / "reports"
    LEARNED_POLICY_RULES_PATH: Path = Path(
        os.getenv("LEARNED_POLICY_RULES_PATH", str(DATASETS_DIR / "learned_policy_rules.json"))
    )

    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1")
    OLLAMA_API_KEY: str = os.getenv("OLLAMA_API_KEY", "ollama")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
    LLM_MAX_OUTPUT_TOKENS: int = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "768"))
    SPECIALTY_BASE_URL: str = os.getenv("SPECIALTY_BASE_URL", os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434/v1"))
    SPECIALTY_API_KEY: str = os.getenv("SPECIALTY_API_KEY", os.getenv("OLLAMA_API_KEY", "ollama"))
    SPECIALTY_OLLAMA_MODEL: str = os.getenv("SPECIALTY_OLLAMA_MODEL", "qwen2.5:1.5b-instruct")

    MAX_TURNS: int = int(os.getenv("MAX_TURNS", "8"))
    MAX_CASES: int = int(os.getenv("MAX_CASES", "0"))
    USE_PROCESSED_CASES: bool = os.getenv("USE_PROCESSED_CASES", "false").lower() == "true"
    ROTATE_CASES: bool = os.getenv("ROTATE_CASES", "true").lower() == "true"
    INITIAL_CASE_MODE: str = os.getenv("INITIAL_CASE_MODE", "performance").strip().lower()
    DOCTOR_MODE: str = os.getenv("DOCTOR_MODE", "single").strip().lower()
    DOCTOR_COUNT: int = int(os.getenv("DOCTOR_COUNT", "3"))

    TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.2"))
    USE_LLM_FOR_PATIENT_AGENT: bool = os.getenv("USE_LLM_FOR_PATIENT_AGENT", "false").lower() == "true"
    USE_LLM_FOR_INTERVIEW_AGENT: bool = os.getenv("USE_LLM_FOR_INTERVIEW_AGENT", "false").lower() == "true"
    USE_LLM_FOR_SPECIALTY_AGENT: bool = os.getenv("USE_LLM_FOR_SPECIALTY_AGENT", "false").lower() == "true"
    USE_LLM_FOR_SPECIALTY_DEPARTMENT_AGENT: bool = os.getenv("USE_LLM_FOR_SPECIALTY_DEPARTMENT_AGENT", "false").lower() == "true"
    USE_LLM_FOR_ER_DEPARTMENT_AGENT: bool = os.getenv("USE_LLM_FOR_ER_DEPARTMENT_AGENT", "false").lower() == "true"
    USE_LLM_FOR_FINAL_DIAGNOSIS_INTEGRATOR: bool = os.getenv("USE_LLM_FOR_FINAL_DIAGNOSIS_INTEGRATOR", "false").lower() == "true"
    USE_STRUCTURED_REFLECTION: bool = os.getenv("USE_STRUCTURED_REFLECTION", "true").lower() == "true"
    USE_LLM_SELF_REFLECTION: bool = os.getenv("USE_LLM_SELF_REFLECTION", "false").lower() == "true"
    LLM_SELF_REFLECTION_MAX_PER_CASE: int = int(os.getenv("LLM_SELF_REFLECTION_MAX_PER_CASE", "1"))
    OFFLINE_REFLECTION_MAX_TRANSCRIPT_ITEMS: int = int(os.getenv("OFFLINE_REFLECTION_MAX_TRANSCRIPT_ITEMS", "12"))
    OFFLINE_REFLECTION_MAX_FALSE_CASES: int = int(os.getenv("OFFLINE_REFLECTION_MAX_FALSE_CASES", "0"))
    STRUCTURED_REFLECTION_MIN_DEPARTMENT_SCORE: int = int(os.getenv("STRUCTURED_REFLECTION_MIN_DEPARTMENT_SCORE", "2"))
    STRUCTURED_REFLECTION_MIN_DEPARTMENT_MARGIN: int = int(os.getenv("STRUCTURED_REFLECTION_MIN_DEPARTMENT_MARGIN", "1"))
    USE_REFLECTION: bool = os.getenv("USE_REFLECTION", "true").lower() == "true"
    USE_LOW_CONFIDENCE_REFLECTION: bool = os.getenv("USE_LOW_CONFIDENCE_REFLECTION", "false").lower() == "true"
    LOW_CONFIDENCE_REFLECTION_MIN: float = float(os.getenv("LOW_CONFIDENCE_REFLECTION_MIN", "0.55"))
    REFLECTION_CONFIDENCE_THRESHOLD: float = float(os.getenv("REFLECTION_CONFIDENCE_THRESHOLD", "0.75"))
    DEPARTMENT_CONFLICT_MIN_SCORE: int = int(os.getenv("DEPARTMENT_CONFLICT_MIN_SCORE", "3"))
    DEPARTMENT_CONFLICT_MIN_MARGIN: int = int(os.getenv("DEPARTMENT_CONFLICT_MIN_MARGIN", "2"))
    POLICY_MIN_DIAGNOSE_CONFIDENCE: float = float(os.getenv("POLICY_MIN_DIAGNOSE_CONFIDENCE", "0.75"))
    POLICY_HIGH_CONFIDENCE_THRESHOLD: float = float(os.getenv("POLICY_HIGH_CONFIDENCE_THRESHOLD", "0.85"))
    POLICY_CONSULT_MIN_DEPARTMENT_SCORE: int = int(os.getenv("POLICY_CONSULT_MIN_DEPARTMENT_SCORE", "2"))
    POLICY_CONSULT_MIN_DEPARTMENT_MARGIN: int = int(os.getenv("POLICY_CONSULT_MIN_DEPARTMENT_MARGIN", "1"))
    USE_LEARNED_POLICY_RULES: bool = os.getenv("USE_LEARNED_POLICY_RULES", "false").lower() == "true"
    USE_WHAT_IF_SHADOW: bool = os.getenv("USE_WHAT_IF_SHADOW", "true").lower() == "true"
    WHAT_IF_MAX_ALTERNATIVES: int = int(os.getenv("WHAT_IF_MAX_ALTERNATIVES", "3"))
    WHAT_IF_ROUTING_MARGIN_THRESHOLD: float = float(os.getenv("WHAT_IF_ROUTING_MARGIN_THRESHOLD", "1.5"))
    REWARD_DIAGNOSIS_CORRECT: float = float(os.getenv("REWARD_DIAGNOSIS_CORRECT", "6.0"))
    REWARD_DIAGNOSIS_INCORRECT: float = float(os.getenv("REWARD_DIAGNOSIS_INCORRECT", "-6.0"))
    REWARD_DEPARTMENT_CORRECT: float = float(os.getenv("REWARD_DEPARTMENT_CORRECT", "5.0"))
    REWARD_DEPARTMENT_INCORRECT: float = float(os.getenv("REWARD_DEPARTMENT_INCORRECT", "-5.0"))
    REWARD_ER_DECISIVE_BONUS: float = float(os.getenv("REWARD_ER_DECISIVE_BONUS", "3.0"))
    REWARD_DIAGNOSTIC_HANDOFF_COMPLETENESS: float = float(os.getenv("REWARD_DIAGNOSTIC_HANDOFF_COMPLETENESS", "2.0"))
    REWARD_RATIONALE_RECORDED: float = float(os.getenv("REWARD_RATIONALE_RECORDED", "1.0"))
    REWARD_TURN_PENALTY: float = float(os.getenv("REWARD_TURN_PENALTY", "0.25"))
    REWARD_LLM_CALL_PENALTY: float = float(os.getenv("REWARD_LLM_CALL_PENALTY", "1.0"))
    REWARD_TEST_PENALTY: float = float(os.getenv("REWARD_TEST_PENALTY", "0.8"))
    REWARD_CONSULT_PENALTY: float = float(os.getenv("REWARD_CONSULT_PENALTY", "1.0"))
    REWARD_ASK_DELAY_PENALTY: float = float(os.getenv("REWARD_ASK_DELAY_PENALTY", "0.5"))
    REWARD_APPROPRIATE_TEST_BONUS: float = float(os.getenv("REWARD_APPROPRIATE_TEST_BONUS", "0.4"))
    REWARD_APPROPRIATE_CONSULT_BONUS: float = float(os.getenv("REWARD_APPROPRIATE_CONSULT_BONUS", "0.4"))
    REWARD_CHIEF_DOCTOR_PENALTY: float = float(os.getenv("REWARD_CHIEF_DOCTOR_PENALTY", "0.5"))


settings = Settings()


