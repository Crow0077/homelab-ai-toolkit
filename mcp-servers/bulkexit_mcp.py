#!/usr/bin/env python3
"""
Bulk Exit — Cloud Migration Analysis MCP Server
================================================
AI-assisted cloud vendor lock-in analysis and migration planning.

Architecture:
  - Lock-in knowledge base: patterns for AWS, GCP, Azure
  - Egress cost calculator: estimates data transfer costs for migration
  - Alternative mapper: suggests equivalent services on competing platforms
  - Migration planner: generates phased migration strategy

Wiki synthesis:
  - aws-exodus-return-experience: all the pain points mapped
  - bulk-solving: L1-L5 framework applied to cloud lock-in
  - for-profit-career-structure: enterprise problem, enterprise customer
  - MCP Apps: could ship as interactive widget for cloud billing analysis

Tools:
  - bukexit_analyze: Analyze a service list for lock-in risks
  - bukexit_egress: Calculate egress costs for migration
  - bukexit_alternatives: Suggest alternative services
  - bukexit_plan: Generate phased migration plan
  - bukexit_risk: Score lock-in severity (0-100)
"""

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("bukexit")

# ── Lock-in Knowledge Base ───────────────────────────────────────────

# Services ranked by lock-in severity (0-100) based on:
# - Portability difficulty
# - Proprietary API surface
# - Data egress costs
# - Operational coupling
LOCKIN_DB = {
    # HIGH lock-in (70-100): nearly impossible to migrate without full rewrite
    "DynamoDB": {
        "severity": 95,
        "category": "database",
        "why": "Proprietary NoSQL API. No direct equivalent. Single-table design patterns are DynamoDB-specific. Migration requires schema redesign + data transformation + application rewrite.",
        "alternatives": {"gcp": "Firestore / Bigtable", "azure": "Cosmos DB", "self_hosted": "Cassandra / ScyllaDB"},
        "migration_difficulty": "extreme",
    },
    "Lambda": {
        "severity": 85,
        "category": "compute",
        "why": "Proprietary event model (API Gateway, S3 triggers, DynamoDB streams). Cold starts, 15-min timeout, layers, custom runtimes — all AWS-specific. Migration means rewriting to Cloud Run / Azure Functions with different trigger model.",
        "alternatives": {"gcp": "Cloud Run / Cloud Functions", "azure": "Azure Functions", "self_hosted": "Knative / OpenFaaS"},
        "migration_difficulty": "hard",
    },
    "SQS": {
        "severity": 60,
        "category": "messaging",
        "why": "Proprietary queue semantics (visibility timeout, FIFO ordering, dead-letter queues). Moderate lock-in — most message brokers have equivalent features.",
        "alternatives": {"gcp": "Cloud Pub/Sub", "azure": "Service Bus", "self_hosted": "RabbitMQ / Kafka"},
        "migration_difficulty": "moderate",
    },
    "SNS": {
        "severity": 55,
        "category": "messaging",
        "why": "Pub/sub with AWS-specific integrations (SMS, email, Lambda, SQS). Topic/filter policies are AWS-specific.",
        "alternatives": {"gcp": "Cloud Pub/Sub", "azure": "Event Grid", "self_hosted": "NATS / Redis Pub/Sub"},
        "migration_difficulty": "moderate",
    },
    "RDS": {
        "severity": 40,
        "category": "database",
        "why": "Managed MySQL/PostgreSQL. Moderate lock-in — data is portable (pg_dump), but automation (snapshots, read replicas, parameter groups) is AWS-specific.",
        "alternatives": {"gcp": "Cloud SQL", "azure": "Azure Database", "self_hosted": "PostgreSQL / MySQL"},
        "migration_difficulty": "easy",
    },
    "EC2": {
        "severity": 25,
        "category": "compute",
        "why": "Standard VMs. Low lock-in — AMIs are AWS-specific but OS images are portable. Networking config (VPC, security groups) is AWS-specific.",
        "alternatives": {"gcp": "Compute Engine", "azure": "Azure VMs", "self_hosted": "KVM / Proxmox"},
        "migration_difficulty": "easy",
    },
    "S3": {
        "severity": 35,
        "category": "storage",
        "why": "Object storage with AWS-specific API. Data is portable (standard formats) but S3 API calls, bucket policies, lifecycle rules, versioning semantics are AWS-specific.",
        "alternatives": {"gcp": "Cloud Storage", "azure": "Blob Storage", "self_hosted": "MinIO / Ceph"},
        "migration_difficulty": "easy",
    },
    "Route 53": {
        "severity": 30,
        "category": "networking",
        "why": "DNS service. Low lock-in technically, but domain transfers can take days and email (WorkMail) is tied to it.",
        "alternatives": {"gcp": "Cloud DNS", "azure": "Azure DNS", "self_hosted": "Bind / PowerDNS"},
        "migration_difficulty": "easy",
    },
    "IAM": {
        "severity": 70,
        "category": "security",
        "why": "Deeply integrated auth system. Roles, policies, trust relationships, instance profiles — all AWS-specific. Every service depends on IAM. Migration means re-architecting the entire auth layer.",
        "alternatives": {"gcp": "Cloud IAM", "azure": "Entra ID", "self_hosted": "Keycloak / Okta"},
        "migration_difficulty": "hard",
    },
    "API Gateway": {
        "severity": 65,
        "category": "networking",
        "why": "REST/HTTP API management with AWS-specific integrations (Lambda, Cognito, WAF). API definitions are somewhat portable (OpenAPI) but the backend wiring is not.",
        "alternatives": {"gcp": "API Gateway / Apigee", "azure": "API Management", "self_hosted": "Kong / Traefik"},
        "migration_difficulty": "moderate",
    },
    "CloudFront": {
        "severity": 20,
        "category": "networking",
        "why": "CDN. Low lock-in — CDN is a commodity. Cache invalidation, origin shield, Lambda@Edge are AWS-specific but standard CDN features exist elsewhere.",
        "alternatives": {"gcp": "Cloud CDN", "azure": "Azure CDN", "self_hosted": "Cloudflare"},
        "migration_difficulty": "easy",
    },
    "EKS": {
        "severity": 30,
        "category": "compute",
        "why": "Managed Kubernetes. Moderate lock-in — Kubernetes is portable but EKS-specific addons (CSI drivers, CNI, IAM roles for service accounts) need replacement.",
        "alternatives": {"gcp": "GKE", "azure": "AKS", "self_hosted": "k3s / OpenShift"},
        "migration_difficulty": "easy",
    },
    "Bedrock": {
        "severity": 60,
        "category": "ai_ml",
        "why": "Managed AI model access. Models are available elsewhere (Claude via Anthropic directly, Llama via Replicate), pricing differs significantly. Bedrock API is AWS-specific.",
        "alternatives": {"gcp": "Vertex AI", "azure": "Azure AI Foundry", "self_hosted": "Ollama / vLLM"},
        "migration_difficulty": "moderate",
    },
    "WorkMail": {
        "severity": 75,
        "category": "productivity",
        "why": "Business email. Shutting down in 2026. Data export is possible but email history, contacts, calendar are bundled. Migration means moving to Google Workspace or Microsoft 365 with weeks of planning.",
        "alternatives": {"gcp": "Google Workspace", "azure": "Microsoft 365", "self_hosted": "Zimbra / Mailcow"},
        "migration_difficulty": "hard",
    },
}

