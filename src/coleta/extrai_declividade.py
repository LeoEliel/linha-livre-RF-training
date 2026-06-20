"""
extrai_declividade.py — Declividade por trecho (Projeto Atola)

Le o DEM Copernicus GLO-30 (output_hh.tif, EPSG:4326, ~30 m), calcula a
declividade CORRETAMENTE e agrega ao longo do buffer de cada trecho (linha).

CORRECAO IMPORTANTE: o DEM esta em GRAUS (EPSG:4326). Calcular np.gradient
direto na resolucao em graus da um valor sem sentido (erro de ~10^4). A
declividade so fica correta apos reprojetar o DEM para um CRS METRICO.
Reprojetamos para SIRGAS 2000 / UTM 20S (EPSG:31980), que cobre RO.
(Math validada: rampa de 8% -> 8.00% apos reprojecao; 864242% sem ela.)

Saidas por trecho (PERCENTUAL, p/ casar com o protocolo de rotulagem):
    decliv_media_pct, decliv_max_pct, frac_plana (<2%), frac_ingreme (>8%)
    decliv_media_graus (auxiliar)

Uso:
    python extrai_declividade.py --dem output_hh.tif \
        --trechos trechos/trechos.geojson --buffer 20 \
        --saida data/interim/declividade.csv
"""

import argparse

import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.io import MemoryFile
from rasterio.mask import mask as rio_mask
from rasterio.warp import calculate_default_transform, reproject, Resampling

CRS_METRICO = "EPSG:31980"  # SIRGAS 2000 / UTM 20S — Rondonia
PLANO_PCT = 2.0             # "muito plano" (empoça)
INGREME_PCT = 8.0          # "ingreme" (erosao/tracao)


def reprojeta_para_metrico(dem_path):
    with rasterio.open(dem_path) as src:
        nodata = src.nodata
        transform, w, h = calculate_default_transform(
            src.crs, CRS_METRICO, src.width, src.height, *src.bounds)
        dst = np.full((h, w), np.nan, dtype="float32")
        reproject(
            source=rasterio.band(src, 1), destination=dst,
            src_transform=src.transform, src_crs=src.crs,
            dst_transform=transform, dst_crs=CRS_METRICO,
            src_nodata=nodata, dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
    dst[dst < -1000] = np.nan  # oceano/vazios COP30
    return dst, transform


def calcula_slope_pct(dem, transform):
    res_x, res_y = abs(transform.a), abs(transform.e)
    dz_dy, dz_dx = np.gradient(dem, res_y, res_x)  # m por m
    return (100.0 * np.sqrt(dz_dx ** 2 + dz_dy ** 2)).astype("float32")


def slope_memfile(slope, transform):
    h, w = slope.shape
    perfil = {"driver": "GTiff", "height": h, "width": w, "count": 1,
              "dtype": "float32", "crs": CRS_METRICO, "transform": transform,
              "nodata": float("nan")}
    mem = MemoryFile()
    with mem.open(**perfil) as ds:
        ds.write(slope, 1)
    return mem


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dem", required=True)
    ap.add_argument("--trechos", required=True)
    ap.add_argument("--buffer", type=float, default=20.0)
    ap.add_argument("--saida", required=True)
    args = ap.parse_args()

    print("Reprojetando DEM para metrico (EPSG:31980)...")
    dem, transform = reprojeta_para_metrico(args.dem)
    slope = calcula_slope_pct(dem, transform)
    print(f"  slope%: media={np.nanmean(slope):.2f} max={np.nanmax(slope):.2f}")

    trechos = gpd.read_file(args.trechos).to_crs(CRS_METRICO)
    bufs = trechos.geometry.buffer(args.buffer)

    mem = slope_memfile(slope, transform)
    linhas = []
    with mem.open() as ds:
        for tid, geom in zip(trechos["trecho_id"], bufs):
            try:
                recorte, _ = rio_mask(ds, [geom.__geo_interface__], crop=True, filled=True)
                vals = recorte[0]
                vals = vals[np.isfinite(vals)]
            except Exception:
                vals = np.array([])
            if vals.size == 0:
                linhas.append({"trecho_id": tid, "decliv_media_pct": None,
                               "decliv_max_pct": None, "frac_plana": None,
                               "frac_ingreme": None, "decliv_media_graus": None})
                continue
            media = float(vals.mean())
            linhas.append({
                "trecho_id": tid,
                "decliv_media_pct": round(media, 2),
                "decliv_max_pct": round(float(vals.max()), 2),
                "frac_plana": round(float((vals < PLANO_PCT).mean()), 3),
                "frac_ingreme": round(float((vals > INGREME_PCT).mean()), 3),
                "decliv_media_graus": round(float(np.degrees(np.arctan(media / 100.0))), 2),
            })

    df = pd.DataFrame(linhas)
    df.to_csv(args.saida, index=False)
    n_ok = df["decliv_media_pct"].notna().sum()
    print(f"OK: {len(df)} trechos ({n_ok} com cobertura do DEM) -> {args.saida}")
    if len(df) - n_ok:
        print(f"  AVISO: {len(df)-n_ok} trechos fora da extensao do DEM (amplie o clip COP30).")


if __name__ == "__main__":
    main()
