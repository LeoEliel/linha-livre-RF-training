"""
treina_rf.py — Random Forest de trafegabilidade (Projeto Atola)

Treina e avalia o modelo SEM gerar imagens — tudo no terminal:
  - distribuicao de classes
  - validacao cruzada por GRUPO (GroupKFold por trecho_id) -> F1-macro
  - matriz de confusao agregada (texto) e classification_report
  - importancia das features
  - SE houver label_origin='verificado': avaliacao honesta treinando em 'regra'
    e testando no subconjunto verificado (o numero que vale para a banca)

Anti-vazamento embutido:
  - split por trecho_id (espacial), nunca aleatorio por linha
  - exclui id/coordenadas/score/colunas-pontuacao das features

Uso:
  python treina_rf.py --dataset data/processed/dataset.csv
"""

import argparse
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import GroupKFold
from sklearn.metrics import f1_score, confusion_matrix, classification_report

CLASSES = ["alta", "media", "baixa", "intransitavel"]
# nunca entram como feature:
EXCLUI = {"trecho_id", "data_obs", "lat_centroide", "lon_centroide", "osm_id",
          "trafegabilidade", "label_origin", "score_total",
          "pt_chuva", "pt_solo", "pt_decliv", "pt_dren", "pt_rev", "molhado",
          "solo_risco"}  # solo_risco e insumo da regra -> fora; usa-se solo_dren_idx


def prepara(df):
    feat_cols = [c for c in df.columns if c not in EXCLUI]
    X = df[feat_cols].copy()
    # one-hot nas categoricas
    cat = X.select_dtypes(exclude=["number", "bool"]).columns.tolist()
    X = pd.get_dummies(X, columns=cat, dummy_na=True)
    # numericas: preenche faltantes com mediana
    for c in X.columns:
        if X[c].dtype != bool:
            X[c] = pd.to_numeric(X[c], errors="coerce")
            X[c] = X[c].fillna(X[c].median())
    return X.fillna(0), feat_cols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--arvores", type=int, default=300)
    ap.add_argument("--folds", type=int, default=5)
    args = ap.parse_args()

    df = pd.read_csv(args.dataset)
    print(f"Dataset: {len(df)} linhas, {df['trecho_id'].nunique()} trechos unicos")
    print("Distribuicao de classes:")
    print(df["trafegabilidade"].value_counts().reindex(CLASSES, fill_value=0).to_string())

    X, feat_cols = prepara(df)
    y = df["trafegabilidade"].values
    grupos = df["trecho_id"].values
    print(f"\nFeatures usadas ({len(feat_cols)}): {', '.join(feat_cols)}")

    n_splits = min(args.folds, df["trecho_id"].nunique())
    gkf = GroupKFold(n_splits=n_splits)
    f1s = []
    y_true_all, y_pred_all = [], []
    print(f"\n=== Validacao cruzada por trecho (GroupKFold, {n_splits} folds) ===")
    for i, (tr, te) in enumerate(gkf.split(X, y, grupos), 1):
        clf = RandomForestClassifier(n_estimators=args.arvores, class_weight="balanced",
                                     random_state=42, n_jobs=-1)
        clf.fit(X.iloc[tr], y[tr])
        pred = clf.predict(X.iloc[te])
        f1 = f1_score(y[te], pred, average="macro", labels=CLASSES, zero_division=0)
        f1s.append(f1)
        y_true_all.extend(y[te]); y_pred_all.extend(pred)
        print(f"  fold {i}: F1-macro = {f1:.3f}  (n_teste={len(te)})")
    print(f"  >> F1-macro medio = {np.mean(f1s):.3f} +/- {np.std(f1s):.3f}")

    print("\n=== Matriz de confusao agregada (linha=real, coluna=previsto) ===")
    cm = confusion_matrix(y_true_all, y_pred_all, labels=CLASSES)
    print("            " + "".join(f"{c[:5]:>8}" for c in CLASSES))
    for i, c in enumerate(CLASSES):
        print(f"{c:>12}" + "".join(f"{v:>8}" for v in cm[i]))
    print("\n=== Classification report (CV) ===")
    print(classification_report(y_true_all, y_pred_all, labels=CLASSES, zero_division=0))

    # importancia (modelo treinado em tudo)
    clf = RandomForestClassifier(n_estimators=args.arvores, class_weight="balanced",
                                 random_state=42, n_jobs=-1).fit(X, y)
    imp = sorted(zip(X.columns, clf.feature_importances_), key=lambda t: -t[1])
    print("=== Importancia das features (top 15) ===")
    for nome, v in imp[:15]:
        print(f"  {v:.3f}  {nome}")

    # avaliacao honesta no subconjunto verificado
    if "label_origin" in df.columns and (df["label_origin"] == "verificado").any():
        ver = df["label_origin"] == "verificado"
        if ver.sum() >= 5 and (~ver).sum() >= 10:
            print(f"\n=== Avaliacao honesta: treino em 'regra' ({(~ver).sum()}), "
                  f"teste em 'verificado' ({ver.sum()}) ===")
            clf2 = RandomForestClassifier(n_estimators=args.arvores, class_weight="balanced",
                                          random_state=42, n_jobs=-1).fit(X[~ver], y[~ver])
            pv = clf2.predict(X[ver])
            f1v = f1_score(y[ver], pv, average="macro", labels=CLASSES, zero_division=0)
            print(f"  F1-macro no conjunto verificado = {f1v:.3f}")
            print(classification_report(y[ver], pv, labels=CLASSES, zero_division=0))
        else:
            print(f"\n(verificados={int(ver.sum())} — poucos p/ avaliacao separada; "
                  f"reporte como calibracao, nao como teste.)")


if __name__ == "__main__":
    main()
