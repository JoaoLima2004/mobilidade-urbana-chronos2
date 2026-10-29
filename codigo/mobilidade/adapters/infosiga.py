"""Infosiga-SP (DETRAN-SP) – sinistros de trânsito.

Conferido na documentação do pacote infosigasp: dados sob CC BY 4.0; arquivo consolidado
'dados_infosiga.zip' (~120 MB; >700 MB descompactado), atualizado mensalmente, com três tabelas
(sinistros, pessoas, veiculos); a tabela de sinistros traz latitude/longitude e município.
NÃO conferido: o link direto do arquivo (informe em INFOSIGA_URL, copiado do portal
dadosabertos.sp.gov.br) e os nomes exatos das colunas – por isso a busca por candidatos abaixo.
Uso previsto: covariável diária e fator de criticidade (a atualização é mensal, não serve ao horário).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pandas as pd

from .. import http
from ..armazenamento import salvar_bruto
from .base import FonteAdapter, ResultadoColeta, ler_csv_robusto, normalizar_nome, parece_html

CANDIDATAS = {
    "data": ["data_sinistro", "data", "data_do_sinistro", "dt_sinistro"],
    "hora": ["hora_sinistro", "hora", "hora_do_sinistro"],
    "municipio": ["municipio", "nome_municipio", "cidade"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lon", "long"],
}


def achar_coluna(df: pd.DataFrame, chave: str) -> str | None:
    cols = {normalizar_nome(c): c for c in df.columns}
    for cand in CANDIDATAS[chave]:
        if cand in cols:
            return cols[cand]
    return None


class Infosiga(FonteAdapter):
    nome = "infosiga"

    def coletar(self, origem: str | None = None) -> ResultadoColeta:
        origem = origem or self.cfg.infosiga_url
        if not origem:
            raise http.FonteIndisponivel("informe --origem ou INFOSIGA_URL (link do arquivo no portal de dados abertos).")
        if origem.lower().startswith(("http://", "https://")):
            r = http.get(origem, timeout=max(self.cfg.timeout, 600), tentativas=self.cfg.tentativas, espera=self.cfg.espera)
            conteudo, nome = r.content, origem.rstrip("/").split("/")[-1] or "infosiga.zip"
        else:
            p = Path(origem)
            conteudo, nome = p.read_bytes(), p.name
        if parece_html(conteudo):
            raise http.FonteIndisponivel("a origem devolveu HTML, não o arquivo de dados.")
        destino = salvar_bruto(self.cfg.data_dir, self.nome, nome, conteudo, {"origem": origem})
        return ResultadoColeta(fonte=self.nome, arquivos=[destino])

    @staticmethod
    def ler_sinistros(caminho, apenas_sao_paulo: bool = True) -> pd.DataFrame:
        """Lê a(s) tabela(s) de sinistros de um .zip (ou de um .csv) e filtra o município de São Paulo."""
        caminho = Path(caminho)
        if caminho.suffix.lower() == ".zip":
            partes = []
            with zipfile.ZipFile(caminho) as z:
                for nome in z.namelist():
                    if "sinistro" in nome.lower() and nome.lower().endswith(".csv"):
                        partes.append(ler_csv_robusto(z.read(nome), low_memory=False))
            if not partes:
                raise ValueError("nenhum CSV de sinistros encontrado no zip; confira os nomes dos arquivos.")
            df = pd.concat(partes, ignore_index=True)
        else:
            df = ler_csv_robusto(caminho, low_memory=False)
        if apenas_sao_paulo:
            col = achar_coluna(df, "municipio")
            if col is None:
                raise ValueError(f"coluna de município não encontrada; colunas: {list(df.columns)[:30]}")
            df = df[df[col].map(normalizar_nome) == "sao_paulo"]
        return df.reset_index(drop=True)

    @staticmethod
    def contagem_diaria(df: pd.DataFrame) -> pd.DataFrame:
        col = achar_coluna(df, "data")
        if col is None:
            raise ValueError(f"coluna de data não encontrada; colunas: {list(df.columns)[:30]}")
        datas = pd.to_datetime(df[col], errors="coerce", dayfirst=True).dt.normalize()
        out = datas.value_counts().sort_index().rename_axis("data").reset_index(name="sinistros")
        return out
