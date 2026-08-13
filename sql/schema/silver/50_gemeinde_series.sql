-- The four Gemeinde statistics time series.
--
-- Thin layer: cast the keys and counts to real types, declare the PKs,
-- keep every column. Bronze landed all of these through to_sql, so `jahr`,
-- `bfs_nr_gemeinde` and `anzahl_personen` are all text.
--
-- KEEP EACH SOURCE'S FULL YEAR RANGE. The ranges differ --
--
--   gemeinde_steuerfuss          2004-2026   (23 years)
--   gemeinde_bevoelkerung        2007-2025   (19 years)
--   gemeinde_bevoelkerung_alter  2015-2025   (11 years)
--   gemeinde_finanzkennzahlen    2019-2024   ( 6 years)  <- binding
--
-- -- and it is tempting to inner-join them into the 2019-2024 intersection
-- so everything lines up. Don't: a 2019 floor silently discards 15 years of
-- tax history, which is exactly the signal the spec wants retained. Four
-- tables, each at its own natural range; callers narrow when they need to.
-- A test asserts the ranges survive the build.
--
-- Note steuerfuss extends to 2026 (an announced rate) while the others stop
-- at 2024/2025, so any "latest year" query must use a per-table max(jahr)
-- or an as-of join rather than a shared constant.

DROP TABLE IF EXISTS silver.gemeinde_steuerfuss CASCADE;

CREATE TABLE silver.gemeinde_steuerfuss (
    bfs_nr                          integer NOT NULL REFERENCES silver.gemeinde (bfs_nr),
    jahr                            integer NOT NULL,
    gesamtsteuerfuss_evang          integer,
    gesamtsteuerfuss_kath           integer,
    gesamtsteuerfuss_konfessionslos integer,
    gesamtsteuerfuss_jp             double precision,
    PRIMARY KEY (bfs_nr, jahr)
);

INSERT INTO silver.gemeinde_steuerfuss
SELECT bfs_nr_gemeinde::integer, left(jahr, 4)::integer,
       gesamtsteuerfuss_evang, gesamtsteuerfuss_kath,
       gesamtsteuerfuss_konfessionslos, gesamtsteuerfuss_jp
FROM bronze.gemeinde_steuerfuss;


DROP TABLE IF EXISTS silver.gemeinde_finanzkennzahlen CASCADE;

CREATE TABLE silver.gemeinde_finanzkennzahlen (
    bfs_nr                                        integer NOT NULL REFERENCES silver.gemeinde (bfs_nr),
    jahr                                          integer NOT NULL,
    selbstfinanzierungsgrad_in                    double precision,
    selbstfinanzierungsanteil_in                  double precision,
    zinsbelastungsanteil_in                       double precision,
    kapitaldienstanteil_in                        double precision,
    investitionsanteil_in                         double precision,
    bruttoverschuldungsanteil_in                  double precision,
    nettoschuld_nettovermogen_pro_einwohner_in_chf double precision,
    nettoverschuldungsquotient_in                 double precision,
    bilanzuberschussquotient_in                   double precision,
    PRIMARY KEY (bfs_nr, jahr)
);

INSERT INTO silver.gemeinde_finanzkennzahlen
SELECT bfs_nr_gemeinde::integer, left(jahr, 4)::integer,
       selbstfinanzierungsgrad_in, selbstfinanzierungsanteil_in,
       zinsbelastungsanteil_in, kapitaldienstanteil_in,
       investitionsanteil_in, bruttoverschuldungsanteil_in,
       nettoschuld_nettovermogen_pro_einwohner_in_chf,
       nettoverschuldungsquotient_in, bilanzuberschussquotient_in
FROM bronze.gemeinde_finanzkennzahlen;


DROP TABLE IF EXISTS silver.gemeinde_bevoelkerung CASCADE;

CREATE TABLE silver.gemeinde_bevoelkerung (
    bfs_nr          integer NOT NULL REFERENCES silver.gemeinde (bfs_nr),
    jahr            integer NOT NULL,
    anzahl_personen integer NOT NULL,
    PRIMARY KEY (bfs_nr, jahr)
);

-- anzahl_personen is text in bronze but verified 100% clean integers, so a
-- plain cast is safe rather than a filtered one.
INSERT INTO silver.gemeinde_bevoelkerung
SELECT bfs_nr_gemeinde::integer, left(jahr, 4)::integer, anzahl_personen::integer
FROM bronze.gemeinde_bevoelkerung;


DROP TABLE IF EXISTS silver.gemeinde_bevoelkerung_alter CASCADE;

CREATE TABLE silver.gemeinde_bevoelkerung_alter (
    bfs_nr                   integer  NOT NULL REFERENCES silver.gemeinde (bfs_nr),
    jahr                     integer  NOT NULL,
    geschlecht_code          smallint NOT NULL,
    geschlecht_bezeichnung   text     NOT NULL,
    alter5klassen_code       smallint NOT NULL,
    alter5klassen_bezeichnung text    NOT NULL,
    anzahl_personen          integer  NOT NULL,
    PRIMARY KEY (bfs_nr, jahr, geschlecht_code, alter5klassen_code)
);

-- alter5klassen_code is the LOWER BOUND of the 5-year band (0, 5, 10 ... 90),
-- which makes it directly usable for numeric bucketing.
INSERT INTO silver.gemeinde_bevoelkerung_alter
SELECT bfs_nr_gemeinde::integer, left(jahr, 4)::integer,
       geschlecht_code, geschlecht_bezeichnung,
       alter5klassen_code, alter5klassen_bezeichnung,
       anzahl_personen::integer
FROM bronze.gemeinde_bevoelkerung_alter;

COMMENT ON COLUMN silver.gemeinde_steuerfuss.jahr IS
    'Runs to 2026 -- an announced rate, further ahead than any other series. '
    'Do not assume a shared latest year across these four tables.';
COMMENT ON COLUMN silver.gemeinde_bevoelkerung_alter.alter5klassen_code IS
    'Lower bound of the 5-year age band (0, 5, ... 90).';
