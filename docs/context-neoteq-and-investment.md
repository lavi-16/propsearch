# Context: neoteq & Investment-Evaluation Strands

**Status:** exploration context, not a build spec
**Owner:** Lavi
**Last updated:** 2026-08-18

---

## Why this file exists

CC has been building the core PropSearch pipeline (bronze → silver → gold) but has no
context on two downstream consumers of that data that are now being explored. This file
gives CC that context in one place. It is not a set of ingestion/schema decisions — those
still need to happen after the exploration queries below produce results.

## Architecture framing

`gold.*` (parcel, building, and their summary tables) is the one shared engine output.
Everything downstream reads from it rather than re-deriving its own version. Individual
use cases ("strands") either query gold directly, or — if they need derived data specific
to their own purpose that has no place in a general-purpose due-diligence record — get
their own schema, the way neoteq already got `neoteq.*` instead of widening gold. Treat
that as the standing pattern: gold stays the shared, stable, generally-useful record;
strand-specific logic (lead scoring, contact status, investment verdicts) lives in its
own namespace.

Two strands right now:

1. **neoteq** — heat pump / PV lead generation
2. **Investment evaluation** — Renditeliegenschaft screening (existing `immo-analyse` skill)

Both are currently just exploration queries against existing gold data, to find out what's
already answerable and what's still missing. Nothing below should be read as "build this."

---

## Strand 1: neoteq

### What it is

A lead-generation concept, separate from PropSearch's due-diligence purpose: identify
buildings that are good candidates for a heat pump and/or PV pitch — old fossil heating,
good roof, no PV yet — so an installer/sales process can reach out.

### Division of responsibility

- **Data/engineering (CC + this pipeline):** candidate identification from gold data,
  and ingesting the one confirmed missing source (BFE/Pronovo PV registry, see below).
- **Contact/outreach strategy:** Lavi is handling this personally. Swiss Grundbuch owner
  lookup is legally gated (Art. 970 ZGB rules out bulk automated lookup), so this needs a
  workaround — direct mail, installer partnerships, etc. Not an engineering task, don't
  build anything for it.

### Confirmed data gap: BFE/Pronovo PV registry — NOW INGESTED (2026-08-18)

`ch.bfe.elektrizitaetsproduktionsanlagen` — existing PV installations. Without this, a
"good roof, no PV" candidate list can't exclude buildings that already have PV, which
would be a bad look on first contact. Ingested via the federal BGDI/STAC bulk GeoPackage
(the Sonnendach/noise route), not the WFS/WMS pattern this note assumed — see CLAUDE.md
"BFE/Pronovo". Note the ASCII collection id above (`elektrizitaetsproduktionsanlagen`);
the umlaut spelling does not resolve. Landed as `bronze.stromproduktion` →
`silver.pv_plant` / `silver.building_pv`, and the neoteq candidate list now excludes
buildings with PV (2,756 → 2,439).

### Candidate identification — critical filtering nuance

The filter logic is roughly: fossil heating (gas/oil) + good solar class (Sonnendach) +
no existing PV (once BFE is ingested).

**Age must be handled carefully.** The relevant question is *when the heating system was
installed or last replaced* — not when the building was constructed. A building from the
1960s could have had its heating replaced last year and would be a bad candidate; a newer
building with an aging original system could be a good one. Building construction year
(which GWR definitely has) is only a weak proxy for this and should not be used as if it
were the real signal.

**Action for CC:** check whether GWR actually carries a heating-installation/replacement
date field distinct from building construction year (something in the federal MADD
schema, possibly not yet decoded into silver). If it exists, use it. If it doesn't, do
not silently filter on building age as a substitute — surface that as an explicit caveat
next to any results, so the candidate count isn't over-trusted.

### Open data gaps beyond BFE

TBD — pending what the exploration query turns up. Don't guess further sources yet.

---

## Strand 2: Investment evaluation (`immo-analyse` skill)

### What it is

An existing skill (not built by CC, lives at `/mnt/skills/user/immo-analyse/`) that does
two-stage Go/No-Go analysis of Swiss Renditeliegenschaften (multi-family/mixed-use
investment properties), focused on cantons AG, SG, TG. Stage 1 works from an Exposé
(listing document) the user provides; Stage 2 works from post-viewing findings. Full
skill content is embedded verbatim below so CC has the actual logic, not a paraphrase.

