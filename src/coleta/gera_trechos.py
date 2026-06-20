"""
gera_trechos.py — Gera a malha de trechos do Projeto Atola

Baixa vias vicinais do OpenStreetMap (Overpass API) numa bbox e as segmenta
em trechos de comprimento ~homogeneo (alvo 1.5 km), atribuindo trecho_id e
calculando o centroide (ponto representativo p/ amostragem de chuva).

Unidade de analise = LINHA. A segmentacao usa shapely.ops.substring sobre a
geometria reprojetada para CRS metrico (SIRGAS 2000 / UTM 20S, EPSG:31980),
que cobre Rondonia. A logica de corte foi validada: corte por arc-length
produz segmentos de comprimento uniforme e preserva vertices internos.

Uso (em Codespaces, com rede):
    # baixar do OSM e segmentar:
    python gera_trechos.py --bbox -10.30 -63.30 -9.60 -62.50 \
        --regiao ARQ --alvo-km 1.5 --saida trechos/trechos.geojson

    # ou segmentar um GeoJSON ja baixado:
    python gera_trechos.py --entrada vias_osm.geojson \
        --regiao ARQ --alvo-km 1.5 --saida trechos/trechos.geojson

bbox = sul oeste norte leste (lat_min lon_min lat_max lon_max).
Default = regiao de Ariquemes / Vale do Jamari.
"""

import argparse
import json

import geopandas as gpd
import requests
from shapely.geometry import LineString, MultiLineString
from shapely.ops import substring

OVERPASS = "https://overpass-api.de/api/interpreter"
CRS_GEO = 4326          # lat/lon
CRS_METRICO = 31980     # SIRGAS 2000 / UTM 20S — cobre Rondonia
# classes de via tratadas como vicinais/rurais:
CLASSES = "track|unclassified|tertiary|residential"


def baixa_osm(bbox):
    """Baixa ways de vias vicinais na bbox (sul,oeste,norte,leste). Retorna GeoDataFrame 4326."""
    s, w, n, e = bbox
    query = f"""
    [out:json][timeout:180];
    (
      way["highway"~"^({CLASSES})$"]({s},{w},{n},{e});
    );
    out geom;
    """
    print(f"Consultando Overpass na bbox {bbox} ...")
    r = requests.post(OVERPASS, data={"data": query}, timeout=300)
    r.raise_for_status()
    elementos = r.json().get("elements", [])
    print(f"  {len(elementos)} vias retornadas.")

    registros = []
    for el in elementos:
        geom = el.get("geometry")
        if not geom or len(geom) < 2:
            continue
        coords = [(p["lon"], p["lat"]) for p in geom]
        tags = el.get("tags", {})
        registros.append({
            "osm_id": el["id"],
            "highway": tags.get("highway"),
            "surface": tags.get("surface"),  # pode ser None — preencher no campo
            "nome": tags.get("name"),
            "geometry": LineString(coords),
        })
    if not registros:
        raise SystemExit("Nenhuma via vicinal encontrada na bbox. Amplie a area.")
    return gpd.GeoDataFrame(registros, crs=CRS_GEO)


def segmenta(linha, alvo_m):
    """Corta uma LineString (em CRS metrico) em segmentos de ~alvo_m. Retorna lista de LineString."""
    L = linha.length
    if L <= alvo_m:
        return [linha]
    n = max(1, round(L / alvo_m))
    passo = L / n
    segs = []
    for i in range(n):
        s = substring(linha, i * passo, (i + 1) * passo)
        if isinstance(s, LineString) and s.length > 0:
            segs.append(s)
    return segs


def centroide_por_comprimento(linha):
    """Ponto no meio do comprimento da linha (representativo, fica sobre o traçado)."""
    return linha.interpolate(linha.length / 2)


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--bbox", nargs=4, type=float,
                     metavar=("SUL", "OESTE", "NORTE", "LESTE"),
                     help="baixar do OSM nesta bbox")
    src.add_argument("--entrada", help="GeoJSON/shapefile de vias ja baixado")
    ap.add_argument("--regiao", default="ARQ", help="prefixo do trecho_id (ex.: ARQ)")
    ap.add_argument("--alvo-km", type=float, default=1.5, help="comprimento-alvo do trecho (km)")
    ap.add_argument("--saida", required=True)
    args = ap.parse_args()

    if args.bbox:
        vias = baixa_osm(args.bbox)
    else:
        vias = gpd.read_file(args.entrada)
        if vias.crs is None:
            vias = vias.set_crs(CRS_GEO)
        vias = vias.to_crs(CRS_GEO)

    # reprojeta para metros, segmenta por via, mantem atributos
    vias_m = vias.to_crs(CRS_METRICO)
    alvo_m = args.alvo_km * 1000.0

    linhas = []
    contador = 1
    for _, via in vias_m.iterrows():
        geom = via.geometry
        partes = geom.geoms if isinstance(geom, MultiLineString) else [geom]
        for parte in partes:
            for seg in segmenta(parte, alvo_m):
                linhas.append({
                    "trecho_id": f"RO-{args.regiao}-{contador:04d}",
                    "osm_id": via.get("osm_id"),
                    "highway": via.get("highway"),
                    "surface": via.get("surface"),
                    "nome": via.get("nome"),
                    "comp_m": round(seg.length, 1),
                    "geometry": seg,
                })
                contador += 1

    trechos_m = gpd.GeoDataFrame(linhas, crs=CRS_METRICO)

    # centroide por comprimento (em metros) e reprojeta tudo de volta p/ 4326
    cent_m = trechos_m.geometry.apply(centroide_por_comprimento)
    cent_geo = gpd.GeoSeries(cent_m, crs=CRS_METRICO).to_crs(CRS_GEO)
    trechos = trechos_m.to_crs(CRS_GEO)
    trechos["lat_centroide"] = cent_geo.y.round(4)
    trechos["lon_centroide"] = cent_geo.x.round(4)

    # ordena colunas
    cols = ["trecho_id", "osm_id", "highway", "surface", "nome",
            "comp_m", "lat_centroide", "lon_centroide", "geometry"]
    trechos = trechos[cols]

    trechos.to_file(args.saida, driver="GeoJSON")
    print(f"OK: {len(trechos)} trechos -> {args.saida}")
    print(f"  comprimento medio: {trechos['comp_m'].mean():.0f} m "
          f"(min {trechos['comp_m'].min():.0f} / max {trechos['comp_m'].max():.0f})")
    sem_surface = trechos['surface'].isna().sum()
    print(f"  trechos sem tag 'surface' (preencher no campo): {sem_surface}")


if __name__ == "__main__":
    main()