CATEGORIES = {
    "compute": "EC2, Lambda, ECS, EKS, Fargate",
    "database": "RDS, DynamoDB, ElastiCache, Redshift, DocumentDB",
    "storage": "S3, EBS, EFS, Glacier",
    "networking": "VPC, CloudFront, Route 53, API Gateway, ELB",
    "messaging": "SQS, SNS, EventBridge, Kinesis",
    "security": "IAM, Cognito, WAF, KMS, Secrets Manager",
    "ai_ml": "Bedrock, SageMaker, Rekognition, Comprehend",
    "productivity": "WorkMail, WorkDocs, Chime",
}

# ── Egress Cost Calculator ───────────────────────────────────────────

EGRESS_RATES = {
    "aws": [
        {"tier_gb": 10, "rate_per_gb": 0.00},      # First 10 TB/month: free tier
        {"tier_gb": 40, "rate_per_gb": 0.09},       # Next 40 TB
        {"tier_gb": 100, "rate_per_gb": 0.085},     # Next 100 TB
        {"tier_gb": float("inf"), "rate_per_gb": 0.07},
    ],
    "gcp": [
        {"tier_gb": 1, "rate_per_gb": 0.00},
        {"tier_gb": float("inf"), "rate_per_gb": 0.08},  # Network Internet Egress
    ],
    "azure": [
        {"tier_gb": 100, "rate_per_gb": 0.00},       # First 100 GB/month free
        {"tier_gb": float("inf"), "rate_per_gb": 0.087},
    ],
}

