"""Construção das séries temporais (RF11) a partir do bruto + covariáveis opcionais."""
from __future__ import annotations

import pandas as pd

from .validacao import exigir_colunas, para_numero, relatorio_qualidade


def montar_timestamp(df: pd.DataFrame, col_ts: str | None, col_data: str | None, col_hora: str | None) -> pd.Series:
    """Devolve a coluna de data/hora: a coluna única `col_ts` ou a combinação `col_data` + `col_hora`.

    `col_hora` aceita '07:30', '7' ou inteiros (hora cheia).
    """
    if col_ts:
        exigir_colunas(df, [col_ts])
        return pd.to_datetime(df[col_ts], errors="coerce", dayfirst=True, format="mixed")
    if col_data and col_hora:
        exigir_colunas(df, [col_data, col_hora])
        data = pd.to_datetime(df[col_data], errors="coerce", dayfirst=True).dt.normalize()
        h = df[col_hora].astype(str).str.strip()
        h = h.where(h.str.contains(":"), h.str.zfill(2) + ":00")
        return data + pd.to_timedelta(h.str.slice(0, 5) + ":00", errors="coerce")
    raise ValueError("informe col_ts, ou col_data e col_hora.")


def _id_serie(df: pd.DataFrame, col_serie: str | list[str]) -> pd.Series:
    """Identificador da série: uma coluna ou várias unidas por ' | ' (ex.: corredor | sentido)."""
    cols = [col_serie] if isinstance(col_serie, str) else list(col_serie)
    exigir_colunas(df, cols)
    sid = df[cols[0]].astype(str).str.strip()
    for c in cols[1:]:
        sid = sid + " | " + df[c].astype(str).str.strip()
    return sid


def selecionar_series(base: pd.DataFrame, min_frac_dias_uteis: float, ate: str | None = None) -> list[str]:
    """Séries com registro em pelo menos `min_frac_dias_uteis` dos dias úteis (seg–sex) do período.

    `ate` limita o período usado na seleção (para não olhar o período de teste do experimento).
    """
    b = base if ate is None else base[base["timestamp"] < pd.Timestamp(ate)]
    dias = b["timestamp"].dt.normalize()
    uteis = dias.dt.day_of_week < 5
    n_uteis = int(pd.date_range(dias.min(), dias.max(), freq="B").size)
    frac = dias[uteis].groupby(b.loc[uteis, "series_id"]).nunique() / max(n_uteis, 1)
    return sorted(frac[frac >= min_frac_dias_uteis].index)


def construir_series(df: pd.DataFrame, *, col_serie: str | list[str], col_alvo: str, col_ts: str | None = None,
                     col_data: str | None = None, col_hora: str | None = None, freq: str = "h",
                     agregacao: str = "mean", ausente_como_zero: bool = False, freq_coleta: str | None = None,
                     agregacao_instante: str = "sum", fator: float = 1.0, min_frac_dias_uteis: float | None = None,
                     selecao_ate: str | None = None) -> tuple[pd.DataFrame, dict]:
    """Retorna (series_longas[timestamp, series_id, target], relatorio_de_qualidade).

    Linhas com timestamp ou indicador inválido são descartadas e CONTADAS no relatório (RF02).
    Modo padrão: duplicatas no mesmo instante são agregadas (média) e as lacunas da grade ficam NaN
    (o tratamento de lacunas é feito no experimento).

    Modo `ausente_como_zero` (bases de EVENTOS, como a lentidão da CET, que só registra o trecho quando há
    fila): os registros do mesmo instante são agregados por `agregacao_instante` (soma dos trechos), a grade
    de coleta (`freq_coleta`, ex. 30min) é completada com 0 desde o primeiro dia da série até o último instante
    da base, e só então a série é levada à frequência `freq` por `agregacao`.
    """
    sid = _id_serie(df, col_serie)
    exigir_colunas(df, [col_alvo])
    ts = montar_timestamp(df, col_ts, col_data, col_hora)
    relatorio = relatorio_qualidade(ts, sid, df[col_alvo])
    base = pd.DataFrame({
        "timestamp": ts,
        "series_id": sid,
        "target": para_numero(df[col_alvo]) * fator,
    }).dropna(subset=["timestamp", "target"])
    base = base[base["target"] >= 0]
    relatorio["linhas_apos_descarte"] = int(len(base))
    if min_frac_dias_uteis:
        manter = selecionar_series(base, min_frac_dias_uteis, selecao_ate)
        relatorio["selecao"] = {"criterio": f"registro em >= {min_frac_dias_uteis:.0%} dos dias úteis"
                                            + (f" antes de {selecao_ate}" if selecao_ate else ""),
                                "series_candidatas": int(base["series_id"].nunique()), "series_mantidas": len(manter)}
        base = base[base["series_id"].isin(manter)]
    partes = []
    if ausente_como_zero:
        passo = freq_coleta or freq
        base["timestamp"] = base["timestamp"].dt.floor(passo)
        fim = base["timestamp"].max()
        for s_id, g in base.groupby("series_id"):
            s = g.groupby("timestamp")["target"].agg(agregacao_instante)
            s = s.reindex(pd.date_range(s.index.min().normalize(), fim, freq=passo), fill_value=0.0)
            s = s.resample(freq).agg(agregacao)
            partes.append(pd.DataFrame({"timestamp": s.index, "series_id": s_id, "target": s.values}))
    else:
        base["timestamp"] = base["timestamp"].dt.floor(freq)
        for s_id, g in base.groupby("series_id"):
            s = g.groupby("timestamp")["target"].agg(agregacao)
            s = s.reindex(pd.date_range(s.index.min(), s.index.max(), freq=freq))
            partes.append(pd.DataFrame({"timestamp": s.index, "series_id": s_id, "target": s.values}))
    if not partes:
        raise ValueError("nenhum registro válido após a validação; veja o relatório de qualidade.")
    out = pd.concat(partes, ignore_index=True)
    relatorio["pct_horas_ausentes"] = float(out["target"].isna().mean())
    relatorio["ausente_como_zero"] = ausente_como_zero
    if ausente_como_zero:
        relatorio["pct_horas_sem_lentidao"] = float((out["target"] == 0).mean())
    return out, relatorio


def anexar_covariaveis(series: pd.DataFrame, clima: pd.DataFrame | None = None,
                       calendario_diario: pd.DataFrame | None = None) -> pd.DataFrame:
    """Junta clima (por hora) e calendário (por dia) e cria hora/dia da semana. Mantém as colunas originais."""
    out = series.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"])
    out["hora"] = out["timestamp"].dt.hour
    out["dia_semana"] = out["timestamp"].dt.day_of_week
    if clima is not None:
        c = clima.copy()
        c["timestamp"] = pd.to_datetime(c["timestamp"])
        out = out.merge(c, on="timestamp", how="left")
    if calendario_diario is not None:
        d = calendario_diario[["data", "feriado", "fim_de_semana"]].copy()
        d["data"] = pd.to_datetime(d["data"])
        out["data"] = out["timestamp"].dt.normalize()
        out = out.merge(d, on="data", how="left").drop(columns="data")
    return out
