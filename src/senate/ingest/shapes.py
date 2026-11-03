"""Census cartographic boundary files -> simplified county shapes (plan §4.8)."""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

from ..config import ROOT
from ..io import Fetcher
from ._base import interim_dir, log, processed_dir, stamp, write_parquet

GENZ_URL = "https://www2.census.gov/geo/tiger/GENZ{year}/shp/cb_{year}_us_county_500k.zip"
MIN_AREA_SQ_DEG = 1e-6


def build_geographies(shapes) -> pd.DataFrame:
    """GeoDataFrame (GEOID, STATEFP, NAME, geometry) -> canonical geographies rows (plan §5.3, county level)."""
    from ..geo.fips import FIPS_STATE

    g = shapes[shapes["STATEFP"].isin(FIPS_STATE) & (shapes["STATEFP"] != "11")].copy()
    cent = g.geometry.representative_point()
    return pd.DataFrame({
        "geoid": g["GEOID"].values, "level": "county", "name": g["NAME"].values,
        "state_po": g["STATEFP"].map(FIPS_STATE).values, "parent_geoid": g["STATEFP"].values,
        "centroid_lon": cent.x.values, "centroid_lat": cent.y.values,
    })


def ingest_shapes(fetcher: Fetcher | None = None, year: int = 2024, work_dir: Path | None = None) -> Path:
    """Download the county cartographic file, drop slivers, write interim GeoParquet + geographies.parquet."""
    import geopandas as gpd

    own = fetcher is None
    fetcher = fetcher or Fetcher()
    try:
        body = fetcher.get(GENZ_URL.format(year=year), "census_shapes")
        work = Path(work_dir or interim_dir() / f"shapes_{year}")
        work.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            z.extractall(work)
        shp = next(work.glob("*.shp"))
        g = gpd.read_file(shp).to_crs(4326)
        g = g[g.geometry.area >= MIN_AREA_SQ_DEG].copy()
        out = work.parent / "county_shapes.parquet"
        g.to_parquet(out)
        geo = stamp(build_geographies(g), "census_shapes", f"GENZ{year}")
        write_parquet(geo, processed_dir() / "geographies.parquet")
        log.info("source_fetch", source="shapes", status="ok", rows=len(geo), fallback=False)
        return out
    finally:
        if own:
            fetcher.close()
