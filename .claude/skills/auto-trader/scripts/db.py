#!/usr/bin/env python3
"""
db.py — SQLite database for trading records, portfolio snapshots, and session logs.

Usage:
    # Migrate from legacy trading_state.json
    python db.py --action migrate

    # Record a trade
    python db.py --action record-trade --ticker MU --side buy --qty 3 --price 443.55 \
        --stop-loss 395 --take-profit 530 --order-type bracket --strategy "earnings dip buy"

    # Close a trade
    python db.py --action close-trade --ticker MU --exit-price 530

    # Take a portfolio snapshot (pulls from Alpaca)
    python db.py --action snapshot

    # Record an analysis session
    python db.py --action record-session --regime "VIX 24, risk-on" \
        --summary "Bought MU dip, added AMD on Samsung catalyst"

    # Add a lesson
    python db.py --action add-lesson --text "Bracket stop legs are DAY orders"

    # Query trades
    python db.py --action show-trades [--ticker MU] [--status open]
    python db.py --action show-pnl
    python db.py --action show-sessions [--limit 5]
    python db.py --action show-lessons
    python db.py --action show-plan
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime

DB_PATH = os.path.expanduser("~/.config/traderz/traderz.db")
STATE_JSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "..", "state", "trading_state.json",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS plan (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    target_pnl_monthly REAL,
    target_pnl_annual REAL,
    target_annual_pct REAL,
    starting_equity REAL,
    max_positions INTEGER,
    max_per_position REAL,
    max_loss_per_trade REAL,
    drawdown_pause_threshold REAL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    asset_class TEXT DEFAULT 'stock',
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL,
    stop_loss REAL,
    take_profit REAL,
    order_type TEXT,
    order_id TEXT,
    status TEXT DEFAULT 'open',
    exit_date TEXT,
    exit_price REAL,
    pnl REAL,
    pnl_pct REAL,
    hold_days INTEGER,
    strategy TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    total_value REAL NOT NULL,
    cash REAL NOT NULL,
    positions_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    session_number INTEGER,
    market_regime TEXT,
    actions_summary TEXT,
    watchlist_notes TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lessons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    lesson TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS media_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    source TEXT NOT NULL,
    author TEXT,
    ticker TEXT NOT NULL,
    call TEXT NOT NULL CHECK (call IN ('bull', 'bear', 'neutral')),
    headline TEXT NOT NULL,
    price_at_call REAL,
    verified_date TEXT,
    price_at_verify REAL,
    correct INTEGER,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(date);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON portfolio_snapshots(date);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date);
CREATE INDEX IF NOT EXISTS idx_media_calls_source ON media_calls(source);
CREATE INDEX IF NOT EXISTS idx_media_calls_ticker ON media_calls(ticker);
CREATE INDEX IF NOT EXISTS idx_media_calls_correct ON media_calls(correct);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    asset_class TEXT DEFAULT 'stock',
    status TEXT DEFAULT 'watching' CHECK (status IN ('watching', 'ready', 'entered', 'removed')),
    setup_type TEXT,
    entry_trigger TEXT,
    entry_price_target REAL,
    stop_loss REAL,
    take_profit REAL,
    position_size_pct REAL,
    analyst_upside_pct REAL,
    thesis TEXT,
    last_price REAL,
    last_checked TEXT,
    added_date TEXT NOT NULL,
    removed_date TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_watchlist_ticker ON watchlist(ticker);
CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status);
"""


