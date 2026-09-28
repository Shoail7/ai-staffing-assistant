import time
import uuid
from typing import Dict, Any, List, Optional, Tuple
from .config import settings
from .logging_config import RequestTracker
from .models import ChatRequest, ChatResponse, CandidateResult
from .db import (
    filter_candidates_sql, get_connection, log_decision,
    save_conversation_turn, get_conversation_state
)
from .jev_client import get_decision_engine
from .llm_client import LLMOrchestratorClient
from .ranking import rank_candidates

class Orchestrator:
    def __init__(self):
        self.llm_client = LLMOrchestratorClient()

    @property
    def decision_engine(self):
        return get_decision_engine()

    async def handle_chat(self, req: ChatRequest) -> ChatResponse:
        tracker = RequestTracker()
        conv_id = req.conversation_id or str(uuid.uuid4())[:8]
        req_id = tracker.request_id

        # 1. Check conversation state for follow-ups (e.g. "show me someone cheaper")
        prev_state = get_conversation_state(conv_id) or {}
        prev_criteria = prev_state.get("last_criteria", {})
        prev_candidate_ids = prev_state.get("last_candidate_ids", [])

        # 2. Intent Classification via LLM
        t0 = time.perf_counter()
        tool_call, active_provider, active_model = await self.llm_client.classify_intent(
            req.message,
            conversation_history=[]
        )
        tracker.record_step("llm_intent_classification", time.perf_counter() - t0, {
            "provider": active_provider,
            "tool": tool_call.get("name")
        })

        tool_name = tool_call.get("name", "match_staff")
        tool_args = tool_call.get("arguments", {})

        # Merge previous criteria if this is a follow-up refinement
        msg_lower = req.message.lower()
        if "cheaper" in msg_lower or "less expensive" in msg_lower:
            if prev_criteria:
                for k, v in prev_criteria.items():
                    if k not in tool_args or not tool_args[k]:
                        tool_args[k] = v

        # Handle clarify tool call
        if tool_name == "clarify":
            clarify_q = tool_args.get("question", "Could you provide more details regarding the role, timeline, or required skills?")
            tracker.record_step("response_formatting", 0.001)
            save_conversation_turn(conv_id, req.message, clarify_q, prev_criteria, prev_candidate_ids)
            return ChatResponse(
                conversation_id=conv_id,
                request_id=req_id,
                message=clarify_q,
                candidates=[],
                is_clarifying_question=True,
                clarifying_question=clarify_q,
                suggestion_chips=["Senior Python Developer", "Fintech Backend Dev", "3-Month React Project"],
                latencies=tracker.step_latencies,
                total_latency_ms=tracker.total_elapsed_ms(),
                llm_provider=active_provider,
                llm_model=active_model
            )

        # Handle get_resource_details
        if tool_name == "get_resource_details":
            cid = tool_args.get("resource_id", "").upper()
            detail_res = self._get_single_resource(cid, req.user_role)
            if detail_res:
                msg = f"Profile details for **{detail_res.full_name}** ({detail_res.seniority} {detail_res.role})."
                save_conversation_turn(conv_id, req.message, msg, prev_criteria, [cid])
                return ChatResponse(
                    conversation_id=conv_id,
                    request_id=req_id,
                    message=msg,
                    candidates=[detail_res],
                    latencies=tracker.step_latencies,
                    total_latency_ms=tracker.total_elapsed_ms(),
                    llm_provider=active_provider,
                    llm_model=active_model
                )

        # 4a. Orchestrator filters candidates in SQL using HARD constraints only
        t_sql = time.perf_counter()
        role = tool_args.get("role")
        skills = tool_args.get("skills", [])
        min_exp = tool_args.get("min_experience_years")
        start_date = tool_args.get("start_date")
        duration = tool_args.get("duration_weeks")
        domain = tool_args.get("domain")

        sql_candidates = filter_candidates_sql(
            role=role,
            skills=skills,
            min_experience_years=min_exp,
            start_date=start_date,
            duration_weeks=duration,
            domain=domain,
            max_results=40  # Top 40 pre-ranked cap
        )
        tracker.record_step("sql_hard_constraint_filtering", time.perf_counter() - t_sql, {
            "candidates_found": len(sql_candidates)
        })

        if not sql_candidates:
            no_match_msg = "No active personnel met all hard constraints (required skills, date window, capacity). Would you like to relax the requirements?"
            save_conversation_turn(conv_id, req.message, no_match_msg, tool_args, [])
            return ChatResponse(
                conversation_id=conv_id,
                request_id=req_id,
                message=no_match_msg,
                candidates=[],
                is_clarifying_question=True,
                clarifying_question=no_match_msg,
                suggestion_chips=["Relax skill requirement", "Change start date", "Expand role scope"],
                latencies=tracker.step_latencies,
                total_latency_ms=tracker.total_elapsed_ms(),
                llm_provider=active_provider,
                llm_model=active_model
            )

        # 4b. Send candidate batches to Jev AI Decision Engine
        t_jev = time.perf_counter()
        project_spec = {
            "role": role,
            "skills": skills,
            "min_experience_years": min_exp,
            "start_date": start_date,
            "duration_weeks": duration,
            "domain": domain
        }
        jev_scores, input_tokens, jev_model_name, is_mock, is_fallback = await self.decision_engine.score_candidates(
            project_spec, sql_candidates
        )
        tracker.record_step("jev_decision_engine_scoring", time.perf_counter() - t_jev, {
            "candidates_scored": len(jev_scores),
            "input_tokens": input_tokens,
            "model": jev_model_name
        })

        # Attach Jev scores to candidates
        combined = []
        for c in sql_candidates:
            cid = c["resource_id"]
            j_res = jev_scores.get(cid, {
                "skill_score": 2.0,
                "skill_confidence": 0.65,
                "burnout_prob": 0.25,
                "burnout_confidence": 0.65
            })
            c_merged = dict(c)
            c_merged.update(j_res)
            combined.append(c_merged)

        # 6. Combine scores in code and apply low-confidence rules
        t_rank = time.perf_counter()
        req_seniority = "Senior" if (min_exp and min_exp >= 5.0) else "Mid"
        ranked_candidates, is_group_tie, all_top3_low = rank_candidates(
            combined,
            requested_seniority=req_seniority,
            user_role=req.user_role
        )
        tracker.record_step("ranking_and_low_confidence_rules", time.perf_counter() - t_rank, {
            "is_tie": is_group_tie,
            "all_top3_low": all_top3_low
        })

        # Calculate estimated Jev cost ($0.042 / 1,000,000 input tokens)
        jev_cost = round((input_tokens * settings.jev_cost_per_million_tokens) / 1_000_000, 6)

        # Handle Case: ALL top 3 are low confidence
        if all_top3_low and "show anyway" not in msg_lower:
            clarifying_text = (
                f"We identified {len(ranked_candidates)} potential candidates, but match confidence is low "
                f"across all top recommendations (uncertain skill alignment or pending timeline commitments). "
                f"To protect project success, please clarify your priorities."
            )
            tracker.record_step("response_assembly", 0.001)
            save_conversation_turn(conv_id, req.message, clarifying_text, tool_args, [c.resource_id for c in ranked_candidates[:5]])
            return ChatResponse(
                conversation_id=conv_id,
                request_id=req_id,
                message=clarifying_text,
                candidates=ranked_candidates[:5],
                is_clarifying_question=True,
                clarifying_question=clarifying_text,
                suggestion_chips=["Relax skill requirement", "Change start date", "Show anyway"],
                latencies=tracker.step_latencies,
                total_latency_ms=tracker.total_elapsed_ms(),
                jev_tokens=input_tokens,
                jev_cost_usd=jev_cost,
                jev_model=jev_model_name,
                is_mock_jev=is_mock,
                is_fallback_scorer=is_fallback,
                llm_provider=active_provider,
                llm_model=active_model
            )

        # Generate grounded explanations for top candidates
        top_candidates = ranked_candidates[:10]
        t_exp = time.perf_counter()
        for idx, cand in enumerate(top_candidates):
            explanation = await self.llm_client.generate_grounded_explanation(
                cand.dict(),
                active_provider
            )
            cand.explanation = explanation
            # Log decision to DECISION_LOG
            log_decision(
                request_id=req_id,
                conversation_id=conv_id,
                candidate_id=cand.resource_id,
                input_state=f"Role: {role}, Skills: {skills}, Domain: {domain}",
                questions={"score_rubric": "0..4", "burnout_noul": "boolean"},
                jev_answers={
                    "skill_score": cand.skill_score,
                    "burnout_prob": cand.burnout_prob
                },
                confidence=min(cand.skill_confidence, cand.burnout_confidence),
                final_rank=idx + 1
            )
        tracker.record_step("grounded_explanation_generation", time.perf_counter() - t_exp)

        # Craft assistant message header
        tie_note = " *(Note: Top candidates are too close to call; PM review recommended)*" if is_group_tie else ""
        header_msg = (
            f"Here are the top ranked candidates for your {domain or ''} project "
            f"matching **{role or 'developer'}** with {', '.join(skills) if skills else 'core'} skills.{tie_note}"
        )

        chips = ["Show someone cheaper", "Find fintech specialists", "Check next quarter availability"]
        if is_group_tie:
            chips.insert(0, "Compare top 2 candidates")

        save_conversation_turn(
            conv_id,
            req.message,
            header_msg,
            tool_args,
            [c.resource_id for c in top_candidates]
        )

        return ChatResponse(
            conversation_id=conv_id,
            request_id=req_id,
            message=header_msg,
            candidates=top_candidates,
            is_clarifying_question=False,
            suggestion_chips=chips,
            latencies=tracker.step_latencies,
            total_latency_ms=tracker.total_elapsed_ms(),
            jev_tokens=input_tokens,
            jev_cost_usd=jev_cost,
            jev_model=jev_model_name,
            is_mock_jev=is_mock,
            is_fallback_scorer=is_fallback,
            llm_provider=active_provider,
            llm_model=active_model
        )

    def _get_single_resource(self, resource_id: str, user_role: str) -> Optional[CandidateResult]:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM PM_RESOURCES WHERE resource_id = ?", (resource_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return None
        d = dict(row)
        # Fetch skills
        cur.execute("SELECT normalized_skill, proficiency, years_used FROM PM_RESOURCE_SKILLS WHERE resource_id = ?", (resource_id,))
        d["skills"] = [dict(sk) for sk in cur.fetchall()]
        conn.close()
        
        display_cost = d["hourly_cost"] if user_role.lower() == "manager" else None
        return CandidateResult(
            resource_id=d["resource_id"],
            full_name=d["full_name"],
            email=d["email"],
            role=d["role"],
            seniority=d["seniority"],
            years_experience=float(d["years_experience"]),
            location=d["location"],
            timezone=d["timezone"],
            primary_domain=d["primary_domain"],
            hourly_cost=display_cost,
            max_allocation_pct=float(d["max_allocation_pct"]),
            current_allocation_pct=25.0,
            concurrent_projects_count=1,
            hours_last_4_weeks=140.0,
            recent_overtime_hours=0.0,
            skill_score=3.5,
            skill_confidence=0.85,
            burnout_prob=0.15,
            burnout_confidence=0.85,
            final_score=0.82,
            confidence_level="HIGH",
            is_low_confidence=False,
            is_tie=False,
            workload_risk=False,
            needs_pm_review=False,
            explanation=f"{d['full_name']} is an active {d['seniority']} {d['role']} with {d['years_experience']} years of experience.",
            score_breakdown={
                "w1_skill": 0.30, "w2_availability": 0.20, "w3_burnout": 0.17, "w4_seniority": 0.15, "w5_cost_penalty": 0.02
            },
            skills=d["skills"]
        )
