# Provenance — ale-0905-replay

## What this is

The verbatim web results one run of `instrument-research` (facet `events`, ALE.PL) received on
**2026-09-05**: 19 files, one per `WebSearch` / `WebFetch` call, in call order, extracted from that
run's transcript with `scripts/extract_tool_results.py`. Nothing is edited, summarised or redacted —
404s and pages about other companies are kept, because they are what the run had to work with.
Reviewed by a human before commit.

Both tools return text written by a model — `WebSearch` a search-engine summary with links,
`WebFetch` a summary of the fetched page — not the pages themselves. Results can also carry the
tool's own instructions to the model ("REMINDER: You MUST include the sources…"); those are
kept too.

## What that run reported

Correct: Phase I running, cap PLN 45.00, up to 42,105,263 shares / PLN 800 m, 15 Jul 2026 –
25 Jun 2027, Erste, fills 3–5 Aug at about PLN 44.67 / 44.71 / 44.97, and the AGM authorisation
(PLN 1.6 bn, PLN 0.01–50.00) described separately. A **control** case.

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

Phase I was the only programme on 5 Sep (RB 26/2026; Phase II came on 22 Sep). Every fact
`expected.md` requires is in the inputs. The report number is not, so it is not required.
