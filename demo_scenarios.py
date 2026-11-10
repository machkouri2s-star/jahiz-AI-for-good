"""Console and Streamlit runner for the four synthetic Jahiz scenarios."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agents.coordinator import JahizCoordinator
from agents.dpa_agent import (
    DataProtectionAuthorityAgent,
    DataProtectionRequest,
)
from agents.messages import CoordinatorResult, EventMessage, RequestKind
from agents.policy_adviser import (
    PolicyAdviser,
    create_anthropic_language_model,
)
from audit.logger import AuditLogger, AuditRecord, read_audit_log
from data.synthetic_pilgrim import SyntheticPilgrim, create_synthetic_pilgrim
from kb.retrieval import ChromaKnowledgeBase, KnowledgeBase, KnowledgePassage
from rules.engine import RuleResult, SessionObservation

_DEMO_TIME = datetime(2026, 11, 12, 8, tzinfo=timezone.utc)


@dataclass
class DemoRuntime:
    """Dependencies and state shared by console and Streamlit demo stages."""

    audit_logger: AuditLogger
    knowledge_base: KnowledgeBase
    policy_adviser: PolicyAdviser
    coordinator: JahizCoordinator
    pilgrim: SyntheticPilgrim
    results: dict[str, CoordinatorResult] = field(default_factory=dict)
    stage_outputs: list[tuple[int, str]] = field(default_factory=list)
    next_stage: int = 1
    session_history: list[SessionObservation] = field(default_factory=list)


def create_demo_runtime(data_directory: str | Path | None = None) -> DemoRuntime:
    """Initialize local Chroma, seeded notes, policy adviser, and audit logger."""
    project_directory = Path(__file__).parent
    runtime_directory = Path(
        data_directory
        or os.environ.get("JAHIZ_DATA_DIR", project_directory / "runtime")
    )
    knowledge_base = ChromaKnowledgeBase(runtime_directory / "chroma")
    knowledge_base.ingest_directory(project_directory / "kb")
    audit_logger = AuditLogger(runtime_directory / "audit.jsonl")
    policy_adviser = PolicyAdviser(
        knowledge_base,
        language_model=create_anthropic_language_model(),
    )
    dpa_agent = DataProtectionAuthorityAgent(audit_logger)
    return DemoRuntime(
        audit_logger=audit_logger,
        knowledge_base=knowledge_base,
        policy_adviser=policy_adviser,
        coordinator=JahizCoordinator(
            audit_logger=audit_logger,
            dpa_agent=dpa_agent,
            policy_adviser=policy_adviser,
        ),
        pilgrim=create_synthetic_pilgrim(),
    )


def run_next_stage(runtime: DemoRuntime) -> tuple[int, str]:
    """Run the next scenario exactly once and return its stage and summary."""
    if runtime.next_stage > 4:
        raise StopIteration("all four demo stages have been completed")
    stage = runtime.next_stage
    output = run_stage(runtime, stage)
    runtime.stage_outputs.append((stage, output))
    runtime.next_stage += 1
    return stage, output


def run_stage(runtime: DemoRuntime, stage: int) -> str:
    """Execute one numbered synthetic scenario."""
    scenarios = {
        1: _normal_scenario,
        2: _pain_scenario,
        3: _commercial_reuse_scenario,
        4: _underreported_effort_scenario,
    }
    try:
        scenario = scenarios[stage]
    except KeyError as error:
        raise ValueError("stage must be between 1 and 4") from error
    return scenario(runtime)


def _normal_scenario(runtime: DemoRuntime) -> str:
    event_time = _DEMO_TIME
    event = EventMessage(
        event_id="demo-stage-1-day-14",
        occurred_at=event_time,
        request_kind=RequestKind.TRAINING_EVENT,
        privacy_request=_privacy_request("demo-stage-1-day-14"),
        participant_id=runtime.pilgrim.participant_id,
        session_history=(
            SessionObservation(5, 0, walking_time_minutes=20),
            SessionObservation(6, 0, walking_time_minutes=20),
        ),
        day_number=14,
        walk_distance_m=420,
    )
    result = _process(runtime, event)
    r6 = _rule(result, "R6")
    if r6.triggered:
        result = runtime.coordinator.record_human_decision(
            result,
            target="R6",
            decision="approve",
            validator_id="synthetic-supervisor-001",
            decided_at=event_time + timedelta(minutes=5),
        )
        runtime.results[event.event_id] = result

    policy_result = _ask_policy(
        runtime,
        event_id="demo-stage-1-readiness-policy",
        query="Does the R6 functional-ready indicator mean medical clearance?",
        at=event_time + timedelta(minutes=6),
    )
    return (
        "Jour 14 : 420 m atteints. R6 a marqué un indicateur fonctionnel; "
        "le superviseur synthétique l'a confirmé. Ce statut n'est pas une "
        "aptitude médicale.\n"
        f"Réponse de l'adviser:\n{policy_result}"
    )


def _pain_scenario(runtime: DemoRuntime) -> str:
    event_time = _DEMO_TIME + timedelta(days=1)
    event = EventMessage(
        event_id="demo-stage-2-pain",
        occurred_at=event_time,
        request_kind=RequestKind.TRAINING_EVENT,
        privacy_request=_privacy_request("demo-stage-2-pain"),
        participant_id=runtime.pilgrim.participant_id,
        session_history=(SessionObservation(4, 5),),
        day_number=6,
    )
    result = _process(runtime, event)
    escalation = runtime.coordinator.escalate_unanswered_pain_alert(
        event.event_id,
        event_time + timedelta(hours=24),
        backup_supervisor_id="synthetic-backup-supervisor",
    )
    policy_result = _ask_policy(
        runtime,
        event_id="demo-stage-2-eu-responsibilities",
        query=(
            "What do the EU AI Act Article 14 human-oversight example and "
            "Article 26 deployer-obligations example say about supervision?"
        ),
        at=event_time + timedelta(hours=24, minutes=1),
        requester_role="agency",
    )
    return (
        f"Jour 6 : douleur 5/10. { _rule(result, 'R4').conclusion } "
        f"Après 24 h sans réponse : {escalation.message} "
        f"({escalation.backup_supervisor_id}).\n"
        f"Réponse de l'adviser:\n{policy_result}"
    )


def _commercial_reuse_scenario(runtime: DemoRuntime) -> str:
    event_time = _DEMO_TIME + timedelta(days=2)
    event_id = "demo-stage-3-commercial-request"
    event = EventMessage(
        event_id=event_id,
        occurred_at=event_time,
        request_kind=RequestKind.DATA_ACCESS_REQUEST,
        privacy_request=_privacy_request(
            event_id,
            requester_role="agency",
            requested_purpose="commercial_pricing",
            individual_data_requested=True,
            aggregate_alternative_available=True,
        ),
        policy_query=(
            "May individual functional records be reused to adjust package prices? "
            "What does the GDPR purpose-limitation example say?"
        ),
    )
    result = _process(runtime, event)
    policy_check = result.messages.policy_check
    return (
        f"Évaluation adviser: {policy_check.adviser_response.text if policy_check.adviser_response else 'aucune réponse'}\n"
        f"Évaluation DPA indépendante: {', '.join(policy_check.dpa_evaluation.findings)}\n"
        f"Décision d'accès: {policy_check.access_control_action}. "
        "Les données individuelles sont refusées; seuls des indicateurs agrégés "
        "et dé-identifiés sont proposés. L'action est journalisée."
    )


def _underreported_effort_scenario(runtime: DemoRuntime) -> str:
    event_time = _DEMO_TIME + timedelta(days=3)
    event_id = "demo-stage-4-r1-increase"
    event = EventMessage(
        event_id=event_id,
        occurred_at=event_time,
        request_kind=RequestKind.TRAINING_EVENT,
        privacy_request=_privacy_request(
            event_id,
        ),
        participant_id=runtime.pilgrim.participant_id,
        session_history=(
            SessionObservation(3, 0, walking_time_minutes=30),
            SessionObservation(4, 0, walking_time_minutes=30),
        ),
        day_number=5,
    )
    result = _process(runtime, event)
    result = runtime.coordinator.record_human_decision(
        result,
        target="R1",
        decision="approve",
        validator_id="synthetic-supervisor-001",
        decided_at=event_time + timedelta(minutes=5),
    )
    runtime.results[event_id] = result

    proposed_minutes = _rule(
        result, "R1"
    ).observed_values["proposed_walking_time_minutes"]
    runtime.audit_logger.write(
        AuditRecord(
            agent="Synthetic incident recorder",
            autonomy_level="L4",
            pseudonymized_inputs={
                "event_id": "demo-stage-4-incident",
                "participant_id": runtime.pilgrim.participant_id,
            },
            request="synthetic_incident:underreported_effort",
            rule_id="R1",
            reasoning_trace={
                "approved_walking_time_minutes": proposed_minutes,
                "reported_effort": (3, 4),
                "synthetic_scenario_ground_truth_effort": 8,
                "ground_truth_available_to_coordinator_at_decision": False,
                "incident_type": "serious synthetic adverse event",
            },
            decision="Serious synthetic incident recorded for review.",
            human_validator="synthetic-supervisor-001",
            human_decision_at=(event_time + timedelta(minutes=5)).isoformat(),
        )
    )

    audit_entries, audit_errors = _read_incident_audit(runtime.audit_logger.path)
    audit_summary = "; ".join(
        f"{entry.get('agent')}: {entry.get('decision')}" for entry in audit_entries
    )
    query = (
        "The audit log for a synthetic incident shows R1 used reported effort "
        "scores 3 and 4, proposed a 10% walking-time increase, and a human "
        "supervisor approved it. The post-event synthetic scenario reveals the "
        "effort was under-reported and a serious adverse event occurred. "
        "Can the prototype be classified as a wellness tool or a medical device? "
        "What design mitigations should be considered?"
    )
    policy_result = _ask_policy(
        runtime,
        event_id="demo-stage-4-regulator-question",
        query=query,
        at=event_time + timedelta(minutes=10),
        requester_role="regulator",
        knowledge_base=_AuditAugmentedKnowledgeBase(
            runtime.knowledge_base,
            runtime.audit_logger.path,
        ),
    )
    error_note = (
        f"Audit read warning: {'; '.join(audit_errors)}"
        if audit_errors
        else ""
    )
    return (
        f"Audit evidence reviewed: {audit_summary or 'no matching entry'}.\n"
        f"Regulator question — adviser response:\n{policy_result}\n"
        f"{error_note}"
    ).strip()


def _process(runtime: DemoRuntime, event: EventMessage) -> CoordinatorResult:
    result = runtime.coordinator.process_event(event)
    runtime.results[event.event_id] = result
    return result


def _ask_policy(
    runtime: DemoRuntime,
    event_id: str,
    query: str,
    at: datetime,
    requester_role: str = "synthetic_supervisor",
    knowledge_base: KnowledgeBase | None = None,
) -> str:
    coordinator = runtime.coordinator
    if knowledge_base is not None:
        adviser = runtime.policy_adviser.with_knowledge_base(knowledge_base)
        coordinator = JahizCoordinator(
            runtime.audit_logger,
            DataProtectionAuthorityAgent(runtime.audit_logger),
            adviser,
        )
    event = EventMessage(
        event_id=event_id,
        occurred_at=at,
        request_kind=RequestKind.POLICY_QUESTION,
        privacy_request=_privacy_request(
            event_id,
            requester_role=requester_role,
        ),
        policy_query=query,
    )
    result = coordinator.process_event(event)
    runtime.results[event.event_id] = result
    response = result.messages.policy_check.adviser_response
    if response is None:
        raise RuntimeError("policy request completed without an adviser response")
    return response.text


class _AuditAugmentedKnowledgeBase:
    """Retrieve policy passages together with the relevant synthetic audit facts."""

    def __init__(self, policy_kb: KnowledgeBase, audit_path: Path) -> None:
        self._policy_kb = policy_kb
        self._audit_path = audit_path

    def search(
        self, query: str, top_k: int = 4
    ) -> tuple[KnowledgePassage, ...]:
        entries, errors = read_audit_log(self._audit_path)
        if errors:
            raise RuntimeError("Cannot retrieve malformed audit entries: " + "; ".join(errors))
        incident_entries = [
            entry
            for entry in entries
            if entry.get("request") == "synthetic_incident:underreported_effort"
            or (
                entry.get("request") == "human_decision:R1"
                and _audit_event_id(entry) == "demo-stage-4-r1-increase"
            )
        ]
        audit_passages_list: list[KnowledgePassage] = []
        for index, entry in enumerate(incident_entries, start=1):
            audit_inputs = entry.get("pseudonymized_inputs")
            event_id = (
                audit_inputs.get("event_id", "unknown")
                if isinstance(audit_inputs, dict)
                else "unknown"
            )
            audit_passages_list.append(
                KnowledgePassage(
                    passage_id=f"audit-{index}",
                    document="audit.jsonl",
                    location=f"event {event_id}",
                    text=json.dumps(entry, ensure_ascii=False, sort_keys=True),
                )
            )
        audit_passages = tuple(audit_passages_list)
        remaining_count = max(0, top_k - len(audit_passages))
        policy_passages = (
            self._policy_kb.search(query, top_k=remaining_count)
            if remaining_count
            else ()
        )
        return (audit_passages + policy_passages)[:top_k]


def _audit_event_id(entry: dict[str, object]) -> str | None:
    inputs = entry.get("pseudonymized_inputs")
    if not isinstance(inputs, dict):
        return None
    event_id = inputs.get("event_id")
    return event_id if isinstance(event_id, str) else None


def _privacy_request(
    event_id: str,
    *,
    requester_role: str = "synthetic_supervisor",
    requested_purpose: str = "functional_preparation",
    individual_data_requested: bool = True,
    aggregate_alternative_available: bool = False,
) -> DataProtectionRequest:
    return DataProtectionRequest(
        event_id=event_id,
        requester_role=requester_role,
        requested_purpose=requested_purpose,
        original_purpose="functional_preparation",
        requested_data_categories=("effort", "pain_score", "functional_status"),
        consent_for_requested_use=True,
        individual_data_requested=individual_data_requested,
        aggregate_alternative_available=aggregate_alternative_available,
    )


def _rule(result: CoordinatorResult, rule_id: str) -> RuleResult:
    try:
        return next(
            rule
            for rule in result.messages.rule_evaluation.results
            if rule.rule_id == rule_id
        )
    except StopIteration as error:
        raise RuntimeError(f"rule {rule_id} was not evaluated") from error


def _read_incident_audit(
    path: Path,
) -> tuple[tuple[dict[str, object], ...], tuple[str, ...]]:
    entries, errors = read_audit_log(path)
    matching = tuple(
        entry
        for entry in entries
        if entry.get("request") == "synthetic_incident:underreported_effort"
        or (
            entry.get("request") == "human_decision:R1"
            and _audit_event_id(entry) == "demo-stage-4-r1-increase"
        )
    )
    return matching, errors


def main() -> None:
    """Run all four demo stages in sequence in a console."""
    runtime = create_demo_runtime()
    while runtime.next_stage <= 4:
        stage, output = run_next_stage(runtime)
        print(f"\n--- Stage {stage} ---\n{output}")


if __name__ == "__main__":
    main()
