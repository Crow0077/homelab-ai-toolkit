#!/usr/bin/env python3
"""
LinkedIn MCP Server — Newsletter & Article Publishing
======================================================
4 tools for AI agents to publish and track LinkedIn content.

Auth: OAuth 2.0 via environment variables or config file.
Set LINKEDIN_ACCESS_TOKEN or LINKEDIN_CLIENT_ID + LINKEDIN_CLIENT_SECRET.

Endpoints:
  linkedin_publish_article  — Long-form newsletter article
  linkedin_publish_post     — Short update / share
  linkedin_get_analytics    — Engagement stats
  linkedin_status           — Health check + token validity

Setup:
  1. Create app at https://www.linkedin.com/developers/
  2. Request scopes: w_member_social, r_organization_social
  3. Generate access token (valid 60 days, refreshable)
  4. Set LINKEDIN_ACCESS_TOKEN + LINKEDIN_AUTHOR_ID env vars
"""

import asyncio
import json
import os
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# ── Configuration ────────────────────────────────────────────
PORT = int(os.environ.get("LINKEDIN_PORT", "8117"))
ACCESS_TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
AUTHOR_ID = os.environ.get("LINKEDIN_AUTHOR_ID", "")
DATA_DIR = Path(os.path.expanduser("~/.linkedin-mcp"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

mcp = FastMCP("linkedin", host="0.0.0.0", port=PORT)

# ── API Helpers ──────────────────────────────────────────────

def linkedin_request(method: str, endpoint: str, body: dict = None) -> dict:
    """Make an authenticated LinkedIn API request."""
    url = f"https://api.linkedin.com/v2/{endpoint}"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
        "LinkedIn-Version": "202505"
    }
    
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return {"ok": True, "data": result}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        return {"ok": False, "error": f"HTTP {e.code}: {error_body[:500]}", "code": e.code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def check_auth() -> dict:
    """Verify LinkedIn credentials are configured and valid."""
    if not ACCESS_TOKEN:
        return {"ok": False, "error": "LINKEDIN_ACCESS_TOKEN not set"}
    if not AUTHOR_ID:
        return {"ok": False, "error": "LINKEDIN_AUTHOR_ID not set (e.g., urn:li:person:YOUR_ID)"}
    
    r = linkedin_request("GET", f"me")
    if not r["ok"]:
        return {"ok": False, "error": f"Token invalid or expired: {r.get('error')}"}
    
    profile = r.get("data", {})
    return {
        "ok": True,
        "author_id": AUTHOR_ID,
        "profile_name": f"{profile.get('localizedFirstName', '')} {profile.get('localizedLastName', '')}".strip(),
        "headline": profile.get("localizedHeadline", ""),
        "token_working": True
    }


def save_article_log(article_data: dict):
    """Log published articles for analytics."""
    log_file = DATA_DIR / "articles.jsonl"
    entry = {
        "timestamp": datetime.now().isoformat(),
        **article_data
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── MCP Tools ────────────────────────────────────────────────

@mcp.tool()
async def linkedin_publish_article(
    title: str,
    body: str,
    description: str = "",
    tags: str = "",
    visibility: str = "PUBLIC"
) -> str:
    """
    Publish a long-form LinkedIn article (newsletter-style).
    
    Args:
        title: Article title (max 200 chars)
        body: Article body in markdown or plain text
        description: Short description / subtitle (max 500 chars)
        tags: Comma-separated tags/hashtags
        visibility: PUBLIC or CONNECTIONS (default: PUBLIC)
    
    Returns the article URL and URN.
    """
    auth = check_auth()
    if not auth["ok"]:
        return json.dumps({"error": auth["error"], "fix": "Set LINKEDIN_ACCESS_TOKEN and LINKEDIN_AUTHOR_ID env vars"})
    
    payload = {
        "author": f"urn:li:person:{AUTHOR_ID}",
        "lifecycleState": "PUBLISHED",
        "visibility": visibility,
        "commentary": body,
        "contentTitle": title[:200] if title else "",
        "contentDescription": description[:500] if description else "",
        "contentLandingPage": "",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": []
        }
    }
    
    r = linkedin_request("POST", "posts", payload)
    
    if not r["ok"]:
        return json.dumps({"error": "Failed to publish article", "detail": r.get("error"), "payload_preview": str(payload)[:300]})
    
    article_urn = r["data"].get("id", "unknown")
    article_url = f"https://www.linkedin.com/feed/update/{article_urn}"
    
    save_article_log({
        "type": "article",
        "title": title[:100],
        "urn": article_urn,
        "tags": tags,
        "char_count": len(body)
    })
    
    return json.dumps({
        "success": True,
        "article_urn": article_urn,
        "article_url": article_url,
        "title": title[:100],
        "author": auth.get("profile_name", "unknown"),
        "visibility": visibility,
        "published_at": datetime.now().isoformat()
    }, indent=2)


@mcp.tool()
async def linkedin_publish_post(
    text: str,
    url: str = "",
    visibility: str = "PUBLIC"
) -> str:
    """
    Publish a short LinkedIn post (status update, not an article).
    
    Args:
        text: Post text (max 3000 chars)
        url: Optional URL to attach
        visibility: PUBLIC or CONNECTIONS
    
    Returns the post URL and URN.
    """
    auth = check_auth()
    if not auth["ok"]:
        return json.dumps({"error": auth["error"]})
    
    payload = {
        "author": f"urn:li:person:{AUTHOR_ID}",
        "lifecycleState": "PUBLISHED",
        "visibility": visibility,
        "commentary": text[:3000],
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": []
        }
    }
    
    if url:
        payload["content"] = {
            "article": {
                "source": url
            }
        }
    
    r = linkedin_request("POST", "posts", payload)
    
    if not r["ok"]:
        return json.dumps({"error": "Failed to publish post", "detail": r.get("error")})
    
    post_urn = r["data"].get("id", "unknown")
    post_url = f"https://www.linkedin.com/feed/update/{post_urn}"
    
    save_article_log({
        "type": "post",
        "urn": post_urn,
        "char_count": len(text)
    })
    
    return json.dumps({
        "success": True,
        "post_urn": post_urn,
        "post_url": post_url,
        "published_at": datetime.now().isoformat()
    }, indent=2)


@mcp.tool()
async def linkedin_get_analytics(days: int = 7) -> str:
    """
    Get engagement analytics for recent posts/articles.
    Reads from local article log.
    
    Args:
        days: How many days to look back
    
    Returns JSON with post history and basic stats.
    """
    log_file = DATA_DIR / "articles.jsonl"
    if not log_file.exists():
        return json.dumps({"articles": [], "total": 0, "message": "No articles published yet"})
    
    articles = []
    cutoff = datetime.now().timestamp() - (days * 86400)
    
    for line in log_file.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry["timestamp"]).timestamp()
            if ts >= cutoff:
                articles.append(entry)
        except:
            pass
    
    return json.dumps({
        "period_days": days,
        "total_articles": len(articles),
        "articles": articles[-20:],
        "tip": "For engagement stats (likes, comments, views), visit LinkedIn Analytics dashboard."
    }, indent=2)


