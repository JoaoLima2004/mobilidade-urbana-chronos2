#!/usr/bin/env python3
"""
Experimento de previsão – TCC Mobilidade Urbana em São Paulo
============================================================

Compara o Chronos-2 (zero-shot) com linhas de base (ingênuo sazonal diário e
semanal, e ingênuo simples) usando validação em janelas deslizantes
(rolling-origin evaluation) e as métricas MAE e MASE.

Uso típico
----------
# 1) Validar o pipeline com dados SINTÉTICOS (não gera resultado científico):
python experimento_previsao.py --demo --skip-chronos

# 2) Rodar com o CSV real (ajuste o mapeamento de colunas):
python experimento_previsao.py \
    --input dados/lentidao_cet.csv \
    --col-timestamp data_hora --col-series localidade --col-target lentidao_km \
    --freq h --horizon 24 --n-windows 14 --min-length-days 30

Saídas (pasta --output, padrão ./resultados)
--------------------------------------------
metricas_por_janela.csv   MAE e MASE por série x janela x modelo
metricas_por_serie.csv    média por série x modelo
resumo_modelos.csv        agregado por modelo (média/mediana)
previsoes.csv             valores observados e previstos (para gráficos)
series_descartadas.csv    séries excluídas e motivo
execucao.json             configuração, versões e data (reprodutibilidade)
fig_*.png                 gráficos
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------


@dataclass
class Config:
    input: str | None
    output: str
    col_timestamp: str
    col_series: str
    col_target: str
    freq: str
    horizon: int
    n_windows: int
    stride: int
    season_daily: int
    season_weekly: int
    min_length_days: int
    max_gap_fill: int
    context_length: int | None
    model_id: str
    device: str
    skip_chronos: bool
    demo: bool
    seed: int
    fim: str | None = None


def steps_per_day_for(freq: str) -> int:
    """Nº de passos em 24 h para a frequência dada (ex.: 'h' -> 24, '15min' -> 96)."""
    return int(round(pd.Timedelta("1D") / pd.Timedelta(pd.tseries.frequencies.to_offset(freq))))


def parse_args(argv=None) -> Config:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", help="CSV de entrada (formato longo: timestamp, série, valor).")
    p.add_argument("--output", default="resultados")
    p.add_argument("--col-timestamp", default="timestamp")
    p.add_argument("--col-series", default="series_id")
    p.add_argument("--col-target", default="target")
    p.add_argument("--freq", default="h", help="Frequência pandas (h = horária, 15min, D...).")
    p.add_argument("--horizon", type=int, default=24, help="Janela de previsão em passos (24 = 24 h).")
    p.add_argument("--n-windows", type=int, default=14, help="Nº de origens de previsão (janelas deslizantes).")
    p.add_argument("--stride", type=int, default=None, help="Passo entre origens (padrão = horizon, sem sobreposição).")
    p.add_argument("--season-daily", type=int, default=None, help="Período sazonal diário em passos (padrão: 24 p/ freq horária).")
    p.add_argument("--season-weekly", type=int, default=None, help="Período sazonal semanal em passos (padrão: 168 p/ freq horária).")
    p.add_argument("--min-length-days", type=int, default=30, help="Histórico mínimo por série, em dias.")
    p.add_argument("--max-gap-fill", type=int, default=3, help="Máx. de passos consecutivos ausentes preenchidos por interpolação.")
    p.add_argument("--context-length", type=int, default=None, help="Limita o histórico enviado ao Chronos-2 (passos). Padrão: tudo até a origem.")
    p.add_argument("--model-id", default="amazon/chronos-2")
    p.add_argument("--device", default="cpu", help="cpu ou cuda.")
    p.add_argument("--skip-chronos", action="store_true", help="Roda apenas as linhas de base.")
    p.add_argument("--demo", action="store_true", help="Usa dados sintéticos para testar o pipeline.")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--fim", help="Último instante usado (inclusive), ex. '2023-12-15 23:00'. A última janela termina aqui.")
    a = p.parse_args(argv)

    steps_per_day = steps_per_day_for(a.freq)
    return Config(
        input=a.input, output=a.output, col_timestamp=a.col_timestamp, col_series=a.col_series,
        col_target=a.col_target, freq=a.freq, horizon=a.horizon, n_windows=a.n_windows,
        stride=a.stride or a.horizon,
        season_daily=a.season_daily or steps_per_day,
        season_weekly=a.season_weekly or steps_per_day * 7,
        min_length_days=a.min_length_days, max_gap_fill=a.max_gap_fill,
        context_length=a.context_length, model_id=a.model_id, device=a.device,
        skip_chronos=a.skip_chronos, demo=a.demo, seed=a.seed, fim=a.fim,
    )


# --------------------------------------------------------------------------
# Dados
# --------------------------------------------------------------------------


def make_demo_data(cfg: Config) -> pd.DataFrame:
    """Séries sintéticas (padrão diário + semanal + ruído). SÓ para testar o código."""
    rng = np.random.default_rng(cfg.seed)
    idx = pd.date_range("2026-01-01", periods=24 * 90, freq=cfg.freq)
    rows = []
    for k in range(6):
        hour = idx.hour.values
        dow = idx.day_of_week.values
        base = 5 + k
        daily = 4 * np.exp(-((hour - 8) ** 2) / 6) + 5 * np.exp(-((hour - 18) ** 2) / 8)
        weekly = np.where(dow >= 5, -0.5, 1.0) * daily
        y = base + weekly + rng.normal(0, 0.8, len(idx))
        rows.append(pd.DataFrame({cfg.col_timestamp: idx, cfg.col_series: f"demo_{k}", cfg.col_target: np.clip(y, 0, None)}))
    return pd.concat(rows, ignore_index=True)


def load_and_prepare(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lê o CSV, regulariza a frequência, trata lacunas e descarta séries insuficientes.

    Retorna (dados_preparados, descartadas).
    """
    if cfg.demo:
        df = make_demo_data(cfg)
    else:
        if not cfg.input:
            sys.exit("Informe --input <arquivo.csv> ou use --demo.")
        df = pd.read_csv(cfg.input)

    missing = [c for c in (cfg.col_timestamp, cfg.col_series, cfg.col_target) if c not in df.columns]
    if missing:
        sys.exit(f"Colunas não encontradas no CSV: {missing}. Colunas disponíveis: {list(df.columns)}")

    df = df[[cfg.col_timestamp, cfg.col_series, cfg.col_target]].copy()
    df.columns = ["timestamp", "series_id", "target"]
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["target"] = pd.to_numeric(df["target"], errors="coerce")
    n0 = len(df)
    df = df.dropna(subset=["timestamp", "series_id"])
    if cfg.fim:
        df = df[df["timestamp"] <= pd.Timestamp(cfg.fim)]
    df["series_id"] = df["series_id"].astype(str)

    prepared, dropped = [], []
    min_len = cfg.min_length_days * steps_per_day_for(cfg.freq)
    need = cfg.horizon + cfg.stride * (cfg.n_windows - 1) + 2 * cfg.season_weekly  # contexto mínimo p/ MASE semanal

    for sid, g in df.groupby("series_id"):
        # agrega duplicatas no mesmo instante (média) e regulariza a grade temporal
        g = g.groupby(g["timestamp"].dt.floor(cfg.freq))["target"].mean()
        full = pd.date_range(g.index.min(), g.index.max(), freq=cfg.freq)
        g = g.reindex(full)
        n_missing = int(g.isna().sum())
        g = g.interpolate(limit=cfg.max_gap_fill, limit_area="inside")
        n_left = int(g.isna().sum())
        # usa o maior trecho final sem lacunas
        if n_left:
            last_valid_break = g[g.isna()].index.max()
            g = g.loc[g.index > last_valid_break]
        if len(g) < max(min_len, need):
            dropped.append({"series_id": sid, "motivo": f"histórico insuficiente ({len(g)} passos; mínimo {max(min_len, need)})",
                            "ausentes_originais": n_missing})
            continue
        out = g.rename("target").rename_axis("timestamp").reset_index()
        out["series_id"] = sid
        prepared.append(out)

    prepared_df = pd.concat(prepared, ignore_index=True) if prepared else pd.DataFrame(columns=["timestamp", "series_id", "target"])
    print(f"[dados] registros lidos: {n0} | séries mantidas: {len(prepared)} | descartadas: {len(dropped)}")
    return prepared_df, pd.DataFrame(dropped, columns=["series_id", "motivo", "ausentes_originais"])


