from __future__ import annotations

from app.agents.specialty_agent import DepartmentDiagnosticAgent


class CardiologyAgent(DepartmentDiagnosticAgent):
    def __init__(self) -> None:
        super().__init__("cardiology")
