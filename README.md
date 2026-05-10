# Homelab AI Toolkit

Production AI infrastructure tools built on a 13-container homelab running Hermes Agent. Every tool here runs on real infrastructure 24/7.

## Projects

### Homelab Immune System (`mcp-servers/immune_mcp.py`)
Autonomous self-healing infrastructure inspired by the human immune system. Four independent detection channels (HTTP, container state, system resources, logs). Quorum sensing requires 2+ channels to agree before acting. Treg arbitrator prevents false-positive restarts.

**Implements AI Insurance Controls 2, 4, and 5:** multi-channel monitoring, guardrail enforcement, human escalation pipeline.

### Bulk Exit (`mcp-servers/bulkexit_mcp.py`)
AI-assisted cloud vendor lock-in analysis. Scores 13 AWS services for lock-in severity (0-100). Multi-tier egress cost calculator for AWS/GCP/Azure. Phased migration planner.

### Hurst Signal Combiner (`trading-tools/hurst_combiner.py`)
Medallion-inspired multi-signal trading engine. Computes Hurst exponents for 6 signal types via R/S analysis. Groups signals by persistent/random/mean-reverting regimes. Same-regime signals compound with bonus weighting.

### Agent Amnesia Detector (`trading-tools/aad.py`)
Context degradation detector for AI agent sessions. Analyzes embedding similarity across early/mid/late session chunks. Detects accelerating degradation before the agent fails.

## Infrastructure

- **Node A:** Dell OptiPlex 7090 SFF, Fedora Server 43, 32GB RAM
- **Agent runtime:** Hermes Agent (DeepSeek V4 Pro)
- **Container fleet:** 13 Podman containers (Firecrawl, n8n, Prometheus, Grafana, Uptime Kuma, Dozzle, Homepage)
- **MCP servers:** 9 total, 60+ tools
- **Wiki:** 162-page interlinked knowledge base

## Career Context

Building toward AI Platform Engineer. These tools demonstrate enterprise AI infrastructure patterns at homelab scale: self-healing systems, multi-signal monitoring, agent evaluation, cloud migration analysis.
