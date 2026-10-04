# Provenance — ale-0829-recon

## What this is

A **reconstruction**, not a replay. A run on 2026-08-29 reported an active buyback with a PLN 50 cap,
up to PLN 1.6 bn, window from 25 Jun 2026 — the AGM authorisation's terms read as a programme. That
run's transcript no longer exists, so this case rebuilds what it plausibly had. **The selection is a
hypothesis**, and is labelled so:

- The run gave neither Phase I's cap (PLN 45) nor a broker, so it most likely saw neither RB 26/2026
  nor the weekly transaction reports, each of which names Erste. Both are left out.
- It gave the authorisation's terms, which no company page states in its text (RB 24/2026 has them
  only in a PDF). They come from `websearch-authorization.txt` — a search-engine summary another run
  received on 2026-09-26, checked to mention nothing after 29 Aug and nothing of Phase I.
- RB 27/2025 is a trap: an earlier, separate programme, also capped at PLN 45.

ESPI files are each report's **full page text** as fetched on 2026-10-04, ending at the
signatures; attachments (PDFs) are not included, as a page fetch would not return them. Unlike the
replay inputs, these are the documents themselves rather than model-written summaries — easier to
read than anything a live run receives.

## Ground truth

Allegro.eu current reports (ESPI), list at <https://www.bankier.pl/gielda/notowania/akcje/ALLEGRO/komunikaty>, read 2026-10-04:

| report | published | content |
|---|---|---|
| RB 27/2025 | 2025-11-18 17:02 | a **separate** programme for employee-incentive awards: cap PLN 45, Santander, 21 Nov 2025 – 31 May 2026 |
| RB 24/2026 | 2026-06-25 16:08 | AGM resolutions adopted; the authorisation's terms (PLN 1.6 bn, PLN 0.01–50.00, 84,210,526 shares, to 25 Jun 2027) are only in the attached PDF |
| RB 26/2026 | 2026-06-25 17:01 | **Phase I**: PLN 800 m, cap PLN 45.00, up to 42,105,263 shares, from 15 Jul 2026 to no later than 25 Jun 2027, Erste |
| RB 32–49/2026 | 2026-07-20 … 09-21 | weekly transaction reports; each cites RB 26/2026 and names Erste; fills are only in attached PDFs |
| RB 48/2026 | 2026-09-21 08:40 | Phase I cap raised PLN 45 → 50 |
| RB 50/2026 | 2026-09-21 18:25 | **Phase I completed**: 17,879,330 shares, PLN 799,999,982.52, average PLN 44.74 |
| RB 51/2026 | 2026-09-22 16:52 | **Phase II**: PLN 800 m, cap PLN 50.00, up to 42,105,263 shares, from 23 Sep 2026 to no later than 25 Jun 2027, Erste |
| RB 53/2026 | 2026-09-28 19:00 | board recommends raising the authorisation's maximum price to PLN 65.00; general meetings planned for 18 Nov 2026 |

## Why the expected answer is right for these inputs

Nothing here states a programme's cap, size, window or broker; the only PLN 50 and PLN 1.6 bn are
the authorisation's. RB 27/2025's own window ended on 31 May 2026.
