---
type: regex
name: fetched-company-source
target: trace
pattern: '"name":"WebFetch","input":\{"url":"https?://[^"]*(about\.allegro\.eu/|bankier\.pl/(wiadomosc/ALLEGRO-EU-S-A-|gielda/notowania/akcje/ALLEGRO/komunikaty)|gpw\.pl)'
weight: 1
---

The run fetched at least one page that the company published or that carries its current reports
verbatim: any page on Allegro's own domain, an ESPI report on Bankier or Bankier's report list, or GPW. This
is what the live case exists to measure. A search summary that only mentions such a page does not
count; the run has to open it.