# --------------------------------------------------------------------------
# Modelos de base
# --------------------------------------------------------------------------


def seasonal_naive(history: np.ndarray, horizon: int, m: int) -> np.ndarray:
    """Repete o último ciclo sazonal de comprimento m."""
    if len(history) < m:
        return np.full(horizon, history[-1])
    last_cycle = history[-m:]
    reps = int(np.ceil(horizon / m))
    return np.tile(last_cycle, reps)[:horizon]


def naive(history: np.ndarray, horizon: int) -> np.ndarray:
    return np.full(horizon, history[-1])


# --------------------------------------------------------------------------
# Métricas
# --------------------------------------------------------------------------


def mae(y: np.ndarray, yhat: np.ndarray) -> float:
    return float(np.mean(np.abs(y - yhat)))


def mase(y: np.ndarray, yhat: np.ndarray, history: np.ndarray, m: int) -> float:
    """MASE (Hyndman & Koehler, 2006) com escala = erro médio absoluto do
    ingênuo sazonal de período m calculado DENTRO da amostra de treino.
    Valores < 1 indicam desempenho melhor que o ingênuo sazonal in-sample."""
    if len(history) <= m:
        return float("nan")
    scale = np.mean(np.abs(history[m:] - history[:-m]))
    if scale == 0:
        return float("nan")
    return float(np.mean(np.abs(y - yhat)) / scale)


