-- gold.gemeinde_year -- the Gemeinde-context fact. One row per Gemeinde per
-- year, 115 rows (5 Gemeinden x 2004-2026).
--
-- THE SPINE IS A UNION, NOT A SOURCE TABLE. Steuerfuss spans 2004-2026 and
-- today happens to cover every year the other three series carry, so
-- sourcing the spine from it would produce the same 115 rows. It is still
-- wrong: a future series carrying a year outside that range would be
-- silently dropped. The UNION below makes every source's year-space part of
-- the key, so a new year arrives instead of vanishing.
--
-- RAGGED IS CORRECT. This table is full of NULLs by design:
--
--   gemeinde_steuerfuss          2004-2026   (23 years)
--   gemeinde_bevoelkerung        2007-2025   (19 years)
--   gemeinde_bevoelkerung_alter  2015-2025   (11 years)  <- the age shares
--   gemeinde_finanzkennzahlen    2019-2024   ( 6 years)  <- binding
--
-- Inner-joining these into their 2019-2024 intersection would look tidy and
-- would throw away 15 years of tax history. Callers narrow; gold does not.
-- Do not "fix" the NULLs, and do not use a shared latest-year constant --
-- there isn't one. Steuerfuss already knows 2026; Finanzkennzahlen stops at
-- 2024.
--
-- WHY THE AGE STRUCTURE IS TWO SHARES AND NOT A JOIN.
-- silver.gemeinde_bevoelkerung_alter is 2 sexes x 19 five-year bands = 38
-- rows per Gemeinde-year. Joining it in directly fans 5 rows into 190 per
-- year -- the same grain mistake the bodenpreis/parcel split avoids. It is
-- aggregated to two shares instead.
--
-- pct_65_plus and pct_under_20 specifically, because both cuts fall EXACTLY
-- on a band boundary (65+ is codes 65..90; under-20 is codes 0,5,10,15), so
-- both are exact sums with no within-band interpolation. A median or mean
-- age would need an interpolation assumption and an invented midpoint for
-- the open-ended 90+ band -- precision the source does not contain, and
-- this project does not invent statistics the source withheld (see the
-- Bodenpreise Zentralwert, which is described but never published).
--
-- They are also the two shares that matter for screening rather than for
-- demography: 65+ proxies downsizing turnover and future supply, under-20
-- proxies family formation, which is what separates EFH from MFH demand.
-- Together they determine the 20-64 working-age share as the residual, so
-- two columns carry three facts.
--
-- Verified on the landed data: the age-class sums reconcile EXACTLY with
-- gemeinde_bevoelkerung.anzahl_personen on all 55 overlapping Gemeinde-
-- years (zero mismatches), so einwohner can come from the population series
-- and the shares from the age series without the two contradicting.

DROP TABLE IF EXISTS gold.gemeinde_year CASCADE;

CREATE TABLE gold.gemeinde_year (
    bfs_nr                          integer  NOT NULL,
    jahr                            integer  NOT NULL,
    gemeinde_name                   text     NOT NULL,
    bezirk_name                     text     NOT NULL,

    -- Steuerfuss (sk-stat-70), 2004-2026
    steuerfuss_evang                integer,
    steuerfuss_kath                 integer,
    steuerfuss_konfessionslos       integer,
    steuerfuss_jp                   double precision,

    -- Finanzkennzahlen (sk-stat-4), 2019-2024 only
    selbstfinanzierungsgrad_pct     double precision,
    selbstfinanzierungsanteil_pct   double precision,
    zinsbelastungsanteil_pct        double precision,
    kapitaldienstanteil_pct         double precision,
    investitionsanteil_pct          double precision,
    bruttoverschuldungsanteil_pct   double precision,
    nettoschuld_pro_einwohner_chf   double precision,
    nettoverschuldungsquotient_pct  double precision,
    bilanzueberschussquotient_pct   double precision,

    -- Bevoelkerung (sk-stat-56), 2007-2025; shares (sk-stat-58) 2015-2025
    einwohner                       integer,
    pct_65_plus                     numeric(4, 1),
    pct_under_20                    numeric(4, 1),

    PRIMARY KEY (bfs_nr, jahr),

    CONSTRAINT gy_einwohner_positive CHECK (einwohner IS NULL OR einwohner > 0),
    CONSTRAINT gy_pct_65_range   CHECK (pct_65_plus  IS NULL OR pct_65_plus  BETWEEN 0 AND 100),
    CONSTRAINT gy_pct_u20_range  CHECK (pct_under_20 IS NULL OR pct_under_20 BETWEEN 0 AND 100),
    -- Both shares come from the same aggregation over the same rows, so one
    -- present without the other means the aggregation lost a band.
    CONSTRAINT gy_shares_paired
        CHECK ((pct_65_plus IS NULL) = (pct_under_20 IS NULL)),
    CONSTRAINT gy_shares_sum_under_100
        CHECK (pct_65_plus IS NULL OR pct_65_plus + pct_under_20 <= 100)
);

