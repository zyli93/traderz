#!/usr/bin/env python3
"""
notify_telegram.py — Send trading session reports to Telegram.

Usage:
    # Send a plain text message (auto-splits if too long)
    python notify_telegram.py --message "Hello from traderz!"

    # Send multiple pages from stdin (one JSON array of strings)
    echo '["page1 text", "page2 text"]' | python notify_telegram.py --action pages

    # Send session report (auto-generates from latest DB data)
    python notify_telegram.py --action report

    # Send a quick alert
    python notify_telegram.py --action alert --message "NKE hit stop loss"

Credentials loaded from ~/.config/traderz/credentials.json:
    TELEGRAM_BOT_TOKEN — Bot token from @BotFather
    TELEGRAM_CHAT_ID   — Your personal chat ID
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

MAX_MSG_LEN = 4000  # Telegram limit is 4096, leave margin


def load_credentials():
    """Load Telegram credentials from config file."""
    config_path = os.path.expanduser("~/.config/traderz/credentials.json")
    if not os.path.exists(config_path):
        print(json.dumps({"error": "Missing credentials file", "path": config_path}))
        sys.exit(1)

    with open(config_path) as f:
        creds = json.load(f)

    token = creds.get("TELEGRAM_BOT_TOKEN")
    chat_id = creds.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print(json.dumps({"error": "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in credentials"}))
        sys.exit(1)

    return token, chat_id


def send_one(token: str, chat_id: str, text: str, parse_mode: str = "Markdown") -> dict:
    """Send a single message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            return {"status": "sent", "message_id": result.get("result", {}).get("message_id")}
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        # If Markdown fails, retry without parse_mode
        if "can't parse" in body.lower() or "bad request" in body.lower():
            payload2 = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
            req2 = urllib.request.Request(url, data=payload2, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req2, timeout=10) as resp2:
                    result2 = json.loads(resp2.read().decode())
                    return {"status": "sent_plain", "message_id": result2.get("result", {}).get("message_id")}
            except Exception as e2:
                return {"error": f"Retry failed: {e2}"}
        return {"error": f"HTTP {e.code}", "detail": body}
    except Exception as e:
        return {"error": str(e)}


def send_pages(token: str, chat_id: str, pages: list[str]) -> list[dict]:
    """Send multiple pages with 0.5s delay between each."""
    results = []
    for page in pages:
        result = send_one(token, chat_id, page)
        results.append(result)
        if len(pages) > 1:
            time.sleep(0.5)
    return results


def split_text(text: str, max_len: int = MAX_MSG_LEN) -> list[str]:
    """Split text into pages at line boundaries."""
    if len(text) <= max_len:
        return [text]

    pages = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            if current:
                pages.append(current.rstrip())
            current = line + "\n"
        else:
            current += line + "\n"
    if current.strip():
        pages.append(current.rstrip())
    return pages


def main():
    parser = argparse.ArgumentParser(description="Send Telegram notifications")
    parser.add_argument("--action", choices=["send", "pages", "report", "alert"], default="send",
                        help="Action type")
    parser.add_argument("--message", type=str, default=None, help="Message text to send")
    parser.add_argument("--date-label", type=str, default=None,
                        help="Date label for page headers, e.g. '4/8'")
    parser.add_argument("--session-label", type=str, default=None,
                        help="Session label, e.g. '早盘' or '收盘'")
    args = parser.parse_args()

    token, chat_id = load_credentials()

    if args.action == "pages":
        # Read JSON array of page strings from stdin
        raw = sys.stdin.read()
        pages = json.loads(raw)
        results = send_pages(token, chat_id, pages)
        print(json.dumps(results, indent=2))
        return

    if args.action == "report":
        text = _build_basic_report()
        pages = split_text(text)
    elif args.action == "alert":
        pages = [f"⚠️ Alert\n{args.message or 'No message provided'}"]
    else:
        if not args.message:
            print(json.dumps({"error": "Provide --message for send action"}))
            sys.exit(1)
        pages = split_text(args.message)

    # Add page headers if multiple pages
    date_lbl = args.date_label or ""
    sess_lbl = args.session_label or ""
    if len(pages) > 1:
        labeled = []
        for i, page in enumerate(pages):
            header = f"📋 {date_lbl} {sess_lbl} 第{i+1}/{len(pages)}页\n{'─' * 20}\n"
            labeled.append(header + page)
        pages = labeled

    results = send_pages(token, chat_id, pages)
    print(json.dumps(results, indent=2))


def _build_basic_report() -> str:
    """Fallback report from DB data (used when Claude doesn't provide custom text)."""
    import subprocess

    def run_db(action, extra_args=None):
        cmd = ["uv", "run", os.path.join(os.path.dirname(__file__), "db.py"), "--action", action]
        if extra_args:
            cmd.extend(extra_args)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return json.loads(result.stdout) if result.stdout.strip() else None
        except Exception:
            return None

    sessions = run_db("show-sessions", ["--limit", "1"])
    session = sessions[0] if sessions else {}

    try:
        trade_script = os.path.join(os.path.dirname(__file__), "trade.py")
        result = subprocess.run(
            ["uv", "run", trade_script, "--action", "portfolio"],
            capture_output=True, text=True, timeout=15,
        )
        portfolio = json.loads(result.stdout) if result.stdout.strip() else {}
    except Exception:
        portfolio = {}

    lines = []
    acct = portfolio.get("account_summary", {})
    total = float(acct.get("portfolio_value", 0))
    cash = float(acct.get("cash", 0))
    pnl = total - 100000
    pnl_pct = (pnl / 100000) * 100
    invested_pct = ((total - cash) / total * 100) if total > 0 else 0

    lines.append(f"Trading Session {session.get('date', 'N/A')}")
    lines.append(f"Portfolio: ${total:,.0f} ({pnl:+,.0f}, {pnl_pct:+.2f}%)")
    lines.append(f"Cash: ${cash:,.0f} ({100 - invested_pct:.0f}%)")
    lines.append("")

    summary = session.get("actions_summary", "")
    if summary:
        lines.append(summary)
        lines.append("")

    positions = portfolio.get("positions", [])
    if positions:
        lines.append("持仓:")
        for p in positions:
            sym = p["symbol"]
            qty = p["qty"]
            entry = float(p["avg_entry_price"])
            cur = float(p["current_price"])
            pl_pct = float(p["unrealized_plpc"]) * 100
            emoji = "🟢" if pl_pct >= 0 else "🔴"
            lines.append(f"{emoji} {sym} {qty}@${entry:.0f} → ${cur:.0f} ({pl_pct:+.1f}%)")

    regime = session.get("market_regime", "")
    if regime:
        lines.append("")
        lines.append(f"宏观: {regime}")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