# --------------------------------------------------------------------------
# Chronos-2
# --------------------------------------------------------------------------


class Chronos2Forecaster:
    """Wrapper fino sobre chronos.Chronos2Pipeline.predict_df (zero-shot, univariado)."""

    def __init__(self, model_id: str, device: str):
        try:
            from chronos import Chronos2Pipeline  # type: ignore
        except ImportError as e:  # pragma: no cover
            sys.exit("Pacote 'chronos-forecasting>=2.0' não instalado. Rode: pip install -r requirements.txt "
                     "(ou use --skip-chronos).")
        self.pipeline = Chronos2Pipeline.from_pretrained(model_id, device_map=device)

    def predict_batch(self, contexts: dict[str, pd.DataFrame], horizon: int, chunk: int = 64) -> dict[str, np.ndarray]:
        """contexts: {chave -> DataFrame[timestamp, target]} ; retorna mediana prevista por chave.

        Cada chave é prevista de forma independente (cross_learning=False, padrão do Chronos-2);
        o envio em blocos só reduz o nº de chamadas ao modelo.
        """
        out = {}
        keys = list(contexts)
        for i in range(0, len(keys), chunk):
            frames = []
            for key in keys[i:i + chunk]:
                f = contexts[key][["timestamp", "target"]].copy()
                f["id"] = key
                frames.append(f)
            pred = self.pipeline.predict_df(
                pd.concat(frames, ignore_index=True),
                prediction_length=horizon,
                quantile_levels=[0.1, 0.5, 0.9],
                id_column="id",
                timestamp_column="timestamp",
                target="target",
            )
            col = "predictions" if "predictions" in pred.columns else "0.5"
            for key, g in pred.groupby("id", sort=False):
                out[str(key)] = g.sort_values("timestamp")[col].to_numpy(dtype=float)
        return out


