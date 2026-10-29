"""Clima – Open-Meteo Historical Weather API (sem chave; uso não comercial).

Conferido: endpoint https://archive-api.open-meteo.com/v1/archive com latitude, longitude,
start_date, end_date, hourly e timezone; ~366 dias por requisição; resposta JSON com
hourly.time e uma lista por variável.
NÃO conferido: a defasagem do arquivo para os dias mais recentes (os últimos dias podem vir vazios/nulos).
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

from .. import http
from ..armazenamento import salvar_bruto
from .base import FonteAdapter, ResultadoColeta

URL = "https://archive-api.open-meteo.com/v1/archive"
VARIAVEIS = {"temperature_2m": "temperatura_c", "precipitation": "precipitacao_mm"}


def blocos(inicio: date, fim: date, dias: int = 360):
    atual = inicio
    while atual <= fim:
        ate = min(atual + timedelta(days=dias - 1), fim)
        yield atual, ate
        atual = ate + timedelta(days=1)


def payload_para_df(payload: dict) -> pd.DataFrame:
    h = payload.get("hourly") or {}
    if "time" not in h:
        raise ValueError(f"resposta sem 'hourly.time': chaves = {list(payload)}")
    df = pd.DataFrame({"timestamp": pd.to_datetime(h["time"])})
    for api, nome in VARIAVEIS.items():
        df[nome] = h.get(api)
    return df


class OpenMeteo(FonteAdapter):
    nome = "openmeteo"

    def coletar(self, inicio: date, fim: date) -> ResultadoColeta:
        res = ResultadoColeta(fonte=self.nome, n_registros=0)
        quadros = []
        for a, b in blocos(inicio, fim):
            r = http.get(URL, params={
                "latitude": self.cfg.lat, "longitude": self.cfg.lon, "start_date": a.isoformat(),
                "end_date": b.isoformat(), "hourly": ",".join(VARIAVEIS), "timezone": "America/Sao_Paulo",
            }, timeout=self.cfg.timeout, tentativas=self.cfg.tentativas, espera=self.cfg.espera)
            payload = r.json()
            res.arquivos.append(salvar_bruto(self.cfg.data_dir, self.nome, f"clima_{a}_{b}.json",
                                             json.dumps(payload).encode(), {"lat": self.cfg.lat, "lon": self.cfg.lon}))
            quadros.append(payload_para_df(payload))
        self.tabela = pd.concat(quadros, ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
        res.n_registros = len(self.tabela)
        nulos = int(self.tabela["precipitacao_mm"].isna().sum())
        if nulos:
            res.observacoes.append(f"{nulos} horas sem precipitação (provável defasagem do arquivo nos dias mais recentes).")
        return res
