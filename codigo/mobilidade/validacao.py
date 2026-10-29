"""Validação e relatório de qualidade dos dados (RF02, RNF05)."""
from __future__ import annotations

import pandas as pd


class ColunasAusentes(ValueError):
    pass


def para_numero(s: pd.Series) -> pd.Series:
    """Converte texto numérico para float aceitando vírgula decimal ('3,5') e milhar com ponto ('1.234,5')."""
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    t = s.astype(str).str.strip()
    com_virgula = t.str.contains(",", regex=False)
    t = t.where(~com_virgula, t.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(t, errors="coerce")


def exigir_colunas(df: pd.DataFrame, colunas: list[str]) -> None:
    faltam = [c for c in colunas if c not in df.columns]
    if faltam:
        raise ColunasAusentes(f"colunas ausentes: {faltam}. Colunas disponíveis: {list(df.columns)}")


def relatorio_qualidade(ts: pd.Series, serie: pd.Series, alvo: pd.Series) -> dict:
    """Recebe as três colunas já extraídas (timestamp, série, indicador) ANTES de qualquer descarte."""
    n = len(ts)
    ts_ok = pd.to_datetime(ts, errors="coerce")
    alvo_num = para_numero(alvo)
    df = pd.DataFrame({"ts": ts_ok, "s": serie.astype(str), "y": alvo_num})
    return {
        "n_linhas": int(n),
        "timestamps_invalidos": int(ts_ok.isna().sum()),
        "indicador_invalido_ou_ausente": int(alvo_num.isna().sum()),
        "indicador_negativo": int((alvo_num < 0).sum()),
        "duplicados_serie_timestamp": int(df.duplicated(["s", "ts"]).sum()),
        "n_series": int(df["s"].nunique()),
        "periodo": [str(ts_ok.min()), str(ts_ok.max())],
        "estatisticas_indicador": {k: (None if pd.isna(v) else float(v)) for k, v in alvo_num.describe().items()},
    }