### Relationship to PropSearch today

None yet — the skill currently works entirely from what the user pastes in (Exposé) plus
a static hardcoded market-data reference table (`references/marktdaten.md`, also embedded
below, dated January 2026). It has no connection to PropSearch's gold data. The
exploration prompt (see conversation) checks how much of the skill's Stage 1 inputs gold
can already answer directly, for one real pilot parcel.

### Noteworthy overlap to check specifically

The skill's static reference table already tracks, per PLZ, categories PropSearch is
independently building *live* for Thurgau:

- `Preis/m²` in marktdaten.md ↔ Landwertzonen / Bodenpreise benchmarks in gold
- `Steuerfuss` and `Bev.wachstum` in marktdaten.md ↔ Gemeinde statistics tables in gold

This overlap only applies to the TG rows in marktdaten.md — AG, SG (until PropSearch
expands there), and ZH remain outside PropSearch's current geography and stay dependent
on the static table regardless. For TG specifically, it's worth the exploration query
checking whether gold's numbers are usable as a live supplement or eventual replacement
for that snapshot — but that's a question to surface from the results, not a decision to
make now.

### Embedded skill: `immo-analyse/SKILL.md` (verbatim)

```markdown
---
name: immo-analyse
description: "Zweistufige Analyse von Schweizer Renditeliegenschaften (MFH, Wohn-/Geschäftshäuser). Stufe 1 - Vorqualifizierung anhand Exposé mit Go/No-Go Empfehlung und Besichtigungsvorbereitung. Stufe 2 - Vertiefte Analyse nach Besichtigung mit finaler Einschätzung. Fokus auf Kantone AG, SG, TG. Nutze diesen Skill wenn (1) User ein Immobilien-Exposé zur Bewertung sendet, (2) User nach Analyse einer Renditeliegenschaft fragt, (3) User Besichtigungsvorbereitung benötigt, (4) User nach Besichtigung eine finale Einschätzung will."
---

# Immobilien-Analyse Skill

Strukturierte Analyse von Renditeliegenschaften für Erstinvestoren mit Fokus auf risikobewusste Entscheidungen.

## Workflow

**Stufe 1: Vorqualifizierung** (Exposé → Go/No-Go + Besichtigungsvorbereitung)
**Stufe 2: Vertiefung** (Nach Besichtigung → Finale Einschätzung)

Vor jeder Analyse: Prüfe ob Stufe 1 oder 2 und wende entsprechendes Output-Template an.

## Stufe 1: Vorqualifizierung

### Benötigte Inputs
- Exposé (PDF oder Infos)
- Optional: Zusätzliche Unterlagen (Grundbuchauszug, Mieterliste)

### Analyse-Prozess

1. **Red Flag Check** - Sofortige Ausschlusskriterien prüfen (siehe unten)
2. **Datenextraktion** - Alle verfügbaren Fakten aus Exposé extrahieren
3. **Lückenanalyse** - Fehlende kritische Informationen identifizieren
4. **Kennzahlenberechnung** - BR, Preis/m², Vergleich mit Marktdaten
5. **Besichtigungsfragen** - Konkrete Punkte für Vor-Ort-Prüfung erstellen

### Red Flags (Automatisches NO-GO)
- Bruttorendite < 4% (ohne klares Wertsteigerungspotenzial)
- Baurecht statt Volleigentum
- Denkmalschutz mit starken Auflagen
- Baujahr vor 1950 ohne dokumentierte Kernsanierung
- Ölheizung ohne konkreten Sanierungsplan (CO2-Gesetz Risiko)
- Gewerbeanteil > 50% der Mieteinnahmen
- Leerstand > 5% (bei Wohnliegenschaften)
- Fehlende Angaben zu Erneuerungsfonds/Sanierungshistorie

### Yellow Flags (Vorsicht/Vertiefen)
- Baujahr 1950-1980 (Asbest-Risiko, Sanierungsstau)
- Heizung > 15 Jahre alt
- Dach > 25 Jahre ohne Sanierung
- Nur ein Hauptmieter (Klumpenrisiko)
- Mieten deutlich unter Markt (Potenzial aber Anfechtungsrisiko)
- Sanierung > 10 Jahre her bei Altbau
- Hoher Gewerbeanteil (25-50%)

### Marktdaten-Referenz
Für PLZ-basierte Marktdaten siehe `references/marktdaten.md`. Bei fehlender PLZ: Kantonale Durchschnittswerte verwenden.

## Stufe 2: Vertiefte Analyse

### Benötigte Inputs
- Ausgefüllte Besichtigungsfragen aus Stufe 1
- Zusätzliche Erkenntnisse von Vor-Ort
- Optional: Mietverträge, Nebenkostenabrechnungen, Grundbuchauszug

### Analyse-Prozess

1. **Delta-Analyse** - Abweichungen Exposé vs. Realität
2. **Investitionsbedarf** - Konkrete Schätzung nächste 5-10 Jahre
3. **Cashflow-Projektion** - Realistische Szenarien (Base/Bull/Bear)
4. **Finanzierungscheck** - Tragbarkeit mit 25% EK
5. **Finale Empfehlung** - Kaufen / Verhandeln / Ablehnen

## Output-Templates

### Stufe 1 Output: Vorqualifizierung

```markdown
# Objektanalyse: [Adresse]
**Datum:** [Datum]
**Status:** STUFE 1 - VORQUALIFIZIERUNG

