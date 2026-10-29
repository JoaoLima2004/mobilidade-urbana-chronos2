"""CET – arquivos anuais 'lentidao_trechos_AAAA.csv' do Portal de Dados Abertos da Prefeitura.

Conferido: existe um recurso CSV de 2023 (≈17 MiB, atualizado em 05/03/2024) no conjunto
'Base de dados sobre lentidão por trechos – CET'. O portal exibiu um desafio CAPTCHA ao acesso
automatizado; se o download por URL falhar, baixe pelo navegador e passe o caminho local.
NÃO conferido: nomes das colunas e granularidade temporal – use o comando `inspecionar`.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .. import http
from ..armazenamento import salvar_bruto
from .base import FonteAdapter, ResultadoColeta, ler_csv_robusto, parece_html


class CetLentidaoCsv(FonteAdapter):
    nome = "cet_lentidao_csv"

    def coletar(self, origem: str) -> ResultadoColeta:
        """`origem` = caminho local ou URL do CSV."""
        if origem.lower().startswith(("http://", "https://")):
            r = http.get(origem, timeout=self.cfg.timeout, tentativas=self.cfg.tentativas, espera=self.cfg.espera)
            conteudo = r.content
            if parece_html(conteudo):
                raise http.FonteIndisponivel(
                    "o portal devolveu uma página HTML (provável desafio CAPTCHA). Baixe o CSV pelo navegador "
                    "e rode novamente com o caminho do arquivo local.")
            nome = origem.rstrip("/").split("/")[-1] or "lentidao.csv"
        else:
            p = Path(origem)
            if not p.exists():
                raise FileNotFoundError(f"arquivo não encontrado: {p}")
            conteudo, nome = p.read_bytes(), p.name
            if parece_html(conteudo):
                raise ValueError("o arquivo parece HTML, não CSV (download interrompido por CAPTCHA?).")
        df = ler_csv_robusto(conteudo)
        destino = salvar_bruto(self.cfg.data_dir, self.nome, nome, conteudo,
                               {"origem": origem, "n_registros": len(df), "colunas": list(df.columns)})
        return ResultadoColeta(fonte=self.nome, arquivos=[destino], n_registros=len(df))

    @staticmethod
    def ler(caminho) -> pd.DataFrame:
        return ler_csv_robusto(Path(caminho))
