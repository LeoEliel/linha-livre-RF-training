# Protocolo de Rotulagem de Trafegabilidade — Projeto Atola

**Versão:** 1.0 — Hackathon IFRO Ariquemes 2026
**Unidade de análise:** trecho de via (geometria de **linha**), por data
**Objetivo:** gerar um label reprodutível e auditável de `trafegabilidade ∈ {alta, média, baixa, intransitável}` para cada par (trecho, data), sem dataset rotulado pré-existente, com transparência metodológica defensável em banca.

---

## 0. Princípio metodológico (leia antes de tudo)

Não existe base pública de trafegabilidade rotulada para vicinais de Rondônia. Logo, o label é **construído**, não baixado. Para que isso seja defensável e não vire "achismo", adotamos **supervisão fraca com verificação amostral** (*weak supervision / programmatic labeling*, paradigma formalizado por Ratner et al., 2016 — Snorkel/data programming):

1. Uma **função de rotulagem** (regra física, Seção 3) atribui um label *provisório* a todos os trechos/datas.
2. Uma **amostra é verificada** por evidência real (campo, foto georreferenciada, relato datado, satélite) — Seção 4.
3. Onde a verificação diverge da regra, **a verificação vence**, e a divergência é registrada.
4. Cada linha carrega a coluna `label_origin` (`verificado` | `regra`), permitindo reportar a métrica do modelo **separadamente no subconjunto verificado** — esse é o número honesto.

### Aviso de circularidade (declare isto na banca)
Se o Random Forest é treinado em labels gerados por uma regra sobre as mesmas features que ele usa, ele tende a **reaprender a regra** — o que, sozinho, não tem valor. O ganho real vem de duas fontes, que precisam estar explícitas na apresentação:
- as **correções da verificação** (onde campo ≠ regra), que injetam sinal que a regra não capta;
- as **interações entre features** que o RF modela e a regra aditiva não (ex.: declividade só vira problema sob chuva — ver Seção 3.3).
A v1 é prova de conceito; a v2 substitui progressivamente labels-regra por labels reais acumulados (campo/crowdsourcing).

---

## 1. Definição do trecho (linha)

A trafegabilidade só é significativa em segmentos relativamente homogêneos. Uma vicinal de 30 km **não** é um único label.

- **Segmentação:** quebrar a malha em trechos-alvo de **1–2 km**, preferindo cortes em pontos naturais (cruzamentos, pontes, mudança de revestimento, mudança de classe de solo).
- **Identificador:** `trecho_id` estável (ex.: `RO-ARQ-LC65-003`). É **chave**, nunca feature.
- **Buffer de amostragem:** para extrair raster/vetor, usar buffer de **15–30 m** de cada lado do eixo (capta leito + drenagem imediata).

---

## 2. Extração de features por linha (zonal statistics)

Como a unidade é linha, cada feature contínua vira **estatística ao longo do traçado**, não valor pontual.

| Feature | Como extrair na linha | Saída |
|---|---|---|
| `decliv_media_pct` | zonal stats (mean) do raster TOPODATA no buffer | float |
| `decliv_max_pct` | zonal stats (max) — pontos críticos localizados | float |
| `frac_plana` | % do comprimento com declividade < 2% | 0–1 |
| `frac_ingreme` | % do comprimento com declividade > 8% | 0–1 |
| `solo_dominante` | classe de solo (IBGE) majoritária **por comprimento** ao longo da linha | categórico |
| `cobertura_dominante` | classe MapBiomas majoritária no buffer | categórico |
| `revestimento` | campo / OSM tag `surface` | categórico |
| `chuva_72h`, `chuva_7d`, `chuva_30d` | Open-Meteo no **centroide** da linha (grid ERA5 ~11 km — o ponto representa a linha toda) | float (mm) |
| `drenagem` | vistoria / proxy visual | boa/regular/ruim |
| `relatos_previos` | relatos da **janela anterior** (defasados, nunca do dia) | int |

> A chuva é amostrada no centroide de propósito: o grid ERA5-Land (~11 km) não distingue trechos vizinhos. A discriminação fina entre vicinais próximas **tem que vir de solo, declividade, drenagem e revestimento** — não da chuva.

---

## 3. Função de rotulagem (regra física)

Score de risco aditivo (0 = melhor trafegabilidade). Soma os pontos das Seções 3.1–3.5 e mapeia para classe na Seção 3.6.

### 3.1 Chuva antecedente (0–3) — regime hídrico
Combina saturação recente (72h) e memória do solo (30d).

| Condição | Pontos | Regime |
|---|---|---|
| `chuva_72h` < 10 e `chuva_30d` < 100 | 0 | **seco** |
| 10 ≤ `chuva_72h` < 30 ou 100 ≤ `chuva_30d` < 200 | 1 | transição |
| 30 ≤ `chuva_72h` < 80 ou 200 ≤ `chuva_30d` < 400 | 2 | **molhado** |
| `chuva_72h` ≥ 80 ou `chuva_30d` ≥ 400 | 3 | **encharcado** |

Defina o flag `molhado = (pontos_chuva ≥ 2)` — ele condiciona a declividade (3.3).

### 3.2 Solo — classe de drenagem natural (0–3)

| Classe (IBGE) | Pontos | Razão |
|---|---|---|
| Latossolo | 0 | profundo, bem drenado |
| Neossolo Quartzarênico | 0–1 | arenoso, drena rápido (tração frouxa quando muito seco) |
| Argissolo | 2 | acúmulo de argila no horizonte B → escorrega molhado |
| Gleissolo / Plintossolo | 3 | hidromórfico → atoleiro crônico |

