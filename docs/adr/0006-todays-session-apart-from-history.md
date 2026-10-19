---
status: "proposed"
date: 2026-10-19
decision-makers:
consulted:
informed:
---

# Today's session apart from history

## Context and Problem Statement

The market data layer (`stock-market-data`) answers with one series of daily candles per
instrument. Until now that series has also held the session of today, as it was forming. Yahoo
returns a bucket for today from the moment the session opens. Until the instrument's first trade,
that bucket has no prices. Separately from the candles, Yahoo reports the last trade's price and
time.

The layer filled the empty bucket's close with that last-trade price and dated it by the last
trade's time. On 2026-10-19 a morning check, run minutes after the open, therefore got a second
candle dated 2026-10-16 for a liquid name. That candle carried only a close and was marked closed
and trusted. For an illiquid name whose last trade was on 2026-09-08, the same fill produced a
candle on that date, and the last closed price went back six weeks. In neither case did the answer
say what had actually happened: today's session was open and had seen no trade yet.

The question is how the layer should tell an agent about today's session so that the agent does
not have to work out what happened from the shape of the candles.

## Decision Drivers

* An agent reading the answer must not have to guess what happened. The state of today's session
  has to be stated outright, not left to be inferred from empty or repeated candles.
* On GPW, a session with no trade has no closing price at all. The exchange's rules say that if no
  trade was concluded in a session, the opening and closing prices are not determined
  (Regulamin Giełdy § 136, Szczegółowe Zasady Obrotu Giełdowego § 10). Before the first trade of
  the day, the only official prices are the last closing price, which serves as the reference
  price, and the orders in the book. A trade from an earlier day is not today's price.
* The own candle store and the GPW archive source hold closed sessions only. They know nothing
  about a session that is still running, so today can come from Yahoo alone.
* The indicators (ATR, swing lows, weekly and monthly candles) must be read from real closed
  sessions only (ADR 0002). A candle composed for a day that did not trade feeds them a price that
  never happened.
* The professional vendors we looked at keep the last price and its date apart from the daily
  series. Bloomberg has `PX_LAST` with `PX_CLOSE_DT`. Datastream has the price `P` with `TIME`,
  "the date of the last recorded close price". LSEG DataScope Select gives the date of its fallback
  close in a field of its own.

## Considered Options

* Keep one series, and fill the latest candle's missing close from the last-trade price
* Keep one series, and add today as a row with no prices, marked untrusted
* Keep one series with the forming candle, and add a separate field that states today's session
* Report today's session apart from the series, and keep the series to closed sessions only

## Decision Outcome

Chosen option: "Report today's session apart from the series, and keep the series to closed
sessions only", because it is the only option in which nothing that reads candles can take today
for a closed session, and in which no candle is ever made from a price of another day.

Each instrument's answer has two parts. The first is today's session: whether it is open, has seen
no trade yet, or has closed, together with the last trade's price and its own date. The second is
the closed history, from the chain of sources ADR 0000 and ADR 0005 set out, Yahoo included as
the last of them.

A session's candle joins the history when that session has closed, so an evening run still reads
the day's close as a fact. A candle, or a closing price, is never composed from the last-trade
fields. A day without a trade gets no candle made up for it.

### Consequences

* Good, because an agent reads the state of today's session in one place, stated in words, and
  sees how old the last price is from its own date.
* Good, because the indicators and weekly or monthly candles are read only from closed sessions,
  with no special row they would have to skip.
* Good, because the own store or the GPW source can never contradict today's state, since today
  is not in the history until its session has closed.
* Bad, because the shape of the answer changes, and every caller has to be moved to it.
* Bad, because the moment a session closes comes from Yahoo, which is delayed by about fifteen
  minutes. A candle read straight after the close may still lack the closing auction. We start with
  no allowance for this and will add one if it turns out to matter.
* Bad, because the state of today's session rests on a single provider. When Yahoo does not
  answer, that state is unknown, and it has to be reported as unknown rather than left out.

## Pros and Cons of the Options

### Keep one series, and fill the latest candle's missing close from the last-trade price

* Good, because nothing has to change.
* Bad, because before the first trade of the day it produces a candle dated by an earlier trade.
  On 2026-10-19 that meant a duplicate of the previous session for a liquid name and a candle six
  weeks old for an illiquid one, both marked closed and trusted.

### Keep one series, and add today as a row with no prices, marked untrusted

* Good, because everything stays in one list, and the layer already marks untrusted candles.
* Bad, because everything that reads candles has to know to skip that row.

### Keep one series with the forming candle, and add a separate field that states today's session

* Good, because the state of today is stated outright, with the last trade's own date.
* Bad, because a candle that is still forming stays in the series beside the closed ones, so the
  series still mixes a session that has ended with one that has not.

### Report today's session apart from the series, and keep the series to closed sessions only

* Good, because today and closed history cannot be mistaken for each other.
* Bad, because it changes the answer every caller reads.

## More Information

Keeps the trust order of ADR 0000 and ADR 0005 for closed sessions, Yahoo included as the last
source. Applies the rule of ADR 0002 to today: values are read from sessions that really closed.
Revisit if a source we trust more than Yahoo starts to report a running session, or if a candle
that joins the history at the close keeps turning out to differ from the final one.
