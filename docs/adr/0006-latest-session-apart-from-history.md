---
status: "proposed"
date: 2026-10-19
decision-makers:
consulted:
informed:
---

# Latest session apart from history

## Context and Problem Statement

The market data layer (`stock-market-data`) gives one series of daily candles for each instrument. Until now this series had also the session of today, while it was still forming. Yahoo gives a bucket for today from the moment the session opens. Until the first trade of the instrument, this bucket has no prices. Separately from the candles, Yahoo gives the price and time of the last trade.

The layer put this last trade price into the empty close and gave the bucket the date of the last trade. Because of this, on 2026-10-19 a morning check run few minutes after the open got a second candle dated 2026-10-16 for a liquid name. This candle had only a close, and it was marked as closed and trusted. For an illiquid name with last trade on 2026-09-08, the same logic made a candle on that date, and the last closed price moved back six weeks. In both cases the answer did not say what really was known: today's session was open, and Yahoo did not show any trade from it yet.

The question is how the layer should show today's session to an agent, so the agent does not need to guess what happened from the shape of the candles.

## Decision Drivers

* An agent who reads the answer must not guess what happened. What is known about the session must be written directly, with the times it comes from. It cannot be something the agent has to read from empty or repeated candles.
* On GPW, a session with no trade has no closing price at all. The exchange rules say that if there was no trade in a session, the opening and closing prices are not set (Regulamin Giełdy § 136, Szczegółowe Zasady Obrotu Giełdowego § 10). Before the first trade of the day, the only official prices are the reference price, which is normally the last closing price, and the orders in the book. A trade from an earlier day is not today's price.
* The own candle store and the GPW archive source have only closed sessions. They know nothing about a session which is still running, so the latest session can come only from Yahoo.
* The layer never guesses a price for a session it does not have (ADR 0002). A candle made for a day from a price of another day is such a guess, and the indicators (ATR, swing lows, weekly and monthly candles) then read a price that never happened.
* The professional vendors we checked keep the last price and its date separate from the daily series. Bloomberg has `PX_LAST` with `PX_CLOSE_DT`. Datastream has the price `P` with `TIME`, "the date of the last recorded close price". LSEG DataScope Select gives the date of its fallback close in a separate field.

## Considered Options

* Keep one series, and fill the missing close of the latest candle with the last trade price
* Keep one series, and add today as a row without prices, marked untrusted
* Keep one series with the forming candle, and add a separate field with the state of today's session
* Show the latest session separately, and when a finished session has no close, take it from the last trade if this trade was inside that session
* Show the latest session separately from the series, and keep in the series only closed sessions

## Decision Outcome

Chosen option: "Show the latest session separately from the series, and keep in the series only closed sessions", because only in this option nothing that reads candles can take a running session as a closed one, and a session goes to the history only when its source itself has it as closed. No candle and no close is made from the last trade fields, not even for a session which is finished.

The answer for each instrument has two parts. First part is the latest session: the newest session that Yahoo has data for. During a session and after its end it is the session of today. On a weekend, a holiday or before the open it is the last session before. Its own date says which session it is. It is shown as Yahoo shows it, with the times the data comes from: the session hours, the last trade price with its own date and time, and the time when the data was read. It does not say more than these facts. For example, it does not say "there was no trade", because Yahoo is delayed by about twenty minutes and a trade can be there already without Yahoo showing it. The agent who reads it can work out the rest from the times. Second part is the closed history, from the chain of sources in ADR 0000 and ADR 0005, with Yahoo as the last one.

A candle goes to the history only when its source has it as a closed session. For Yahoo it means: the session is finished, by the session hours that Yahoo gives, and the candle has a close. Yahoo puts the running session into the same list of candles, and the morning after a session the close of this session can be missing. Such a candle does not go to the history. Until then the session is shown only in the latest session part. Closed GPW sessions come mostly from the GPW archive source, which is collected after the session. We never make a candle or a closing price from the last trade fields. A day without a trade gets no made-up candle.

### Consequences

* Good, because an agent reads the latest session in one place, sees from its date which session it is, and sees from the dates and times how old the last price is and how fresh the data is.
* Good, because the indicators and the weekly or monthly candles use only closed sessions, and there is no special row that they must skip.
* Neutral, because the same session can be for some time in both parts: in the history from the GPW archive, collected in the evening, and in the latest session part from Yahoo. The prices can be different (the last trade and the close from the auction). Each part says its source, so the agent sees where each price comes from.
* Bad, because the shape of the answer changes, and every caller must be moved to it.
* Bad, because the history can come later. On 2026-10-24 and 2026-10-28, the morning after a session, Yahoo had no close in the candle of that session for GPW and XETRA names. The close came back during the next session. For names outside GPW, and for a GPW day which was not collected, the last closed session in the history can be one session older, or more, for some time. For GPW names it does not matter, because the GPW archive gives the finished session in the evening. The last closed price has then an older date, but it is a real price.
* Bad, because for a short time after the end of a session, Yahoo's candle can have a close from before the closing auction. On 2026-10-27 at 17:11 the close was the price from 16:49, and the final close was there at 18:24. A run in this window can put a close which is not final into the history, with Yahoo as its source. We accept this narrow window. Nothing from Yahoo is stored, so the next run gets the final close.
* Bad, because the latest session depends on one provider only. When Yahoo does not answer, it is unknown, and it must be shown as unknown, not left out.

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

### Show the latest session separately, and when a finished session has no close, take it from the last trade if this trade was inside that session

* Good, because the history gets the close of a finished session earlier, and the price really comes from that session.
* Bad, because it takes the price from the last trade fields, not from a candle, and puts it into the history before the source itself has this session as closed. This is again the mixing which this decision wants to stop.

### Show the latest session separately from the series, and keep in the series only closed sessions

* Good, because the latest session and the closed history cannot be confused.
* Bad, because the history can come later: a session from Yahoo goes there only when it is finished and its candle has a close, and Yahoo can give the close of a finished session later.
* Bad, because it changes the answer that every caller reads.

## More Information

Keeps the trust order of ADR 0000 and ADR 0005 for closed sessions, with Yahoo as the last source. Narrows ADR 0005: it leaves to Yahoo "the session of today before the archive is published", and this session now goes to the latest session part, not to the history. Applies the rule of ADR 0002, that the layer never guesses a price for a session it does not have, also to the latest session. Come back to this decision if a source we trust more than Yahoo starts to give a running session, or if Yahoo keeps the close of a finished session missing for so long that the history of names outside GPW is often behind.
