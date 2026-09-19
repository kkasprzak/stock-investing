"""Deterministic, offline regression tests for scripts/journal.py.

No fixtures and nothing frozen: the script has no network and no clock — every event carries
its own date — so the suite is deterministic by construction.

Symbols, quantities, prices and dates here are invented. They are shaped like real ones —
whole share counts, fractional ETF tranches, two currencies — because that is what exercises
the folds, but no line describes a position anyone holds.

Run:  python3 -m unittest discover -s trading-plan/skills/position-journal/tests
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import journal  # noqa: E402


def opened(date, symbol, qty, price, currency="PLN"):
    return {"as_of": date, "event": journal.OPENED, "symbol": symbol,
            "qty": qty, "price": price, "currency": currency}


def closed(date, symbol, qty, price, currency="PLN"):
    return {"as_of": date, "event": journal.CLOSED, "symbol": symbol,
            "qty": qty, "price": price, "currency": currency}


class JournalCase(unittest.TestCase):
    """A scratch log per test — nothing leaks between cases, nothing touches a real book."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "data", "journal.jsonl")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def given(self, *events):
        for e in events:
            journal.append(self.path, e)

    def events(self):
        return journal.load(self.path)


# --- the transition table ----------------------------------------------------

class TestWrite(JournalCase):

    def test_an_open_on_a_free_symbol_is_recorded(self):
        payload, code = journal.write(self.path, opened("2024-02-05", "NOVA.PL", 12, 100.00))
        self.assertTrue(payload["written"])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.events()), 1)

    def test_a_second_open_is_an_add_on_not_a_duplicate(self):
        # Arrange — a position already held
        self.given(opened("2024-02-05", "NOVA.PL", 12, 100.00))
        # Act — buying more of the same name
        payload, code = journal.write(self.path, opened("2024-03-14", "NOVA.PL", 8, 110.00))
        # Assert — legal; the doctrine gate on add-ons lives in sizing, not here
        self.assertTrue(payload["written"])
        self.assertEqual(code, 0)

    def test_a_close_matching_the_held_quantity_is_recorded(self):
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00))
        payload, code = journal.write(self.path, closed("2024-04-19", "ACME.PL", 80, 22.50))
        self.assertTrue(payload["written"])
        self.assertEqual(code, 0)

    def test_the_close_of_a_position_built_from_tranches_matches_their_sum(self):
        self.given(opened("2024-02-05", "NOVA.PL", 12, 100.00),
                   opened("2024-03-14", "NOVA.PL", 8, 110.00))
        payload, _ = journal.write(self.path, closed("2024-03-28", "NOVA.PL", 20, 95.00))
        self.assertTrue(payload["written"])

    def test_re_running_the_same_event_writes_nothing_and_does_not_fail(self):
        # Arrange — the morning check already recorded this stop-out
        self.given(closed("2024-04-19", "ACME.PL", 80, 22.50))
        # Act — the same session runs again
        payload, code = journal.write(self.path, closed("2024-04-19", "ACME.PL", 80, 22.50))
        # Assert — a re-run is harmless, so the flow must carry on, not stop
        self.assertFalse(payload["written"])
        self.assertEqual(payload["reason"], "already recorded")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.events()), 1)

    def test_a_harmless_rerun_does_not_report_what_the_log_believes(self):
        # Assert — last_event is for diagnosing a real problem, not noise on the happy path
        self.given(closed("2024-04-19", "ACME.PL", 80, 22.50))
        payload, _ = journal.write(self.path, closed("2024-04-19", "ACME.PL", 80, 22.50))
        self.assertNotIn("last_event", payload)

    def test_a_close_on_a_symbol_we_do_not_hold_is_refused_not_crashed(self):
        payload, code = journal.write(self.path, closed("2024-04-19", "ACME.PL", 80, 22.50))
        self.assertFalse(payload["written"])
        self.assertEqual(payload["reason"], "no open position")
        self.assertEqual(code, 1)
        self.assertEqual(self.events(), [])

    def test_a_close_after_a_close_is_refused(self):
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00),
                   closed("2024-04-19", "ACME.PL", 80, 22.50))
        payload, code = journal.write(self.path, closed("2024-04-22", "ACME.PL", 80, 22.00))
        self.assertEqual(payload["reason"], "no open position")
        self.assertEqual(code, 1)

    def test_a_partial_close_is_recorded_because_the_log_holds_facts_not_verdicts(self):
        # Scaling out can predate the doctrine that bans it. Whether it should have happened
        # is the deciding flow's business; that it happened is this file's.
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00))
        payload, code = journal.write(self.path, closed("2024-04-19", "ACME.PL", 40, 22.50))
        self.assertTrue(payload["written"])
        self.assertEqual(code, 0)

    def test_a_close_for_more_than_we_hold_is_refused(self):
        # A transcription slip off a screenshot looks exactly like this
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00))
        payload, code = journal.write(self.path, closed("2024-04-19", "ACME.PL", 110, 22.50))
        self.assertEqual(payload["reason"], "qty exceeds position")
        self.assertEqual(code, 1)

    def test_an_event_dated_before_the_symbols_last_one_is_refused(self):
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00),
                   closed("2024-04-19", "ACME.PL", 80, 22.50))
        payload, code = journal.write(self.path, opened("2024-04-08", "ACME.PL", 10, 26.00))
        self.assertEqual(payload["reason"], "out of order")
        self.assertEqual(code, 1)

    def test_yesterdays_stop_out_is_accepted_because_nothing_newer_exists(self):
        # Arrange — a morning check recording the previous session's exit is normal
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00))
        # Act — dated yesterday, written today
        payload, code = journal.write(self.path, closed("2024-04-19", "ACME.PL", 80, 22.50))
        # Assert — backdating is only refused when it lands behind something already recorded
        self.assertTrue(payload["written"])
        self.assertEqual(code, 0)

    def test_another_symbols_later_event_does_not_block_this_one(self):
        # Ordering is per symbol; two names have independent timelines
        self.given(closed("2024-08-21", "TERA.PL", 3, 380.00))
        payload, code = journal.write(self.path, opened("2024-08-05", "ORBI.PL", 4, 300.00))
        self.assertTrue(payload["written"])
        self.assertEqual(code, 0)

    def test_a_state_refusal_reports_what_the_log_believes(self):
        # Assert — without this the operator has to open the file mid-error
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00),
                   closed("2024-04-19", "ACME.PL", 80, 22.50))
        payload, _ = journal.write(self.path, closed("2024-04-22", "ACME.PL", 80, 22.00))
        self.assertEqual(payload["last_event"], "position_closed 2024-04-19")

    def test_a_refused_event_echoes_the_call_so_the_error_names_its_subject(self):
        payload, _ = journal.write(self.path, closed("2024-04-19", "ACME.PL", 80, 22.50))
        self.assertEqual(payload["symbol"], "ACME.PL")
        self.assertEqual(payload["event"], "position_closed")
        self.assertEqual(payload["as_of"], "2024-04-19")

    def test_the_written_line_keeps_the_six_fields_in_a_fixed_order(self):
        # git diffs are read by humans; a shuffled key order makes them unreadable
        journal.write(self.path, opened("2024-04-02", "ACME.PL", 80, 25.00))
        with open(self.path, encoding="utf-8") as f:
            line = f.readline()
        self.assertEqual(list(json.loads(line).keys()),
                         ["as_of", "event", "symbol", "qty", "price", "currency"])


