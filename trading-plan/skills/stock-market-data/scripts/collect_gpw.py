#!/usr/bin/env python3
"""stock-market-data collector: one session of the GPW quotation archive into the gpw store.

  python3 collect_gpw.py --gpw DIR                      # today's session
  python3 collect_gpw.py --gpw DIR --date 2026-10-16    # exactly that session

One request for one session, the whole equity market on one page (ADR 0005). Each traded row goes
into <ISIN>.csv under --gpw, the own store's file format, source "gpw"; rows with volume 0 are not
sessions and are left out. A session already in a file is left alone when GPW gives the same
quote and replaced, and named in the report, when it gives another (GPW corrects a page after
publishing it). Nothing else is decided here: no other day is fetched, the directory is not read
to find a missed day, and the page is not judged complete. When to run it, and running it again
with --date for a day missed or fetched too early, is the caller's business. An empty page (a
holiday, or a session not yet published: the two look the same) writes nothing and exits 0.

The server often resets the connection: the request is tried again after a pause of PAUSE
seconds, TRIES times in all; then exit 3 with nothing written. A page the parser no longer
accepts, or a store file that is not one, exits 1 with nothing written: the source stops until
the parser is fixed. Prints a JSON report; committing the directory is the user's step (git diff
is the review). Never runs git.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                        # market_data/ sits next to this file (PYTHONSAFEPATH-proof)

from market_data import store_file                          # noqa: E402
from market_data.importers import gpw                       # noqa: E402
from market_data.importers.gpw import GpwFormatError        # noqa: E402
from market_data.store_file import StoreFileError           # noqa: E402

EXIT_REJECTED = 1                               # the page (or a store file) is not acceptable
EXIT_USAGE = 2                                  # same code argparse uses for a bad command line
EXIT_UNAVAILABLE = 3                            # the archive gave no page

URL = "https://www.gpw.pl/archiwum-notowan-full?type=10&instrument=&date={:%d-%m-%Y}"
# Without a browser's User-Agent and Accept-Language the server refuses the request, and without
# an Accept it resets the connection (urllib sends none; curl always does, so it never showed).
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
           "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "pl-PL,pl;q=0.9"}
TRIES = 3
PAUSE = 30                                      # seconds between tries: one request, then a human's pause
TIMEOUT = 30

_WEEKEND = {5: "Saturday", 6: "Sunday"}
# What reached no answer (HTTPError, an answer, is caught before these).
_NETWORK_ERRORS = (OSError, http.client.HTTPException)


class Unavailable(Exception):
    """The archive gave no page; the message says why."""


def fetch(session: date, *, opener, sleep) -> bytes:
    """The archive page for `session`. A network failure is tried again after PAUSE, never after
    the last try; an HTTP status is the server's answer and is not. Raises Unavailable."""
    request = urllib.request.Request(URL.format(session), headers=HEADERS)
    why = None
    for t in range(TRIES):
        if t:
            sleep(PAUSE)
        try:
            with opener(request, timeout=TIMEOUT) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            e.close()                           # the error carries the response body
            raise Unavailable(f"{request.full_url}: HTTP {e.code}") from None
        except _NETWORK_ERRORS as e:
            why = getattr(e, "reason", None) or e
    raise Unavailable(f"{request.full_url}: no answer after {TRIES} tries, the last: {why}")


def _session(text: str) -> date:
    try:
        day = date.fromisoformat(text)
        if day.isoformat() != text:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date YYYY-MM-DD") from None
    return day


def main(argv=None, *, today: date | None = None, opener=urllib.request.urlopen,
         sleep=time.sleep) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gpw", required=True, metavar="DIR",
                    help="the gpw store, one CSV per ISIN; created when missing, its parent never")
    ap.add_argument("--date", type=_session, metavar="YYYY-MM-DD",
                    help="the session to collect; today when left out")
    args = ap.parse_args(argv)

    if "${" in args.gpw:
        # A skill line whose ${CLAUDE_PROJECT_DIR} was not substituted: never create that directory.
        print(f"--gpw {args.gpw!r} holds an unsubstituted variable; pass the real path",
              file=sys.stderr)
        return EXIT_USAGE
    store = Path(args.gpw)
    if not store.parent.exists():
        # Most likely an empty ${CLAUDE_PROJECT_DIR}: bash turns it into /data/gpw.
        print(f"--gpw {args.gpw!r}: parent directory '{store.parent}' does not exist; was "
              f"${{CLAUDE_PROJECT_DIR}} substituted?", file=sys.stderr)
        return EXIT_USAGE
    today = today or date.today()
    session = args.date or today
    if session.weekday() in _WEEKEND:
        hint = "" if args.date else "; for a past session pass --date"
        print(f"{session} is a {_WEEKEND[session.weekday()]}: no session{hint}", file=sys.stderr)
        return EXIT_USAGE
    if session > today:
        print(f"--date {session} is after today {today}", file=sys.stderr)
        return EXIT_USAGE

    try:
        page = fetch(session, opener=opener, sleep=sleep)
    except Unavailable as e:
        print(f"collect failed, nothing written: {e}", file=sys.stderr)
        return EXIT_UNAVAILABLE
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        published = gpw.table(page)             # every row, for the count of those left out
        incoming = gpw.parse(page, session)
    except GpwFormatError as e:
        return _rejected(f"{URL.format(session)}: {e}")
    if store.exists() and not store.is_dir():
        return _rejected(f"--gpw {store} is not a directory")
    paths = {isin: store / f"{isin}.csv" for isin in incoming}
    # Every stored file is read before any is written, so a broken one stops the run whole.
    try:
        for path in paths.values():
            if path.exists():
                store_file.read(path)
    except StoreFileError as e:
        return _rejected(f"{e}; the store file was left as it is")

    report = {"session": session.isoformat(), "fetched_at": fetched_at, "dir": str(store),
              "empty": not published, "rows": len(incoming),
              "skipped_volume_0": sum(1 for r in published if r.volume == 0),
              "added": 0, "unchanged": 0, "changed": 0, "changed_isins": []}
    written = 0
    for isin, row in incoming.items():
        try:
            merged = store_file.merge_into(paths[isin], [row])   # the parent was checked above
        except (StoreFileError, OSError) as e:  # no write permission, disk full
            print(f"collect stopped at {paths[isin]}: cannot write: {e}; {written} files before it "
                  f"were written, a run with --date {session} after the fix completes the session",
                  file=sys.stderr)
            return EXIT_REJECTED
        written += bool(merged.added or merged.changed)
        report["added"] += merged.added
        report["unchanged"] += merged.unchanged
        report["changed"] += merged.changed
        if merged.changed:
            report["changed_isins"].append(str(isin))
    report["changed_isins"].sort()
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


def _rejected(why: str) -> int:
    print(f"collect rejected, nothing written: {why}", file=sys.stderr)
    return EXIT_REJECTED


if __name__ == "__main__":
    sys.exit(main())