# --------------------------------------------------------------------------
# Validação em janelas deslizantes
# --------------------------------------------------------------------------


def rolling_origins(n: int, horizon: int, n_windows: int, stride: int) -> list[int]:
    """Índices de origem (primeiro ponto previsto). A última janela termina no fim da série."""
    last = n - horizon
    origins = [last - stride * k for k in range(n_windows)]
    return sorted(o for o in origins if o > 0)


def run_experiment(data: pd.DataFrame, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    chronos = None if cfg.skip_chronos else Chronos2Forecaster(cfg.model_id, cfg.device)
    metric_rows, forecast_rows = [], []

    series = {sid: g.sort_values("timestamp").reset_index(drop=True) for sid, g in data.groupby("series_id")}
    for sid, g in series.items():
        y_all = g["target"].to_numpy(dtype=float)
        ts_all = g["timestamp"]
        origins = rolling_origins(len(g), cfg.horizon, cfg.n_windows, cfg.stride)

        # Chronos-2: todas as origens da série em lote (cada contexto termina antes da sua origem)
        chronos_preds: dict[int, np.ndarray] = {}
        if chronos is not None:
            contexts = {}
            for o in origins:
                start = max(0, o - cfg.context_length) if cfg.context_length else 0
                contexts[f"{sid}|{o}"] = g.iloc[start:o][["timestamp", "target"]]
            preds_lote = chronos.predict_batch(contexts, cfg.horizon)
            chronos_preds = {o: preds_lote[f"{sid}|{o}"] for o in origins}

        for w, o in enumerate(origins):
            hist = y_all[:o]
            truth = y_all[o:o + cfg.horizon]
            preds = {
                f"SN_diario(m={cfg.season_daily})": seasonal_naive(hist, cfg.horizon, cfg.season_daily),
                f"SN_semanal(m={cfg.season_weekly})": seasonal_naive(hist, cfg.horizon, cfg.season_weekly),
                "Ingenuo": naive(hist, cfg.horizon),
            }
            if o in chronos_preds:
                preds["Chronos-2"] = chronos_preds[o]
            for model, yhat in preds.items():
                metric_rows.append({
                    "series_id": sid, "janela": w, "origem": ts_all.iloc[o], "modelo": model,
                    "MAE": mae(truth, yhat),
                    # MASE normalizado pelo mesmo ingênuo sazonal diário para todos os modelos
                    "MASE": mase(truth, yhat, hist, cfg.season_daily),
                })
                for h in range(cfg.horizon):
                    forecast_rows.append({"series_id": sid, "janela": w, "modelo": model,
                                          "timestamp": ts_all.iloc[o + h], "passo": h + 1,
                                          "observado": truth[h], "previsto": yhat[h]})
        print(f"[exp] {sid}: {len(origins)} janelas avaliadas")
    return pd.DataFrame(metric_rows), pd.DataFrame(forecast_rows)


# --------------------------------------------------------------------------
# Agregação e gráficos
# --------------------------------------------------------------------------


def summarize(metrics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_series = metrics.groupby(["series_id", "modelo"], as_index=False)[["MAE", "MASE"]].mean()
    summary = by_series.groupby("modelo")[["MAE", "MASE"]].agg(["mean", "median"])
    summary.columns = [f"{m}_{a}" for m, a in summary.columns]
    summary = summary.reset_index().sort_values("MASE_mean")
    # % de séries em que cada modelo tem MASE médio menor que o ingênuo sazonal diário (referência principal)
    wins = by_series.pivot(index="series_id", columns="modelo", values="MASE")
    ref = next((c for c in wins.columns if c.startswith("SN_diario")), None)
    summary["n_series"] = wins.shape[0]
    if ref is not None:
        summary["pct_series_vence_SN_diario"] = summary["modelo"].map(
            lambda m: float((wins[m] < wins[ref]).mean() * 100) if m != ref else float("nan"))
    return by_series, summary


def make_figures(metrics: pd.DataFrame, forecasts: pd.DataFrame, out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    by_series = metrics.groupby(["series_id", "modelo"], as_index=False)["MASE"].mean()
    models = list(by_series["modelo"].unique())

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.boxplot([by_series.loc[by_series.modelo == m, "MASE"].dropna() for m in models], tick_labels=models, showmeans=True)
    ax.axhline(1.0, ls="--", lw=0.8, color="gray")
    ax.set_ylabel("MASE (por série)")
    ax.set_title("Distribuição do MASE por modelo")
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right")
    fig.tight_layout()
    fig.savefig(out / "fig_mase_por_modelo.png", dpi=160)
    plt.close(fig)

    by_step = forecasts.assign(erro=lambda d: (d.observado - d.previsto).abs()).groupby(["modelo", "passo"], as_index=False)["erro"].mean()
    fig, ax = plt.subplots(figsize=(7, 4))
    for m, g in by_step.groupby("modelo"):
        ax.plot(g["passo"], g["erro"], label=m)
    ax.set_xlabel("Passo à frente")
    ax.set_ylabel("MAE")
    ax.set_title("Erro por passo do horizonte")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "fig_mae_por_passo.png", dpi=160)
    plt.close(fig)

    # exemplo: última janela da primeira série
    sid = forecasts["series_id"].iloc[0]
    jan = forecasts.loc[forecasts.series_id == sid, "janela"].max()
    ex = forecasts[(forecasts.series_id == sid) & (forecasts.janela == jan)]
    fig, ax = plt.subplots(figsize=(8, 4))
    obs = ex[ex.modelo == ex.modelo.iloc[0]]
    ax.plot(obs["timestamp"], obs["observado"], "k-", lw=2, label="Observado")
    for m, g in ex.groupby("modelo"):
        ax.plot(g["timestamp"], g["previsto"], label=m, lw=1.2)
    ax.set_title(f"Exemplo de previsão – série {sid}, última janela")
    ax.legend(fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out / "fig_exemplo_previsao.png", dpi=160)
    plt.close(fig)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def main(argv=None) -> None:
    cfg = parse_args(argv)
    out = Path(cfg.output)
    out.mkdir(parents=True, exist_ok=True)
    np.random.seed(cfg.seed)

    data, dropped = load_and_prepare(cfg)
    dropped.to_csv(out / "series_descartadas.csv", index=False)
    if data.empty:
        sys.exit("Nenhuma série atende aos critérios de histórico mínimo. Veja series_descartadas.csv.")

    metrics, forecasts = run_experiment(data, cfg)
    by_series, summary = summarize(metrics)

    metrics.to_csv(out / "metricas_por_janela.csv", index=False)
    by_series.to_csv(out / "metricas_por_serie.csv", index=False)
    summary.to_csv(out / "resumo_modelos.csv", index=False)
    forecasts.to_csv(out / "previsoes.csv", index=False)
    make_figures(metrics, forecasts, out)

    meta = {
        "executado_em": datetime.now().isoformat(timespec="seconds"),
        "dados_sinteticos": cfg.demo,
        "config": asdict(cfg),
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "n_series": int(data["series_id"].nunique()),
        "periodo_dados": [str(data["timestamp"].min()), str(data["timestamp"].max())],
    }
    for pacote in ("chronos-forecasting", "torch", "matplotlib"):
        try:
            meta[pacote.replace("-", "_")] = importlib.metadata.version(pacote)
        except importlib.metadata.PackageNotFoundError:
            meta[pacote.replace("-", "_")] = None
    (out / "execucao.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print("\n=== Resumo por modelo (média entre séries) ===")
    print(summary.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    if cfg.demo:
        print("\nATENÇÃO: dados SINTÉTICOS – estes números só validam o código, não são resultado científico.")


if __name__ == "__main__":
    main()
