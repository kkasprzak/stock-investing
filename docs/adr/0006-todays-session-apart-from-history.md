---
status: "proposed"
date: 2026-10-19
decision-makers:
consulted:
informed:
---

# Today's session apart from history

## Context and Problem Statement

The market data layer (`stock-market-data`) gives one series of daily candles for each instrument. Until now this series had also the session of today, while it was still forming. Yahoo gives a bucket for today from the moment the session opens. Until the first trade of the instrument, this bucket has no prices. Separately from the candles, Yahoo gives the price and time of the last trade.

The layer put this last trade price into the empty close and gave the bucket the date of the last trade. Because of this, on 2026-10-19 a morning check run few minutes after the open got a second candle dated 2026-10-16 for a liquid name. This candle had only a close, and it was marked as closed and trusted. For an illiquid name with last trade on 2026-09-08, the same logic made a candle on that date, and the last closed price moved back six weeks. In both cases the answer did not say what really happened: today's session was open and there was no trade yet.

The question is how the layer should show today's session to an agent, so the agent does not need to guess what happened from the shape of the candles.

## Decision Drivers

* An agent who reads the answer must not guess what happened. The state of today's session must be written directly. It cannot be something the agent has to read from empty or repeated candles.
* On GPW, a session with no trade has no closing price at all. The exchange rules say that if there was no trade in a session, the opening and closing prices are not set (Regulamin Giełdy § 136, Szczegółowe Zasady Obrotu Giełdowego § 10). Before the first trade of the day, the only official prices are the last closing price (it is the reference price) and the orders in the book. A trade from an earlier day is not today's price.
* The own candle store and the GPW archive source have only closed sessions. They know nothing about a session which is still running, so today can come only from Yahoo.
* The indicators (ATR, swing lows, weekly and monthly candles) must use only real closed sessions (ADR 0002). A candle made for a day without any trade gives them a price that never happened.
* The professional vendors we checked keep the last price and its date separate from the daily series. Bloomberg has `PX_LAST` with `PX_CLOSE_DT`. Datastream has the price `P` with `TIME`, "the date of the last recorded close price". LSEG DataScope Select gives the date of its fallback close in a separate field.

## Considered Options

* Keep one series, and fill the missing close of the latest candle with the last trade price
* Keep one series, and add today as a row without prices, marked untrusted
* Keep one series with the forming candle, and add a separate field with the state of today's session
* Show today's session separately from the series, and keep in the series only closed sessions

## Decision Outcome

Chosen option: "Show today's session separately from the series, and keep in the series only closed sessions", because only in this option nothing that reads candles can take today as a closed session, and no candle is ever made from a price of another day.

The answer for each instrument has two parts. First part is today's session: is it open, is there no trade yet, or is it closed, together with the last trade price and its own date. Second part is the closed history, from the chain of sources in ADR 0000 and ADR 0005, with Yahoo as the last one.

The candle of a session goes to the history when this session is closed. So an evening run still reads the close of the day as a fact. We never make a candle or a closing price from the last trade fields. A day without a trade gets no made-up candle.

### Consequences

* Good, because an agent reads the state of today's session in one place, written in words, and sees from its own date how old the last price is.
* Good, because the indicators and the weekly or monthly candles use only closed sessions, and there is no special row that they must skip.
* Good, because the own store or the GPW source cannot disagree with today's state, as today is not in the history until its session is closed.
* Bad, because the shape of the answer changes, and every caller must be moved to it.
* Bad, because Yahoo gives the prices about fifteen minutes late. The moment when the session closes is correct, because it comes from the session hours that Yahoo gives. But a candle read just after this moment can still be without the final close from the closing auction. We start without any extra time for this, and we will add it if it turns out to be a problem.
* Bad, because the state of today's session depends on one provider only. When Yahoo does not answer, this state is unknown, and it must be shown as unknown, not left out.

## Pros and Cons of the Options

### Keep one series, and fill the missing close of the latest candle with the last trade price

* Good, because nothing has to change.
* Bad, because before the first trade of the day it makes a candle with the date of an earlier trade. On 2026-10-19 this gave a copy of the previous session for a liquid name and a six weeks old candle for an illiquid one, both marked as closed and trusted.

### Keep one series, and add today as a row without prices, marked untrusted

* Good, because everything stays in one list, and the layer marks untrusted candles already.
* Bad, because everything that reads candles must know to skip this row.

### Keep one series with the forming candle, and add a separate field with the state of today's session

* Good, because the state of today is written directly, with the own date of the last trade.
* Bad, because a candle which is still forming stays in the series next to the closed ones, so the series still mixes a finished session with a not finished one.

### Show today's session separately from the series, and keep in the series only closed sessions

* Good, because today and the closed history cannot be confused.
* Bad, because it changes the answer that every caller reads.

## More Information

Keeps the trust order of ADR 0000 and ADR 0005 for closed sessions, with Yahoo as the last source. Uses the rule of ADR 0002 also for today: values come only from sessions which really closed. Come back to this decision if a source we trust more than Yahoo starts to give a running session, or if a candle that goes to the history at the close is often different from the final one.
