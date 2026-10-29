"""Linha de comando do pipeline.

Exemplos:
  python -m mobilidade.cli inspecionar dados/bruto/cet_lentidao_csv/arquivo.csv
  python -m mobilidade.cli coletar cet-csv --origem ~/Downloads/lentidao_trechos_2023.csv
  python -m mobilidade.cli coletar cet-api --anos 2017 2018
  python -m mobilidade.cli coletar clima --inicio 2023-01-01 --fim 2023-12-31
  python -m mobilidade.cli coletar calendario --anos 2023
  python -m mobilidade.cli series --entrada <arquivo bruto> --col-ts data_hora --col-serie trecho --col-alvo lentidao
  python -m mobilidade.cli status
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from . import armazenamento as arm
from .adapters.calendario import Calendario
from .adapters.cet_api import CetLentidaoApi
from .adapters.cet_csv import CetLentidaoCsv
from .adapters.infosiga import Infosiga
from .adapters.openmeteo import OpenMeteo
from .config import Config
from .http import FonteIndisponivel
from .registro import RegistroExecucao, ultimas
from .series import anexar_covariaveis, construir_series


def _ler_qualquer(caminho: Path) -> pd.DataFrame:
    if caminho.suffix.lower() == ".json":
        return CetLentidaoApi.ler(caminho)
    if caminho.suffix.lower() == ".parquet":
        return pd.read_parquet(caminho)
    return CetLentidaoCsv.ler(caminho)


def cmd_inspecionar(args, cfg: Config) -> int:
    df = _ler_qualquer(Path(args.arquivo))
    print(f"Linhas: {len(df)} | Colunas: {len(df.columns)}\n")
    resumo = pd.DataFrame({"tipo": df.dtypes.astype(str), "nulos": df.isna().sum(), "distintos": df.nunique(),
                           "exemplo": df.iloc[0] if len(df) else None})
    print(resumo.to_string())
    print("\nPrimeiras linhas:")
    print(df.head(5).to_string())
    print("\nDica: identifique a coluna de data/hora, a de localidade/trecho e a do indicador, e use-as em `series`.")
    return 0


def cmd_coletar(args, cfg: Config) -> int:
    fonte = args.fonte
    params = {k: v for k, v in vars(args).items() if k not in ("func", "cmd", "fonte")}
    with RegistroExecucao(cfg.data_dir, "coleta", fonte, params) as reg:
        if fonte == "cet-api":
            res = CetLentidaoApi(cfg).coletar(anos=args.anos, limite=args.limite)
        elif fonte == "cet-csv":
            res = CetLentidaoCsv(cfg).coletar(args.origem)
        elif fonte == "infosiga":
            ad = Infosiga(cfg)
            res = ad.coletar(args.origem)
            if args.processar:
                sin = ad.ler_sinistros(res.arquivos[0])
                dest = arm.salvar_tabela(ad.contagem_diaria(sin), cfg.data_dir / "tratado" / "infosiga_sinistros_diarios")
                res.observacoes.append(f"contagem diária gravada em {dest}")
        elif fonte == "clima":
            ad = OpenMeteo(cfg)
            res = ad.coletar(date.fromisoformat(args.inicio), date.fromisoformat(args.fim))
            res.observacoes.append(f"tratado: {arm.salvar_tabela(ad.tabela, cfg.data_dir / 'tratado' / 'clima_horario')}")
        elif fonte == "calendario":
            ad = Calendario(cfg)
            res = ad.coletar(args.anos)
            anos = sorted(args.anos)
            flags = ad.flags_diarios(ad.tabela, f"{anos[0]}-01-01", f"{anos[-1]}-12-31")
            res.observacoes.append(f"tratado: {arm.salvar_tabela(flags, cfg.data_dir / 'tratado' / 'calendario_diario')}")
        else:  # pragma: no cover
            raise SystemExit(f"fonte desconhecida: {fonte}")
        reg.n_registros = res.n_registros
        reg.mensagem = " | ".join(res.observacoes)
    print(f"[{fonte}] ok: {res.n_registros} registros; arquivos: {[str(a) for a in res.arquivos]}")
    for o in res.observacoes:
        print("  -", o)
    return 0


def cmd_series(args, cfg: Config) -> int:
    df = pd.concat([_ler_qualquer(Path(e)) for e in args.entrada], ignore_index=True)
    params = {k: v for k, v in vars(args).items() if k not in ("func", "cmd")}
    with RegistroExecucao(cfg.data_dir, "series", "cet", params) as reg:
        series, qual = construir_series(df, col_serie=args.col_serie, col_alvo=args.col_alvo, col_ts=args.col_ts,
                                        col_data=args.col_data, col_hora=args.col_hora, freq=args.freq,
                                        ausente_como_zero=args.ausente_como_zero, freq_coleta=args.freq_coleta,
                                        fator=args.fator, min_frac_dias_uteis=args.min_frac_dias_uteis,
                                        selecao_ate=args.selecao_ate)
        clima = cal = None
        if not args.sem_covariaveis:
            p = arm.achar_tabela(cfg.data_dir, "clima_horario")
            clima = arm.ler_tabela(p) if p else None
            p = arm.achar_tabela(cfg.data_dir, "calendario_diario")
            cal = arm.ler_tabela(p) if p else None
        final = anexar_covariaveis(series, clima, cal)
        saida = cfg.data_dir / "tratado"
        saida.mkdir(parents=True, exist_ok=True)
        final.to_csv(saida / "series_horarias.csv", index=False)  # entrada do experimento
        pq = arm.salvar_tabela(final, saida / "series_horarias")
        (saida / "relatorio_qualidade.json").write_text(json.dumps(qual, indent=2, ensure_ascii=False), encoding="utf-8")
        reg.n_registros = len(final)
        reg.mensagem = f"covariáveis: clima={'sim' if clima is not None else 'não'}, calendário={'sim' if cal is not None else 'não'}"
    print(f"Séries: {final['series_id'].nunique()} | linhas: {len(final)} | % horas ausentes: {qual['pct_horas_ausentes']:.1%}")
    print(f"Gravado: {saida / 'series_horarias.csv'} e {pq}")
    print(f"Relatório de qualidade: {saida / 'relatorio_qualidade.json'}")
    print("\nPróximo passo (experimento):\n  python experimento/experimento_previsao.py --input "
          f"{saida / 'series_horarias.csv'} --col-timestamp timestamp --col-series series_id --col-target target")
    return 0


def cmd_status(args, cfg: Config) -> int:
    for e in ultimas(cfg.data_dir, args.n):
        print(f"{e['inicio']}  {e['etapa']:<8} {e['fonte']:<18} {e['status']:<5} n={e['n_registros']}  {e['mensagem'][:90]}")
    return 0


def main(argv=None) -> int:
    cfg = Config.from_env()
    p = argparse.ArgumentParser(prog="mobilidade", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("inspecionar"); s.add_argument("arquivo"); s.set_defaults(func=cmd_inspecionar)

    c = sub.add_parser("coletar"); cs = c.add_subparsers(dest="fonte", required=True)
    x = cs.add_parser("cet-api"); x.add_argument("--anos", type=int, nargs="+", required=True); x.add_argument("--limite", type=int, default=1000)
    x = cs.add_parser("cet-csv"); x.add_argument("--origem", required=True)
    x = cs.add_parser("infosiga"); x.add_argument("--origem"); x.add_argument("--processar", action="store_true")
    x = cs.add_parser("clima"); x.add_argument("--inicio", required=True); x.add_argument("--fim", required=True)
    x = cs.add_parser("calendario"); x.add_argument("--anos", type=int, nargs="+", required=True)
    c.set_defaults(func=cmd_coletar)

    s = sub.add_parser("series"); s.add_argument("--entrada", required=True, nargs="+")
    s.add_argument("--col-ts"); s.add_argument("--col-data"); s.add_argument("--col-hora")
    s.add_argument("--col-serie", required=True, nargs="+", help="uma ou mais colunas (ex.: corredor sentido)")
    s.add_argument("--col-alvo", required=True)
    s.add_argument("--freq", default="h"); s.add_argument("--sem-covariaveis", action="store_true")
    s.add_argument("--ausente-como-zero", action="store_true",
                   help="base de eventos: instante sem registro = 0 (soma por instante, grade completada com 0)")
    s.add_argument("--freq-coleta", help="passo de coleta da fonte (ex.: 30min), usado com --ausente-como-zero")
    s.add_argument("--fator", type=float, default=1.0, help="multiplica o indicador (ex.: 0.001 para m -> km)")
    s.add_argument("--min-frac-dias-uteis", type=float, help="mantém séries com registro em >= essa fração dos dias úteis")
    s.add_argument("--selecao-ate", help="data limite (exclusiva) do período usado na seleção de séries")
    s.set_defaults(func=cmd_series)

    s = sub.add_parser("status"); s.add_argument("-n", type=int, default=20); s.set_defaults(func=cmd_status)

    args = p.parse_args(argv)
    try:
        return args.func(args, cfg)
    except FonteIndisponivel as e:
        print(f"ERRO (fonte indisponível): {e}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
