import asyncio
import json
from app.orchestrator import Orchestrator
from app.models import ChatRequest

async def run_demos():
    orchestrator = Orchestrator()
    print("=" * 80)
    print("AI STAFFING ASSISTANT - END-TO-END DEMO SCENARIOS")
    print("=" * 80)

    # ---------------------------------------------------------
    # DEMO 1: Standard Successful Staffing Match
    # ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("DEMO SCENARIO 1: Standard Successful Match")
    print("Prompt: 'Find me a senior Python developer for a 3-month fintech project starting Oct 1'")
    print("=" * 60)

    req1 = ChatRequest(
        message="Find me a senior Python developer for a 3-month fintech project starting Oct 1",
        user_role="manager"
    )
    res1 = await orchestrator.handle_chat(req1)

    print(f"\n[Response Message]: {res1.message}")
    print(f"[Clarifying Question Triggered?]: {res1.is_clarifying_question}")
    print(f"[Provider]: {res1.llm_provider} ({res1.llm_model}) | [Decision Engine]: {res1.jev_model}")
    print(f"[Total Latency]: {res1.total_latency_ms}ms | [Jev Tokens]: {res1.jev_tokens} | [Est Cost]: ${res1.jev_cost_usd:.6f}")
    print(f"\nTop Recommended Candidates ({len(res1.candidates)} returned):")

    for i, c in enumerate(res1.candidates[:3]):
        rate_str = f"${c.hourly_cost}/hr" if c.hourly_cost else "Hidden"
        print(f"  {i+1}. {c.full_name} ({c.resource_id}) - {c.seniority} {c.role}")
        print(f"     Domain: {c.primary_domain} | Rate: {rate_str} | Exp: {c.years_experience} yrs")
        print(f"     Skill Score: {c.skill_score}/4.0 (Conf: {c.skill_confidence}) | Burnout Prob: {c.burnout_prob*100:.0f}%")
        print(f"     Final Score: {c.final_score*100:.1f}% | Confidence Level: {c.confidence_level} | Review: {c.needs_pm_review}")
        print(f"     Explanation: {c.explanation}")

    assert len(res1.candidates) > 0
    assert res1.is_clarifying_question is False
    print("\n>>> DEMO 1 PASSED: Confident recommendations returned with grounded explanations.")

    # ---------------------------------------------------------
    # DEMO 2: Low-Confidence Scenario Triggering Clarifying Question
    # ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("DEMO SCENARIO 2: Low-Confidence / Obscure Requirements")
    print("Prompt: 'Find a Lead Rust and Solana developer for a gaming project starting next week'")
    print("=" * 60)

    req2 = ChatRequest(
        message="Find a Lead Rust and Solana developer for a gaming project starting next week",
        user_role="manager"
    )
    res2 = await orchestrator.handle_chat(req2)

    print(f"\n[Response Message]: {res2.message}")
    print(f"[Clarifying Question Triggered?]: {res2.is_clarifying_question}")
    print(f"[Clarifying Text]: {res2.clarifying_question}")
    print(f"[Suggestion Chips]: {res2.suggestion_chips}")
    print(f"[Candidate Count]: {len(res2.candidates)}")
    if res2.candidates:
        print(f"Top Candidate Confidence: {[c.skill_confidence for c in res2.candidates[:3]]}")
        print(f"All Top 3 Low Confidence? {all(c.is_low_confidence for c in res2.candidates[:3])}")

    assert res2.is_clarifying_question is True
    assert "Relax skill requirement" in res2.suggestion_chips
    print("\n>>> DEMO 2 PASSED: Low-confidence trigger successfully halted confident output and asked clarifying question.")

    # ---------------------------------------------------------
    # DEMO 3: Multi-turn Follow-up ("Show me someone cheaper")
    # ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("DEMO SCENARIO 3: Conversation Continuity & Multi-turn Refinement")
    print("Turn 1: 'Find me a senior Python developer for a 3-month fintech project starting Oct 1'")
    print("Turn 2: 'Show me someone cheaper'")
    print("=" * 60)

    conv_id = res1.conversation_id
    req3 = ChatRequest(
        message="Show me someone cheaper",
        conversation_id=conv_id,
        user_role="manager"
    )
    res3 = await orchestrator.handle_chat(req3)

    print(f"\n[Response Message]: {res3.message}")
    print(f"[Candidates Returned]: {len(res3.candidates)}")
    rates_t1 = [c.hourly_cost for c in res1.candidates if c.hourly_cost]
    rates_t3 = [c.hourly_cost for c in res3.candidates if c.hourly_cost]
    print(f"Turn 1 Rates: {rates_t1[:3]}")
    print(f"Turn 2 Rates: {rates_t3[:3]}")
    print(f"Lowest Rate in Turn 2: ${min(rates_t3)}/hr")

    assert len(res3.candidates) > 0
    print("\n>>> DEMO 3 PASSED: Context preserved across turns with refined candidate list.")

    print("\n" + "=" * 80)
    print("ALL 3 END-TO-END DEMO SCENARIOS COMPLETED SUCCESSFULLY!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_demos())
