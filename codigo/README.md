# Pipeline de dados – Mobilidade Urbana SP (TCC)

Ingestão → bruto (cópia fiel + manifesto) → validação → séries horárias (+ clima e calendário) → experimento Chronos-2.

```
fontes externas ──► adapters/ ──► dados/bruto/<fonte>/  (arquivo original + .meta.json com sha256, data, parâmetros)
                                   │
                                   ├─► validacao.py (relatório de qualidade)
                                   └─► series.py ──► dados/tratado/series_horarias.{csv,parquet}
                                                          │
                                       experimento/experimento_previsao.py ──► resultados/
```

## Estado de cada fonte (executado com dados reais em 24/10/2026)

| Fonte | Adaptador | Estado | Observações |
|---|---|---|---|
| CET lentidão por trechos (CSV anual, Portal de Dados Abertos) | `cet_csv.py` | **executado** (2022: 155.301 linhas; 2023: 158.496) | colunas `data` (dd/mm/aaaa hh:mm, a cada 30 min), `corredor`, `sentido`, `expressa`, `descricao`, `tamanho` (m em lentidão), `nome_regiao`. Base de **eventos**: só registra trecho com fila. Descontinuada em 31/12/2023 (de 2024 em diante: Waze, não comparável) |
| Clima – Open-Meteo | `openmeteo.py` | **executado** (17.520 horas, 2022–2023) | coletado, ainda não usado pelo modelo (univariado) |
| Calendário – BrasilAPI | `calendario.py` | **executado** (32 feriados, 2022–2023) | só feriados nacionais; 25/01, 09/07 e 20/11 acrescentados à mão |
| CET LentidaoTransito v1 (API Store) | `cet_api.py` | só simulação | anos 2001–2018; exige token; não usada |
| Infosiga-SP | `infosiga.py` | só simulação | link direto e colunas não verificados; não usada |

Downloads (pelo navegador; o portal bloqueia acesso automatizado) – salvar em `dados/entrada/`:
[lentidao_trechos_2023.csv](https://dados.prefeitura.sp.gov.br/dataset/f03433f4-0d4b-44b4-a23b-17111bbb392a/resource/b183971e-0f64-42ec-ac3c-f4ec99f2711c/download/lentidao_trechos_2023.csv) ·
[lentidaotrechos2022.csv](https://dados.prefeitura.sp.gov.br/dataset/f03433f4-0d4b-44b4-a23b-17111bbb392a/resource/81edda3d-7313-4690-add8-2fb241b7c64a/download/lentidaotrechos2022.csv) ·
[dicionario-de-dados.csv](https://dados.prefeitura.sp.gov.br/dataset/f03433f4-0d4b-44b4-a23b-17111bbb392a/resource/176d789e-d23f-42d4-88a4-d7c40ba39669/download/dicionario-de-dados.csv)

## Uso

```bash
pip install -r requirements.txt
cp .env.example .env        # preencha o que for usar; exporte as variáveis (ou use direnv)

# 1) Trazer o dado de lentidão (cópia fiel + manifesto) e conferir as colunas
python -m mobilidade.cli coletar cet-csv --origem dados/entrada/lentidaotrechos2022.csv
python -m mobilidade.cli coletar cet-csv --origem dados/entrada/lentidao_trechos_2023.csv
python -m mobilidade.cli inspecionar dados/entrada/lentidao_trechos_2023.csv

# 2) Covariáveis (coletadas; o modelo ainda é univariado)
python -m mobilidade.cli coletar clima --inicio 2022-01-01 --fim 2023-12-31
python -m mobilidade.cli coletar calendario --anos 2022 2023

# 3) Séries horárias: corredor|sentido, km em lentidão (soma dos trechos por instante; instante sem registro = 0)
python -m mobilidade.cli series --entrada dados/entrada/lentidaotrechos2022.csv dados/entrada/lentidao_trechos_2023.csv \
    --col-ts data --col-serie corredor sentido --col-alvo tamanho --fator 0.001 \
    --ausente-como-zero --freq-coleta 30min --min-frac-dias-uteis 0.5 --selecao-ate 2023-12-02

# 4) Experimento – rodada principal (teste 02–15/12/2023) e sensibilidades
python experimento/experimento_previsao.py --input dados/tratado/series_horarias.csv --fim "2023-12-15 23:00" --output resultados/principal
python experimento/experimento_previsao.py --input dados/tratado/series_horarias.csv --fim "2023-12-29 23:00" --output resultados/sens_fim_de_ano
python experimento/experimento_previsao.py --input dados/tratado/series_horarias.csv --fim "2023-12-15 23:00" --stride 192 --output resultados/sens_espacada  # 8 dias: janelas passam por todos os dias da semana

python -m mobilidade.cli status      # histórico de execuções (RF25/RF28)
```

## Testes

```bash
python -m unittest -v     # 23 testes, com respostas simuladas (não usam a internet)
```

Os testes validam a lógica (paginação, cabeçalho, erros, CSV com vírgula decimal, CAPTCHA, séries, base de eventos, log) e o experimento (linhas de base, MAE/MASE, janelas, fluxo completo com `--demo --skip-chronos`). CET CSV, Open-Meteo e BrasilAPI já foram executados com dados reais; API v1 e Infosiga seguem testados só com simulação.

Ambiente usado na rodada de 24/10/2026: Python 3.12, pandas 3.1, chronos-forecasting 2.3.2, torch 2.14 (CPU); ~5 min por rodada com 35 séries.