---

## 1. KURZÜBERSICHT

| Kriterium | Wert | Bewertung |
|-----------|------|-----------|
| Kaufpreis | CHF X | |
| Bruttorendite | X.X% | 🟢/🟡/🔴 |
| Preis/m² | CHF X | vs. Markt: +/-X% |
| Baujahr | XXXX | |
| Letzte Sanierung | XXXX | |
| Gewerbeanteil | X% | |

---

## 2. RED FLAG CHECK

🔴 **Ausschlusskriterien:**
- [ ] BR < 4%: [Status]
- [ ] Baurecht: [Status]
- [ ] Denkmalschutz: [Status]
- [ ] Altbau ohne Sanierung: [Status]
- [ ] Ölheizung ohne Plan: [Status]
- [ ] Gewerbe > 50%: [Status]
- [ ] Leerstand > 5%: [Status]

**Ergebnis:** [BESTANDEN / NICHT BESTANDEN]

---

## 3. YELLOW FLAGS

🟡 **Risikofaktoren zur Vertiefung:**
[Liste mit Begründung]

---

## 4. STANDORTANALYSE

**Makrolage:**
- Gemeinde: [Name], Kanton [XX]
- Einwohner: [Anzahl], Wachstum: [+/-X%]
- Steuerfuss: [X%]
- Leerstandsquote Gemeinde: [X%]

**Mikrolage:**
- ÖV-Anbindung: [Bewertung]
- Infrastruktur: [Bewertung]
- Lärmbelastung: [Einschätzung]

**Marktvergleich:**
- Ø Miete/m² PLZ: CHF [X]
- Ø Kaufpreis/m² PLZ: CHF [X]
- Objekt vs. Markt: [Einschätzung]

---

## 5. OBJEKTANALYSE

**Struktur:**
[Beschreibung Einheiten, Flächen, Nutzung]

**Zustand (soweit beurteilbar):**
[Einschätzung basierend auf Exposé/Fotos]

**Mieteinnahmen:**
| Einheit | Fläche | Ist-Miete | Marktmiete (geschätzt) |
|---------|--------|-----------|------------------------|
| ... | ... | ... | ... |

---

## 6. FEHLENDE INFORMATIONEN

❓ **Kritisch (vor Besichtigung klären):**
[Liste]

❓ **Wichtig (bei Besichtigung erfragen):**
[Liste]

---

## 7. BESICHTIGUNGS-CHECKLISTE

### Bausubstanz prüfen
- [ ] Dachzustand (von aussen, Dachboden falls zugänglich)
- [ ] Fassade (Risse, Feuchtigkeit, Isolation)
- [ ] Fenster (Alter, Zustand, Dichtungen)
- [ ] Keller (Feuchtigkeit, Schimmel)
- [ ] Haustechnik-Raum (Heizung, Boiler, Alter)

### Fragen an Verkäufer/Makler
- [ ] Sanierungshistorie detailliert?
- [ ] Erneuerungsfonds vorhanden? Höhe?
- [ ] Mietverträge einsehbar?
- [ ] Kündigungsfristen Mieter?
- [ ] Grund für Verkauf?
- [ ] Wie lange im Eigentum?
- [ ] Bekannte Mängel/Streitigkeiten?
- [ ] Nebenkosten-Abrechnung der letzten 3 Jahre?

