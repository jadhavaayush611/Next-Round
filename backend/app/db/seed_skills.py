"""
Curated seed catalog for backend and software engineering placement skills.
Provides stable canonical identities and known aliases for deterministic lookup.
"""

from typing import TypedDict


class SeedSkillEntry(TypedDict):
    canonical_name: str
    category: str
    aliases: list[str]


SEED_SKILLS: list[SeedSkillEntry] = [
    # Programming Languages
    {
        "canonical_name": "Python",
        "category": "Programming Language",
        "aliases": ["py", "python3"],
    },
    {
        "canonical_name": "Go",
        "category": "Programming Language",
        "aliases": ["golang"],
    },
    {
        "canonical_name": "Java",
        "category": "Programming Language",
        "aliases": ["java8", "java11", "java17", "java21"],
    },
    {
        "canonical_name": "Kotlin",
        "category": "Programming Language",
        "aliases": [],
    },
    {
        "canonical_name": "Rust",
        "category": "Programming Language",
        "aliases": ["rustlang"],
    },
    {
        "canonical_name": "TypeScript",
        "category": "Programming Language",
        "aliases": ["ts"],
    },
    {
        "canonical_name": "JavaScript",
        "category": "Programming Language",
        "aliases": ["js", "ecmascript"],
    },
    {
        "canonical_name": "C++",
        "category": "Programming Language",
        "aliases": ["cpp"],
    },
    {
        "canonical_name": "C#",
        "category": "Programming Language",
        "aliases": ["csharp", "dotnet c#"],
    },
    {
        "canonical_name": "SQL",
        "category": "Programming Language",
        "aliases": ["structured query language"],
    },
    # Frameworks & Libraries
    {
        "canonical_name": "FastAPI",
        "category": "Framework",
        "aliases": ["fast-api"],
    },
    {
        "canonical_name": "Django",
        "category": "Framework",
        "aliases": [],
    },
    {
        "canonical_name": "Flask",
        "category": "Framework",
        "aliases": [],
    },
    {
        "canonical_name": "Spring Boot",
        "category": "Framework",
        "aliases": ["springboot", "spring-boot"],
    },
    {
        "canonical_name": "Node.js",
        "category": "Framework",
        "aliases": ["nodejs", "node"],
    },
    {
        "canonical_name": "Express.js",
        "category": "Framework",
        "aliases": ["express", "expressjs"],
    },
    {
        "canonical_name": ".NET",
        "category": "Framework",
        "aliases": ["dotnet", ".net core"],
    },
    # Databases & Storage
    {
        "canonical_name": "PostgreSQL",
        "category": "Database",
        "aliases": ["postgres", "pgsql", "psql"],
    },
    {
        "canonical_name": "MySQL",
        "category": "Database",
        "aliases": [],
    },
    {
        "canonical_name": "Redis",
        "category": "Database",
        "aliases": [],
    },
    {
        "canonical_name": "MongoDB",
        "category": "Database",
        "aliases": ["mongo"],
    },
    {
        "canonical_name": "SQLite",
        "category": "Database",
        "aliases": ["sqlite3"],
    },
    {
        "canonical_name": "Elasticsearch",
        "category": "Database",
        "aliases": ["elastic", "es"],
    },
    # DevOps, Cloud & Tools
    {
        "canonical_name": "Docker",
        "category": "DevOps & Infrastructure",
        "aliases": ["dockerfile", "containerization"],
    },
    {
        "canonical_name": "Kubernetes",
        "category": "DevOps & Infrastructure",
        "aliases": ["k8s"],
    },
    {
        "canonical_name": "Git",
        "category": "DevOps & Infrastructure",
        "aliases": ["git-vcs"],
    },
    {
        "canonical_name": "Linux",
        "category": "DevOps & Infrastructure",
        "aliases": ["unix"],
    },
    {
        "canonical_name": "AWS",
        "category": "DevOps & Infrastructure",
        "aliases": ["amazon web services"],
    },
    {
        "canonical_name": "GCP",
        "category": "DevOps & Infrastructure",
        "aliases": ["google cloud", "google cloud platform"],
    },
    {
        "canonical_name": "CI/CD",
        "category": "DevOps & Infrastructure",
        "aliases": ["cicd", "continuous integration"],
    },
    # Architecture & Concepts
    {
        "canonical_name": "REST API",
        "category": "Architecture & Concepts",
        "aliases": ["rest", "restful", "restful api"],
    },
    {
        "canonical_name": "GraphQL",
        "category": "Architecture & Concepts",
        "aliases": ["gql"],
    },
    {
        "canonical_name": "gRPC",
        "category": "Architecture & Concepts",
        "aliases": [],
    },
    {
        "canonical_name": "Kafka",
        "category": "Architecture & Concepts",
        "aliases": ["apache kafka"],
    },
    {
        "canonical_name": "RabbitMQ",
        "category": "Architecture & Concepts",
        "aliases": [],
    },
    {
        "canonical_name": "Microservices",
        "category": "Architecture & Concepts",
        "aliases": ["microservice architecture"],
    },
]