def calculate_egress_cost(data_gb: float, provider: str = "aws") -> dict:
    """Calculate egress cost for migrating data OFF a provider."""
    rates = EGRESS_RATES.get(provider, EGRESS_RATES["aws"])
    remaining = data_gb
    total_cost = 0.0
    tier_details = []
    
    for i, tier in enumerate(rates):
        prev_cumulative = sum(t["tier_gb"] for t in rates[:i]) if i > 0 else 0
        tier_size = min(tier["tier_gb"], remaining)
        
        if tier_size <= 0:
            break
        
        cost = tier_size * tier["rate_per_gb"]
        total_cost += cost
        tier_details.append({
            "tier": f"{prev_cumulative:.0f}-{prev_cumulative + tier['tier_gb']:.0f} GB" if tier["tier_gb"] < float("inf") else f">{prev_cumulative:.0f} GB",
            "amount_gb": round(tier_size, 1),
            "rate": tier["rate_per_gb"],
            "cost": round(cost, 2),
        })
        
        remaining -= tier_size
        if remaining <= 0:
            break
    
    return {
        "provider": provider,
        "total_data_gb": data_gb,
        "total_cost_usd": round(total_cost, 2),
        "effective_rate_per_gb": round(total_cost / max(data_gb, 1), 4),
        "tiers": tier_details,
        "note": "Data transfer IN is usually free. Egress costs apply to data leaving the provider." if provider == "aws" else "",
    }