### Mieterstruktur
- [ ] Wie lange sind Mieter im Objekt?
- [ ] Gab es Mieterausfälle?
- [ ] Mietzinsanpassungen in letzten Jahren?

### Rechtliches
- [ ] Grundbuchauszug anfordern
- [ ] Baubewilligungen vorhanden?
- [ ] Dienstbarkeiten/Lasten?
- [ ] Stockwerkeigentum oder Alleineigentum?

---

## 8. VORLÄUFIGE EINSCHÄTZUNG

**Go/No-Go:** [🟢 GO / 🟡 BEDINGT / 🔴 NO-GO]

**Begründung:**
[2-3 Sätze]

**Nächste Schritte:**
1. [Konkrete Aktion]
2. [Konkrete Aktion]
3. [Konkrete Aktion]

---

*Analyse erstellt für Stufe 2 nach Besichtigung. Alle Angaben basierend auf Exposé-Informationen.*
```

### Stufe 2 Output: Finale Analyse

```markdown
# Finale Objektanalyse: [Adresse]
**Datum:** [Datum]
**Status:** STUFE 2 - FINALE EINSCHÄTZUNG

---

## 1. DELTA-ANALYSE (Exposé vs. Realität)

| Aspekt | Exposé | Realität | Delta |
|--------|--------|----------|-------|
| Zustand | ... | ... | +/- |
| ... | ... | ... | ... |

**Wesentliche Abweichungen:**
[Beschreibung]

---

## 2. INVESTITIONSBEDARF (5-10 Jahre)

| Massnahme | Zeitraum | Geschätzte Kosten |
|-----------|----------|-------------------|
| ... | ... | CHF ... |
| **Total** | | **CHF ...** |

**Annahmen:**
[Begründung der Schätzungen]

---

## 3. CASHFLOW-PROJEKTION

### Szenario-Übersicht

| Szenario | Jahres-CF | Rendite nach Invest |
|----------|-----------|---------------------|
| Base | CHF ... | X.X% |
| Bull | CHF ... | X.X% |
| Bear | CHF ... | X.X% |

### Base Case Details
[Detaillierte Berechnung]

---

## 4. FINANZIERUNGSCHECK

| Parameter | Wert |
|-----------|------|
| Kaufpreis | CHF ... |
| Eigenkapital (25%) | CHF ... |
| Hypothek | CHF ... |
| Tragbarkeit (5% kalk.) | CHF ... |
| Mieteinnahmen | CHF ... |
| **Deckungsgrad** | **X%** |

**Einschätzung Finanzierbarkeit:**
[Bewertung]

---

## 5. STÄRKEN & SCHWÄCHEN

**Stärken:**
+ [Punkt]
+ [Punkt]

**Schwächen:**
- [Punkt]
- [Punkt]

**Chancen:**
↑ [Punkt]

**Risiken:**
↓ [Punkt]

---

## 6. PREISVERHANDLUNG

**Faire Preisspanne:** CHF [X] - CHF [Y]

**Begründung:**
[Herleitung]

**Verhandlungsargumente:**
1. [Argument]
2. [Argument]

---

## 7. FINALE EMPFEHLUNG

### Verdict: [KAUFEN / VERHANDELN / ABLEHNEN]

**Begründung:**
[Ausführliche Begründung 3-5 Sätze]

**Bedingungen (falls VERHANDELN):**
1. [Bedingung]
2. [Bedingung]

**Nächste Schritte:**
1. [Aktion]
2. [Aktion]

---

*Finale Analyse basierend auf Exposé und Besichtigungserkenntnissen.*
```

## Berechnungslogik

### Bruttorendite
```
BR = (Netto-Mieteinnahmen p.a. / Kaufpreis) × 100
```

### Nettorendite (vereinfacht)
```
NR = ((Mieteinnahmen - Betriebskosten - Rückstellungen) / Kaufpreis) × 100
Betriebskosten: ~1-1.5% des Gebäudeversicherungswerts p.a.
Rückstellungen: ~0.5-1% für Instandhaltung
```

### Preis/m² Bewertung
```
Objektwert = Preis / Nutzfläche
Vergleich mit Marktdaten aus references/marktdaten.md
Abweichung > 15%: Hinterfragen
```

### Tragbarkeitsrechnung (Bank-Perspektive)
```
Kalkulatorische Kosten:
- Hypothekarzins: 5% (kalkulatorisch)
- Amortisation: 1% (falls > 65% Belehnung)
- Nebenkosten: 1%