INSERT INTO gold.gemeinde_year (
    bfs_nr, jahr, gemeinde_name, bezirk_name,
    steuerfuss_evang, steuerfuss_kath, steuerfuss_konfessionslos, steuerfuss_jp,
    selbstfinanzierungsgrad_pct, selbstfinanzierungsanteil_pct,
    zinsbelastungsanteil_pct, kapitaldienstanteil_pct, investitionsanteil_pct,
    bruttoverschuldungsanteil_pct, nettoschuld_pro_einwohner_chf,
    nettoverschuldungsquotient_pct, bilanzueberschussquotient_pct,
    einwohner, pct_65_plus, pct_under_20
)
WITH gemeinde_year AS (
    -- Every (Gemeinde, year) any series knows about. UNION, not the widest
    -- single table -- see the header.
    SELECT bfs_nr, jahr FROM silver.gemeinde_steuerfuss
    UNION
    SELECT bfs_nr, jahr FROM silver.gemeinde_finanzkennzahlen
    UNION
    SELECT bfs_nr, jahr FROM silver.gemeinde_bevoelkerung
    UNION
    SELECT bfs_nr, jahr FROM silver.gemeinde_bevoelkerung_alter
),
altersstruktur AS (
    -- 38 rows per Gemeinde-year collapsed to one. Band boundaries fall
    -- exactly on 20 and 65, so these are exact sums, not estimates.
    SELECT
        bfs_nr,
        jahr,
        round(100.0 * sum(anzahl_personen) FILTER (WHERE alter5klassen_code >= 65)
              / sum(anzahl_personen), 1) AS pct_65_plus,
        round(100.0 * sum(anzahl_personen) FILTER (WHERE alter5klassen_code < 20)
              / sum(anzahl_personen), 1) AS pct_under_20
    FROM silver.gemeinde_bevoelkerung_alter
    GROUP BY bfs_nr, jahr
)
SELECT
    gy.bfs_nr,
    gy.jahr,
    g.gemeinde_name,
    g.bezirk_name,

    s.gesamtsteuerfuss_evang,
    s.gesamtsteuerfuss_kath,
    s.gesamtsteuerfuss_konfessionslos,
    s.gesamtsteuerfuss_jp,

    f.selbstfinanzierungsgrad_in,
    f.selbstfinanzierungsanteil_in,
    f.zinsbelastungsanteil_in,
    f.kapitaldienstanteil_in,
    f.investitionsanteil_in,
    f.bruttoverschuldungsanteil_in,
    f.nettoschuld_nettovermogen_pro_einwohner_in_chf,
    f.nettoverschuldungsquotient_in,
    f.bilanzuberschussquotient_in,

    b.anzahl_personen,
    a.pct_65_plus,
    a.pct_under_20
FROM gemeinde_year gy
JOIN      silver.gemeinde                    g USING (bfs_nr)
LEFT JOIN silver.gemeinde_steuerfuss         s USING (bfs_nr, jahr)
LEFT JOIN silver.gemeinde_finanzkennzahlen   f USING (bfs_nr, jahr)
LEFT JOIN silver.gemeinde_bevoelkerung       b USING (bfs_nr, jahr)
LEFT JOIN altersstruktur                     a USING (bfs_nr, jahr);

CREATE INDEX gemeinde_year_jahr_idx ON gold.gemeinde_year (jahr);

COMMENT ON TABLE gold.gemeinde_year IS
    'Gemeinde context fact, one row per (bfs_nr, jahr). Joins to gold.parcel '
    'on bfs_nr -- but ALWAYS with a year predicate. bfs_nr alone multiplies '
    '9,879 parcels by up to 23 years.';
COMMENT ON COLUMN gold.gemeinde_year.pct_65_plus IS
    'Share of population aged 65+. Exact sum over whole 5-year bands, not '
    'interpolated. NULL outside 2015-2025 -- the age series does not reach '
    'further back, and that is a coverage fact, not a zero.';
COMMENT ON COLUMN gold.gemeinde_year.pct_under_20 IS
    'Share of population aged under 20. With pct_65_plus this determines the '
    '20-64 working-age share as the residual.';
COMMENT ON COLUMN gold.gemeinde_year.steuerfuss_jp IS
    'Juristische Personen. Note this series runs to 2026 while '
    'Finanzkennzahlen stops at 2024 -- there is no shared "latest year".';
COMMENT ON COLUMN gold.gemeinde_year.nettoschuld_pro_einwohner_chf IS
    'Source name is nettoschuld_nettovermogen_... -- a NEGATIVE value is net '
    'wealth, not a data error.';
