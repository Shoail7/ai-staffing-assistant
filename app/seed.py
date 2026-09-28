import random
from datetime import datetime, timedelta
from faker import Faker
from .db import init_db, get_connection

def seed_database():
    """Seeds the SQLite database with 300 resources, 60 projects, ~900 allocations, and ~1500 skills."""
    # Fix random seeds for complete reproducibility
    random.seed(42)
    Faker.seed(42)
    fake = Faker()

    init_db()
    conn = get_connection()
    cur = conn.cursor()

    # Clear existing data to ensure clean seed
    cur.executescript("""
        DELETE FROM DECISION_LOG;
        DELETE FROM MESSAGES;
        DELETE FROM CONVERSATIONS;
        DELETE FROM PM_RESOURCE_SKILLS;
        DELETE FROM PM_SKILL_ALIASES;
        DELETE FROM PM_RESOURCE_PROJECTS;
        DELETE FROM PM_PROJECTS;
        DELETE FROM PM_RESOURCES;
    """)

    # 1. Seed Skill Aliases
    aliases_data = [
        # Canonical -> Variants
        ("python", "Python"),
        ("python 3", "Python"),
        ("python3", "Python"),
        ("py", "Python"),
        ("react", "React"),
        ("reactjs", "React"),
        ("react.js", "React"),
        ("node", "Node.js"),
        ("nodejs", "Node.js"),
        ("node.js", "Node.js"),
        ("typescript", "TypeScript"),
        ("ts", "TypeScript"),
        ("javascript", "JavaScript"),
        ("js", "JavaScript"),
        ("sql", "SQL"),
        ("postgres", "SQL"),
        ("postgresql", "SQL"),
        ("mysql", "SQL"),
        ("docker", "Docker"),
        ("docker engine", "Docker"),
        ("kubernetes", "Kubernetes"),
        ("k8s", "Kubernetes"),
        ("aws", "AWS"),
        ("aws cloud", "AWS"),
        ("amazon web services", "AWS"),
        ("azure", "Azure"),
        ("microsoft azure", "Azure"),
        ("gcp", "GCP"),
        ("google cloud", "GCP"),
        ("pytorch", "PyTorch"),
        ("torch", "PyTorch"),
        ("tensorflow", "TensorFlow"),
        ("tf", "TensorFlow"),
        ("spark", "Spark"),
        ("apache spark", "Spark"),
        ("airflow", "Airflow"),
        ("apache airflow", "Airflow"),
        ("kafka", "Kafka"),
        ("apache kafka", "Kafka"),
        ("golang", "Go"),
        ("go", "Go"),
        ("java", "Java"),
        ("core java", "Java"),
        ("c#", "C#"),
        (".net", "C#"),
        ("csharp", "C#"),
        ("graphql", "GraphQL"),
        ("mongodb", "MongoDB"),
        ("mongo", "MongoDB"),
        ("redis", "Redis"),
        ("figma", "Figma"),
        ("selenium", "Selenium"),
        ("cypress", "Cypress"),
        ("terraform", "Terraform"),
        ("snowflake", "Snowflake"),
        ("fastapi", "FastAPI"),
        ("django", "Django"),
        ("flask", "Flask"),
        ("rust", "Rust"),
        ("solana", "Solana")
    ]
    cur.executemany("INSERT INTO PM_SKILL_ALIASES (alias, normalized_skill) VALUES (?, ?)", aliases_data)

    # 2. Seed 60 Projects
    domains = ["fintech", "healthcare", "retail", "telecom", "logistics", "education", "gaming"]
    project_names = [
        "Core Banking Modernization", "Fraud Detection Engine", "Clinical Trials Portal",
        "E-Commerce Cart Checkout", "5G Network Slicing Platform", "Fleet Routing Optimizer",
        "Student Learning LMS", "MMORPG Quest Engine", "Algorithmic Trading Bot",
        "HIPAA Patient Gateway", "Supply Chain Inventory Ledger", "Telecom Billing Hub",
        "Omnichannel Loyalty Engine", "Real-Time Telemetry Pipeline", "Mobile Payment Switch",
        "Insurance Claims Automator", "Genomics Analysis Pipeline", "Warehouse Robotics Dispatch",
        "Video Streaming Backend", "Cloud Security Scanner", "Micro-Lending Credit Scorer",
        "Wearables Health Sync", "Retail Recommendation ML", "Automated Load Balancer",
        "Web3 Smart Contract Escrow", "Dynamic Pricing Engine", "Predictive Maintenance Hub",
        "Automated Tax Compliance", "Customer 360 CDP", "AR/VR 3D Asset Pipeline"
    ]
    # Multiply to reach 60 projects
    project_rows = []
    base_date = datetime(2026, 1, 1)
    for i in range(1, 61):
        pid = f"PROJ-{i:03d}"
        name = f"{project_names[(i - 1) % len(project_names)]} Phase {(i % 3) + 1}"
        domain = domains[(i - 1) % len(domains)]
        # Dates span across 2026
        start_offset = random.randint(-180, 60)
        proj_start = base_date + timedelta(days=start_offset)
        duration_days = random.randint(60, 240)
        proj_end = proj_start + timedelta(days=duration_days)
        status = "in_progress" if proj_start <= datetime.now() <= proj_end else ("completed" if proj_end < datetime.now() else "planning")
        project_rows.append((pid, name, domain, proj_start.strftime("%Y-%m-%d"), proj_end.strftime("%Y-%m-%d"), status))

    cur.executemany("""
        INSERT INTO PM_PROJECTS (project_id, name, domain, start_date, end_date, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, project_rows)

    # 3. Seed 300 Resources
    roles = [
        "Backend Dev", "Frontend Dev", "Data Engineer", "ML Engineer",
        "QA", "DevOps", "Designer", "Business Analyst", "Project Manager"
    ]
    seniorities = ["Junior", "Mid", "Senior", "Lead"]
    locations = [
        ("New York, USA", "EST"), ("San Francisco, USA", "PST"),
        ("Austin, USA", "CST"), ("London, UK", "GMT"),
        ("Berlin, Germany", "CET"), ("Toronto, Canada", "EST"),
        ("Bangalore, India", "IST"), ("Singapore", "SGT")
    ]

    resource_rows = []
    resource_ids = []
    for i in range(1, 301):
        rid = f"RES-{i:03d}"
        resource_ids.append(rid)
        name = fake.name()
        email = f"{name.lower().replace(' ', '.')}{i}@consulting.internal"
        role = random.choices(
            roles, 
            weights=[30, 20, 15, 10, 8, 8, 4, 3, 2] # More developers and data engineers
        )[0]
        seniority = random.choices(seniorities, weights=[20, 40, 30, 10])[0]

        # Experience mapped to seniority
        if seniority == "Junior":
            years_exp = round(random.uniform(1.0, 3.0), 1)
            hourly_cost = round(random.uniform(45.0, 75.0), 1)
        elif seniority == "Mid":
            years_exp = round(random.uniform(3.0, 6.0), 1)
            hourly_cost = round(random.uniform(80.0, 120.0), 1)
        elif seniority == "Senior":
            years_exp = round(random.uniform(6.0, 11.0), 1)
            hourly_cost = round(random.uniform(125.0, 170.0), 1)
        else: # Lead
            years_exp = round(random.uniform(10.0, 18.0), 1)
            hourly_cost = round(random.uniform(175.0, 240.0), 1)

        loc, tz = random.choice(locations)
        status = "on_leave" if random.random() < 0.12 else "active"
        primary_domain = random.choice(domains)
        max_alloc = 100.0
        notes = f"Specialized in {primary_domain} solutions. {seniority} level contributor."

        resource_rows.append((
            rid, name, email, role, seniority, years_exp,
            loc, tz, hourly_cost, max_alloc, status, primary_domain, notes
        ))

    cur.executemany("""
        INSERT INTO PM_RESOURCES (
            resource_id, full_name, email, role, seniority, years_experience,
            location, timezone, hourly_cost, max_allocation_pct, status,
            primary_domain, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, resource_rows)

    # 4. Seed ~900 Resource Allocations (PM_RESOURCE_PROJECTS)
    # Target workloads:
    # ~15% fully free or low allocation (0 projects)
    # ~55% healthy load (1-2 projects, 40-80% alloc)
    # ~15% heavy load (2 projects, 80-100% alloc)
    # ~15% burnout risk (3+ concurrent projects, >100% alloc, >45 weekly hours)
    alloc_rows = []
    today = datetime.now()

    for idx, rid in enumerate(resource_ids):
        bucket = idx % 100
        if bucket < 10:
            # Low load: 1 project
            num_projects = 1
        elif bucket < 60:
            # Normal load: 2-3 projects
            num_projects = random.randint(2, 3)
        elif bucket < 80:
            # Heavy load: 3-4 projects
            num_projects = random.randint(3, 4)
        else:
            # Overworked/burnout risk: 4-6 concurrent/overlapping projects
            num_projects = random.randint(4, 6)

        sampled_projs = random.sample(range(1, 61), num_projects)
        for pid_num in sampled_projs:
            pid = f"PROJ-{pid_num:03d}"
            if bucket >= 80:
                # Overworked: high allocation per project
                alloc_pct = round(random.uniform(35.0, 50.0), 0)
                weekly_hours = round(alloc_pct * 0.45, 1) # leads to >45-55 hrs/wk
            elif bucket >= 60:
                alloc_pct = round(random.uniform(30.0, 45.0), 0)
                weekly_hours = round(alloc_pct * 0.4, 1)
            else:
                alloc_pct = round(random.uniform(20.0, 35.0), 0)
                weekly_hours = round(alloc_pct * 0.4, 1)

            p_start = today - timedelta(days=random.randint(20, 150))
            p_end = today + timedelta(days=random.randint(30, 180))
            alloc_rows.append((
                rid, pid, alloc_pct,
                p_start.strftime("%Y-%m-%d"),
                p_end.strftime("%Y-%m-%d"),
                weekly_hours,
                "Core Contributor"
            ))

    cur.executemany("""
        INSERT INTO PM_RESOURCE_PROJECTS (
            resource_id, project_id, allocation_pct, start_date, end_date,
            weekly_hours, role_on_project
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, alloc_rows)

    # 5. Seed ~1,500 Resource Skills (PM_RESOURCE_SKILLS)
    # Role-based skill pools
    role_skill_map = {
        "Backend Dev": [
            ("Python", "Python"), ("Python3", "Python"), ("SQL", "SQL"), ("PostgreSQL", "SQL"),
            ("Docker", "Docker"), ("Kubernetes", "Kubernetes"), ("AWS", "AWS"), ("FastAPI", "FastAPI"),
            ("Django", "Django"), ("Redis", "Redis"), ("Kafka", "Kafka"), ("Go", "Go")
        ],
        "Frontend Dev": [
            ("React", "React"), ("ReactJS", "React"), ("TypeScript", "TypeScript"), ("JavaScript", "JavaScript"),
            ("Figma", "Figma"), ("Node.js", "Node.js"), ("Cypress", "Cypress"), ("GraphQL", "GraphQL")
        ],
        "Data Engineer": [
            ("Python", "Python"), ("SQL", "SQL"), ("Spark", "Spark"), ("Airflow", "Airflow"),
            ("Snowflake", "Snowflake"), ("Kafka", "Kafka"), ("AWS", "AWS"), ("Docker", "Docker")
        ],
        "ML Engineer": [
            ("Python", "Python"), ("PyTorch", "PyTorch"), ("TensorFlow", "TensorFlow"), ("SQL", "SQL"),
            ("Docker", "Docker"), ("AWS", "AWS"), ("Spark", "Spark"), ("FastAPI", "FastAPI")
        ],
        "QA": [
            ("Selenium", "Selenium"), ("Cypress", "Cypress"), ("Python", "Python"), ("JavaScript", "JavaScript"),
            ("SQL", "SQL"), ("Docker", "Docker")
        ],
        "DevOps": [
            ("Docker", "Docker"), ("Kubernetes", "Kubernetes"), ("Terraform", "Terraform"), ("AWS", "AWS"),
            ("Azure", "Azure"), ("Python", "Python"), ("Go", "Go"), ("GCP", "GCP")
        ],
        "Designer": [
            ("Figma", "Figma"), ("UI Design", "Figma"), ("Prototyping", "Figma"), ("JavaScript", "JavaScript")
        ],
        "Business Analyst": [
            ("SQL", "SQL"), ("Data Analysis", "SQL"), ("Agile", "Agile"), ("Figma", "Figma")
        ],
        "Project Manager": [
            ("Agile", "Agile"), ("Scrum", "Agile"), ("JIRA", "JIRA"), ("SQL", "SQL")
        ]
    }

    skill_rows = []
    today_str = today.strftime("%Y-%m-%d")

    for rid, name, email, role, seniority, years_exp, loc, tz, cost, max_alloc, status, domain, notes in resource_rows:
        available_skills = role_skill_map.get(role, role_skill_map["Backend Dev"])
        # Give 4-7 skills per resource
        num_skills = min(len(available_skills), random.randint(4, 7))
        chosen_skills = random.sample(available_skills, num_skills)

        for skill_name, norm_name in chosen_skills:
            if seniority == "Junior":
                proficiency = random.choices([1, 2, 3], weights=[30, 50, 20])[0]
                years_used = round(min(years_exp, random.uniform(0.5, 2.5)), 1)
            elif seniority == "Mid":
                proficiency = random.choices([2, 3, 4], weights=[20, 50, 30])[0]
                years_used = round(min(years_exp, random.uniform(1.5, 4.5)), 1)
            elif seniority == "Senior":
                proficiency = random.choices([3, 4, 5], weights=[20, 50, 30])[0]
                years_used = round(min(years_exp, random.uniform(3.0, 8.0)), 1)
            else: # Lead
                proficiency = random.choices([4, 5], weights=[40, 60])[0]
                years_used = round(min(years_exp, random.uniform(5.0, 12.0)), 1)

            skill_rows.append((
                rid, skill_name, norm_name, proficiency, years_used, today_str
            ))

    cur.executemany("""
        INSERT INTO PM_RESOURCE_SKILLS (
            resource_id, skill_name, normalized_skill, proficiency, years_used, last_used_date
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, skill_rows)

    conn.commit()

    # Print summary counts for verification
    cur.execute("SELECT COUNT(*) FROM PM_RESOURCES")
    res_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM PM_PROJECTS")
    proj_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM PM_RESOURCE_PROJECTS")
    alloc_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM PM_RESOURCE_SKILLS")
    skill_count = cur.fetchone()[0]

    conn.close()
    print(f"Database seeded successfully:")
    print(f"  - PM_RESOURCES: {res_count} rows")
    print(f"  - PM_PROJECTS: {proj_count} rows")
    print(f"  - PM_RESOURCE_PROJECTS: {alloc_count} rows")
    print(f"  - PM_RESOURCE_SKILLS: {skill_count} rows")

if __name__ == "__main__":
    seed_database()
