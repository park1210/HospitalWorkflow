from __future__ import annotations

from app.agents.specialty_agent import SpecialtyAgent


class ConsultModule:
    def __init__(self) -> None:
        self.specialty_agent = SpecialtyAgent()

    def run(self, department: str, state: dict, transcript: list[dict[str, str]]) -> dict[str, str]:
        opinion = self.specialty_agent.consult(department, state, transcript)
        return {
            "department": department,
            "opinion": opinion,
        }
