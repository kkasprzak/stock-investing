# Provenance — ale-0926-replay

## What this is

The verbatim web results one run of `instrument-research` (facet `events`, ALE.PL) received on
**2026-09-26**: 19 files, one per `WebSearch` / `WebFetch` call, in call order, extracted from that
run's transcript with `scripts/extract_tool_results.py`. Nothing is edited, summarised or redacted —
404s and pages about other companies are kept, because they are what the run had to work with.
Reviewed by a human before commit.

Both tools return text written by a model — `WebSearch` a search-engine summary with links,
`WebFetch` a summary of the fetched page — not the pages themselves. Results can also carry the
tool's own instructions to the model ("REMINDER: You MUST include the sources…"); those are
kept too.

## What that run reported

The case this suite exists for. The run returned, in part:

> ACTIVE. AGM (2026-06-25) authorized a buyback of up to PLN 1.6bn, price range PLN
> 0.01–50.00/share […] Phase I price cap was raised to PLN 50/share on 2026-09-21 […] Phase II
> adopted 2026-09-22 allocating up to PLN 800m […]

A certain status resting on search-engine summaries, the authorisation framed as the programme,
Phase I's raised cap given as the live one, and Phase II with no cap. The substance — a Phase II
exists — was true; the reading of the sources was not.

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

No company report about Phase II reached the run: Phase II appears only in a search-engine
summary (file `15`), with its size but not its cap or start. A careful reading therefore cannot
confirm the current programme's cap — which is what `expected.md` asks it to say.

## Inputs worth knowing about

- `07`, `14`: Allegro IR pages about the buyback — HTTP 404. (`08`, another IR page, loaded but had no date.)
- `12`: a GlobeNewswire page about **Ayvens**, not Allegro.
- `16`: a Bankier transaction report whose fills are in a PDF the fetch could not read.
- `11`: a summary that ties the current buyback to the 2025 employee-incentive programme.
- `15`: the only source for Phase II — a search-engine summary.
