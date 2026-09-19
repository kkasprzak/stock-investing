#!/usr/bin/env python3
"""position-journal: an append-only log of position events, and the folds over it.

Records what happened — a position was opened, a position was closed — and answers three
questions from that log: what we hold, whether a name was ever ours, and how many shares we
held on a given date.

It never records what was *supposed* to happen: a plan that did not execute leaves no event.

Run:   python3 journal.py <command> [options]
Tests: python3 -m unittest discover -s <skill>/tests
"""
import argparse
import json
import os
import sys

# cwd-relative, like risk.py — so the skill works the same in a repo or in a plugin.
DEFAULT_JOURNAL = os.path.join(os.getcwd(), "data", "journal.jsonl")

OPENED = "position_opened"
CLOSED = "position_closed"

# Fractional share counts (9.6666) summed from tranches never land on the last digit.
# Quantities are compared with a tolerance, never with ==.
TOL = 1e-6


def _r(x, n=4):
    """Round for reading. Float noise is not information."""
    return round(x + 0.0, n)


def _qty(x):
    """Share counts as people write them: 15 for shares, 9.6666 for a fractional ETF.

    Every line of the log carries one of these forever, and `50.0` for fifty shares reads as
    an artefact of the parser rather than as the count.
    """
    v = _r(x)
    return int(v) if v == int(v) else v


# --- the log -----------------------------------------------------------------

