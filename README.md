# Atola — Plataforma Preditiva de Trafegabilidade em Vicinais de Rondônia

Modelo de classificação (Random Forest) que prevê a trafegabilidade de estradas vicinais não pavimentadas da Amazônia Ocidental em quatro classes: **alta / média / baixa / intransitável**.
Hackathon IFRO Ariquemes 2026.

> **Unidade de análise:** trecho de via (geometria de linha), por data.
> **Label:** construído por supervisão fraca + verificação amostral. Ver [`PROTOCOLO_ROTULAGEM.md`](./PROTOCOLO_ROTULAGEM.md).

---

## Estrutura do repositório

```
linha-livre-RF-training/
├── README.md
├── PROTOCOLO_ROTULAGEM.md        # protocolo de rotulagem (ciente de declividade)
├── requirements.txt
├── data/
│   ├── raw/                      # downloads brutos (gitignore p/ rasters grandes)
│   ├── interim/                  # extrações intermediárias
│   └── processed/                # tabela final de treino (CSV)
├── src/
│   ├── coleta/
│   │   ├── coleta_open_meteo.py  # ✅ pronto (chuva) — ver exemplo abaixo
│   │   ├── extrai_declividade.py # TOPODATA → zonal stats na linha (a fazer)
│   │   └── extrai_solo.py        # IBGE pedologia → join espacial (a fazer)
│   ├── rotulagem/
│   │   └── aplica_regra.py       # função de rotulagem (Seção 3 do protocolo)
│   └── modelo/
│       └── treina_rf.py          # Random Forest + GroupKFold por trecho_id
└── trechos/
    └── trechos.geojson           # linhas dos trechos segmentados (1–2 km)
```

---

## Fontes de dados

### ✅ Tier 1 — download imediato (faça agora, baixa dificuldade)

Estas três cobrem 100% de Rondônia, são gratuitas, oficiais e não exigem cadastro complexo. São o suficiente para um dataset defensável.

| Camada | Fonte | Acesso | Formato | Como entra na linha |
|---|---|---|---|---|
| **Chuva** (72h/7d/30d) | Open-Meteo (reanálise ERA5-Land / Copernicus) | API, sem chave — `archive-api.open-meteo.com` | JSON | GET no centroide da linha; soma de janelas |
| **Declividade** | TOPODATA / INPE (derivado de SRTM) | download por quadrícula — `dsr.inpe.br/topodata` (ver nota https) | GeoTIFF 30 m | zonal stats (mean/max/frac) no buffer da linha |
| **Solo** | IBGE — Pedologia estadual de Rondônia | FTP público — `geoftp.ibge.gov.br` (Geociências › Pedologia) | Shapefile | join espacial; classe majoritária por comprimento |

**Notas de acesso:**
- TOPODATA: o INPE ainda serve por `http`; se o navegador bloquear, use "Salvar como" no link, ou o catálogo STAC em `data.inpe.br` (formato COG). Baixe as quadrículas que cobrem o Vale do Jamari / Ariquemes.
- IBGE Pedologia: usar o recorte **estadual de RO** (mais fino que o nacional 1:5M). Ciente da herança RADAMBRASIL (1:1.000.000) em parte da Amazônia — o solo discrimina *região*, não *trecho vizinho*. Declarar como limitação.
- Open-Meteo: ERA5-Land tem grid ~11 km — chuva é regional, não local (por design; ver protocolo).

### 🕓 Tier 2 — baixo custo, se sobrar tempo

| Camada | Fonte | Por quê fica em 2º |
|---|---|---|
| Cobertura do solo (proxy drenagem) | MapBiomas | barato, mas é complementar |
| Tráfego + revestimento (proxy) | OpenStreetMap (Overpass: `highway`, `surface`) | exige Overpass QL |
| Validação de chuva | INMET BDMEP (1–2 estações: Ariquemes, Ji-Paraná) | só valida Open-Meteo; **não interpolar** |

### 📋 Fontes planejadas (documentadas, fora do escopo das 48h)

| Camada | Fonte | Por quê é "futuro" |
|---|---|---|
| Passabilidade histórica de vias em cheia | **CENSIPAM** (SIPAMHidro / Centro Regional de Porto Velho) | dados brutos exigem ofício institucional; portais públicos servem consciência situacional, não CSV estruturado |
| Feature engineering visual (NDWI, poças crônicas, sulcos) | **Google Earth Engine** / Street View | curva de aprendizado + auth incompatíveis com 48h; alto valor em v2 |
| Tráfego por produção agrícola | **Censo Agropecuário IBGE** | join pesado, sinal indireto |
| Label-assist da classe "intransitável" | scraping leve de notícias locais | **apenas** como sinal fraco/validação, nunca como label principal (viés de cobertura catastrófica) |
| Ensaios de solo (pesos do modelo) | Repositório IFRO / BDTD (comportamento mecânico de latossolos em RO) | embasamento teórico, não dado tabular |

---

## Como rodar (Codespaces)

```bash
pip install -r requirements.txt

# 1) Chuva — preenche chuva_72h/7d/30d a partir dos centroides
python src/coleta/coleta_open_meteo.py \
    --trechos trechos/trechos.geojson \
    --datas data/raw/datas_alvo.csv \
    --saida data/interim/chuva.csv
```

`requirements.txt` mínimo: `requests pandas geopandas rasterio rasterstats shapely scikit-learn`.

---

## Compromisso de IA responsável

- Todas as fontes são públicas, oficiais e citáveis (INPE, IBGE, Copernicus/ERA5).
- Pipeline reproduzível; label auditável por protocolo aberto (`label_origin`, `score_total`).
- Validação por grupo de trecho (anti-vazamento espacial) e features defasadas (anti-vazamento de alvo).
- Métrica reportada: F1-macro + matriz de confusão, com performance separada no subconjunto verificado.
