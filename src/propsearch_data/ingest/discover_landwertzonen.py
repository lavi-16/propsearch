"""
Discover and pull Thurgau Landwertzonen (land value zones) via WFS.

WHY THIS NEEDS TO RUN FROM YOUR OWN NETWORK, NOT CLAUDE'S SANDBOX
------------------------------------------------------------------
Claude's fetch tool honors ows.geo.tg.ch's robots.txt, which asks automated
crawlers to stay out. That's a polite-crawler convention, not an access
control -- WFS servers are built to be called by scripts and GIS software,
so it's very likely this just works from your machine or from Claude Code
running with real network access. If it *doesn't* work even from there,
that would mean there's an actual IP/referrer restriction, which is a
different problem with a different fix (e.g. going through geodienste.ch
or requesting access via agi@tg.ch).

WHAT'S CONFIRMED VS. GUESSED
------------------------------------------------------------------
Confirmed: the URL pattern ows.geo.tg.ch/geofy_access_proxy/{slug} is real
-- I saw it working for oereb_ortsplanung_bauzonen (zoning) and
gewaesserkataster_gewaesser (water), both live services.

Guessed: the slug for Landwertzonen. I don't have it confirmed, so this
script tries several plausible candidates and tells you which one (if any)
actually answers, rather than assuming.

Also approximate: PILOT_BBOX below is a rough guess at the Bodensee-front
cluster (Kreuzlingen/Taegerwilen/Bottighofen/Muensterlingen/Ermatingen) --
verify it against a real coordinate before trusting results.
"""

import json
import requests

BASE = "https://ows.geo.tg.ch/geofy_access_proxy/{slug}"

# Candidate service slugs, based on the naming pattern seen in other
# confirmed TG WFS services. None of these are verified -- that's the
# point of find_working_slug() below.
CANDIDATE_SLUGS = [
    "landwertzonen",
    "landwertzonen_liegenschaften",
    "steuerverwaltung_landwertzonen",
    "sv_landwertzonen",
]

# EPSG:2056 (LV95) bbox roughly covering the pilot Gemeinden -- APPROXIMATE,
# widen or correct against a known point (e.g. a Kreuzlingen address) first.
PILOT_BBOX = "2740000,1273000,2755000,1281000"


def find_working_slug():
    for slug in CANDIDATE_SLUGS:
        url = BASE.format(slug=slug)
        params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetCapabilities"}
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200 and b"WFS_Capabilities" in r.content[:300]:
                print(f"working slug found: {slug}")
                return slug, url
            print(f"  {slug}: HTTP {r.status_code}, not a WFS capabilities doc")
        except requests.RequestException as e:
            print(f"  {slug}: {e}")
    return None, None


def describe_feature_type(base_url):
    params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "DescribeFeatureType"}
    r = requests.get(base_url, params=params, timeout=15)
    r.raise_for_status()
    print(r.text[:3000])
    return r.text


def get_features(base_url, typename):
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": typename,
        "BBOX": f"{PILOT_BBOX},EPSG:2056",
        "OUTPUTFORMAT": "application/json",
    }
    r = requests.get(base_url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    slug, base_url = find_working_slug()

    if not base_url:
        print("\nNone of the guessed slugs worked. Reliable fallback:")
        print("  1. Open map.geo.tg.ch, switch to topic 'ech'")
        print("  2. Turn on the Landwertzonen layer")
        print("  3. Open browser dev tools -> Network tab")
        print("  4. Look for the actual WFS/WMS request the viewer makes")
        print("     -- that URL contains the real service slug + layer names.")
        raise SystemExit(1)

    print("\n--- DescribeFeatureType output (real field names) ---")
    describe_feature_type(base_url)

    # After reading the XSD printed above, set the real typename, e.g.:
    # typename = "ms:landwertzonen_liegenschaften_f"
    typename = "REPLACE_WITH_REAL_TYPENAME_FROM_XSD_ABOVE"

    geojson = get_features(base_url, typename)
    with open("landwertzonen_pilot.geojson", "w") as f:
        json.dump(geojson, f, indent=2)
    print(f"\nSaved {len(geojson.get('features', []))} features to landwertzonen_pilot.geojson")
