from __future__ import annotations

from app.agents.specialty_agent import DepartmentDiagnosticAgent


class GastroenterologyAgent(DepartmentDiagnosticAgent):
    def __init__(self) -> None:
        super().__init__("gastroenterology")