Tragbar wenn: Mieteinnahmen > Kalkulatorische Kosten × 1.1
```

## Hinweise

- Bei fehlendem PLZ-Marktdaten: Kantonsdurchschnitt verwenden
- Gewerbe konservativ bewerten (höheres Leerstandsrisiko)
- Bei Altbauten (vor 1980) immer Asbest-Risiko erwähnen
- Referenzzinssatz aktuell: 1.25% (Stand Januar 2026)
```

### Embedded reference: `immo-analyse/references/marktdaten.md` (verbatim)

```markdown
# Marktdaten Schweiz (AG, SG, TG, ZH)

Stand: Januar 2026

## Referenzzinssatz
**Aktuell: 1.25%**
Maximale Eigenkapitalrendite gemäss OR 269: Referenzzins + 2% = **3.25%**

## Aargau (AG)

| PLZ | Ort | Miete/m² | Preis/m² | Leerstand | Steuerfuss | Bev.wachstum |
|-----|-----|----------|----------|-----------|------------|--------------|
| 5000 | Aarau | 22.50 | 6'850 | 1.2% | 108% | +0.8% |
| 5033 | Buchs AG | 21.00 | 6'200 | 1.5% | 110% | +1.2% |
| 5034 | Suhr | 21.50 | 6'400 | 1.3% | 105% | +1.0% |
| 5035 | Unterentfelden | 20.50 | 5'900 | 1.4% | 112% | +0.9% |
| 5200 | Brugg | 20.00 | 5'800 | 1.8% | 115% | +0.5% |
| 5210 | Windisch | 21.00 | 6'100 | 1.6% | 108% | +0.7% |
| 5400 | Baden | 26.00 | 8'200 | 0.9% | 94% | +1.1% |
| 5430 | Wettingen | 24.50 | 7'600 | 1.0% | 97% | +1.0% |
| 5432 | Neuenhof | 23.00 | 7'000 | 1.2% | 105% | +0.8% |
| 5600 | Lenzburg | 22.00 | 6'600 | 1.4% | 102% | +0.9% |
| 5610 | Wohlen | 21.00 | 6'200 | 1.6% | 108% | +0.7% |
| 8957 | Spreitenbach | 22.50 | 6'800 | 1.3% | 78% | +1.5% |

**Kantonsdurchschnitt AG:** Miete 21.00/m², Preis 6'500/m², Leerstand 1.4%, Steuerfuss 105%

## St. Gallen (SG)

| PLZ | Ort | Miete/m² | Preis/m² | Leerstand | Steuerfuss | Bev.wachstum |
|-----|-----|----------|----------|-----------|------------|--------------|
| 9000 | St. Gallen | 19.38 | 6'800 | 2.1% | 144% | +0.4% |
| 9008 | St. Gallen | 20.50 | 7'200 | 1.8% | 144% | +0.5% |
| 9010 | St. Gallen | 18.50 | 6'400 | 2.3% | 144% | +0.3% |
| 9200 | Gossau SG | 18.00 | 5'800 | 2.2% | 128% | +0.6% |
| 9300 | Wittenbach | 18.50 | 6'000 | 1.9% | 115% | +0.7% |
| 9400 | Rorschach | 18.00 | 5'600 | 2.5% | 130% | +0.3% |
| 9403 | Goldach | 19.00 | 6'200 | 2.0% | 98% | +0.8% |
| 9404 | Rorschacherberg | 20.00 | 6'800 | 1.6% | 90% | +0.9% |
| 9424 | Rheineck | 17.50 | 5'400 | 2.3% | 110% | +0.4% |
| 9430 | St. Margrethen | 17.00 | 5'200 | 2.5% | 105% | +0.3% |
| 9435 | Heerbrugg | 17.50 | 5'400 | 2.2% | 108% | +0.5% |
| 9436 | Balgach | 18.00 | 5'600 | 2.0% | 61% | +0.8% |
| 9450 | Altstätten | 17.00 | 5'100 | 2.6% | 123% | +0.2% |
| 9500 | Wil SG | 19.00 | 6'000 | 1.8% | 118% | +0.7% |
| 8640 | Rapperswil-Jona | 24.00 | 8'500 | 1.0% | 80% | +1.2% |

**Kantonsdurchschnitt SG:** Miete 18.50/m², Preis 5'800/m², Leerstand 2.0%, Steuerfuss 120%

## Thurgau (TG)

| PLZ | Ort | Miete/m² | Preis/m² | Leerstand | Steuerfuss | Bev.wachstum |
|-----|-----|----------|----------|-----------|------------|--------------|
| 8500 | Frauenfeld | 19.50 | 6'200 | 1.4% | 117% | +0.9% |
| 8505 | Pfyn | 17.50 | 5'400 | 1.8% | 125% | +0.5% |
| 8570 | Weinfelden | 18.50 | 5'700 | 1.6% | 112% | +0.7% |
| 8580 | Amriswil | 18.00 | 5'500 | 1.7% | 115% | +0.6% |
| 8590 | Romanshorn | 18.50 | 5'600 | 1.5% | 118% | +0.7% |
| 9320 | Arbon | 19.00 | 6'000 | 1.4% | 108% | +0.8% |
| 8280 | Kreuzlingen | 21.00 | 7'200 | 1.2% | 102% | +1.0% |
| 8274 | Tägerwilen | 20.00 | 6'800 | 1.3% | 75% | +1.2% |
| 8272 | Ermatingen | 19.50 | 6'500 | 1.4% | 85% | +0.9% |

**Kantonsdurchschnitt TG:** Miete 18.50/m², Preis 5'800/m², Leerstand 1.5%, Steuerfuss 110%

## Zürich (ZH) - Referenz

| PLZ | Ort | Miete/m² | Preis/m² | Leerstand | Steuerfuss | Bev.wachstum |
|-----|-----|----------|----------|-----------|------------|--------------|
| 8400 | Winterthur | 26.00 | 8'500 | 0.9% | 125% | +1.0% |
| 8404 | Winterthur | 24.00 | 7'800 | 1.0% | 125% | +1.1% |

**Kantonsdurchschnitt ZH:** Miete 30.00/m², Preis 11'000/m², Leerstand 0.7%, Steuerfuss 110%

## Rendite-Benchmarks

| Kategorie | Bruttorendite | Bewertung |
|-----------|---------------|-----------|
| Sehr attraktiv | > 5.5% | 🟢🟢 |
| Attraktiv | 4.5-5.5% | 🟢 |
| Moderat | 3.5-4.5% | 🟡 |
| Unter Markt | < 3.5% | 🔴 |

## Preis-Benchmarks nach Region

| Region | Preis/m² günstig | Preis/m² Markt | Preis/m² teuer |
|--------|------------------|----------------|----------------|
| AG Zentral (Baden, Wettingen) | < 7'000 | 7'000-8'500 | > 8'500 |
| AG Peripher | < 5'500 | 5'500-6'500 | > 6'500 |
| SG Stadt | < 6'000 | 6'000-7'500 | > 7'500 |
| SG Land | < 5'000 | 5'000-6'000 | > 6'000 |
| TG Seenähe | < 6'000 | 6'000-7'500 | > 7'500 |
| TG Inland | < 5'000 | 5'000-6'000 | > 6'000 |

## Hinweise zur Verwendung

- Daten basieren auf Inseraten und Transaktionen 2024/2025
- Bei fehlender PLZ: Kantonsdurchschnitt verwenden
- Abweichung Objekt vs. Markt > 15%: Begründung erforderlich
- Bei Gewerbeimmobilien: Miete/m² ca. 20-30% tiefer als Wohnen
- Leerstand > Kantonsdurchschnitt: Erhöhtes Vermietungsrisiko einkalkulieren
```

---

## What this file is NOT

- Not a build spec or ingestion plan — the only confirmed-needed new source above is the
  BFE/Pronovo PV registry for neoteq.
- Not a decision to widen gold or create new schemas — that follows from what the
  exploration queries (run separately, see conversation) actually find.
- Not a replacement for the `immo-analyse` skill itself — this is a copy for CC's context
  only; the live skill stays at `/mnt/skills/user/immo-analyse/`.