def load(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append(path, event):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# --- the fold ----------------------------------------------------------------

def events_for(events, symbol):
    return [e for e in events if e["symbol"] == symbol]


def episodes_for(events, symbol):
    """Fold one symbol's events into episodes.

    An episode is one holding: opened, possibly added to, then closed. A symbol held twice
    has two episodes — which is the whole point: the second one is a re-entry.
    """
    episodes, current = [], None
    for e in events_for(events, symbol):
        if e["event"] == OPENED:
            if current is None:
                current = {"opened": e["as_of"], "closed": None, "exit": None,
                           "currency": e["currency"], "tranches": [], "closes": []}
                episodes.append(current)
            current["tranches"].append({"date": e["as_of"], "qty": e["qty"], "price": e["price"]})
        elif e["event"] == CLOSED:
            if current is not None:
                current["closes"].append({"date": e["as_of"], "qty": e["qty"], "price": e["price"]})
                if abs(_balance(current)) <= TOL:
                    current["closed"] = e["as_of"]
                    current["exit"] = e["price"]
                    current = None
    return episodes


def _balance(episode):
    """Shares still held in this episode: everything bought, less everything sold."""
    return (sum(t["qty"] for t in episode["tranches"])
            - sum(c["qty"] for c in episode["closes"]))


def held_qty(episode):
    return _qty(_balance(episode))


def entry_of(episode):
    """Weighted average over the episode's tranches.

    Whether an add-on should average into `entry` or be counted as a separate tranche is an
    open doctrine question (Risk management, Unsettled parameters). Until it is settled the
    doctrine says to compute on the whole position — which is this. Change the fold and every
    entry recomputes; nothing is baked into the log.
    """
    q = sum(t["qty"] for t in episode["tranches"])
    if q == 0:
        return None
    return _r(sum(t["qty"] * t["price"] for t in episode["tranches"]) / q)


def open_episode(events, symbol):
    episodes = episodes_for(events, symbol)
    if episodes and episodes[-1]["closed"] is None:
        return episodes[-1]
    return None


def last_event(events, symbol):
    evs = events_for(events, symbol)
    return evs[-1] if evs else None


def _describe(event):
    """The log's view of a symbol, for a human reading a refusal."""
    return "{} {}".format(event["event"], event["as_of"])


# --- reads -------------------------------------------------------------------

def state(events):
    """A — what we hold.

    This is NOT the operational state. portfolio.md is, because that is the file reconciled
    against the broker screenshot every session. This exists to check that file against the
    log, and the fields are named after its columns so the two line up.
    """
    positions = []
    for symbol in sorted({e["symbol"] for e in events}):
        episode = open_episode(events, symbol)
        if episode is None:
            continue
        positions.append({"symbol": symbol,
                          "qty": held_qty(episode),
                          "currency": episode["currency"],
                          "opened": episode["opened"],
                          "entry": entry_of(episode)})
    return {"positions": positions}


def history(events, symbol):
    """B — was this name ever ours, and when did we leave."""
    return {"symbol": symbol,
            "episodes": [{"opened": e["opened"], "closed": e["closed"],
                          "exit": e["exit"], "currency": e["currency"]}
                         for e in episodes_for(events, symbol)]}


def held(events, symbol, on):
    """C — how many shares we held on a date.

    Inclusive at both ends. On the close date the answer is the quantity held, because a
    dividend right is established at the close of the last session carrying it: selling
    during that session does not forfeit it.

    Returns a count, not a yes/no — entitlement is per share, and a bare `true` invites
    multiplying by the position's *current* size.
    """
    for episode in episodes_for(events, symbol):
        if episode["opened"] <= on and (episode["closed"] is None or on <= episode["closed"]):
            qty = (sum(t["qty"] for t in episode["tranches"] if t["date"] <= on)
                   - sum(c["qty"] for c in episode["closes"] if c["date"] < on))
            return {"symbol": symbol, "on": on, "qty_on_date": _qty(qty)}
    return {"symbol": symbol, "on": on, "qty_on_date": 0}


# --- writes ------------------------------------------------------------------

def refusal(events, candidate):
    """Why this event may not be appended, or None.

    Returns (reason, fatal). `already recorded` is not fatal — a re-run is harmless and the
    caller should carry on. A state refusal is fatal: it means the screenshot was misread.
    """
    key = (candidate["as_of"], candidate["event"], candidate["symbol"])
    for e in events:
        if (e["as_of"], e["event"], e["symbol"]) == key:
            return "already recorded", False

    previous = last_event(events, candidate["symbol"])
    if previous is not None and candidate["as_of"] < previous["as_of"]:
        return "out of order", True

    if candidate["event"] == CLOSED:
        episode = open_episode(events, candidate["symbol"])
        if episode is None:
            return "no open position", True
        if candidate["qty"] - _balance(episode) > TOL:
            return "qty exceeds position", True

    return None, False


def write(path, candidate):
    """Append unless the log forbids it. Returns (payload, exit_code)."""
    events = load(path)
    reason, fatal = refusal(events, candidate)

    echo = {"event": candidate["event"], "symbol": candidate["symbol"],
            "as_of": candidate["as_of"]}

    if reason is None:
        append(path, candidate)
        return dict({"written": True}, **echo), 0

    payload = dict({"written": False, "reason": reason}, **echo)
    previous = last_event(events, candidate["symbol"])
    if fatal and previous is not None:
        payload["last_event"] = _describe(previous)
    return payload, (1 if fatal else 0)


def check(path):
    """Replay every line through the same rule the write path uses.

    The log is hand-built once, at import, so the lines nobody validated are exactly the ones
    most likely to be wrong. Sharing the rule with `write` is deliberate — two copies of the
    invariant would drift.
    """
    events = load(path)
    problems, seen = [], []
    for i, e in enumerate(events, start=1):
        reason, _ = refusal(seen, e)
        if reason is not None:
            problems.append({"line": i, "reason": reason,
                             "event": e["event"], "symbol": e["symbol"], "as_of": e["as_of"]})
        seen.append(e)
    return {"file": path, "events": len(events), "ok": not problems, "problems": problems}


# --- cli ---------------------------------------------------------------------

def _event_args(parser):
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--qty", required=True, type=float)
    parser.add_argument("--price", required=True, type=float)
    parser.add_argument("--currency", required=True,
                        help="required, never defaulted — a EUR position silently read as PLN "
                             "is a mistake nobody sees")
    parser.add_argument("--date", required=True, metavar="YYYY-MM-DD",
                        help="the session the event belongs to, never taken from the clock")


def build_parser():
    ap = argparse.ArgumentParser(prog="journal.py", description=__doc__.split("\n")[0])
    ap.add_argument("--journal", default=DEFAULT_JOURNAL, metavar="FILE")
    sub = ap.add_subparsers(dest="command", required=True)

    _event_args(sub.add_parser("opened", help="a position was opened, or added to"))
    _event_args(sub.add_parser("closed", help="a position was closed in full"))

    sub.add_parser("state", help="what we hold, folded from the log")
    sub.add_parser("check", help="validate the whole log")

    h = sub.add_parser("history", help="every episode for one symbol")
    h.add_argument("--symbol", required=True)

    o = sub.add_parser("held", help="how many shares we held on a date")
    o.add_argument("--symbol", required=True)
    o.add_argument("--on", required=True, metavar="YYYY-MM-DD")

    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    path = args.journal

    if args.command in ("opened", "closed"):
        candidate = {"as_of": args.date,
                     "event": OPENED if args.command == "opened" else CLOSED,
                     "symbol": args.symbol,
                     "qty": _qty(args.qty),
                     "price": args.price,
                     "currency": args.currency}
        payload, code = write(path, candidate)
    elif args.command == "state":
        payload, code = state(load(path)), 0
    elif args.command == "history":
        payload, code = history(load(path), args.symbol), 0
    elif args.command == "held":
        payload, code = held(load(path), args.symbol, args.on), 0
    else:
        payload = check(path)
        code = 0 if payload["ok"] else 1

    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
