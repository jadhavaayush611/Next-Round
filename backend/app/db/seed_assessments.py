"""
Curated seed competencies and initial published assessment definitions.
Provides foundational assessment catalog records across all 5 dimensions.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.models.assessment_definition import (
    AssessmentDefinition,
    AssessmentDifficulty,
    AssessmentStatus,
    AssessmentType,
)
from app.models.assessment_task import AssessmentTask, TaskType
from app.models.competency import Competency, CompetencyDimension
from app.models.evaluation_rubric import EvaluationMode, EvaluationRubric
from app.models.skill import Skill
from app.repositories.assessment_definition import AssessmentDefinitionRepository
from app.repositories.competency import CompetencyRepository
from app.repositories.skill import SkillRepository
from app.services.skill_service import SkillService

SEED_COMPETENCIES: list[dict[str, Any]] = [
    {
        "identifier": "comp-py-memory-gil",
        "name": "Python Memory Model and GIL Dynamics",
        "description": "Understanding object allocation, reference counting, cyclic garbage collection, and Global Interpreter Lock concurrency implications.",
        "dimension": CompetencyDimension.KNOWLEDGE,
        "skill_name": "Python",
    },
    {
        "identifier": "comp-fastapi-async-api",
        "name": "Asynchronous REST API Implementation",
        "description": "Building high-throughput, non-blocking HTTP endpoints, dependency injection graphs, and request lifecycle management in FastAPI.",
        "dimension": CompetencyDimension.PRACTICAL_IMPLEMENTATION,
        "skill_name": "FastAPI",
    },
    {
        "identifier": "comp-py-concurrency-debugging",
        "name": "AsyncIO and Threading Bug Diagnosis",
        "description": "Detecting, isolating, and rectifying race conditions, event-loop starvation, and shared-state deadlocks in Python services.",
        "dimension": CompetencyDimension.DEBUGGING_CODE_COMPREHENSION,
        "skill_name": "Python",
    },
    {
        "identifier": "comp-sql-indexing-performance",
        "name": "Relational Indexing and SQL Query Optimization",
        "description": "Analyzing query execution plans, selecting covering B-tree indexes, and eliminating table scans for high-concurrency workloads.",
        "dimension": CompetencyDimension.PRACTICAL_IMPLEMENTATION,
        "skill_name": "SQL",
    },
    {
        "identifier": "comp-sysdesign-cache-invalidation",
        "name": "Distributed Caching and Consistency Tradeoffs",
        "description": "Evaluating write-through, write-back, and cache-aside patterns, stale read tolerances, and stampede mitigation strategies.",
        "dimension": CompetencyDimension.SYSTEM_DESIGN_TRADEOFFS,
        "skill_name": "System Design",
    },
    {
        "identifier": "comp-tech-comm-architecture",
        "name": "Architectural Rationale Articulation",
        "description": "Explaining engineering decisions, constraints, performance boundaries, and trade-offs clearly to technical and cross-functional peers.",
        "dimension": CompetencyDimension.TECHNICAL_COMMUNICATION,
        "skill_name": "System Design",
    },
]

SEED_ASSESSMENTS: list[dict[str, Any]] = [
    {
        "identifier": "python-backend-foundations",
        "version": 1,
        "title": "Python Backend Engineering Foundations",
        "description": "Comprehensive evaluation of asynchronous Python service design, error handling, and robust concurrency practices.",
        "assessment_type": AssessmentType.PRACTICAL_CODING,
        "difficulty": AssessmentDifficulty.INTERMEDIATE,
        "duration_minutes": 45,
        "status": AssessmentStatus.PUBLISHED,
        "tasks": [
            {
                "identifier": "task-async-rate-limiter",
                "order_index": 0,
                "task_type": TaskType.CODING,
                "title": "Sliding Window Rate Limiter",
                "prompt": "Implement an in-memory sliding window rate limiter class `SlidingWindowLimiter` supporting async calls. Ensure non-blocking execution and thread/coroutine safety.",
                "payload": {
                    "language": "python",
                    "starter_code": "class SlidingWindowLimiter:\n    def __init__(self, limit: int, window_seconds: float):\n        pass\n\n    async def allow_request(self, key: str) -> bool:\n        pass\n",
                    "public_test_cases": [
                        {
                            "description": "Allows requests within limit",
                            "limit": 2,
                            "window_seconds": 1.0,
                        }
                    ],
                },
                "task_metadata": {
                    "estimated_time_minutes": 25,
                    "target_language": "python",
                },
                "competency_identifier": "comp-fastapi-async-api",
                "rubric": {
                    "evaluation_mode": EvaluationMode.AUTOMATED,
                    "criteria": [
                        {
                            "criterion_id": "correctness_window_sliding",
                            "name": "Sliding Window Accuracy",
                            "description": "Correctly evicts expired timestamps and accounts for current window capacity.",
                            "eval_type": "CONFORMANCE",
                            "guidelines": [
                                "Timestamps older than window_seconds must not consume quota"
                            ],
                        },
                        {
                            "criterion_id": "concurrency_safety",
                            "name": "Async Concurrency Safety",
                            "description": "Utilizes appropriate async primitives (e.g. asyncio.Lock) to prevent race conditions during state mutation.",
                            "eval_type": "QUALITATIVE",
                            "guidelines": [
                                "No unshielded shared dictionary mutations across concurrent coroutines"
                            ],
                        },
                    ],
                    "rubric_metadata": {
                        "hidden_test_suite": "tests.assessments.hidden.test_rate_limiter_edge_cases",
                        "benchmark_latency_ms": 5.0,
                    },
                },
            },
            {
                "identifier": "task-race-condition-debug",
                "order_index": 1,
                "task_type": TaskType.CODE_ANALYSIS,
                "title": "Asyncio Connection Pool Race Condition",
                "prompt": "Inspect the provided connection pool snippet. Identify the concurrency race condition that causes connection leaks under high contention, and document the resolution.",
                "payload": {
                    "language": "python",
                    "source_code": "class DBConnectionPool:\n    async def acquire(self):\n        if not self._available:\n            await self._create_conn()\n        return self._available.pop()\n",
                },
                "task_metadata": {
                    "estimated_time_minutes": 20,
                    "target_language": "python",
                },
                "competency_identifier": "comp-py-concurrency-debugging",
                "rubric": {
                    "evaluation_mode": EvaluationMode.RUBRIC_SEMI_AUTOMATED,
                    "criteria": [
                        {
                            "criterion_id": "defect_identification",
                            "name": "Defect Root Cause Identification",
                            "description": "Clearly pinpoints the check-then-act race between checking self._available and popping from it.",
                            "eval_type": "QUALITATIVE",
                            "guidelines": [
                                "Must identify that context switch during _create_conn allows other coroutines to drain available pool"
                            ],
                        },
                    ],
                    "rubric_metadata": {
                        "expected_solution_summary": "Atomic check-and-acquire using an asyncio semaphore or bounded queue.",
                    },
                },
            },
        ],
    },
    {
        "identifier": "sql-database-fundamentals",
        "version": 1,
        "title": "PostgreSQL Query Optimization & Indexing",
        "description": "Practical evaluation of SQL indexing strategies, query execution analysis, and constraint design in relational databases.",
        "assessment_type": AssessmentType.PRACTICAL_CODING,
        "difficulty": AssessmentDifficulty.INTERMEDIATE,
        "duration_minutes": 40,
        "status": AssessmentStatus.PUBLISHED,
        "tasks": [
            {
                "identifier": "task-sql-index-optimization",
                "order_index": 0,
                "task_type": TaskType.CODING,
                "title": "Covering Index for Multi-Tenant Orders Query",
                "prompt": "Write a PostgreSQL DDL statement creating an optimal index for the provided multi-tenant orders query, avoiding sequential table scans.",
                "payload": {
                    "language": "sql",
                    "starter_code": "-- Create the optimal index here\nCREATE INDEX ...\n",
                    "public_test_cases": [
                        {
                            "description": "Query plan utilizes Index Scan rather than Seq Scan",
                            "input": "SELECT tenant_id, order_id, total_amount FROM orders WHERE tenant_id = 42 AND created_at >= '2026-01-01' ORDER BY created_at DESC;",
                        }
                    ],
                },
                "task_metadata": {
                    "estimated_time_minutes": 20,
                    "target_language": "sql",
                },
                "competency_identifier": "comp-sql-indexing-performance",
                "rubric": {
                    "evaluation_mode": EvaluationMode.AUTOMATED,
                    "criteria": [
                        {
                            "criterion_id": "composite_index_order",
                            "name": "Composite Index Column Ordering",
                            "description": "Index columns ordered correctly: equality predicate (tenant_id) first, then range/sort predicate (created_at).",
                            "eval_type": "CONFORMANCE",
                            "guidelines": [
                                "Index leading column must be tenant_id",
                                "Second column must be created_at",
                            ],
                        },
                    ],
                    "rubric_metadata": {
                        "benchmark_latency_ms": 2.0,
                    },
                },
            }
        ],
    },
]


def seed_assessment_catalog(db: Session) -> None:
    """
    Idempotently seeds canonical skills, technical competencies, and baseline published assessments.
    Safe to execute multiple times without duplicating or mutating existing records.
    """
    # 1. Ensure canonical skills exist
    skill_service = SkillService(db)
    skill_service.seed_catalog()

    skill_repo = SkillRepository(db)
    # Ensure "System Design" exists as a canonical skill if not seeded
    sys_design_skill = skill_repo.get_by_canonical_name("System Design")
    if not sys_design_skill:
        sys_design_skill = Skill(
            canonical_name="System Design",
            category="Architecture",
            aliases=["distributed systems", "system architecture"],
        )
        db.add(sys_design_skill)
        db.commit()
        db.refresh(sys_design_skill)

    fastapi_skill = skill_repo.get_by_canonical_name("FastAPI")
    if not fastapi_skill:
        fastapi_skill = Skill(
            canonical_name="FastAPI",
            category="Framework",
            aliases=["fast-api"],
        )
        db.add(fastapi_skill)
        db.commit()
        db.refresh(fastapi_skill)

    sql_skill = skill_repo.get_by_canonical_name("SQL")
    if not sql_skill:
        sql_skill = Skill(
            canonical_name="SQL",
            category="Programming Language",
            aliases=["structured query language"],
        )
        db.add(sql_skill)
        db.commit()
        db.refresh(sql_skill)

    # 2. Seed Competencies
    comp_repo = CompetencyRepository(db)
    for comp_entry in SEED_COMPETENCIES:
        existing_comp = comp_repo.get_by_identifier(comp_entry["identifier"])
        if not existing_comp:
            skill = skill_repo.get_by_canonical_name(comp_entry["skill_name"])
            if skill:
                comp = Competency(
                    skill_id=skill.id,
                    identifier=comp_entry["identifier"],
                    name=comp_entry["name"],
                    description=comp_entry["description"],
                    dimension=comp_entry["dimension"],
                    is_active=True,
                )
                db.add(comp)
    db.commit()

    # 3. Seed Assessment Definitions
    def_repo = AssessmentDefinitionRepository(db)
    for assess_entry in SEED_ASSESSMENTS:
        existing_def = def_repo.get_by_identifier_and_version(
            str(assess_entry["identifier"]), int(assess_entry["version"])
        )
        if not existing_def:
            definition = AssessmentDefinition(
                identifier=str(assess_entry["identifier"]),
                version=int(assess_entry["version"]),
                title=str(assess_entry["title"]),
                description=str(assess_entry["description"]),
                assessment_type=assess_entry["assessment_type"],
                difficulty=assess_entry["difficulty"],
                duration_minutes=assess_entry["duration_minutes"],
                status=assess_entry["status"],
            )
            db.add(definition)
            db.flush()

            tasks_list: list[dict[str, Any]] = assess_entry["tasks"]
            for task_data in tasks_list:
                matched_comp = comp_repo.get_by_identifier(
                    str(task_data["competency_identifier"])
                )
                task = AssessmentTask(
                    assessment_definition_id=definition.id,
                    competency_id=matched_comp.id if matched_comp else None,
                    identifier=str(task_data["identifier"]),
                    order_index=int(task_data["order_index"]),
                    task_type=task_data["task_type"],
                    title=str(task_data["title"]),
                    prompt=str(task_data["prompt"]),
                    payload=task_data["payload"],
                    task_metadata=task_data["task_metadata"],
                )
                db.add(task)
                db.flush()

                rubric_data: dict[str, Any] | None = task_data.get("rubric")
                if rubric_data:
                    rubric = EvaluationRubric(
                        task_id=task.id,
                        evaluation_mode=rubric_data["evaluation_mode"],
                        criteria=rubric_data["criteria"],
                        rubric_metadata=rubric_data["rubric_metadata"],
                    )
                    db.add(rubric)

    db.commit()
