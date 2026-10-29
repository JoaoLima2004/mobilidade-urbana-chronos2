#!/usr/bin/env python3
"""
Evidências de execução – TCC Mobilidade Urbana SP
=================================================

Lê o que o pipeline e o experimento gravaram em disco e produz material verificável:

  hashes.csv               SHA-256 dos arquivos brutos (conferível baixando o mesmo arquivo do portal) e do código
  exemplo_rastreado.json   uma hora real de um corredor, do registro bruto da CET até as previsões de cada modelo
  reprodutibilidade.json   comparação entre duas execuções independentes da rodada principal
  tabela_por_serie.csv     MAE/MASE de cada série (35) por modelo
  cobertura_por_serie.csv  dias úteis sem registro por série (lacuna de monitoramento ou ausência de fila)
  robustez_sem_series_zeradas.json  resumo sem as séries que ficaram sem registro em todo o teste
  fig_teste_corredores.png previsto x observado nos 14 dias de teste
  fig_mae_por_hora.png     erro médio por hora do dia

Uso:
python experimento/gerar_evidencias.py --principal resultados/principal --reproducao resultados/reproducao
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]

# Paleta categórica de referência (3 primeiros tons, validados para daltonismo no modo claro)
COR = {"Observado": "#0b0b0b", "Chronos-2": "#2a78d6", "SN_diario": "#eb6834", "SN_semanal": "#1baf7a"}
TRACO = {"Observado": "-", "Chronos-2": "-", "SN_diario": "--", "SN_semanal": ":"}
TINTA_SEC, GRADE = "#52514e", "#e4e3df"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def curto(modelo: str) -> str:
    return modelo.split("(")[0]


def estilo(ax):
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(TINTA_SEC)
    ax.tick_params(colors=TINTA_SEC, labelsize=8)
    ax.grid(axis="y", color=GRADE, lw=0.6)
    ax.set_axisbelow(True)


# --------------------------------------------------------------------------
def gerar_hashes(out: Path) -> pd.DataFrame:
    linhas = []
    for meta in sorted((RAIZ / "dados" / "bruto").rglob("*.meta.json")):
        m = json.loads(meta.read_text(encoding="utf-8"))
        arq = meta.with_name(meta.name[: -len(".meta.json")])
        linhas.append({"tipo": "dado bruto", "fonte": m.get("fonte"), "arquivo": arq.name, "bytes": arq.stat().st_size,
                       "registros": m.get("n_registros"), "sha256_manifesto": m.get("sha256"),
                       "sha256_recalculado": sha256(arq), "coletado_em": m.get("coletado_em")})
    for cod in ["experimento/experimento_previsao.py", "mobilidade/series.py", "mobilidade/validacao.py",
                "mobilidade/adapters/cet_csv.py", "mobilidade/cli.py"]:
        p = RAIZ / cod
        linhas.append({"tipo": "código", "fonte": "pipeline", "arquivo": cod, "bytes": p.stat().st_size,
                       "sha256_recalculado": sha256(p)})
    df = pd.DataFrame(linhas)
    df["confere"] = np.where(df["tipo"] == "dado bruto", df["sha256_manifesto"] == df["sha256_recalculado"], None)
    df.to_csv(out / "hashes.csv", index=False)
    return df


def gerar_exemplo(principal: Path, out: Path, serie: str, instante: str) -> dict:
    """Refaz à mão, a partir do CSV bruto, o valor de uma hora da série e junta as previsões gravadas."""
    from mobilidade.adapters.cet_csv import CetLentidaoCsv  # noqa: E402

    t = pd.Timestamp(instante)
    corredor, sentido = [s.strip() for s in serie.split("|")]
    bruto = sorted((RAIZ / "dados" / "bruto" / "cet_lentidao_csv").glob(f"*{t.year}*.csv"))[-1]
    df = CetLentidaoCsv.ler(bruto)
    df["ts"] = pd.to_datetime(df["data"], format="%d/%m/%Y %H:%M")
    sel = df[(df.corredor.str.strip() == corredor) & (df.sentido.str.strip() == sentido)
             & (df.ts >= t) & (df.ts < t + pd.Timedelta("1h"))]
    por_meia_hora = {h.strftime("%H:%M"): int(sel.loc[sel.ts == h, "tamanho"].sum())
                     for h in [t, t + pd.Timedelta("30min")]}
    valor_manual = float(np.mean(list(por_meia_hora.values())) / 1000)

    series = pd.read_csv(RAIZ / "dados" / "tratado" / "series_horarias.csv", parse_dates=["timestamp"])
    valor_serie = float(series.loc[(series.series_id == serie) & (series.timestamp == t), "target"].iloc[0])
    prev = pd.read_csv(principal / "previsoes.csv", parse_dates=["timestamp"])
    p = prev[(prev.series_id == serie) & (prev.timestamp == t)]
    ex = {
        "serie": serie, "instante": str(t), "arquivo_bruto": bruto.name,
        "registros_brutos": sel[["data", "descricao", "tamanho"]].to_dict("records"),
        "metros_por_meia_hora": por_meia_hora,
        "km_calculado_a_mao": round(valor_manual, 4),
        "km_na_serie_horaria": round(valor_serie, 4),
        "confere": bool(np.isclose(valor_manual, valor_serie)),
        "previsoes_gravadas": {curto(r.modelo): round(float(r.previsto), 4) for r in p.itertuples()},
        "janela": int(p["janela"].iloc[0]), "passo_a_frente": int(p["passo"].iloc[0]),
    }
    (out / "exemplo_rastreado.json").write_text(json.dumps(ex, indent=2, ensure_ascii=False), encoding="utf-8")
    return ex


def gerar_reprodutibilidade(a: Path, b: Path, out: Path) -> dict:
    ma, mb = pd.read_csv(a / "metricas_por_janela.csv"), pd.read_csv(b / "metricas_por_janela.csv")
    pa, pb = pd.read_csv(a / "previsoes.csv"), pd.read_csv(b / "previsoes.csv")
    ea = json.loads((a / "execucao.json").read_text(encoding="utf-8"))
    eb = json.loads((b / "execucao.json").read_text(encoding="utf-8"))
    rep = {
        "execucao_1": ea["executado_em"], "execucao_2": eb["executado_em"],
        "linhas_metricas": [len(ma), len(mb)], "linhas_previsoes": [len(pa), len(pb)],
        "max_dif_abs_MAE": float((ma["MAE"] - mb["MAE"]).abs().max()),
        "max_dif_abs_previsao": float((pa["previsto"] - pb["previsto"]).abs().max()),
        "max_dif_abs_previsao_chronos": float((pa.loc[pa.modelo == "Chronos-2", "previsto"].to_numpy()
                                               - pb.loc[pb.modelo == "Chronos-2", "previsto"].to_numpy()).__abs__().max()),
    }
    rep["resultado_identico"] = rep["max_dif_abs_MAE"] < 1e-6 and rep["max_dif_abs_previsao"] < 1e-6
    (out / "reprodutibilidade.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return rep


def gerar_cobertura_e_robustez(principal: Path, out: Path, fim: str) -> dict:
    """Dias úteis sem nenhum registro por série (lacuna de monitoramento OU ausência real de fila – a base
    não distingue) e o resumo do experimento sem as séries que ficaram zeradas em todo o período de teste."""
    s = pd.read_csv(RAIZ / "dados" / "tratado" / "series_horarias.csv", parse_dates=["timestamp"])
    s = s[s.timestamp <= pd.Timestamp(fim)]
    cal = pd.read_parquet(RAIZ / "dados" / "tratado" / "calendario_diario.parquet")
    feriados = set(cal.loc[cal.feriado == 1, "data"])
    d = s.groupby(["series_id", s.timestamp.dt.normalize()]).target.sum().rename("km").reset_index()
    d = d[(d.timestamp.dt.day_of_week < 5) & ~d.timestamp.isin(feriados)]

    def maior_seq(zeros):
        m = c = 0
        for z in zeros:
            c = c + 1 if z else 0
            m = max(m, c)
        return m

    cob = d.groupby("series_id").apply(lambda g: pd.Series({
        "dias_uteis_sem_registro": int((g.km == 0).sum()),
        "maior_seq_dias_uteis_sem_registro": maior_seq((g.km == 0).tolist())}))
    cob.to_csv(out / "cobertura_por_serie.csv")

    m = pd.read_csv(principal / "metricas_por_serie.csv")
    prev = pd.read_csv(principal / "previsoes.csv")
    obs = prev[prev.modelo == "Chronos-2"].groupby("series_id").observado.sum()
    zeradas = sorted(obs[obs == 0].index)
    sub = m[~m.series_id.isin(zeradas)]
    w = sub.pivot(index="series_id", columns="modelo", values="MASE")
    dia = next(c for c in w.columns if c.startswith("SN_diario"))
    sem = next(c for c in w.columns if c.startswith("SN_semanal"))
    rob = {"series_zeradas_no_teste": zeradas, "n_series": int(len(w)),
           "MAE_medio": sub.groupby("modelo").MAE.mean().round(4).to_dict(),
           "MASE_medio": sub.groupby("modelo").MASE.mean().round(4).to_dict(),
           "chronos_vence_SN_diario": int((w["Chronos-2"] < w[dia]).sum()),
           "chronos_vence_SN_semanal": int((w["Chronos-2"] < w[sem]).sum())}
    (out / "robustez_sem_series_zeradas.json").write_text(json.dumps(rob, indent=2, ensure_ascii=False), encoding="utf-8")
    return rob


def gerar_tabela_por_serie(principal: Path, out: Path) -> pd.DataFrame:
    s = pd.read_csv(principal / "metricas_por_serie.csv")
    s["modelo"] = s["modelo"].map(curto)
    t = s.pivot(index="series_id", columns="modelo", values=["MAE", "MASE"])
    t.columns = [f"{m}_{mod}" for m, mod in t.columns]
    t = t.sort_values("MAE_Chronos-2", ascending=False).reset_index()
    t.to_csv(out / "tabela_por_serie.csv", index=False)
    return t


# --------------------------------------------------------------------------
def figuras(principal: Path, out: Path, corredores: list[str]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold"})
    prev = pd.read_csv(principal / "previsoes.csv", parse_dates=["timestamp"])

    # 1) previsto x observado nos 14 dias de teste (cada dia é uma janela, prevista só com o passado)
    fig, axs = plt.subplots(len(corredores), 1, figsize=(9, 2.8 * len(corredores)), sharex=True)
    for ax, sid in zip(np.atleast_1d(axs), corredores):
        g = prev[prev.series_id == sid].copy()
        g["m"] = g.modelo.map(curto)
        obs = g[g.m == "Chronos-2"].sort_values("timestamp")
        ax.plot(obs.timestamp, obs.observado, color=COR["Observado"], lw=2.0, label="Observado")
        for m in ("SN_semanal", "SN_diario", "Chronos-2"):
            h = g[g.m == m].sort_values("timestamp")
            ax.plot(h.timestamp, h.previsto, color=COR[m], ls=TRACO[m], lw=1.4 if m != "Chronos-2" else 1.8,
                    label={"SN_diario": "Ingênuo sazonal diário", "SN_semanal": "Ingênuo sazonal semanal"}.get(m, m))
        ax.set_title(sid, loc="left")
        ax.set_ylabel("km em lentidão")
        estilo(ax)
    np.atleast_1d(axs)[0].legend(ncol=4, fontsize=8, frameon=False, loc="upper left", bbox_to_anchor=(0, 1.32))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %d/%m"))
    fig.suptitle("Previsto × observado – período de teste (02 a 15/12/2023)", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "fig_teste_corredores.png", dpi=170)
    plt.close(fig)

    # 2) MAE por hora do dia (todas as séries)
    prev["m"] = prev.modelo.map(curto)
    prev["erro"] = (prev.observado - prev.previsto).abs()
    por_hora = prev[prev.m != "Ingenuo"].groupby(["m", prev.timestamp.dt.hour]).erro.mean().unstack(0)
    fig, ax = plt.subplots(figsize=(8, 3.2))
    for m in ("SN_semanal", "SN_diario", "Chronos-2"):
        ax.plot(por_hora.index, por_hora[m], color=COR[m], ls=TRACO[m], lw=2, marker="o", ms=3.5,
                label={"SN_diario": "Ingênuo sazonal diário", "SN_semanal": "Ingênuo sazonal semanal"}.get(m, m))
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("Hora do dia")
    ax.set_ylabel("MAE (km)")
    ax.set_title("Erro médio por hora do dia – 35 séries, 14 dias de teste", loc="left")
    ax.legend(frameon=False, fontsize=8)
    estilo(ax)
    fig.tight_layout()
    fig.savefig(out / "fig_mae_por_hora.png", dpi=170)
    plt.close(fig)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--principal", default="resultados/principal")
    p.add_argument("--reproducao", default="resultados/reproducao")
    p.add_argument("--output", default="resultados/evidencias")
    p.add_argument("--fim", default="2023-12-15 23:00", help="Mesmo --fim da rodada principal.")
    p.add_argument("--serie-exemplo", default="Marginal Tietê | Castelo/A.Senna")
    p.add_argument("--instante-exemplo", default="2023-12-05 08:00")
    p.add_argument("--corredores", nargs="+", default=["Marginal Tietê | Castelo/A.Senna",
                                                         "Marginal Pinheiros | Interlagos/Castelo"])
    a = p.parse_args(argv)
    import sys
    sys.path.insert(0, str(RAIZ))
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    principal, reproducao = Path(a.principal), Path(a.reproducao)

    h = gerar_hashes(out)
    print(h[["tipo", "arquivo", "registros", "sha256_recalculado", "confere"]].to_string(index=False))
    ex = gerar_exemplo(principal, out, a.serie_exemplo, a.instante_exemplo)
    print("\nexemplo rastreado:", json.dumps({k: ex[k] for k in ("metros_por_meia_hora", "km_calculado_a_mao",
                                                                 "km_na_serie_horaria", "confere", "previsoes_gravadas")},
                                             ensure_ascii=False))
    if (reproducao / "execucao.json").exists():
        print("\nreprodutibilidade:", gerar_reprodutibilidade(principal, reproducao, out))
    print("\nrobustez:", gerar_cobertura_e_robustez(principal, out, a.fim))
    gerar_tabela_por_serie(principal, out)
    figuras(principal, out, a.corredores)
    print(f"\nEvidências gravadas em {out}")


if __name__ == "__main__":
    main()