# ── MCP Tools ────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="bukexit_analyze",
            description="Analyze a list of cloud services for lock-in risk. Input service names (comma-separated) and get severity scores, reasons, and migration difficulty per service.",
            inputSchema={
                "type": "object",
                "properties": {
                    "services": {
                        "type": "string",
                        "description": "Comma-separated list of AWS service names (e.g., 'DynamoDB,Lambda,S3,RDS,EC2')"
                    }
                },
                "required": ["services"]
            }
        ),
        Tool(
            name="bukexit_egress",
            description="Calculate data egress costs for migrating data OFF a cloud provider. Input data size in GB and provider.",
            inputSchema={
                "type": "object",
                "properties": {
                    "data_gb": {
                        "type": "number",
                        "description": "Total data to migrate in gigabytes"
                    },
                    "provider": {
                        "type": "string",
                        "description": "Cloud provider: aws, gcp, azure",
                        "default": "aws"
                    }
                },
                "required": ["data_gb"]
            }
        ),
        Tool(
            name="bukexit_alternatives",
            description="Get migration alternatives for a specific AWS service. Shows equivalent services on GCP, Azure, and self-hosted options.",
            inputSchema={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "AWS service name (e.g., 'DynamoDB', 'Lambda', 'S3')"
                    }
                },
                "required": ["service"]
            }
        ),
        Tool(
            name="bukexit_plan",
            description="Generate a phased migration plan for a list of services, ordered by least-to-most risky. Low lock-in services first, high lock-in last.",
            inputSchema={
                "type": "object",
                "properties": {
                    "services": {
                        "type": "string",
                        "description": "Comma-separated list of services to migrate"
                    }
                },
                "required": ["services"]
            }
        ),
        Tool(
            name="bukexit_risk",
            description="Overall vendor lock-in risk score (0-100). Aggregates severity across all services, weighted by lock-in difficulty.",
            inputSchema={
                "type": "object",
                "properties": {
                    "services": {
                        "type": "string",
                        "description": "Comma-separated list of services in use"
                    }
                },
                "required": ["services"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    
    if name == "bukexit_analyze":
        services = [s.strip() for s in arguments["services"].split(",")]
        
        output = "## 🔓 Bulk Exit — Lock-in Analysis\n\n"
        output += "| Service | Severity | Difficulty | Why |\n"
        output += "|---------|----------|------------|-----|\n"
        
        found = 0
        total_severity = 0
        for svc in services:
            info = LOCKIN_DB.get(svc)
            if info:
                sev_icon = "🔴" if info["severity"] >= 70 else ("🟡" if info["severity"] >= 40 else "🟢")
                output += f"| {sev_icon} {svc} | {info['severity']}/100 | {info['migration_difficulty']} | {info['why'][:80]}... |\n"
                total_severity += info["severity"]
                found += 1
            else:
                output += f"| ❓ {svc} | ? | unknown | Not in lock-in database. May be low-risk or proprietary. |\n"
        
        avg_sev = total_severity / max(found, 1)
        output += f"\n**Services analyzed:** {found}\n"
        output += f"**Average lock-in severity:** {avg_sev:.0f}/100\n"
        
        if avg_sev >= 70:
            output += "\n⚠️ **HIGH LOCK-IN** — Migration will be expensive and slow. Consider a phased approach over 6-12 months.\n"
        elif avg_sev >= 40:
            output += "\n⚡ **MODERATE LOCK-IN** — Migration is feasible but requires planning. Budget 3-6 months.\n"
        else:
            output += "\n✅ **LOW LOCK-IN** — Migration is straightforward. Most services have direct equivalents.\n"
        
        return [TextContent(type="text", text=output)]
    
    elif name == "bukexit_egress":
        data_gb = arguments["data_gb"]
        provider = arguments.get("provider", "aws")
        result = calculate_egress_cost(data_gb, provider)
        
        output = f"## 💸 Egress Cost — {provider.upper()}\n\n"
        output += f"**Data to migrate:** {data_gb:.1f} GB\n"
        output += f"**Estimated cost:** ${result['total_cost_usd']:,.2f}\n"
        output += f"**Effective rate:** ${result['effective_rate_per_gb']:.4f}/GB\n\n"
        output += "### Tier Breakdown\n\n"
        output += "| Tier | Amount | Rate | Cost |\n"
        output += "|------|--------|------|------|\n"
        for t in result["tiers"]:
            output += f"| {t['tier']} | {t['amount_gb']} GB | ${t['rate']}/GB | ${t['cost']:,.2f} |\n"
        
        if result.get("note"):
            output += f"\n📝 {result['note']}\n"
        
        output += f"\n**Comparison:**\n"
        for p in ["aws", "gcp", "azure"]:
            if p != provider:
                comp = calculate_egress_cost(data_gb, p)
                output += f"- {p.upper()} egress: ${comp['total_cost_usd']:,.2f} (${comp['effective_rate_per_gb']:.4f}/GB)\n"
        
        return [TextContent(type="text", text=output)]
    
    elif name == "bukexit_alternatives":
        service = arguments["service"]
        info = LOCKIN_DB.get(service)
        
        if not info:
            return [TextContent(type="text", text=f"Unknown service: {service}. Known services: {', '.join(sorted(LOCKIN_DB.keys()))}")]
        
        output = f"## 🔄 Alternatives for {service}\n\n"
        output += f"**Lock-in severity:** {info['severity']}/100 ({info['migration_difficulty']})\n"
        output += f"**Why it locks you in:** {info['why']}\n\n"
        output += "### Equivalent Services\n\n"
        output += "| Platform | Service |\n"
        output += "|----------|--------|\n"
        for platform, alt in info["alternatives"].items():
            plat_name = {"gcp": "Google Cloud", "azure": "Microsoft Azure", "self_hosted": "Self-Hosted"}.get(platform, platform)
            output += f"| {plat_name} | {alt} |\n"
        
        output += f"\n**Migration difficulty:** {info['migration_difficulty'].upper()}\n"
        
        return [TextContent(type="text", text=output)]
    
    elif name == "bukexit_plan":
        services = [s.strip() for s in arguments["services"].split(",")]
        
        # Sort by severity: easiest first
        sorted_services = sorted(services, key=lambda s: LOCKIN_DB.get(s, {}).get("severity", 50))
        
        output = "## 📋 Migration Plan — Phased by Risk\n\n"
        output += "**Strategy:** Migrate low-lock-in services first (quick wins, build confidence).\n"
        output += "Leave high-lock-in services for last (require rewrite, need experience).\n\n"
        
        phases = {"easy": [], "moderate": [], "hard": [], "extreme": []}
        for svc in sorted_services:
            info = LOCKIN_DB.get(svc)
            if not info:
                continue
            phases[info["migration_difficulty"]].append(svc)
        
        phase_num = 1
        for difficulty in ["easy", "moderate", "hard", "extreme"]:
            if not phases[difficulty]:
                continue
            
            time_est = {"easy": "1-2 weeks", "moderate": "2-4 weeks", "hard": "1-2 months", "extreme": "2-4 months"}
            
            output += f"### Phase {phase_num}: {difficulty.upper()} services ({time_est[difficulty]})\n\n"
            output += "| Service | Severity | Alternative |\n"
            output += "|---------|----------|-------------|\n"
            
            for svc in phases[difficulty]:
                info = LOCKIN_DB[svc]
                alt = info["alternatives"].get("self_hosted", info["alternatives"].get("gcp", "?"))
                output += f"| {svc} | {info['severity']}/100 | {alt} |\n"
            
            output += "\n"
            phase_num += 1
        
        output += "---\n"
        output += "💡 **Tip:** Start with S3 + EC2 + RDS. These are the easiest to migrate and represent the bulk of most workloads.\n"
        output += "⚠️ **Warning:** Save DynamoDB + Lambda for last. These require application rewrites.\n"
        
        return [TextContent(type="text", text=output)]
    
    elif name == "bukexit_risk":
        services = [s.strip() for s in arguments["services"].split(",")]
        
        total_severity = 0
        max_severity = 0
        hard_services = []
        
        for svc in services:
            info = LOCKIN_DB.get(svc)
            if info:
                total_severity += info["severity"]
                max_severity = max(max_severity, info["severity"])
                if info["migration_difficulty"] in ("hard", "extreme"):
                    hard_services.append(svc)
        
        # Weighted risk: average severity + penalty for high-lock-in services
        n = max(len(services), 1)
        avg = total_severity / n
        penalty = len(hard_services) * 10  # Each hard service adds 10 points penalty
        risk_score = min(100, avg + penalty * 0.3)
        
        output = f"## 🎯 Bulk Exit Risk Score\n\n"
        output += f"### Risk: {risk_score:.0f}/100\n\n"
        
        if risk_score >= 70:
            output += "🔴 **CRITICAL** — Deeply locked in. Migration will require 6-12 months and significant re-architecture.\n\n"
        elif risk_score >= 40:
            output += "🟡 **SIGNIFICANT** — Moderate lock-in. Migration is achievable in 3-6 months with planning.\n\n"
        else:
            output += "🟢 **MANAGEABLE** — Low lock-in. Migration is mostly lift-and-shift.\n\n"
        
        output += f"- **Average severity:** {avg:.0f}/100\n"
        output += f"- **Max severity:** {max_severity}/100\n"
        output += f"- **Hard-to-migrate services:** {len(hard_services)} ({', '.join(hard_services) if hard_services else 'none'})\n"
        output += f"- **Penalty:** +{penalty * 0.3:.0f} points for {len(hard_services)} hard services\n"
        
        if hard_services:
            output += f"\n⚠️ These services will be the most expensive to migrate:\n"
            for svc in hard_services:
                info = LOCKIN_DB[svc]
                output += f"  - **{svc}** ({info['severity']}/100): {info['why'][:100]}...\n"
        
        return [TextContent(type="text", text=output)]
    
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