### 3.3 Declividade — relação **não-monotônica** (0–3)
Este é o ponto central. Declividade **não** é "quanto maior pior". É um U invertido:

- **Muito plana (< 2%):** água não escoa → empoça → atoleiro. **Pior sob chuva.**
- **Moderada (2–8%):** faixa ótima — drena sem erodir. **Menor risco.**
- **Íngreme (> 8%):** erosão, sulcos, voçoroca, e perda de tração na subida em solo argiloso molhado. **Pior sob chuva.**

O risco da declividade **dobra no regime molhado** (interação chuva×relevo):

| Condição (use `decliv_media_pct`, reforçada por `frac_*`) | Seco | Molhado |
|---|---|---|
| 2% ≤ média ≤ 8% (e `frac_ingreme` baixo) | 0 | 0 |
| média < 2% (ou `frac_plana` > 0,4) | 1 | 2 |
| 8% < média ≤ 15% (ou `frac_ingreme` > 0,3) | 1 | 2 |
| média > 15% (ou `frac_ingreme` > 0,5) | 2 | 3 |

### 3.4 Drenagem da infraestrutura (0–2)
`boa` = 0 · `regular` = 1 · `ruim` = 2 (sarjetas/bueiros obstruídos ou inexistentes).

### 3.5 Revestimento (0–2)
`pavimento` = 0 · `cascalho`/`piçarra` = 1 · `terra` = 2.

### 3.6 Mapeamento score → classe
`score_total = 3.1 + 3.2 + 3.3 + 3.4 + 3.5` (máx. ≈ 13)

| score_total | trafegabilidade |
|---|---|
| 0–2 | **alta** |
| 3–5 | **média** |
| 6–8 | **baixa** |
| ≥ 9 | **intransitável** |

> Os limiares são **calibráveis** contra a amostra verificada (Seção 4). Não os trate como sagrados; documente qualquer ajuste.

---

## 4. Verificação amostral (o que torna o label "real")

1. **Gerar** labels provisórios pela regra para todos os (trecho, data).
2. **Amostrar para verificar**, com prioridade para:
   - **estratificação por classe prevista** (garantir que as 4 classes sejam verificadas);
   - **casos de fronteira** (score próximo dos limiares 2/3, 5/6, 8/9);
   - **classes raras** ("intransitável", "alta").
   - Tamanho mínimo: **≥ 20 linhas** ou 15–20% do dataset (o que for maior).
3. **Fontes de verdade aceitas** (registrar qual foi usada por linha):
   - visita de campo com GPS;
   - foto georreferenciada datada;
   - relato datado de morador/produtor/motorista (WhatsApp) sobre a condição na/perto da data;
   - imagem de satélite recente (Sentinel-2 via navegador EO / MapBiomas) evidenciando lâmina d'água ou interrupção.
4. **Resolver divergências:** onde regra ≠ verificação, **verificação vence**; marcar `label_origin = verificado` e registrar a divergência.
5. **Medir concordância** regra×verificação: acurácia + **kappa de Cohen**. Reportar o número. Se kappa baixo (< 0,4), recalibrar limiares da Seção 3.6 e repetir.
6. **Documentar todas as divergências** numa tabela (transparência > perfeição).

---

## 5. Esquema final da linha do dataset

Colunas de **papel** explícito para evitar vazamento:

| coluna | papel |
|---|---|
| `trecho_id` | chave (NÃO feature) |
| `data_obs` | chave temporal |
| `lat_centroide`, `lon_centroide` | metadado (NÃO feature) |
| `revestimento`, `solo_dominante`, `cobertura_dominante` | feature |
| `decliv_media_pct`, `decliv_max_pct`, `frac_plana`, `frac_ingreme` | feature |
| `chuva_72h`, `chuva_7d`, `chuva_30d`, `mes` | feature |
| `drenagem`, `trafego_cat`, `relatos_previos` | feature |
| `trafegabilidade` | **LABEL** |
| `label_origin` | `verificado` \| `regra` |
| `score_total` | auditoria (NÃO feature) |

---

## 6. Regras anti-vazamento (obrigatórias)

- **Split por grupo:** `GroupKFold` / `GroupShuffleSplit` usando `trecho_id` como grupo. Nenhum trecho cruza a fronteira treino/teste (evita o modelo decorar a via — vazamento espacial).
- **Causalidade temporal:** toda feature usa apenas informação disponível **até** `data_obs`. `relatos_previos` é **defasado** (janela anterior), nunca do dia/evento que define o label — senão o relato *é* o label (vazamento de alvo).
- **Coordenada e id fora das features.**
- **Métrica honesta:** reportar F1-macro + matriz de confusão, e **uma linha separada** com a performance só no subconjunto `label_origin = verificado`.

---

## 7. Referências de fundamentação

- Ratner, A. et al. (2016). *Data Programming: Creating Large Training Sets, Quickly.* NeurIPS. — paradigma de supervisão fraca.
- Baesso & Gonçalves (2003) — avaliação de condição de estradas não pavimentadas (base do ICRNP); fundamenta a definição das 4 classes.
- Nunes, T. V. L. (2003) — *Previsão de efeitos em estradas vicinais de terra com redes neurais artificiais*, UFC. — precedente de ML em vicinal no Brasil.
- DNIT (2005) — *Manual de Conservação Rodoviária*; taxonomia de defeitos (atoleiro, erosão, etc.).
