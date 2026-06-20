"""
aplica_regra.py — Funcao de rotulagem (Projeto Atola)

Junta os CSVs de features por trecho/data e aplica a regra fisica do
PROTOCOLO_ROTULAGEM.md (Secao 3), gerando o label provisorio com a interacao
chuva x declividade. Marca label_origin='regra' e, onde houver ancoras
verificadas (DER/noticias/observacao de seca), sobrescreve e marca 'verificado'.

Entradas (CSV):
  --chuva        trecho_id,data_obs,chuva_72h,chuva_7d,chuva_30d,mes,lat_centroide,lon_centroide
  --solo         trecho_id,solo_ordem,solo_textura,solo_relevo,solo_dren_idx,solo_risco
  --declividade  trecho_id,decliv_media_pct,decliv_max_pct,frac_plana,frac_ingreme
  --campo        (opcional) trecho_id,revestimento,drenagem,canaleta
  --trechos      (opcional) trechos.geojson p/ herdar 'surface' -> revestimento
  --ancoras      (opcional) trecho_id,data_obs,trafegabilidade  [label real]
  --saida        CSV final de treino

Uso:
  python aplica_regra.py --chuva chuva.csv --solo solo.csv \
      --declividade declividade.csv --campo campo.csv --ancoras ancoras.csv \
      --saida data/processed/dataset.csv
"""

import argparse
import pandas as pd

CLASSES = ["alta", "media", "baixa", "intransitavel"]
SURF_REV = {  # tag OSM -> (revestimento, pontos)
    "asphalt": ("pavimento", 0), "paved": ("pavimento", 0), "concrete": ("pavimento", 0),
    "gravel": ("cascalho", 1), "fine_gravel": ("cascalho", 1), "compacted": ("cascalho", 1),
    "pebblestone": ("cascalho", 1),
    "unpaved": ("terra", 2), "dirt": ("terra", 2), "ground": ("terra", 2),
    "earth": ("terra", 2), "mud": ("terra", 2),
}
DREN_PTS = {"boa": 0, "regular": 1, "ruim": 2}
# revestimento condicionado a chuva: terra so penaliza forte quando molhado
# (estrada de terra seca e trafegavel). seco / molhado:
REV_SECO = {"pavimento": 0, "cascalho": 0, "terra": 1}
REV_MOLH = {"pavimento": 0, "cascalho": 1, "terra": 2}


def p_chuva(c72, c30):
    c72, c30 = (c72 or 0), (c30 or 0)
    if c72 >= 80 or c30 >= 400: return 3
    if c72 >= 30 or c30 >= 200: return 2
    if c72 >= 10 or c30 >= 100: return 1
    return 0


def p_decliv(media, fpl, fing, molhado):
    if media is None or pd.isna(media): return 0
    fpl, fing = (fpl or 0), (fing or 0)
    if 2 <= media <= 8 and fing < 0.3:
        return 0
    if media > 15 or fing > 0.5:
        return 3 if molhado else 2
    # plano (<2% ou muita fracao plana) OU ingreme moderado (8-15% ou fing>0.3)
    return 2 if molhado else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chuva", required=True)
    ap.add_argument("--solo", required=True)
    ap.add_argument("--declividade", required=True)
    ap.add_argument("--campo")
    ap.add_argument("--trechos")
    ap.add_argument("--ancoras")
    ap.add_argument("--saida", required=True)
    args = ap.parse_args()

    df = pd.read_csv(args.chuva)                       # base: trecho x data
    df = df.merge(pd.read_csv(args.solo), on="trecho_id", how="left")
    df = df.merge(pd.read_csv(args.declividade), on="trecho_id", how="left")

    # revestimento: campo > tag OSM do trechos.geojson > terra (default)
    rev = {}
    if args.trechos:
        import json
        g = json.load(open(args.trechos))
        for f in g["features"]:
            p = f["properties"]; rev[p["trecho_id"]] = (p.get("surface") or "").lower()
    if args.campo:
        campo = pd.read_csv(args.campo)
        df = df.merge(campo, on="trecho_id", how="left")
    for c in ["revestimento", "drenagem", "canaleta"]:
        if c not in df.columns: df[c] = None

    def revest_row(r):
        if isinstance(r.get("revestimento"), str) and r["revestimento"].strip():
            return r["revestimento"].strip().lower()
        return SURF_REV.get(rev.get(r["trecho_id"], ""), ("terra", 2))[0]
    df["revestimento"] = df.apply(revest_row, axis=1)

    # --- pontuacao da regra ---
    df["pt_chuva"] = df.apply(lambda r: p_chuva(r.get("chuva_72h"), r.get("chuva_30d")), axis=1)
    df["molhado"] = df["pt_chuva"] >= 2
    df["pt_solo"] = df["solo_risco"].fillna(1).astype(int)
    df["pt_decliv"] = df.apply(
        lambda r: p_decliv(r.get("decliv_media_pct"), r.get("frac_plana"),
                           r.get("frac_ingreme"), r["molhado"]), axis=1)
    df["pt_dren"] = df["drenagem"].map(lambda v: DREN_PTS.get(str(v).strip().lower(), 0))
    df["pt_rev"] = df.apply(
        lambda r: (REV_MOLH if r["molhado"] else REV_SECO).get(
            str(r["revestimento"]).strip().lower(), 2 if r["molhado"] else 1), axis=1)

    df["score_total"] = df[["pt_chuva", "pt_solo", "pt_decliv", "pt_dren", "pt_rev"]].sum(axis=1)

    def classe(s):
        if s <= 2: return "alta"
        if s <= 5: return "media"
        if s <= 8: return "baixa"
        return "intransitavel"
    df["trafegabilidade"] = df["score_total"].apply(classe)
    df["label_origin"] = "regra"

    # --- ancoras verificadas sobrescrevem ---
    if args.ancoras:
        anc = pd.read_csv(args.ancoras)
        anc["data_obs"] = anc["data_obs"].astype(str)
        df["data_obs"] = df["data_obs"].astype(str)
        chave = ["trecho_id", "data_obs"]
        anc = anc[chave + ["trafegabilidade"]].rename(columns={"trafegabilidade": "_verif"})
        df = df.merge(anc, on=chave, how="left")
        mask = df["_verif"].notna()
        df.loc[mask, "trafegabilidade"] = df.loc[mask, "_verif"]
        df.loc[mask, "label_origin"] = "verificado"
        df = df.drop(columns=["_verif"])
        print(f"ancoras aplicadas: {int(mask.sum())} linhas verificadas")

    df.to_csv(args.saida, index=False)
    print(f"OK: {len(df)} linhas -> {args.saida}")
    print("\nDistribuicao de classes:")
    print(df["trafegabilidade"].value_counts().reindex(CLASSES, fill_value=0).to_string())
    print("\nlabel_origin:", dict(df["label_origin"].value_counts()))
    falta_solo = df["solo_risco"].isna().sum()
    falta_dec = df["decliv_media_pct"].isna().sum()
    if falta_solo or falta_dec:
        print(f"AVISO: sem solo={falta_solo}, sem declividade={falta_dec} (usaram default).")


if __name__ == "__main__":
    main()