@mcp.tool()
async def linkedin_status() -> str:
    """
    Check LinkedIn MCP server health and authentication status.
    """
    auth = check_auth()
    
    log_file = DATA_DIR / "articles.jsonl"
    article_count = 0
    if log_file.exists():
        article_count = len(log_file.read_text().strip().split("\n")) if log_file.read_text().strip() else 0
    
    return json.dumps({
        "server": "OPERATIONAL",
        "port": PORT,
        "auth": "✓ VALID" if auth["ok"] else f"✗ {auth.get('error', 'unknown')}",
        "profile": auth.get("profile_name", "unknown") if auth["ok"] else None,
        "articles_published": article_count,
        "timestamp": datetime.now().isoformat()
    }, indent=2)


if __name__ == "__main__":
    print(f"📰 LinkedIn MCP Server — Port {PORT}")
    print(f"   4 tools: publish_article, publish_post, get_analytics, status")
    
    auth = check_auth()
    if auth["ok"]:
        print(f"   ✅ Authenticated as: {auth.get('profile_name', 'unknown')}")
    else:
        print(f"   ⚠️  Not authenticated: {auth.get('error', 'unknown')}")
        print(f"   Set LINKEDIN_ACCESS_TOKEN and LINKEDIN_AUTHOR_ID to enable publishing")
    
    mcp.run(transport="streamable-http")
