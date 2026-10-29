"""Calendário – feriados nacionais (BrasilAPI v1) + feriado municipal de São Paulo.

Conferido: GET https://brasilapi.com.br/api/feriados/v1/{ano} devolve lista de {date, name, type}
e cobre SOMENTE feriados nacionais. Os feriados locais que valem na capital (25/01 municipal, 09/07
estadual e 20/11, municipal até 2023 e nacional desde 2024) são acrescentados manualmente.
Feriados "ponte"/pontos facultativos e eventos (jogos, shows) NÃO estão cobertos.
"""
from __future__ import annotations

import json

import pandas as pd

from .. import http
from ..armazenamento import salvar_bruto
from .base import FonteAdapter, ResultadoColeta

URL = "https://brasilapi.com.br/api/feriados/v1/{ano}"
MUNICIPAIS_SP = {"01-25": ("Aniversário da cidade de São Paulo", "municipal"),
                 "07-09": ("Revolução Constitucionalista de 1932", "estadual"),
                 "11-20": ("Dia da Consciência Negra", "municipal")}


class Calendario(FonteAdapter):
    nome = "calendario"

    def coletar(self, anos: list[int]) -> ResultadoColeta:
        linhas, arquivos = [], []
        for ano in anos:
            r = http.get(URL.format(ano=ano), timeout=self.cfg.timeout, tentativas=self.cfg.tentativas,
                         espera=self.cfg.espera)
            payload = r.json()
            arquivos.append(salvar_bruto(self.cfg.data_dir, self.nome, f"feriados_{ano}.json",
                                         json.dumps(payload, ensure_ascii=False).encode("utf-8"), {"ano": ano}))
            for item in payload:
                linhas.append({"data": item["date"], "feriado_nome": item["name"], "tipo": item.get("type", "national")})
            for mmdd, (nome, tipo) in MUNICIPAIS_SP.items():
                linhas.append({"data": f"{ano}-{mmdd}", "feriado_nome": nome, "tipo": tipo})
        df = pd.DataFrame(linhas)
        df["data"] = pd.to_datetime(df["data"])
        self.tabela = df.drop_duplicates("data").sort_values("data").reset_index(drop=True)
        return ResultadoColeta(fonte=self.nome, arquivos=arquivos, n_registros=len(self.tabela))

    @staticmethod
    def flags_diarios(feriados: pd.DataFrame, inicio, fim) -> pd.DataFrame:
        dias = pd.DataFrame({"data": pd.date_range(inicio, fim, freq="D")})
        dias["dia_semana"] = dias["data"].dt.day_of_week
        dias["fim_de_semana"] = (dias["dia_semana"] >= 5).astype(int)
        dias["feriado"] = dias["data"].isin(set(feriados["data"])).astype(int)
        return dias
