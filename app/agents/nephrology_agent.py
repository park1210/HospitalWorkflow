from __future__ import annotations

from app.agents.specialty_agent import DepartmentDiagnosticAgent


class NephrologyAgent(DepartmentDiagnosticAgent):
    def __init__(self) -> None:
        super().__init__("nephrology")
