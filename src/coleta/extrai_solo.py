"""
extrai_solo.py — Solo e risco de drenagem por trecho (Projeto Atola)

Cruza cada trecho (linha) com a Pedologia 1:250.000 do IBGE (pedo_area.shp,
SiBCS, EPSG:4674 / SIRGAS 2000) e extrai a ordem de solo DOMINANTE por
comprimento, alem de textura/relevo/erosao.

>>> O mapa ordem->risco vem de DADO REAL do IBGE, nao de suposicao <<<
Cruzamento do campo 'drenagem' x 'ordem' nos 5.645 pontos de pedo_ponto.shp
(89% com drenagem preenchida, n=5034). Risco medio de drenagem por ordem
(escala 0=bem drenado ... 5=muito mal drenado), VERIFICADO:

    LATOSSOLO   0.54 [n=1151]      NITOSSOLO   1.02 [n=111]
    NEOSSOLO    0.99 [n=473]       CHERNOSSOLO 1.73 [n=75]
    ARGISSOLO   1.03 [n=1315]      LUVISSOLO   1.69 [n=67]
    CAMBISSOLO  1.23 [n=348]       ESPODOSSOLO 3.44 [n=64]
    PLINTOSSOLO 2.30 [n=247]       VERTISSOLO  2.91 [n=32]
    GLEISSOLO   3.82 [n=199]       ORGANOSSOLO 4.92 [n=13]
    PLANOSSOLO  3.10 [n=165]

Saidas: solo_ordem, solo_textura, solo_relevo, solo_erosao,
        solo_dren_idx (indice continuo 0-5, feature do RF),
        solo_risco    (bucket 0-3, consumido pela Secao 3.2 do protocolo)

CRITICO: pedo_area.shp e o BRASIL inteiro (114k poligonos, ~628 MB). Lemos com
filtro de BBOX — so os poligonos da area de estudo entram na memoria.

Uso:
    python extrai_solo.py --solo pedo_area.shp \
        --trechos trechos/trechos.geojson \
        --bbox -63.20 -10.10 -62.85 -9.72 \
        --saida data/interim/solo.csv
    bbox = oeste sul leste norte
"""

import argparse
import pandas as pd
import geopandas as gpd

CRS_METRICO = "EPSG:31980"  # SIRGAS 2000 / UTM 20S

# indice continuo de drenagem por ordem (media empirica do pedo_ponto, 0-5)
DREN_IDX = {
    "LATOSSOLO": 0.54, "NEOSSOLO": 0.99, "ARGISSOLO": 1.03, "NITOSSOLO": 1.02,
    "CAMBISSOLO": 1.23, "LUVISSOLO": 1.69, "CHERNOSSOLO": 1.73, "PLINTOSSOLO": 2.30,
    "VERTISSOLO": 2.91, "PLANOSSOLO": 3.10, "ESPODOSSOLO": 3.44, "GLEISSOLO": 3.82,
    "ORGANOSSOLO": 4.92,
}


def idx_de(ordem):
    if not isinstance(ordem, str) or not ordem.strip():
        return None
    return DREN_IDX.get(ordem.strip().upper().split()[0])


def risco_de(idx):
    """Bucket 0-3 a partir do indice continuo (limiares sobre a escala 0-5)."""
    if idx is None:
        return None
    if idx < 0.8:
        return 0
    if idx < 1.5:
        return 1
    if idx < 2.5:
        return 2
    return 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", required=True)
    ap.add_argument("--trechos", required=True)
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("OESTE", "SUL", "LESTE", "NORTE"))
    ap.add_argument("--saida", required=True)
    args = ap.parse_args()

    oeste, sul, leste, norte = args.bbox
    print("Lendo pedologia com filtro de bbox...")
    solo = gpd.read_file(args.solo, bbox=(oeste, sul, leste, norte))
    print(f"  {len(solo)} poligonos na area.")
    if solo.empty:
        raise SystemExit("Nenhum poligono na bbox (ordem: oeste sul leste norte).")

    cols = [c for c in ["ordem", "subordem", "textura", "relevo", "erosao", "legenda"]
            if c in solo.columns]
    solo = solo[cols + ["geometry"]].to_crs(CRS_METRICO)
    trechos = gpd.read_file(args.trechos).to_crs(CRS_METRICO)

    inter = gpd.overlay(trechos[["trecho_id", "geometry"]], solo,
                        how="intersection", keep_geom_type=False)
    inter = inter[inter.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    inter["comp"] = inter.geometry.length
    dom = inter.loc[inter.groupby("trecho_id")["comp"].idxmax()].copy()

    dom = dom.rename(columns={"ordem": "solo_ordem", "subordem": "solo_subordem",
                              "textura": "solo_textura", "relevo": "solo_relevo",
                              "erosao": "solo_erosao"})
    dom["solo_dren_idx"] = dom["solo_ordem"].apply(idx_de)
    dom["solo_risco"] = dom["solo_dren_idx"].apply(risco_de)

    sc = [c for c in ["trecho_id", "solo_ordem", "solo_subordem", "solo_textura",
                      "solo_relevo", "solo_erosao", "solo_dren_idx", "solo_risco"]
          if c in dom.columns]
    df = trechos[["trecho_id"]].drop_duplicates().merge(
        pd.DataFrame(dom[sc]), on="trecho_id", how="left")

    df.to_csv(args.saida, index=False)
    n_ok = df["solo_ordem"].notna().sum() if "solo_ordem" in df else 0
    print(f"OK: {len(df)} trechos ({n_ok} com solo) -> {args.saida}")
    if "solo_ordem" in df.columns:
        print(df["solo_ordem"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
