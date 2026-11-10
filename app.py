"""Streamlit interfaces for the synthetic Jahiz prototype."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone

import streamlit as st

from agents.dpa_agent import DataProtectionRequest
from agents.messages import CoordinatorResult, EventMessage, RequestKind
from audit.logger import AuditRecord, read_audit_log
from demo_scenarios import DemoRuntime, create_demo_runtime, run_next_stage
from rules.engine import SessionObservation


def main() -> None:
    """Render the selected participant, supervisor, agency, or demo view."""
    st.set_page_config(page_title="Jahiz", page_icon="🕋", layout="wide")
    _add_accessible_styles()
    st.title("Jahiz — préparation fonctionnelle au Hajj")
    st.warning(
        "Prototype de démonstration avec données synthétiques : aucune validation "
        "clinique, aucun diagnostic et aucune fatwa. « Prêt » est uniquement un "
        "indicateur fonctionnel."
    )

    runtime = _get_runtime()
    view = st.sidebar.radio(
        "Interface",
        (
            "Simulateur pèlerin",
            "Tableau superviseur",
            "Vue agence",
            "Scénarios",
        ),
    )
    if view == "Simulateur pèlerin":
        _show_pilgrim(runtime)
    elif view == "Tableau superviseur":
        _show_supervisor(runtime)
    elif view == "Vue agence":
        _show_agency(runtime)
    else:
        _show_scenarios(runtime)


def _get_runtime() -> DemoRuntime:
    if "jahiz_runtime" not in st.session_state:
        try:
            st.session_state["jahiz_runtime"] = create_demo_runtime()
        except (RuntimeError, FileNotFoundError, OSError) as error:
            st.error(f"Initialisation Jahiz impossible : {error}")
            st.stop()
    return st.session_state["jahiz_runtime"]


def _show_pilgrim(runtime: DemoRuntime) -> None:
    st.header("Simulateur pèlerin")
    st.markdown(
        '<div dir="rtl" style="font-size:1.35rem;font-weight:700">'
        "سجّل المجهود والألم، واطلب مساعدة المشرف عند الحاجة."
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("**Darija :** سجّل المجهود والألم، وعيّط للمشرف إلا احتجتي.")
    st.write("**Français :** Choisissez l'effort et la douleur; un superviseur reste disponible.")
    st.caption(
        f"Profil fictif : {runtime.pilgrim.display_name}, {runtime.pilgrim.age} ans. "
        "Les consentements de participation et de données de santé sont distincts."
    )

    participation_consent = st.checkbox(
        "J'accepte de participer au programme (consentement de participation séparé).",
        key="jahiz_participation_consent",
    )
    health_consent = st.checkbox(
        "J'autorise séparément la collecte de mes données fonctionnelles pour ce programme.",
        key="jahiz_health_consent",
    )
    if not participation_consent or not health_consent:
        st.info("Aucune donnée d'effort ou de douleur ne sera enregistrée sans les deux consentements.")
    else:
        _show_checkin_controls(runtime)

    if st.button("Appeler le superviseur / عيّط للمشرف", use_container_width=True):
        _record_supervisor_call(runtime)

    st.divider()
    st.write(
        "En cas de douleur importante, arrêtez l'exercice et contactez un superviseur. "
        "Ce prototype ne fournit pas de conseil médical."
    )


def _show_checkin_controls(runtime: DemoRuntime) -> None:
    st.subheader("Enregistrement en un clic")
    effort_column, pain_column = st.columns(2)
    with effort_column:
        effort = st.radio(
            "Effort / المجهود (0-10)",
            options=tuple(range(11)),
            horizontal=True,
            key="jahiz_effort",
        )
    with pain_column:
        pain = st.radio(
            "Douleur / الألم (0-10)",
            options=tuple(range(11)),
            horizontal=True,
            key="jahiz_pain",
        )
    time_column, day_column = st.columns(2)
    with time_column:
        walking_time = st.number_input(
            "Temps de marche (minutes)",
            min_value=1.0,
            max_value=180.0,
            value=20.0,
            step=1.0,
        )
    with day_column:
        default_day = min(max(len(runtime.session_history) + 1, 1), 14)
        day_number = st.number_input(
            "Jour du programme",
            min_value=1,
            max_value=14,
            value=default_day,
            step=1,
        )
    walk_distance = st.number_input(
        "Marche de 6 minutes (mètres; facultatif sauf au jour 14)",
        min_value=0.0,
        max_value=2000.0,
        value=0.0,
        step=10.0,
    )
    fatigue_morning_severe = st.checkbox(
        "Fatigue matinale sévère / تعب شديد في الصباح"
    )
    joint_pain_persistent = st.checkbox(
        "Douleur articulaire persistante / ألم مفصلي مستمر"
    )
    if st.button("Enregistrer ma séance", type="primary", use_container_width=True):
        now = datetime.now(timezone.utc)
        runtime.pilgrim.authorize_health_data_collection(now)
        _record_pilgrim_consent(runtime, now)
        observation = SessionObservation(
            effort=int(effort),
            pain_score=int(pain),
            joint_pain_persistent=joint_pain_persistent,
            walking_time_minutes=float(walking_time),
        )
        history = tuple((*runtime.session_history[-1:], observation))
        event_id = f"pilgrim-checkin-{uuid.uuid4()}"
        event = EventMessage(
            event_id=event_id,
            occurred_at=now,
            request_kind=RequestKind.TRAINING_EVENT,
            privacy_request=DataProtectionRequest(
                event_id=event_id,
                requester_role="pilgrim",
                requested_purpose="functional_preparation",
                original_purpose="functional_preparation",
                requested_data_categories=("effort", "pain_score", "walking_time"),
                consent_for_requested_use=True,
                individual_data_requested=True,
                aggregate_alternative_available=False,
            ),
            participant_id=runtime.pilgrim.participant_id,
            session_history=history,
            day_number=int(day_number),
            walk_distance_m=float(walk_distance),
            fatigue_morning_severe=fatigue_morning_severe,
        )
        result = runtime.coordinator.process_event(event)
        runtime.results[event_id] = result
        runtime.session_history.append(observation)
        st.success("Séance enregistrée; les règles sont vérifiées sans appel LLM.")
        st.json(asdict(result.messages.rule_evaluation))


def _record_pilgrim_consent(runtime: DemoRuntime, recorded_at: datetime) -> None:
    for purpose in ("program_participation", "health_data"):
        runtime.audit_logger.write(
            AuditRecord(
                agent="Pilgrim Consent Interface",
                autonomy_level="L4",
                pseudonymized_inputs={
                    "participant_id": runtime.pilgrim.participant_id,
                    "consent_purpose": purpose,
                },
                request=f"consent:{purpose}",
                decision="Consent affirmed before data collection.",
                human_decision_at=recorded_at.isoformat(),
            )
        )


def _record_supervisor_call(runtime: DemoRuntime) -> None:
    now = datetime.now(timezone.utc)
    event_id = f"supervisor-call-{uuid.uuid4()}"
    event = EventMessage(
        event_id=event_id,
        occurred_at=now,
        request_kind=RequestKind.SUPERVISOR_CALL,
        privacy_request=DataProtectionRequest(
            event_id=event_id,
            requester_role="pilgrim",
            requested_purpose="supervisor_contact",
            original_purpose="supervisor_contact",
            requested_data_categories=("call_request",),
            consent_for_requested_use=True,
            individual_data_requested=False,
            aggregate_alternative_available=False,
        ),
        participant_id=runtime.pilgrim.participant_id,
    )
    result = runtime.coordinator.process_event(event)
    runtime.results[event_id] = result
    st.success("Demande d'appel transmise au tableau superviseur.")


@st.fragment(run_every="60s")
def _show_supervisor(runtime: DemoRuntime) -> None:
    st.header("Tableau de bord superviseur")
    for escalation in runtime.coordinator.escalate_due_pain_alerts(
        datetime.now(timezone.utc),
        backup_supervisor_id="backup-supervisor-001",
    ):
        st.warning(
            f"Escalade automatique vers {escalation.backup_supervisor_id} : "
            f"{escalation.message}"
        )
    consented = bool(
        st.session_state.get("jahiz_health_consent", False)
        and st.session_state.get("jahiz_participation_consent", False)
    )
    if not consented:
        st.info("Le pèlerin n'a pas accordé le consentement actif : détails individuels masqués.")
    if st.session_state.get("jahiz_participation_consent", False):
        _show_absence_form(runtime)
    else:
        st.info("Le suivi individuel des absences nécessite le consentement de participation.")
    results = list(runtime.results.values())
    if not results:
        st.info("Aucune priorité enregistrée pour le moment.")
    for result in sorted(results, key=_priority_sort_key):
        _show_priority(runtime, result, consented)
    _show_audit(runtime, consented)


def _show_priority(
    runtime: DemoRuntime,
    result: CoordinatorResult,
    consented: bool,
) -> None:
    event = result.messages.event
    flags = _priority_flags(result)
    if not flags:
        return
    title = f"{' · '.join(flags)} — {event.event_id}"
    with st.expander(title, expanded=True):
        if consented:
            st.write(f"Participant : {runtime.pilgrim.display_name} (synthetic)")
            st.write(f"ID pseudonymisé : {event.participant_id}")
            if event.session_history:
                st.write(
                    [
                        {
                            "effort": session.effort,
                            "pain_score": session.pain_score,
                            "walking_time_minutes": session.walking_time_minutes,
                        }
                        for session in event.session_history
                    ]
                )
        else:
            st.write("Identité et mesures individuelles masquées.")
        st.write(f"Autonomie : {result.messages.rule_evaluation.autonomy_level}")
        for notification in result.messages.rule_evaluation.supervisor_notifications:
            st.warning(notification)
        if consented:
            st.json(asdict(result.messages.rule_evaluation))
            st.json(asdict(result.messages.policy_check))
        for target in result.pending_human_actions:
            _human_action_buttons(runtime, result, target)


def _priority_flags(result: CoordinatorResult) -> list[str]:
    flags: list[str] = []
    event = result.messages.event
    if event.request_kind is RequestKind.SUPERVISOR_CALL:
        flags.append("appel demandé")
    if result.messages.policy_check.access_control_action:
        flags.append("demande de données")
    for rule in result.messages.rule_evaluation.results:
        if rule.triggered:
            flags.append(
                {
                    "R1": "augmentation proposée",
                    "R3": "effort élevé/fatigue",
                    "R4": "douleur",
                    "R5": "absence",
                    "R6": "indicateur prêt",
                    "R2": "charge maintenue",
                }.get(rule.rule_id, rule.rule_id)
            )
    if result.pending_human_actions:
        flags.append("validation humaine requise")
    return flags


def _show_absence_form(runtime: DemoRuntime) -> None:
    with st.expander("Suivi de présence", expanded=False):
        absence_days = st.number_input(
            "Jours d'absence consécutifs",
            min_value=0,
            max_value=30,
            value=0,
            step=1,
            key="jahiz_absence_days",
        )
        if st.button("Évaluer l'absence", key="evaluate-absence"):
            now = datetime.now(timezone.utc)
            event_id = f"attendance-{uuid.uuid4()}"
            event = EventMessage(
                event_id=event_id,
                occurred_at=now,
                request_kind=RequestKind.TRAINING_EVENT,
                privacy_request=DataProtectionRequest(
                    event_id=event_id,
                    requester_role="supervisor",
                    requested_purpose="functional_preparation",
                    original_purpose="functional_preparation",
                    requested_data_categories=("attendance",),
                    consent_for_requested_use=True,
                    individual_data_requested=True,
                    aggregate_alternative_available=False,
                ),
                participant_id=runtime.pilgrim.participant_id,
                absence_days=int(absence_days),
            )
            runtime.results[event_id] = runtime.coordinator.process_event(event)
            st.success("Présence évaluée avec la règle déterministe R5.")


def _priority_sort_key(result: CoordinatorResult) -> tuple[int, float]:
    rule_ids = {
        rule.rule_id
        for rule in result.messages.rule_evaluation.results
        if rule.triggered
    }
    if "R4" in rule_ids:
        priority = 0
    elif result.messages.event.request_kind is RequestKind.SUPERVISOR_CALL:
        priority = 1
    elif "R5" in rule_ids:
        priority = 2
    elif "R3" in rule_ids:
        priority = 3
    elif "R1" in rule_ids:
        priority = 4
    elif "R6" in rule_ids:
        priority = 5
    elif result.messages.policy_check.access_control_action:
        priority = 6
    else:
        priority = 7
    return priority, -result.messages.event.occurred_at.timestamp()


def _human_action_buttons(
    runtime: DemoRuntime,
    result: CoordinatorResult,
    target: str,
) -> None:
    if target in {"R4", "health_decision", "religious_question"}:
        if st.button(
            f"Accuser réception : {target}",
            key=f"ack-{result.messages.event.event_id}-{target}",
        ):
            updated = runtime.coordinator.record_human_decision(
                result,
                target=target,
                decision="acknowledge",
                validator_id="supervisor-001",
                decided_at=max(
                    datetime.now(timezone.utc),
                    result.messages.event.occurred_at,
                ),
            )
            runtime.results[result.messages.event.event_id] = updated
            st.success(updated.messages.human_decisions[-1].applied_action)
        return

    left, right = st.columns(2)
    with left:
        if st.button(
            f"Valider {target}",
            key=f"approve-{result.messages.event.event_id}-{target}",
        ):
            updated = runtime.coordinator.record_human_decision(
                result,
                target=target,
                decision="approve",
                validator_id="supervisor-001",
                decided_at=max(
                    datetime.now(timezone.utc),
                    result.messages.event.occurred_at,
                ),
            )
            runtime.results[result.messages.event.event_id] = updated
            st.success(updated.messages.human_decisions[-1].applied_action)
    with right:
        if st.button(
            f"Refuser {target}",
            key=f"refuse-{result.messages.event.event_id}-{target}",
        ):
            updated = runtime.coordinator.record_human_decision(
                result,
                target=target,
                decision="refuse",
                validator_id="supervisor-001",
                decided_at=max(
                    datetime.now(timezone.utc),
                    result.messages.event.occurred_at,
                ),
            )
            runtime.results[result.messages.event.event_id] = updated
            st.info(updated.messages.human_decisions[-1].applied_action)


def _show_audit(runtime: DemoRuntime, consented: bool) -> None:
    st.subheader("Trace d'audit JSONL")
    entries, errors = read_audit_log(runtime.audit_logger.path)
    if errors:
        st.error("Certaines lignes JSONL sont invalides : " + " ; ".join(errors))
    if not entries:
        st.info("Aucune entrée d'audit.")
        return
    if not consented:
        st.caption("Mesures et traces individuelles masquées faute de consentement actif.")
    for entry in reversed(entries[-50:]):
        if consented:
            st.json(entry)
        else:
            st.json(
                {
                    key: entry.get(key)
                    for key in ("timestamp", "agent", "autonomy_level", "rule_id")
                    if key in entry
                }
            )


def _show_agency(runtime: DemoRuntime) -> None:
    st.header("Vue agence — uniquement agrégée et dé-identifiée")
    st.write(
        "Aucune identité ni mesure individuelle n'est accessible dans cette vue. "
        "Les exports individuels à des fins commerciales sont refusés."
    )
    participant_ids = {
        result.messages.event.participant_id
        for result in runtime.results.values()
        if result.messages.event.participant_id
    }
    participant_count = len(participant_ids)
    if participant_count < 5:
        st.info(
            "Indicateurs masqués par suppression des petits groupes "
            "(seuil de publication : 5 participants)."
        )
    else:
        rule_counts: dict[str, int] = {}
        for result in runtime.results.values():
            for rule in result.messages.rule_evaluation.results:
                if rule.triggered:
                    rule_counts[rule.rule_id] = rule_counts.get(rule.rule_id, 0) + 1
        st.metric("Événements agrégés", len(runtime.results))
        st.json(rule_counts)
    st.subheader("Indicateurs agrégés disponibles")
    st.write(
        "- Taux agrégé de participation, avec suppression des petits groupes.\n"
        "- Distribution agrégée de l'effort, sans lignes individuelles.\n"
        "- Nombre agrégé d'indicateurs fonctionnels « prêt », jamais une aptitude médicale."
    )


def _show_scenarios(runtime: DemoRuntime) -> None:
    st.header("Rejouer les quatre scénarios synthétiques")
    st.write(f"Prochain stage : {min(runtime.next_stage, 4)} / 4")
    if st.button(
        "Stage suivant",
        type="primary",
        disabled=runtime.next_stage > 4,
        use_container_width=True,
    ):
        try:
            stage, output = run_next_stage(runtime)
        except (RuntimeError, OSError, ValueError) as error:
            st.error(f"Le scénario a échoué : {error}")
        else:
            st.session_state["jahiz_last_stage"] = stage
            st.session_state["jahiz_last_output"] = output
    for stage, output in runtime.stage_outputs:
        with st.expander(f"Stage {stage}", expanded=True):
            st.write(output)


def _add_accessible_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #ffffff; color: #111111; }
        [data-testid="stSidebar"] { background: #edf2f5; }
        .stMarkdown, label, p, h1, h2, h3 { color: #111111 !important; }
        .stButton button {
            min-height: 3.2rem;
            font-size: 1.15rem;
            font-weight: 700;
            border: 2px solid #003b5c;
            background: #003b5c;
            color: #ffffff;
        }
        div[role="radiogroup"] label {
            min-height: 2.8rem;
            padding: 0.3rem 0.6rem;
            font-size: 1.1rem;
        }
        :focus-visible { outline: 4px solid #ffbf47 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
