#!/usr/bin/env python3
"""
Homelab Immune System (HIS) MCP Server
======================================
Autonomous self-healing infrastructure inspired by the immune system.

Architecture:
  - Multi-channel health checks (HTTP, container status, system resources, logs)
  - Each channel = "immune cell" producing a confidence signal (IL-2 analogue)
  - Treg arbitrator prevents false positives (mob mentality suppression)
  - Quorum sensing: requires consensus across channels before acting
  - Immune memory: tracks past incidents, prevents thrashing (restart loops)
  - Auto-heal: restarts containers only when quorum threshold is met

Wiki synthesis:
  - quorum-sensing-immunity (IL-2 as consensus signal, Treg arbiter)
  - information-based-immunity (multi-channel detection, no single point of failure)
  - ouroboros-principle (memory prevents repeated mistakes)
  - datadog-production-agents (proactive over reactive, eval every action)
  - homelab-architecture (the actual container fleet being monitored)

Tools:
  - immune_diagnose: Full multi-channel health scan with confidence scores
  - immune_heal: Auto-heal a service (restart if quorum confirms it's truly down)
  - immune_quorum: Show current quorum state — which channels agree
  - immune_history: Show past incidents and healing actions
  - immune_treg: Treg report — what was suppressed and why
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import httpx

server = Server("immune")

STATE_DIR = Path.home() / ".cache" / "immune"
STATE_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = STATE_DIR / "history.json"
TREG_FILE = STATE_DIR / "treg_suppressions.json"

# ── Immune memory (persistent) ──────────────────────────────────────

def load_json(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []

def save_json(path: Path, data: list) -> None:
    path.write_text(json.dumps(data, indent=2))

# ── Shell / HTTP helpers ─────────────────────────────────────────────

async def run_cmd(cmd: str) -> tuple[str, str, int]:
    proc = await asyncio.create_subprocess_shell(
        cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return stdout.decode().strip(), stderr.decode().strip(), proc.returncode

async def check_http(url: str, timeout: int = 5) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            elapsed = resp.elapsed.total_seconds()
            return {"status": "up", "code": resp.status_code, "latency_ms": round(elapsed * 1000)}
    except Exception as e:
        return {"status": "down", "error": str(e)[:120]}

# ── Immune channels ──────────────────────────────────────────────────

SERVICES = {
    "n8n":              {"http": "http://localhost:5678",   "container": "n8n"},
    "firecrawl-api":    {"http": "http://localhost:3002",   "container": "firecrawl-api"},
    "uptime-kuma":      {"http": "http://localhost:3001",   "container": "uptime-kuma"},
    "grafana":          {"http": "http://localhost:3003",   "container": "grafana"},
    "prometheus":       {"http": "http://localhost:9091",   "container": "prometheus"},
    "homepage":         {"http": "http://localhost:3000",   "container": "homepage"},
    "dozzle":           {"http": "http://localhost:8080",   "container": "dozzle"},
}

async def channel_http(service_name: str, url: str) -> dict:
    """Channel 1: HTTP health check. Returns confidence 1.0 if up, 0.0 if down."""
    result = await check_http(url)
    if result["status"] == "up":
        return {
            "channel": "http",
            "status": "up",
            "confidence": 1.0,
            "detail": f"HTTP {result['code']} ({result['latency_ms']}ms)"
        }
    return {
        "channel": "http",
        "status": "down",
        "confidence": 0.0,
        "detail": result.get("error", "unknown")
    }

async def channel_container(container_name: str) -> dict:
    """Channel 2: Container runtime check via podman inspect."""
    stdout, stderr, rc = await run_cmd(
        f"podman inspect --format '{{{{.State.Running}}}}|{{{{.State.StartedAt}}}}|{{{{.State.RestartCount}}}}' {container_name}"
    )
    if rc != 0:
        return {"channel": "container", "status": "down", "confidence": 0.0, "detail": "container not found"}
    
    parts = stdout.split("|")
    running = parts[0] == "true" if parts else False
    restarts = int(parts[2]) if len(parts) > 2 else 0
    
    if running:
        # High restarts = degraded confidence (thrashing)
        if restarts > 3:
            return {"channel": "container", "status": "degraded", "confidence": 0.3, 
                    "detail": f"running but {restarts} restarts (thrashing)"}
        return {"channel": "container", "status": "up", "confidence": 1.0, 
                "detail": f"running (started {parts[1][:19] if len(parts) > 1 else '?'})"}
    return {"channel": "container", "status": "down", "confidence": 0.0, "detail": "not running"}

async def channel_system() -> dict:
    """Channel 3: System resource pressure. Low confidence if resources are strained."""
    stdout, _, _ = await run_cmd("free | grep Mem | awk '{print $3/$2 * 100}'")
    try:
        mem_pct = float(stdout)
    except (ValueError, TypeError):
        mem_pct = 50
    
    stdout2, _, _ = await run_cmd("df -h / | tail -1 | awk '{print $5}' | tr -d '%'")
    try:
        disk_pct = float(stdout2)
    except (ValueError, TypeError):
        disk_pct = 50
    
    # Confidence drops when resources are tight
    mem_conf = max(0.0, 1.0 - (mem_pct / 95))  # 0% at 95%+ usage
    disk_conf = max(0.0, 1.0 - (disk_pct / 95))
    system_conf = min(mem_conf, disk_conf)
    
    return {
        "channel": "system",
        "status": "healthy" if system_conf > 0.5 else "strained",
        "confidence": round(system_conf, 2),
        "detail": f"RAM {mem_pct:.0f}%, Disk {disk_pct:.0f}%"
    }

async def channel_logs(container_name: str) -> dict:
    """Channel 4: Recent log error scan."""
    stdout, _, rc = await run_cmd(
        f"podman logs --tail 50 {container_name} 2>&1 | grep -ciE 'error|fatal|panic|traceback|crash' || echo 0"
    )
    try:
        errors = int(stdout.strip())
    except ValueError:
        errors = 0
    
    if errors >= 10:
        return {"channel": "logs", "status": "degraded", "confidence": 0.1, 
                "detail": f"{errors} errors in last 50 lines"}
    elif errors >= 3:
        return {"channel": "logs", "status": "degraded", "confidence": 0.4, 
                "detail": f"{errors} errors in last 50 lines"}
    elif errors > 0:
        return {"channel": "logs", "status": "ok", "confidence": 0.8, 
                "detail": f"{errors} errors"}
    return {"channel": "logs", "status": "clean", "confidence": 1.0, "detail": "no errors"}

# ── Treg Arbitrator ──────────────────────────────────────────────────

def treg_arbitrate(channel_results: list[dict]) -> dict:
    """
    Treg cell analogue: prevents false-positive healing actions.
    
    Rules:
    1. Must have 2+ channels reporting "down" to confirm a true failure
    2. If only 1 channel says "down" and others say "up", this is likely a transient blip → suppress
    3. Average confidence across all channels must be < 0.3 to auto-heal
    4. If container is thrashing (high restart count), suppress healing (let it rest)
    """
    downs = [c for c in channel_results if c["status"] == "down"]
    ups = [c for c in channel_results if c["status"] == "up"]
    degraded = [c for c in channel_results if c["status"] == "degraded"]
    avg_conf = sum(c["confidence"] for c in channel_results) / max(len(channel_results), 1)
    
    # Check for thrashing
    thrashing_channel = next((c for c in channel_results if "thrashing" in c.get("detail", "")), None)
    
    quorum_down = len(downs) >= 2
    quorum_ok = len(ups) >= 2
    suppressed = False
    reason = ""
    
    if thrashing_channel:
        suppressed = True
        reason = f"THRASHING DETECTED: {thrashing_channel['detail']}. Suppressing restart to prevent restart loop."
    elif len(downs) == 1 and len(ups) >= 1:
        suppressed = True
        reason = f"Single-channel down ({downs[0]['channel']}) with {len(ups)} channels up. Likely transient — suppressed."
    elif len(downs) >= 2 and avg_conf > 0.3:
        suppressed = True
        reason = f"Multiple channels down but avg confidence {avg_conf:.2f} > 0.3 threshold. Suppressed — investigate manually."
    elif len(downs) >= 2 and avg_conf <= 0.3:
        reason = f"QUORUM CONFIRMED: {len(downs)} channels report down, avg confidence {avg_conf:.2f}. Healing recommended."
    elif len(downs) == 0 and len(degraded) > 0:
        reason = f"Degraded but not down ({len(degraded)} channels). Monitor, no action."
    else:
        reason = f"Healthy: {len(ups)} channels up, {len(downs)} down, avg confidence {avg_conf:.2f}"
    
    return {
        "quorum_down": quorum_down,
        "should_heal": (len(downs) >= 2 and avg_conf <= 0.3 and not thrashing_channel),
        "suppressed": suppressed,
        "suppression_reason": reason if suppressed else "",
        "avg_confidence": round(avg_conf, 2),
        "channels_down": len(downs),
        "channels_up": len(ups),
        "channels_degraded": len(degraded),
        "verdict": reason,
    }

# ── MCP Tools ────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="immune_diagnose",
            description="Full multi-channel health scan of all services. Each service gets confidence scores from HTTP, container status, system resources, and log channels. Returns quorum-based diagnosis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Specific service to diagnose, or 'all' for every service",
                        "default": "all"
                    }
                }
            }
        ),
        Tool(
            name="immune_heal",
            description="Auto-heal a service — restarts container ONLY if quorum confirms it's truly down (2+ channels agree, confidence < 0.3, not thrashing). Safe: won't restart healthy containers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Service name to attempt healing (use immune_diagnose first to confirm)"},
                    "force": {
                        "type": "boolean",
                        "description": "Skip Treg arbitration and force restart (dangerous)",
                        "default": False
                    }
                },
                "required": ["service"]
            }
        ),
        Tool(
            name="immune_quorum",
            description="Show current quorum state for all services — which immune channels agree, which disagree. Like a lymphocyte census.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="immune_history",
            description="Show past immune incidents and healing actions. Immune memory — tracks what happened to prevent recurrence.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of past incidents to show", "default": 20}
                }
            }
        ),
        Tool(
            name="immune_treg",
            description="Treg suppression report — what healing actions were blocked, why, and what the outcome was.",
            inputSchema={"type": "object", "properties": {}}
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    
    if name == "immune_diagnose":
        service_name = arguments.get("service", "all")
        targets = {service_name: SERVICES[service_name]} if service_name != "all" else SERVICES
        
        if service_name != "all" and service_name not in SERVICES:
            return [TextContent(type="text", text=f"Unknown service: {service_name}. Known: {', '.join(SERVICES)}")]
        
        output = "## 🧬 Homelab Immune System — Full Diagnosis\n\n"
        output += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        output += f"**Services scanned:** {len(targets)}\n\n"
        
        # System-level channel first
        sys_channel = await channel_system()
        output += f"### 🖥 System Environment\n"
        output += f"- **{sys_channel['channel']}:** {sys_channel['detail']} (conf: {sys_channel['confidence']})\n\n"
        
        output += "| Service | HTTP | Container | Logs | Quorum | Action |\n"
        output += "|---------|------|-----------|------|--------|--------|\n"
        
        actionable = []
        for svc_name, svc_info in targets.items():
            http_result = await channel_http(svc_name, svc_info["http"])
            container_result = await channel_container(svc_info["container"])
            log_result = await channel_logs(svc_info["container"])
            
            channels = [http_result, container_result, log_result]
            arbitration = treg_arbitrate(channels)
            
            http_icon = "🟢" if http_result["status"] == "up" else "🔴"
            container_icon = "🟢" if container_result["status"] == "up" else ("🟡" if container_result["status"] == "degraded" else "🔴")
            logs_icon = "🟢" if log_result["confidence"] >= 0.8 else ("🟡" if log_result["confidence"] >= 0.4 else "🔴")
            
            action = ""
            if arbitration["should_heal"]:
                action = "🔧 HEAL"
                actionable.append(svc_name)
            elif arbitration["suppressed"]:
                action = "🛡 SUPPRESSED"
            elif arbitration["channels_degraded"] > 0:
                action = "👁 MONITOR"
            else:
                action = "✅ OK"
            
            output += f"| {svc_name} | {http_icon} | {container_icon} | {logs_icon} | "
            output += f"{arbitration['verdict'][:50]} | {action} |\n"
        
        output += f"\n### 📊 Summary\n"
        output += f"- **Actionable (needs healing):** {len(actionable)} — {', '.join(actionable) if actionable else 'none'}\n"
        output += f"- **System confidence:** {sys_channel['confidence']}\n"
        output += f"\nRun `immune_heal <service>` to auto-heal any actionable service.\n"
        output += f"Run `immune_treg` to see what was suppressed and why.\n"
        
        return [TextContent(type="text", text=output)]
    
    elif name == "immune_heal":
        service_name = arguments["service"]
        force = arguments.get("force", False)
        
        if service_name not in SERVICES:
            return [TextContent(type="text", text=f"Unknown service: {service_name}")]
        
        svc_info = SERVICES[service_name]
        
        # Run full diagnosis first
        http_result = await channel_http(service_name, svc_info["http"])
        container_result = await channel_container(svc_info["container"])
        log_result = await channel_logs(svc_info["container"])
        channels = [http_result, container_result, log_result]
        arbitration = treg_arbitrate(channels)
        
        history = load_json(HISTORY_FILE)
        
        if not force and not arbitration["should_heal"]:
            # Record suppression
            suppressions = load_json(TREG_FILE)
            suppressions.append({
                "timestamp": datetime.now().isoformat(),
                "service": service_name,
                "channels": {c["channel"]: c["status"] for c in channels},
                "arbitration": arbitration,
                "reason": "Treg suppressed: insufficient quorum or low confidence"
            })
            save_json(TREG_FILE, suppressions[-50:])
            
            return [TextContent(type="text", text=
                f"🛡 **TREG SUPPRESSED** — {service_name} will NOT be restarted.\n\n"
                f"**Reason:** {arbitration['suppression_reason']}\n\n"
                f"**Channel breakdown:**\n"
                f"- HTTP: {http_result['status']} ({http_result['detail']})\n"
                f"- Container: {container_result['status']} ({container_result['detail']})\n"
                f"- Logs: {log_result['status']} ({log_result['detail']})\n\n"
                f"Use `immune_heal {service_name} force=true` to override."
            )]
        
        # Proceed with healing
        action = "force_restart" if force else "quorum_restart"
        _, stderr, rc = await run_cmd(f"podman restart {svc_info['container']}")
        
        if rc != 0:
            history.append({
                "timestamp": datetime.now().isoformat(),
                "service": service_name,
                "action": action,
                "result": "FAILED",
                "error": stderr[:200],
                "quorum": arbitration
            })
            save_json(HISTORY_FILE, history[-100:])
            return [TextContent(type="text", text=f"🔴 **HEAL FAILED** — {service_name}\nError: {stderr}")]
        
        # Verify after restart
        await asyncio.sleep(2)
        verify = await channel_http(service_name, svc_info["http"])
        
        history.append({
            "timestamp": datetime.now().isoformat(),
            "service": service_name,
            "action": action,
            "result": "SUCCESS" if verify["status"] == "up" else "DEGRADED",
            "post_heal_status": verify["status"],
            "quorum": arbitration
        })
        save_json(HISTORY_FILE, history[-100:])
        
        icon = "🟢" if verify["status"] == "up" else "🟡"
        return [TextContent(type="text", text=
            f"{icon} **HEALED** — {service_name} restarted successfully.\n\n"
            f"**Pre-heal confidence:** {arbitration['avg_confidence']}\n"
            f"**Post-heal status:** {verify['status']} — {verify.get('detail', '')}\n"
            f"**Channels that confirmed:** {arbitration['channels_down']} down, {arbitration['channels_up']} up\n"
            f"{'(force mode — Treg bypassed)' if force else ''}"
        )]
    
    elif name == "immune_quorum":
        output = "## 🧬 Quorum Census — Immune Channel Agreement\n\n"
        output += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        for svc_name, svc_info in SERVICES.items():
            http_result = await channel_http(svc_name, svc_info["http"])
            container_result = await channel_container(svc_info["container"])
            log_result = await channel_logs(svc_info["container"])
            
            channels = [http_result, container_result, log_result]
            arbitration = treg_arbitrate(channels)
            
            output += f"### {svc_name}\n"
            output += f"- **HTTP:** {http_result['status']} — conf {http_result['confidence']} — {http_result['detail']}\n"
            output += f"- **Container:** {container_result['status']} — conf {container_result['confidence']} — {container_result['detail']}\n"
            output += f"- **Logs:** {log_result['status']} — conf {log_result['confidence']} — {log_result['detail']}\n"
            output += f"- **Verdict:** {arbitration['verdict']}\n\n"
        
        return [TextContent(type="text", text=output)]
    
    elif name == "immune_history":
        limit = arguments.get("limit", 20)
        history = load_json(HISTORY_FILE)
        recent = history[-limit:]
        
        if not recent:
            return [TextContent(type="text", text="## 📜 Immune History\n\nNo incidents recorded. The system has been healthy.")]
        
        output = f"## 📜 Immune History (last {len(recent)} incidents)\n\n"
        output += "| Time | Service | Action | Result | Confidence |\n"
        output += "|------|---------|--------|--------|------------|\n"
        
        for entry in reversed(recent):
            ts = entry.get("timestamp", "?")[:19]
            svc = entry["service"]
            action = entry["action"]
            result = entry["result"]
            conf = entry.get("quorum", {}).get("avg_confidence", "?")
            output += f"| {ts} | {svc} | {action} | {result} | {conf} |\n"
        
        # Stats
        successes = sum(1 for e in recent if e["result"] == "SUCCESS")
        failures = sum(1 for e in recent if e["result"] == "FAILED")
        output += f"\n**Success rate:** {successes}/{len(recent)} "
        output += f"({round(successes/max(len(recent),1)*100)}%)\n"
        
        return [TextContent(type="text", text=output)]
    
    elif name == "immune_treg":
        suppressions = load_json(TREG_FILE)
        
        if not suppressions:
            return [TextContent(type="text", text="## 🛡 Treg Suppression Report\n\nNo suppressions recorded. All healing actions passed quorum.")]
        
        output = f"## 🛡 Treg Suppression Report ({len(suppressions)} total)\n\n"
        output += "Recent suppressions:\n\n"
        
        for entry in reversed(suppressions[-15:]):
            ts = entry.get("timestamp", "?")[:19]
            svc = entry["service"]
            reason = entry.get("reason", "?")[:100]
            channels = entry.get("channels", {})
            output += f"**{ts}** — {svc}\n"
            output += f"  Blocked: {reason}\n"
            output += f"  Channels: {channels}\n\n"
        
        return [TextContent(type="text", text=output)]
    
    return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
