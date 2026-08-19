-- silver.gemeinde_energiefoerderung -- cantonal energy-subsidy programme.
-- One row per Gemeinde per year, a COUNT of subsidised projects per measure.
--
-- From bronze.gemeinde_energiefoerderung (data.tg.ch div-energie-2). This is
-- the cantonal Energiefoerderprogramm, which carries the federal
-- "Gebaeudeprogramm" measures (Gebaeudehuelle, GEAK-Sanierung).
--
-- GEMEINDE-LEVEL CONTEXT, NOT PER-BUILDING. It carries no building/parcel id
-- and is deliberately NOT joined to neoteq.candidate (a test asserts no such
-- link exists). It is an adoption/market signal -- how many heat pumps or
-- envelope renovations were subsidised in a Gemeinde in a year. Grain
-- (bfs_nr, jahr), 2008-2024, all 5 pilot Gemeinden.
--
-- KEEP THE FULL YEAR RANGE, like the four series in 50_gemeinde_series.sql:
-- callers narrow when they need to. Thin layer -- cast the text keys/counts to
-- real types, declare the PK, keep every measure column. Bronze landed this
-- through to_sql, so the keys are text and `jahr` is a 'YYYY' string; the count
-- columns are wrapped `nullif(col::text, '')::integer` so both the int-typed
-- columns and the one text-typed column (machbarkeitsstudie) cast uniformly.

DROP TABLE IF EXISTS silver.gemeinde_energiefoerderung CASCADE;

CREATE TABLE silver.gemeinde_energiefoerderung (
    bfs_nr              integer NOT NULL REFERENCES silver.gemeinde (bfs_nr),
    jahr                integer NOT NULL,
    gebaeudehuelle      integer,
    geak_sanierung      integer,
    minergie_sanierung  integer,
    minergie_neubau     integer,
    holz                integer,
    waermepumpe         integer,
    waermenetzanschluss integer,
    waermenetzprojekt   integer,
    solarthermieanlage  integer,
    solarstromanlage    integer,
    batteriespeicher    integer,
    energieeffizienz    integer,
    neleuchtungsanlagen integer,
    komfortlueftung     integer,
    elektrofahrzeug     integer,
    ladeinfrastruktur   integer,
    geak_plus           integer,
    machbarkeitsstudie  integer,
    energieanalyse      integer,
    wkk                 integer,
    biogasanlage        integer,
    sonstige            integer,
    total               integer,
    PRIMARY KEY (bfs_nr, jahr)
);

INSERT INTO silver.gemeinde_energiefoerderung
SELECT
    bfs_nr_gemeinde::integer,
    left(jahr, 4)::integer,
    nullif(gebaeudehuelle::text, '')::integer,
    nullif(geak_sanierung::text, '')::integer,
    nullif(minergie_sanierung::text, '')::integer,
    nullif(minergie_neubau::text, '')::integer,
    nullif(holz::text, '')::integer,
    nullif(waermepumpe::text, '')::integer,
    nullif(waermenetzanschluss::text, '')::integer,
    nullif(waermenetzprojekt::text, '')::integer,
    nullif(solarthermieanlage::text, '')::integer,
    nullif(solarstromanlage::text, '')::integer,
    nullif(batteriespeicher::text, '')::integer,
    nullif(energieeffizienz::text, '')::integer,
    nullif(neleuchtungsanlagen::text, '')::integer,
    nullif(komfortlueftung::text, '')::integer,
    nullif(elektrofahrzeug::text, '')::integer,
    nullif(ladeinfrastruktur::text, '')::integer,
    nullif(geak_plus::text, '')::integer,
    nullif(machbarkeitsstudie::text, '')::integer,
    nullif(energieanalyse::text, '')::integer,
    nullif(wkk::text, '')::integer,
    nullif(biogasanlage::text, '')::integer,
    nullif(sonstige::text, '')::integer,
    nullif(total::text, '')::integer
FROM bronze.gemeinde_energiefoerderung;

COMMENT ON TABLE silver.gemeinde_energiefoerderung IS
    'Cantonal energy-subsidy programme, one row per Gemeinde-year, a count of '
    'subsidised projects per measure. Gemeinde-level adoption/market context, '
    'not per-building; deliberately not joined to neoteq.candidate.';
COMMENT ON COLUMN silver.gemeinde_energiefoerderung.waermepumpe IS
    'Count of subsidised heat-pump projects in the Gemeinde that year -- a '
    'competitive/adoption signal for the neoteq strand, not a per-building fact.';