# --- A: what we hold ---------------------------------------------------------

class TestState(JournalCase):

    def test_a_closed_symbol_does_not_appear(self):
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00),
                   closed("2024-04-19", "ACME.PL", 80, 22.50))
        self.assertEqual(journal.state(self.events())["positions"], [])

    def test_quantity_is_the_sum_of_tranches(self):
        self.given(opened("2024-02-05", "NOVA.PL", 12, 100.00),
                   opened("2024-03-14", "NOVA.PL", 8, 110.00))
        self.assertEqual(journal.state(self.events())["positions"][0]["qty"], 20)

    def test_entry_is_the_weighted_average_of_tranches(self):
        # 10 @ 40.00 and 10 @ 30.00 average to 35.00
        self.given(opened("2024-02-05", "NOVA.PL", 10, 40.00),
                   opened("2024-03-14", "NOVA.PL", 10, 30.00))
        self.assertEqual(journal.state(self.events())["positions"][0]["entry"], 35.00)

    def test_a_single_tranche_position_reports_the_price_it_was_bought_at(self):
        self.given(opened("2024-02-05", "NOVA.PL", 12, 100.00))
        self.assertEqual(journal.state(self.events())["positions"][0]["entry"], 100.00)

    def test_opened_is_the_first_tranche_not_the_last(self):
        self.given(opened("2023-11-06", "VEGA.DE", 4.1111, 30.00, "EUR"),
                   opened("2024-02-19", "VEGA.DE", 2.3333, 32.00, "EUR"))
        self.assertEqual(journal.state(self.events())["positions"][0]["opened"], "2023-11-06")

    def test_a_re_entry_shows_only_the_current_episode(self):
        # Arrange — a name sold in April and bought back in June
        self.given(opened("2024-03-05", "ZEN.PL", 20, 60.00),
                   closed("2024-04-18", "ZEN.PL", 20, 55.00),
                   opened("2024-06-11", "ZEN.PL", 15, 58.00))
        position = journal.state(self.events())["positions"][0]
        # Assert — the old episode must not leak into what we hold now
        self.assertEqual(position["qty"], 15)
        self.assertEqual(position["opened"], "2024-06-11")

    def test_positions_keep_their_own_currency(self):
        self.given(opened("2024-02-05", "NOVA.PL", 12, 100.00),
                   opened("2023-11-06", "VEGA.DE", 9.6666, 31.00, "EUR"))
        by_symbol = {p["symbol"]: p for p in journal.state(self.events())["positions"]}
        self.assertEqual(by_symbol["NOVA.PL"]["currency"], "PLN")
        self.assertEqual(by_symbol["VEGA.DE"]["currency"], "EUR")

    def test_a_partial_close_reduces_the_position_without_ending_it(self):
        self.given(opened("2024-01-08", "LUNA.PL", 6, 200.00),
                   opened("2024-01-29", "LUNA.PL", 2.5, 210.00),
                   closed("2024-02-26", "LUNA.PL", 6, 190.00))
        position = journal.state(self.events())["positions"][0]
        self.assertEqual(position["qty"], 2.5)
        self.assertEqual(position["opened"], "2024-01-08")   # still the same holding

    def test_a_close_that_takes_the_balance_to_zero_ends_the_episode(self):
        self.given(opened("2024-01-08", "LUNA.PL", 6, 200.00),
                   closed("2024-02-26", "LUNA.PL", 3, 190.00),
                   closed("2024-05-20", "LUNA.PL", 3, 175.00))
        self.assertEqual(journal.state(self.events())["positions"], [])

    def test_entry_stays_the_average_of_what_we_bought_not_of_what_is_left(self):
        # Selling part of a position does not re-price the shares still held
        self.given(opened("2024-02-05", "NOVA.PL", 10, 40.00),
                   opened("2024-03-14", "NOVA.PL", 10, 30.00),
                   closed("2024-03-28", "NOVA.PL", 5, 35.00))
        self.assertEqual(journal.state(self.events())["positions"][0]["entry"], 35.00)

    def test_three_fractional_tranches_sum_without_float_noise(self):
        self.given(opened("2023-11-06", "VEGA.DE", 4.1111, 30.00, "EUR"),
                   opened("2024-01-15", "VEGA.DE", 3.2222, 31.50, "EUR"),
                   opened("2024-02-19", "VEGA.DE", 2.3333, 32.00, "EUR"))
        self.assertEqual(journal.state(self.events())["positions"][0]["qty"], 9.6666)


