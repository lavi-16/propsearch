"""
The building spine -- the new grain below the parcel, and the three traps
its constraints exist to make unreachable: the GSTAT demolished-building
filter, null-means-unrecorded on a raw register, and egrid-as-a-link.
"""


def test_building_row_count(scalar):
    assert scalar("SELECT count(*) FROM silver.building") == 11217
    assert scalar("SELECT count(DISTINCT egid) FROM silver.building") == 11217


def test_geometry_type_and_srid(rows):
    assert rows(
        "SELECT DISTINCT GeometryType(geom), ST_SRID(geom) FROM silver.building"
    ) == [("POINT", 2056)]


# --- GSTAT: demolished must never read as current -------------------------


def test_gstat_split(scalar):
    """700 demolished + 125 projected/approved/under-construction look
    entirely current; is_existing is what keeps them out of a current count."""
    assert scalar("SELECT count(*) FROM silver.building WHERE is_existing") == 10392
    assert scalar("SELECT count(*) FROM silver.building WHERE NOT is_existing") == 825
    assert scalar(
        "SELECT count(*) FROM silver.building WHERE gstat = '1007'"
    ) == 700


def test_is_existing_is_tied_to_gstat(scalar):
    """The CHECK also enforces this; asserted here so a break localises."""
    assert scalar(
        "SELECT count(*) FROM silver.building WHERE is_existing <> (gstat = '1004')"
    ) == 0


# --- egrid is a link, not a key, not a FK ---------------------------------


def test_egrid_join_rate_to_parcel(scalar):
    """92.2% resolve to a parcel; the rest have no egrid or sit outside the
    pilot Landwertzonen set. This is why egrid is nullable and not a FK."""
    assert scalar(
        "SELECT count(*) FROM silver.building b "
        "JOIN silver.parcel p ON p.egrid = b.egrid"
    ) == 10344
    assert scalar("SELECT count(*) FROM silver.building WHERE egrid IS NULL") == 383


def test_one_parcel_holds_many_buildings(scalar):
    """The fan-out the grain warning is about: aggregate before any per-parcel
    count. Some parcels carry many buildings."""
    assert scalar(
        "SELECT max(n) FROM (SELECT count(*) n FROM silver.building "
        "WHERE egrid IS NOT NULL GROUP BY egrid) x"
    ) >= 20


# --- null means unrecorded ------------------------------------------------


def test_nulls_are_preserved_not_zeroed(scalar):
    """A raw register: an unrecorded measure is NULL, never 0. The empty
    strings from MADD must land as NULL, and the CHECKs forbid a 0."""
    assert scalar(
        "SELECT count(*) FROM silver.building WHERE volume_m3 IS NOT NULL"
    ) < 1000  # ~3.5% filled
    assert scalar(
        "SELECT count(*) FROM silver.building "
        "WHERE area_m2 = 0 OR volume_m3 = 0 OR floors = 0 OR dwellings = 0"
    ) == 0
    assert scalar(
        "SELECT count(*) FROM silver.building WHERE year_built IS NOT NULL "
        "AND year_built NOT BETWEEN 1200 AND 2035"
    ) == 0


# --- decode is 1:1, not fanned ---------------------------------------------


def test_code_decode_did_not_fan_out(scalar):
    """Decoding via bronze.gwr_kodes must join on (cecodid, cmerkm); joining
    on cecodid alone would multiply rows. Row count proves it stayed 1:1."""
    assert scalar("SELECT count(*) FROM silver.building") == 11217
    # A decoded label exists wherever the raw code does.
    assert scalar(
        "SELECT count(*) FROM silver.building b JOIN bronze.gwr_gebaeude g "
        "ON g.egid = b.egid WHERE g.gkat <> '' AND b.building_category IS NULL"
    ) == 0
