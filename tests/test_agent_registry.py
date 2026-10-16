from copy import deepcopy
import unittest

from test_diagnostic_gate import Client, response, source
from app.core.agent_registry import AgentRegistry
from app.core.longitudinal_runner import run_longitudinal
from app.core.hospital_llm_policy import HospitalLLMPolicy
from app.core.hospital_parallel_scheduler import HospitalParallelScheduler
from app.llm.role_call import RoleCallError


def manifest():
    return {"schema_version": 1, "agents": [
        {"agent_id": "er", "role": "er", "department": "", "model": "test-er", "version": "fixture-v1", "keywords": []},
        {"agent_id": "neuro", "role": "specialty", "department": "neurology", "model": "test-neuro", "version": "fixture-v1", "keywords": ["synthetic", "old finding"]},
        {"agent_id": "cardio", "role": "specialty", "department": "cardiology", "model": "test-cardio", "version": "fixture-v1", "keywords": ["cardio"]}]}


class ModelsClient(Client):
    def __init__(self, *responses):
        super().__init__(*responses)
        self.models = []

    def chat_json(self, system, user, model=None, schema=None):
        self.models.append(model)
        return super().chat_json(system, user, model, schema)


class RegistryTests(unittest.TestCase):
    def test_validation_rejects_duplicate_unknown_department_and_missing_er(self):
        data = manifest()
        variants = []
        duplicate = deepcopy(data)
        duplicate["agents"].append(deepcopy(duplicate["agents"][1]))
        variants.append(duplicate)
        unknown = deepcopy(data)
        unknown["agents"][1]["department"] = "not-a-department"
        variants.append(unknown)
        missing = deepcopy(data)
        missing["agents"].pop(0)
        variants.append(missing)
        for variant in variants:
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                AgentRegistry(variant)

    def test_rule_uses_observed_memory_excludes_superseded_and_gold(self):
        registry = AgentRegistry(manifest())
        observed = {"chief_complaint": "unknown", "gold_label": "synthetic",
                    "hidden_test_results": {"result": "synthetic"}}
        self.assertEqual(registry.route(observed, ["neurology"], mode="rule")["allowed_departments"], [])
        observed["longitudinal_memory"] = {"records": [{"text": "old finding", "status_as_of_visit": "historical"}]}
        self.assertEqual(registry.route(observed, ["neurology"], mode="rule")["allowed_departments"], ["neurology"])
        observed["longitudinal_memory"]["records"][0]["status_as_of_visit"] = "superseded"
        self.assertEqual(registry.route(observed, ["neurology"], mode="rule")["allowed_departments"], [])

    def test_random_reproducibility_and_availability(self):
        registry = AgentRegistry(manifest())
        departments = ["neurology", "cardiology", "surgery"]
        first = registry.route({}, departments, mode="random", seed=21)
        self.assertEqual(first, registry.route({}, list(reversed(departments)), mode="random", seed=21))
        self.assertNotIn("surgery", first["candidate_departments"])
        self.assertEqual(len(first["allowed_departments"]), 1)
        self.assertEqual(registry.route({}, [], mode="random")["allowed_departments"], [])

    def test_registered_model_used_in_real_scheduler_path(self):
        data = source()
        data["longitudinal"] = {"patient_id": "p", "visit_id": "v", "started_at": "2026-01-01T00:00:00Z"}
        client = ModelsClient(response("request_test", target="T"),
            response("consult_specialty", target="neurology"), response(certainty="supported", indices=[0]))
        result = run_longitudinal([data], registry_manifest=manifest(), routing_mode="rule", client=client)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(client.models, ["test-er", "test-er", "test-neuro"])
        audit = result["visits"][0]["final_state"]["cases"]["gate"]["llm_audit"]
        self.assertEqual(audit[-1]["routing"]["executing_agent"]["agent_id"], "neuro")
        self.assertEqual(result["routing_config"]["registry"], manifest())
        self.assertEqual(len(client.models), 3)  # no router inference request

    def test_er_only_removes_consult_and_records_failure_context(self):
        runtime = HospitalParallelScheduler().initialize([source()]).case("gate")
        client = ModelsClient(response("consult_specialty", target="neurology"))
        policy = HospitalLLMPolicy({"max_decisions": 12, "max_questions": 2}, client=client)
        policy.agent_registry, policy.routing_mode = AgentRegistry(manifest()), "er_only"
        policy.departments = ["neurology"]
        with self.assertRaises(RoleCallError):
            policy.evaluate_er_case(runtime, doctor_id="er")
        self.assertNotIn("consult_specialty", client.payloads[0]["allowed_actions"])
        self.assertEqual(runtime.llm_audit[-1]["routing"]["mode"], "er_only")

    def test_llm_mode_keeps_all_registered_options_and_unknown_binding_fails(self):
        registry = AgentRegistry(manifest())
        self.assertEqual(registry.route({}, ["neurology", "cardiology", "surgery"])["allowed_departments"], ["cardiology", "neurology"])
        with self.assertRaises(ValueError):
            registry.get("specialty", "surgery")
        with self.assertRaises(ValueError):
            run_longitudinal([], routing_mode="random")


if __name__ == "__main__":
    unittest.main()