# --- B: was this name ever ours ----------------------------------------------

class TestHistory(JournalCase):

    def test_a_name_never_held_has_no_episodes(self):
        self.given(opened("2024-02-05", "NOVA.PL", 12, 100.00))
        self.assertEqual(journal.history(self.events(), "KITE.PL")["episodes"], [])

    def test_a_closed_episode_carries_the_date_and_price_we_left_at(self):
        # The weekly needs both to say what changed since the exit
        self.given(opened("2024-02-12", "HELM.PL", 25, 80.00),
                   closed("2024-05-03", "HELM.PL", 25, 92.50))
        episode = journal.history(self.events(), "HELM.PL")["episodes"][0]
        self.assertEqual(episode["closed"], "2024-05-03")
        self.assertEqual(episode["exit"], 92.50)

    def test_an_open_position_has_an_episode_with_nothing_on_the_exit_side(self):
        # One shape, no special case — null rather than an absent key
        self.given(opened("2024-06-11", "ZEN.PL", 15, 58.00))
        episode = journal.history(self.events(), "ZEN.PL")["episodes"][0]
        self.assertIsNone(episode["closed"])
        self.assertIsNone(episode["exit"])

    def test_a_re_entry_shows_both_episodes_in_order(self):
        # Arrange — the case the journal exists for
        self.given(opened("2024-03-05", "ZEN.PL", 20, 60.00),
                   closed("2024-04-18", "ZEN.PL", 20, 55.00),
                   opened("2024-06-11", "ZEN.PL", 15, 58.00))
        episodes = journal.history(self.events(), "ZEN.PL")["episodes"]
        self.assertEqual(len(episodes), 2)
        self.assertEqual(episodes[0]["closed"], "2024-04-18")
        self.assertIsNone(episodes[1]["closed"])


# --- C: how many shares on a date --------------------------------------------

