-- silver.gemeinde -- the 5 pilot Gemeinden.
--
-- Built from bronze.gemeinde_bevoelkerung because it is the only landed
-- table carrying BOTH bfs_nr_gemeinde and gemeinde_name. Deriving the
-- dimension from data keeps the BFS numbers out of the DDL; the pilot set
-- is defined by what was ingested, not by a hardcoded list here.
--
-- bezirk_name is normalised by stripping the "Bezirk " prefix:
-- gemeinde_bevoelkerung says "Bezirk Kreuzlingen", bodenpreise says
-- "Kreuzlingen". Silver picks the short form so a join on name works.

DROP TABLE IF EXISTS silver.gemeinde CASCADE;

CREATE TABLE silver.gemeinde (
    bfs_nr        integer PRIMARY KEY,
    gemeinde_name text    NOT NULL,
    bezirk_nr     integer NOT NULL,
    bezirk_name   text    NOT NULL
);

INSERT INTO silver.gemeinde (bfs_nr, gemeinde_name, bezirk_nr, bezirk_name)
SELECT DISTINCT
    bfs_nr_gemeinde::integer,
    gemeinde_name,
    bezirk_nr::integer,
    regexp_replace(bezirk_name, '^Bezirk ', '')
FROM bronze.gemeinde_bevoelkerung;

COMMENT ON TABLE silver.gemeinde IS
    'Pilot Gemeinden (Bezirk Kreuzlingen). Every silver table keys Gemeinde '
    'on bfs_nr integer; bronze is inconsistent (text, integer, bigint, and a '
    'string prefix in bauzonen.t_id).';
