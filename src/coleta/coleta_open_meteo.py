"""
coleta_open_meteo.py — Coletor de precipitação antecedente (Projeto Atola)

Para cada trecho (linha) e cada data-alvo, calcula a chuva acumulada nas
janelas de 72h (3 dias), 7 dias e 30 dias anteriores, usando a reanálise
ERA5-Land servida pela Open-Meteo Archive API (gratuita, sem chave).

A chuva é amostrada no CENTROIDE da linha: o grid ERA5-Land (~11 km) não
distingue trechos vizinhos, então um ponto representa a linha inteira.

Uso:
    python coleta_open_meteo.py --trechos trechos.geojson \
        --datas datas_alvo.csv --saida chuva.csv

Entradas:
    --trechos : GeoJSON/shapefile de linhas com coluna `trecho_id`
    --datas   : CSV com coluna `data_obs` (YYYY-MM-DD). Se omitido, usa --datas-fixas
    --saida   : CSV de saída

NOTA: rode em ambiente com rede (Codespaces). Não testado offline.
Granularidade: usa precipitação DIÁRIA (precipitation_sum). Para 72h exatas
por hora, troque para `hourly=precipitation` — comentário no fim do arquivo.
"""

import argparse
import time
from datetime import date, timedelta

import pandas as pd
import requests

try:
    import geopandas as gpd
except ImportError:
    gpd = None

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
TIMEZONE = "America/Porto_Velho"
JANELAS = {"chuva_72h": 3, "chuva_7d": 7, "chuva_30d": 30}  # dias
MAX_JANELA = max(JANELAS.values())


def carrega_centroides(caminho_trechos):
    """Lê linhas e retorna DataFrame: trecho_id, lat_centroide, lon_centroide."""
    if gpd is None:
        raise ImportError("geopandas é necessário para ler geometrias de linha.")
    gdf = gpd.read_file(caminho_trechos)
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    gdf = gdf.to_crs(4326)
    cent = gdf.geometry.centroid
    return pd.DataFrame({
        "trecho_id": gdf["trecho_id"].astype(str),
        "lat_centroide": cent.y.round(4),
        "lon_centroide": cent.x.round(4),
    })


def busca_serie(lat, lon, dt_inicio, dt_fim, tentativas=3):
    """Retorna dict {data(str): precipitacao_mm} para o intervalo pedido."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": dt_inicio.isoformat(),
        "end_date": dt_fim.isoformat(),
        "daily": "precipitation_sum",
        "timezone": TIMEZONE,
    }
    for t in range(tentativas):
        try:
            r = requests.get(ARCHIVE_URL, params=params, timeout=30)
            r.raise_for_status()
            d = r.json()["daily"]
            return dict(zip(d["time"], d["precipitation_sum"]))
        except Exception as e:  # noqa: BLE001
            if t == tentativas - 1:
                raise
            time.sleep(2 ** t)  # backoff
    return {}


def soma_janela(serie, data_ref, n_dias):
    """Soma precipitação na janela de n_dias terminando em data_ref (inclusive)."""
    total = 0.0
    for k in range(n_dias):
        dia = (data_ref - timedelta(days=k)).isoformat()
        v = serie.get(dia)
        if v is not None:
            total += v
    return round(total, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trechos", required=True)
    ap.add_argument("--datas", help="CSV com coluna data_obs (YYYY-MM-DD)")
    ap.add_argument("--datas-fixas", nargs="*", default=[],
                    help="datas YYYY-MM-DD se não usar --datas")
    ap.add_argument("--saida", required=True)
    args = ap.parse_args()

    centroides = carrega_centroides(args.trechos)

    if args.datas:
        datas = pd.read_csv(args.datas)["data_obs"].astype(str).tolist()
    else:
        datas = args.datas_fixas
    datas = sorted({date.fromisoformat(d) for d in datas})
    if not datas:
        raise SystemExit("Nenhuma data-alvo fornecida (--datas ou --datas-fixas).")

    # Cache por célula de grid: arredonda p/ deduplicar pontos quase iguais.
    inicio_global = min(datas) - timedelta(days=MAX_JANELA)
    fim_global = max(datas)
    cache = {}

    linhas = []
    for _, row in centroides.iterrows():
        chave = (round(row.lat_centroide, 2), round(row.lon_centroide, 2))
        if chave not in cache:
            cache[chave] = busca_serie(chave[0], chave[1], inicio_global, fim_global)
            time.sleep(0.3)  # gentil com a API
        serie = cache[chave]

        for d in datas:
            registro = {
                "trecho_id": row.trecho_id,
                "data_obs": d.isoformat(),
                "lat_centroide": row.lat_centroide,
                "lon_centroide": row.lon_centroide,
                "mes": d.month,
            }
            for nome, n in JANELAS.items():
                registro[nome] = soma_janela(serie, d, n)
            linhas.append(registro)

    df = pd.DataFrame(linhas)
    df.to_csv(args.saida, index=False)
    print(f"OK: {len(df)} linhas ({len(centroides)} trechos x {len(datas)} datas) "
          f"-> {args.saida}")
    print(f"Chamadas à API: {len(cache)} (células de grid únicas)")


if __name__ == "__main__":
    main()

# --- Para 72h EXATAS (horárias) em vez de aproximação diária de 3 dias ---
# Troque `daily=precipitation_sum` por `hourly=precipitation`, peça o intervalo
# terminando no timestamp da consulta, e some as 72/168/720 horas anteriores.
# A versão diária é suficiente e defensável para o hackathon.
