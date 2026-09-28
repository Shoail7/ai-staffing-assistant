import asyncio
from typing import List, Dict, Any
from app.orchestrator import Orchestrator
from app.models import ChatRequest

BENCHMARK_CASES = [
    {
        "id": "CASE-1",
        "description": "Senior Python Developer in Fintech",
        "prompt": "Find me a senior Python developer for a 3-month fintech project starting Oct 1",
        "expected_role": "Backend Dev",
        "expected_skills": ["Python"],
        "expected_domain": "fintech",
        "expected_min_seniority": ["Senior", "Lead"]
    },
    {
        "id": "CASE-2",
        "description": "Frontend React Specialist in Healthcare",
        "prompt": "Find a Lead React developer for a healthcare clinical portal",
        "expected_role": "Frontend Dev",
        "expected_skills": ["React"],
        "expected_domain": "healthcare",
        "expected_min_seniority": ["Lead", "Senior"]
    },
    {
        "id": "CASE-3",
        "description": "Data Engineer for Logistics Telemetry",
        "prompt": "We need a Data Engineer with Spark and Airflow experience for a logistics data pipeline",
        "expected_role": "Data Engineer",
        "expected_skills": ["Spark", "Airflow"],
        "expected_domain": "logistics",
        "expected_min_seniority": ["Mid", "Senior", "Lead"]
    },
    {
        "id": "CASE-4",
        "description": "QA Automation Engineer with Selenium",
        "prompt": "Find a QA tester with Selenium skills for web app testing",
        "expected_role": "QA",
        "expected_skills": ["Selenium"],
        "expected_domain": None,
        "expected_min_seniority": ["Junior", "Mid", "Senior", "Lead"]
    },
    {
        "id": "CASE-5",
        "description": "DevOps Engineer with Kubernetes and AWS",
        "prompt": "Looking for a senior DevOps engineer with Kubernetes and AWS infrastructure skills",
        "expected_role": "DevOps",
        "expected_skills": ["Kubernetes", "AWS"],
        "expected_domain": None,
        "expected_min_seniority": ["Senior", "Lead"]
    }
]

async def run_evaluation():
    orchestrator = Orchestrator()
    print("=" * 80)
    print("AI STAFFING ASSISTANT - BENCHMARK EVALUATION (eval.py)")
    print("Comparing recommendations against hand-labelled ideal staffing criteria")
    print("=" * 80)

    total_cases = len(BENCHMARK_CASES)
    role_matches = 0
    skill_matches = 0
    domain_matches = 0
    seniority_matches = 0
    top1_agreements = 0
    top3_agreements = 0

    results_table = []

    for case in BENCHMARK_CASES:
        req = ChatRequest(message=case["prompt"], user_role="manager")
        resp = await orchestrator.handle_chat(req)
        candidates = resp.candidates

        if not candidates:
            results_table.append({
                "id": case["id"],
                "desc": case["description"],
                "top1_name": "None",
                "role_ok": False,
                "skill_ok": False,
                "domain_ok": False,
                "sen_ok": False,
                "top1_match": False
            })
            continue

        top1 = candidates[0]
        # Check role match
        r_ok = (case["expected_role"].lower() in top1.role.lower())
        if r_ok:
            role_matches += 1

        # Check skills match
        top1_skills = [s.get("normalized_skill", "") for s in getattr(top1, "skills", [])]
        sk_ok = any(req_s.lower() in [s.lower() for s in top1_skills] for req_s in case["expected_skills"])
        if sk_ok:
            skill_matches += 1

        # Check domain match (if requested)
        d_ok = True
        if case["expected_domain"]:
            d_ok = (top1.primary_domain.lower() == case["expected_domain"].lower())
            if d_ok:
                domain_matches += 1
        else:
            domain_matches += 1

        # Check seniority match
        s_ok = top1.seniority in case["expected_min_seniority"]
        if s_ok:
            seniority_matches += 1

        # Full Top-1 Agreement (Role + Skill + Seniority + Domain if specified)
        top1_ideal = r_ok and sk_ok and s_ok and d_ok
        if top1_ideal:
            top1_agreements += 1

        # Top-3 Agreement (At least 2 out of top 3 are ideal)
        top3_ideal_count = 0
        for cand in candidates[:3]:
            c_r = case["expected_role"].lower() in cand.role.lower()
            c_s = cand.seniority in case["expected_min_seniority"]
            c_d = True if not case["expected_domain"] else (cand.primary_domain.lower() == case["expected_domain"].lower())
            if c_r and c_s and c_d:
                top3_ideal_count += 1
        if top3_ideal_count >= 2:
            top3_agreements += 1

        results_table.append({
            "id": case["id"],
            "desc": case["description"],
            "top1_name": f"{top1.full_name} ({top1.seniority} {top1.role})",
            "role_ok": r_ok,
            "skill_ok": sk_ok,
            "domain_ok": d_ok,
            "sen_ok": s_ok,
            "top1_match": top1_ideal
        })

    print(f"\n{'Case ID':<8} | {'Scenario':<34} | {'Role':<6} | {'Skill':<6} | {'Domain':<6} | {'Seniority':<9} | {'Top-1 Ideal'}")
    print("-" * 88)
    for r in results_table:
        print(f"{r['id']:<8} | {r['desc']:<34} | {str(r['role_ok']):<6} | {str(r['skill_ok']):<6} | {str(r['domain_ok']):<6} | {str(r['sen_ok']):<9} | {str(r['top1_match'])}")

    print("\n" + "=" * 60)
    print("ACCURACY & AGREEMENT METRICS:")
    print("=" * 60)
    print(f"Role Accuracy:          {role_matches / total_cases * 100:.1f}% ({role_matches}/{total_cases})")
    print(f"Skill Alignment Rate:   {skill_matches / total_cases * 100:.1f}% ({skill_matches}/{total_cases})")
    print(f"Domain Alignment Rate:  {domain_matches / total_cases * 100:.1f}% ({domain_matches}/{total_cases})")
    print(f"Seniority Alignment:    {seniority_matches / total_cases * 100:.1f}% ({seniority_matches}/{total_cases})")
    print(f"Top-1 Agreement Rate:   {top1_agreements / total_cases * 100:.1f}% ({top1_agreements}/{total_cases})")
    print(f"Top-3 Agreement Rate:   {top3_agreements / total_cases * 100:.1f}% ({top3_agreements}/{total_cases})")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_evaluation())