class TestHeld(JournalCase):

    def test_before_the_first_purchase_we_held_nothing(self):
        # The dividend case: ex-date 2024-07-15, position opened six sessions later
        self.given(opened("2024-07-23", "TERA.PL", 3, 400.00))
        self.assertEqual(journal.held(self.events(), "TERA.PL", "2024-07-15")["qty_on_date"], 0)

    def test_on_the_open_date_we_already_held_it(self):
        self.given(opened("2024-07-23", "TERA.PL", 3, 400.00))
        self.assertEqual(journal.held(self.events(), "TERA.PL", "2024-07-23")["qty_on_date"], 3)

    def test_between_tranches_only_the_shares_bought_so_far_count(self):
        # Assert — returning the current size here would treble a dividend
        self.given(opened("2023-11-06", "VEGA.DE", 4.1111, 30.00, "EUR"),
                   opened("2024-01-15", "VEGA.DE", 3.2222, 31.50, "EUR"),
                   opened("2024-02-19", "VEGA.DE", 2.3333, 32.00, "EUR"))
        self.assertEqual(journal.held(self.events(), "VEGA.DE", "2024-01-02")["qty_on_date"], 4.1111)

    def test_on_the_close_date_we_still_held_the_position(self):
        # A dividend right is established at the close of the last session carrying it, so
        # selling during that session does not forfeit it
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00),
                   closed("2024-04-19", "ACME.PL", 80, 22.50))
        self.assertEqual(journal.held(self.events(), "ACME.PL", "2024-04-19")["qty_on_date"], 80)

    def test_after_the_close_we_held_nothing(self):
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00),
                   closed("2024-04-19", "ACME.PL", 80, 22.50))
        self.assertEqual(journal.held(self.events(), "ACME.PL", "2024-04-22")["qty_on_date"], 0)

    def test_after_a_partial_close_only_the_remaining_shares_count(self):
        self.given(opened("2024-01-08", "LUNA.PL", 6, 200.00),
                   opened("2024-01-29", "LUNA.PL", 2.5, 210.00),
                   closed("2024-02-26", "LUNA.PL", 6, 190.00))
        self.assertEqual(journal.held(self.events(), "LUNA.PL", "2024-03-04")["qty_on_date"], 2.5)

    def test_on_the_day_of_a_partial_close_we_still_held_the_larger_position(self):
        # Same boundary as a full close: the session's holding is what counts
        self.given(opened("2024-01-08", "LUNA.PL", 6, 200.00),
                   closed("2024-02-26", "LUNA.PL", 3, 190.00))
        self.assertEqual(journal.held(self.events(), "LUNA.PL", "2024-02-26")["qty_on_date"], 6)

    def test_a_name_never_held_is_zero_not_an_error(self):
        self.assertEqual(journal.held(self.events(), "KITE.PL", "2024-04-19")["qty_on_date"], 0)

    def test_a_date_between_two_episodes_is_zero(self):
        self.given(opened("2024-03-05", "ZEN.PL", 20, 60.00),
                   closed("2024-04-18", "ZEN.PL", 20, 55.00),
                   opened("2024-06-11", "ZEN.PL", 15, 58.00))
        self.assertEqual(journal.held(self.events(), "ZEN.PL", "2024-05-10")["qty_on_date"], 0)

    def test_the_answer_is_a_count_so_it_cannot_be_multiplied_by_the_wrong_size(self):
        self.given(opened("2024-03-05", "ZEN.PL", 20, 60.00),
                   closed("2024-04-18", "ZEN.PL", 20, 55.00),
                   opened("2024-06-11", "ZEN.PL", 15, 58.00))
        self.assertEqual(journal.held(self.events(), "ZEN.PL", "2024-03-20")["qty_on_date"], 20)


# --- the log as a whole ------------------------------------------------------

class TestCheck(JournalCase):

    def test_a_clean_log_passes(self):
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00),
                   closed("2024-04-19", "ACME.PL", 80, 22.50))
        report = journal.check(self.path)
        self.assertTrue(report["ok"])
        self.assertEqual(report["events"], 2)

    def test_a_missing_journal_is_an_empty_one_not_a_crash(self):
        report = journal.check(self.path)
        self.assertTrue(report["ok"])
        self.assertEqual(report["events"], 0)

    def test_a_close_without_an_open_is_found_with_its_line_number(self):
        # A hand-built log is exactly where this happens
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00),
                   closed("2024-04-19", "ACME.PL", 80, 22.50),
                   closed("2024-04-22", "ACME.PL", 80, 22.00))
        report = journal.check(self.path)
        self.assertFalse(report["ok"])
        self.assertEqual(report["problems"][0]["line"], 3)
        self.assertEqual(report["problems"][0]["reason"], "no open position")

    def test_check_uses_the_same_rule_as_the_write_path(self):
        # Two copies of the invariant would drift; this pins that they are one
        self.given(opened("2024-04-02", "ACME.PL", 80, 25.00),
                   opened("2024-03-11", "ACME.PL", 10, 26.00))
        self.assertEqual(journal.check(self.path)["problems"][0]["reason"], "out of order")


if __name__ == "__main__":
    unittest.main()