def get_db():
    """Get a database connection, creating tables if needed."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def rows_to_list(rows):
    """Convert sqlite3.Row objects to list of dicts."""
    return [dict(r) for r in rows]


def is_crypto(ticker):
    """Check if a ticker is a crypto pair."""
    crypto_bases = [
        "BTC", "ETH", "SOL", "XRP", "DOGE", "LINK", "AVAX", "DOT",
        "LTC", "UNI", "SHIB", "PEPE", "AAVE", "BCH",
    ]
    normalized = ticker.replace("/", "").upper()
    return any(
        normalized.startswith(base) and normalized.endswith(("USD", "USDT", "USDC"))
        for base in crypto_bases
    )


def detect_asset_class(ticker):
    if is_crypto(ticker):
        return "crypto"
    return "stock"


# ── Actions ──────────────────────────────────────────────────────────────────


def migrate(conn, force=False):
    """Migrate data from trading_state.json into SQLite."""
    # Resolve path relative to project root
    state_path = os.path.normpath(STATE_JSON_PATH)
    if not os.path.exists(state_path):
        # Try from CWD
        state_path = os.path.join(os.getcwd(), "state", "trading_state.json")
    if not os.path.exists(state_path):
        return {"error": f"State file not found at {state_path}"}

    count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    if count > 0 and not force:
        return {
            "error": "Database already has trades. Use --force to re-migrate.",
            "existing_trades": count,
        }

    with open(state_path) as f:
        state = json.load(f)

    migrated = {"plan": 0, "closed_trades": 0, "open_positions": 0, "sessions": 0, "lessons": 0}

    # Plan
    p = state.get("plan", {})
    if p:
        conn.execute(
            """INSERT OR REPLACE INTO plan
               (id, target_pnl_monthly, target_pnl_annual, target_annual_pct,
                starting_equity, max_positions, max_per_position,
                max_loss_per_trade, drawdown_pause_threshold)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p.get("target_pnl_monthly"), p.get("target_pnl_annual"),
             p.get("target_annual_pct"), p.get("starting_equity"),
             p.get("max_positions"), p.get("max_per_position"),
             p.get("max_loss_per_trade"), p.get("drawdown_pause_threshold")),
        )
        migrated["plan"] = 1

    # Closed trades
    for t in state.get("closed_trades", []):
        conn.execute(
            """INSERT INTO trades
               (date, ticker, asset_class, side, qty, price, status,
                exit_date, exit_price, pnl, pnl_pct, hold_days, strategy)
               VALUES (?, ?, ?, 'buy', ?, ?, 'closed', ?, ?, ?, ?, ?, ?)""",
            (t.get("entry_date"), t.get("ticker"),
             t.get("asset_class", detect_asset_class(t.get("ticker", ""))),
             t.get("qty"), t.get("entry_price"), t.get("exit_date"),
             t.get("exit_price"), t.get("pnl"), t.get("pnl_pct"),
             t.get("hold_days"), t.get("strategy")),
        )
        migrated["closed_trades"] += 1

    # Open positions
    for p in state.get("open_positions", []):
        conn.execute(
            """INSERT INTO trades
               (date, ticker, asset_class, side, qty, price,
                stop_loss, take_profit, order_id, status, notes)
               VALUES (?, ?, ?, 'buy', ?, ?, ?, ?, ?, 'open', ?)""",
            (p.get("entry_date"), p.get("ticker"),
             p.get("asset_class", detect_asset_class(p.get("ticker", ""))),
             p.get("qty"), p.get("entry_price"),
             p.get("stop_loss"), p.get("take_profit"),
             p.get("stop_order_id"), p.get("notes")),
        )
        migrated["open_positions"] += 1

    # Sessions
    for s in state.get("sessions", []):
        summary = s.get("actions_summary", "")
        if not summary and "actions" in s:
            summary = json.dumps(s["actions"], default=str)
        conn.execute(
            """INSERT INTO sessions
               (date, session_number, market_regime, actions_summary,
                watchlist_notes, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (s.get("date"), s.get("session_number"), s.get("market_regime"),
             summary, s.get("watchlist_notes"), s.get("notes")),
        )
        migrated["sessions"] += 1

    # Lessons
    session_dates = [s.get("date", "2026-03-13") for s in state.get("sessions", [])]
    for i, lesson in enumerate(state.get("lessons_learned", [])):
        lesson_date = session_dates[i] if i < len(session_dates) else session_dates[-1] if session_dates else "2026-03-13"
        conn.execute(
            "INSERT INTO lessons (date, lesson) VALUES (?, ?)",
            (lesson_date, lesson),
        )
        migrated["lessons"] += 1

    conn.commit()
    return {"status": "migrated", "counts": migrated, "source": state_path}


def record_trade(conn, ticker, side, qty, price, stop_loss=None,
                 take_profit=None, order_type="market", order_id=None,
                 status="open", strategy=None, notes=None, asset_class=None,
                 trade_date=None):
    """Record a new trade."""
    if not asset_class:
        asset_class = detect_asset_class(ticker)
    if not trade_date:
        trade_date = date.today().isoformat()

    cur = conn.execute(
        """INSERT INTO trades
           (date, ticker, asset_class, side, qty, price, stop_loss, take_profit,
            order_type, order_id, status, strategy, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (trade_date, ticker.upper(), asset_class, side, qty, price,
         stop_loss, take_profit, order_type, order_id, status, strategy, notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def close_trade(conn, ticker, exit_price, exit_date=None, pnl=None, notes=None):
    """Close the most recent open trade for a ticker."""
    if not exit_date:
        exit_date = date.today().isoformat()

    row = conn.execute(
        "SELECT * FROM trades WHERE ticker = ? AND status = 'open' ORDER BY date DESC LIMIT 1",
        (ticker.upper(),),
    ).fetchone()
    if not row:
        return {"error": f"No open trade found for {ticker}"}

    row = dict(row)
    if pnl is None and row["price"]:
        if row["side"] == "buy":
            pnl = (exit_price - row["price"]) * row["qty"]
        else:
            pnl = (row["price"] - exit_price) * row["qty"]

    pnl_pct = None
    if pnl is not None and row["price"] and row["qty"]:
        cost = row["price"] * row["qty"]
        pnl_pct = round((pnl / cost) * 100, 2) if cost else None

    entry_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
    hold_days = (datetime.strptime(exit_date, "%Y-%m-%d").date() - entry_date).days

    conn.execute(
        """UPDATE trades SET status = 'closed', exit_date = ?, exit_price = ?,
           pnl = ?, pnl_pct = ?, hold_days = ?, notes = COALESCE(?, notes)
           WHERE id = ?""",
        (exit_date, exit_price, round(pnl, 2) if pnl else None, pnl_pct,
         hold_days, notes, row["id"]),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM trades WHERE id = ?", (row["id"],)).fetchone()
    return dict(updated)


def snapshot(conn):
    """Take a portfolio snapshot from Alpaca."""
    try:
        from alpaca.trading.client import TradingClient

        api_key = os.environ.get("ALPACA_API_KEY")
        secret_key = os.environ.get("ALPACA_SECRET_KEY")
        if not api_key or not secret_key:
            config_path = os.path.expanduser("~/.config/traderz/credentials.json")
            if os.path.exists(config_path):
                with open(config_path) as f:
                    creds = json.load(f)
                api_key = creds.get("ALPACA_API_KEY")
                secret_key = creds.get("ALPACA_SECRET_KEY")
        if not api_key:
            return {"error": "No Alpaca credentials found"}

        client = TradingClient(api_key, secret_key, paper=True)
        account = client.get_account()
        positions = client.get_all_positions()

        total_value = float(account.portfolio_value)
        cash = float(account.cash)
        pos_list = []
        for p in positions:
            pos_list.append({
                "symbol": p.symbol,
                "qty": str(p.qty),
                "avg_entry_price": str(p.avg_entry_price),
                "current_price": str(p.current_price),
                "market_value": str(p.market_value),
                "unrealized_pl": str(p.unrealized_pl),
            })

        today = date.today().isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO portfolio_snapshots
               (date, total_value, cash, positions_json)
               VALUES (?, ?, ?, ?)""",
            (today, total_value, cash, json.dumps(pos_list)),
        )
        conn.commit()
        return {
            "status": "snapshot_saved",
            "date": today,
            "total_value": total_value,
            "cash": cash,
            "positions": pos_list,
        }
    except Exception as e:
        return {"error": str(e)}


def record_session(conn, regime, summary, session_date=None,
                   session_number=None, watchlist_notes=None, notes=None):
    """Record an analysis session."""
    if not session_date:
        session_date = date.today().isoformat()
    if session_number is None:
        row = conn.execute(
            "SELECT MAX(session_number) as mx FROM sessions WHERE date = ?",
            (session_date,),
        ).fetchone()
        session_number = (row["mx"] or 0) + 1

    cur = conn.execute(
        """INSERT INTO sessions
           (date, session_number, market_regime, actions_summary,
            watchlist_notes, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_date, session_number, regime, summary, watchlist_notes, notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def add_lesson(conn, text, lesson_date=None):
    """Add a lesson learned."""
    if not lesson_date:
        lesson_date = date.today().isoformat()
    cur = conn.execute(
        "INSERT INTO lessons (date, lesson) VALUES (?, ?)",
        (lesson_date, text),
    )
    conn.commit()
    return {"id": cur.lastrowid, "date": lesson_date, "lesson": text}


def show_trades(conn, ticker=None, status=None, since=None, asset_class=None):
    """Query trades with optional filters."""
    query = "SELECT * FROM trades WHERE 1=1"
    params = []
    if ticker:
        query += " AND ticker = ?"
        params.append(ticker.upper())
    if status and status != "all":
        query += " AND status = ?"
        params.append(status)
    if since:
        query += " AND date >= ?"
        params.append(since)
    if asset_class:
        query += " AND asset_class = ?"
        params.append(asset_class)
    query += " ORDER BY date DESC, id DESC"
    rows = conn.execute(query, params).fetchall()
    return rows_to_list(rows)


def show_pnl(conn):
    """Show P&L summary."""
    closed = conn.execute(
        "SELECT * FROM trades WHERE status = 'closed'"
    ).fetchall()
    closed = rows_to_list(closed)

    total_pnl = sum(t["pnl"] or 0 for t in closed)
    wins = [t for t in closed if (t["pnl"] or 0) > 0]
    losses = [t for t in closed if (t["pnl"] or 0) < 0]
    avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0

    open_trades = conn.execute(
        "SELECT * FROM trades WHERE status = 'open'"
    ).fetchall()

    # Daily P&L from snapshots
    snapshots = conn.execute(
        "SELECT date, total_value FROM portfolio_snapshots ORDER BY date"
    ).fetchall()

    return {
        "realized_pnl": round(total_pnl, 2),
        "total_closed_trades": len(closed),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(len(wins) / len(closed), 2) if closed else 0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "open_trades": rows_to_list(open_trades),
        "snapshots": rows_to_list(snapshots),
    }


def show_sessions(conn, limit=10, since=None):
    """Show recent sessions."""
    query = "SELECT * FROM sessions"
    params = []
    if since:
        query += " WHERE date >= ?"
        params.append(since)
    query += " ORDER BY date DESC, session_number DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return rows_to_list(rows)


def show_lessons(conn):
    """Show all lessons."""
    rows = conn.execute("SELECT * FROM lessons ORDER BY date, id").fetchall()
    return rows_to_list(rows)


def show_plan(conn):
    """Show trading plan."""
    row = conn.execute("SELECT * FROM plan WHERE id = 1").fetchone()
    return dict(row) if row else {"error": "No plan configured"}


def record_media_call(conn, source, ticker, call, headline, price_at_call,
                      author=None, call_date=None, notes=None):
    """Record a media/analyst directional call for later verification."""
    if not call_date:
        call_date = date.today().isoformat()
    cur = conn.execute(
        """INSERT INTO media_calls
           (date, source, author, ticker, call, headline, price_at_call, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (call_date, source, author, ticker.upper(), call, headline,
         price_at_call, notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM media_calls WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def verify_media_call(conn, call_id, price_at_verify, correct, verify_date=None):
    """Verify a previous media call as correct or incorrect."""
    if not verify_date:
        verify_date = date.today().isoformat()
    conn.execute(
        """UPDATE media_calls SET verified_date = ?, price_at_verify = ?, correct = ?
           WHERE id = ?""",
        (verify_date, price_at_verify, 1 if correct else 0, call_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM media_calls WHERE id = ?", (call_id,)).fetchone()
    return dict(row) if row else {"error": f"No media call with id {call_id}"}


def show_media_calls(conn, source=None, ticker=None, verified=None):
    """Show media calls with optional filters."""
    query = "SELECT * FROM media_calls WHERE 1=1"
    params = []
    if source:
        query += " AND source = ?"
        params.append(source)
    if ticker:
        query += " AND ticker = ?"
        params.append(ticker.upper())
    if verified == "yes":
        query += " AND correct IS NOT NULL"
    elif verified == "no":
        query += " AND correct IS NULL"
    query += " ORDER BY date DESC, id DESC"
    rows = conn.execute(query, params).fetchall()
    return rows_to_list(rows)


def add_watchlist(conn, ticker, setup_type=None, entry_trigger=None,
                  entry_price_target=None, stop_loss=None, take_profit=None,
                  position_size_pct=None, analyst_upside_pct=None, thesis=None,
                  last_price=None, notes=None, asset_class=None, add_date=None):
    """Add a ticker to the watchlist."""
    if not asset_class:
        asset_class = detect_asset_class(ticker)
    if not add_date:
        add_date = date.today().isoformat()
    # Check if already watching
    existing = conn.execute(
        "SELECT * FROM watchlist WHERE ticker = ? AND status IN ('watching', 'ready')",
        (ticker.upper(),),
    ).fetchone()
    if existing:
        # Update existing entry
        conn.execute(
            """UPDATE watchlist SET setup_type = COALESCE(?, setup_type),
               entry_trigger = COALESCE(?, entry_trigger),
               entry_price_target = COALESCE(?, entry_price_target),
               stop_loss = COALESCE(?, stop_loss), take_profit = COALESCE(?, take_profit),
               position_size_pct = COALESCE(?, position_size_pct),
               analyst_upside_pct = COALESCE(?, analyst_upside_pct),
               thesis = COALESCE(?, thesis), last_price = COALESCE(?, last_price),
               notes = COALESCE(?, notes), last_checked = datetime('now'),
               updated_at = datetime('now')
               WHERE id = ?""",
            (setup_type, entry_trigger, entry_price_target, stop_loss, take_profit,
             position_size_pct, analyst_upside_pct, thesis, last_price, notes,
             existing["id"]),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM watchlist WHERE id = ?", (existing["id"],)).fetchone()
        return dict(row)

    cur = conn.execute(
        """INSERT INTO watchlist
           (ticker, asset_class, status, setup_type, entry_trigger,
            entry_price_target, stop_loss, take_profit, position_size_pct,
            analyst_upside_pct, thesis, last_price, last_checked, added_date, notes)
           VALUES (?, ?, 'watching', ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?)""",
        (ticker.upper(), asset_class, setup_type, entry_trigger,
         entry_price_target, stop_loss, take_profit, position_size_pct,
         analyst_upside_pct, thesis, last_price, add_date, notes),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM watchlist WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def update_watchlist(conn, ticker, status=None, last_price=None, notes=None,
                     entry_trigger=None, setup_type=None, entry_price_target=None,
                     stop_loss=None, take_profit=None):
    """Update a watchlist entry."""
    row = conn.execute(
        "SELECT * FROM watchlist WHERE ticker = ? AND status IN ('watching', 'ready') ORDER BY id DESC LIMIT 1",
        (ticker.upper(),),
    ).fetchone()
    if not row:
        return {"error": f"No active watchlist entry for {ticker}"}

    updates = []
    params = []
    if status:
        updates.append("status = ?")
        params.append(status)
        if status == "removed":
            updates.append("removed_date = ?")
            params.append(date.today().isoformat())
    if last_price is not None:
        updates.append("last_price = ?")
        params.append(last_price)
    if notes:
        updates.append("notes = ?")
        params.append(notes)
    if entry_trigger:
        updates.append("entry_trigger = ?")
        params.append(entry_trigger)
    if setup_type:
        updates.append("setup_type = ?")
        params.append(setup_type)
    if entry_price_target is not None:
        updates.append("entry_price_target = ?")
        params.append(entry_price_target)
    if stop_loss is not None:
        updates.append("stop_loss = ?")
        params.append(stop_loss)
    if take_profit is not None:
        updates.append("take_profit = ?")
        params.append(take_profit)

    updates.append("last_checked = datetime('now')")
    updates.append("updated_at = datetime('now')")
    params.append(row["id"])

    conn.execute(
        f"UPDATE watchlist SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM watchlist WHERE id = ?", (row["id"],)).fetchone()
    return dict(updated)


def remove_watchlist(conn, ticker):
    """Remove a ticker from the watchlist."""
    return update_watchlist(conn, ticker, status="removed")


def show_watchlist(conn, status=None, ticker=None):
    """Show watchlist entries."""
    query = "SELECT * FROM watchlist WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    else:
        query += " AND status IN ('watching', 'ready')"
    if ticker:
        query += " AND ticker = ?"
        params.append(ticker.upper())
    query += " ORDER BY added_date DESC, id DESC"
    rows = conn.execute(query, params).fetchall()
    return rows_to_list(rows)


def show_media_stats(conn, source=None):
    """Show accuracy stats for media sources."""
    query = """
        SELECT source,
               COUNT(*) as total_calls,
               SUM(CASE WHEN correct IS NOT NULL THEN 1 ELSE 0 END) as verified,
               SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as correct_calls,
               SUM(CASE WHEN correct = 0 THEN 1 ELSE 0 END) as wrong_calls,
               ROUND(CAST(SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) AS REAL) /
                     NULLIF(SUM(CASE WHEN correct IS NOT NULL THEN 1 ELSE 0 END), 0) * 100, 1)
                     as accuracy_pct
        FROM media_calls
    """
    params = []
    if source:
        query += " WHERE source = ?"
        params.append(source)
    query += " GROUP BY source ORDER BY total_calls DESC"
    rows = conn.execute(query, params).fetchall()
    return rows_to_list(rows)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Trading Database Manager")
    parser.add_argument(
        "--action", required=True,
        choices=[
            "migrate", "record-trade", "close-trade", "snapshot",
            "record-session", "add-lesson",
            "show-trades", "show-pnl", "show-sessions", "show-lessons", "show-plan",
            "record-media-call", "verify-media-call",
            "show-media-calls", "show-media-stats",
            "add-watchlist", "update-watchlist", "remove-watchlist", "show-watchlist",
        ],
    )
    # Trade args
    parser.add_argument("--ticker", default=None)
    parser.add_argument("--side", default=None, choices=["buy", "sell"])
    parser.add_argument("--qty", type=float, default=None)
    parser.add_argument("--price", type=float, default=None)
    parser.add_argument("--stop-loss", type=float, default=None)
    parser.add_argument("--take-profit", type=float, default=None)
    parser.add_argument("--order-type", default="market")
    parser.add_argument("--order-id", default=None)
    parser.add_argument("--status", default=None)
    parser.add_argument("--strategy", default=None)
    parser.add_argument("--notes", default=None)
    parser.add_argument("--asset-class", default=None)
    parser.add_argument("--date", default=None, help="Override date (YYYY-MM-DD)")
    # Close trade args
    parser.add_argument("--exit-price", type=float, default=None)
    parser.add_argument("--exit-date", default=None)
    parser.add_argument("--pnl", type=float, default=None)
    # Session args
    parser.add_argument("--regime", default=None)
    parser.add_argument("--summary", default=None)
    parser.add_argument("--session-number", type=int, default=None)
    parser.add_argument("--watchlist-notes", default=None)
    # Lesson args
    parser.add_argument("--text", default=None)
    # Media call args
    parser.add_argument("--source", default=None, help="Media source (e.g. benzinga, reuters)")
    parser.add_argument("--author", default=None, help="Analyst/author name")
    parser.add_argument("--call", default=None, choices=["bull", "bear", "neutral"])
    parser.add_argument("--headline", default=None)
    parser.add_argument("--price-at-call", type=float, default=None)
    parser.add_argument("--call-id", type=int, default=None, help="ID for verify-media-call")
    parser.add_argument("--price-at-verify", type=float, default=None)
    parser.add_argument("--correct", default=None, choices=["yes", "no"])
    parser.add_argument("--verified", default=None, choices=["yes", "no"])
    # Watchlist args
    parser.add_argument("--setup-type", default=None, help="Setup type (e.g. 'pullback to SMA20')")
    parser.add_argument("--entry-trigger", default=None, help="What needs to happen to enter")
    parser.add_argument("--entry-price-target", type=float, default=None)
    parser.add_argument("--position-size-pct", type=float, default=None)
    parser.add_argument("--analyst-upside-pct", type=float, default=None)
    parser.add_argument("--thesis", default=None, help="Why we like this ticker")
    parser.add_argument("--last-price", type=float, default=None)
    # Query args
    parser.add_argument("--since", default=None)
    parser.add_argument("--limit", type=int, default=10)
    # Migration
    parser.add_argument("--force", action="store_true")

    args = parser.parse_args()
    conn = get_db()

    try:
        if args.action == "migrate":
            result = migrate(conn, force=args.force)

        elif args.action == "record-trade":
            if not args.ticker or not args.side or not args.qty:
                result = {"error": "--ticker, --side, and --qty are required"}
            else:
                result = record_trade(
                    conn, args.ticker, args.side, args.qty, args.price,
                    args.stop_loss, args.take_profit, args.order_type,
                    args.order_id, args.status or "open", args.strategy,
                    args.notes, args.asset_class, args.date,
                )

        elif args.action == "close-trade":
            if not args.ticker or not args.exit_price:
                result = {"error": "--ticker and --exit-price are required"}
            else:
                result = close_trade(
                    conn, args.ticker, args.exit_price,
                    args.exit_date, args.pnl, args.notes,
                )

        elif args.action == "snapshot":
            result = snapshot(conn)

        elif args.action == "record-session":
            if not args.regime or not args.summary:
                result = {"error": "--regime and --summary are required"}
            else:
                result = record_session(
                    conn, args.regime, args.summary, args.date,
                    args.session_number, args.watchlist_notes, args.notes,
                )

        elif args.action == "add-lesson":
            if not args.text:
                result = {"error": "--text is required"}
            else:
                result = add_lesson(conn, args.text, args.date)

        elif args.action == "show-trades":
            result = show_trades(conn, args.ticker, args.status, args.since, args.asset_class)

        elif args.action == "show-pnl":
            result = show_pnl(conn)

        elif args.action == "show-sessions":
            result = show_sessions(conn, args.limit, args.since)

        elif args.action == "show-lessons":
            result = show_lessons(conn)

        elif args.action == "show-plan":
            result = show_plan(conn)

        elif args.action == "record-media-call":
            if not all([args.source, args.ticker, args.call, args.headline]):
                result = {"error": "--source, --ticker, --call, and --headline are required"}
            else:
                result = record_media_call(
                    conn, args.source, args.ticker, args.call, args.headline,
                    args.price_at_call, args.author, args.date, args.notes,
                )

        elif args.action == "verify-media-call":
            if not args.call_id or args.price_at_verify is None or not args.correct:
                result = {"error": "--call-id, --price-at-verify, and --correct are required"}
            else:
                result = verify_media_call(
                    conn, args.call_id, args.price_at_verify,
                    args.correct == "yes", args.date,
                )

        elif args.action == "show-media-calls":
            result = show_media_calls(conn, args.source, args.ticker, args.verified)

        elif args.action == "show-media-stats":
            result = show_media_stats(conn, args.source)

        elif args.action == "add-watchlist":
            if not args.ticker:
                result = {"error": "--ticker is required"}
            else:
                result = add_watchlist(
                    conn, args.ticker, args.setup_type, args.entry_trigger,
                    args.entry_price_target, args.stop_loss, args.take_profit,
                    args.position_size_pct, args.analyst_upside_pct, args.thesis,
                    args.last_price, args.notes, args.asset_class, args.date,
                )

        elif args.action == "update-watchlist":
            if not args.ticker:
                result = {"error": "--ticker is required"}
            else:
                result = update_watchlist(
                    conn, args.ticker, args.status, args.last_price, args.notes,
                    args.entry_trigger, args.setup_type, args.entry_price_target,
                    args.stop_loss, args.take_profit,
                )

        elif args.action == "remove-watchlist":
            if not args.ticker:
                result = {"error": "--ticker is required"}
            else:
                result = remove_watchlist(conn, args.ticker)

        elif args.action == "show-watchlist":
            result = show_watchlist(conn, args.status, args.ticker)

        else:
            result = {"error": f"Unknown action: {args.action}"}

        print(json.dumps(result, indent=2, default=str))

    finally:
        conn.close()


if __name__ == "__main__":
    main()
