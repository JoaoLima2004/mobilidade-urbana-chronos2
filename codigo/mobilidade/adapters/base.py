"""Contrato comum dos adaptadores (padrão Adapter – Seção 5.3 do documento de especificação)."""
from __future__ import annotations

import io
import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..config import Config


@dataclass
class ResultadoColeta:
    fonte: str
    arquivos: list[Path] = field(default_factory=list)
    n_registros: int | None = None
    observacoes: list[str] = field(default_factory=list)


class FonteAdapter(ABC):
    """Cada fonte externa implementa `coletar` (grava o bruto) e `ler` (devolve DataFrame)."""

    nome: str = "fonte"

    def __init__(self, cfg: Config):
        self.cfg = cfg

    @abstractmethod
    def coletar(self, **kwargs) -> ResultadoColeta: ...


def normalizar_nome(s: str) -> str:
    """'Hora do Sinistro' -> 'hora_do_sinistro' (sem acento, minúsculo, com _)."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def ler_csv_robusto(origem: Path | bytes, **kw) -> pd.DataFrame:
    """Lê CSV de portais públicos: tenta UTF-8 e Latin-1, detecta ; ou , como separador."""
    dados = origem if isinstance(origem, bytes) else Path(origem).read_bytes()
    ultimo: Exception | None = None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = dados.decode(enc)
        except UnicodeDecodeError as e:
            ultimo = e
            continue
        amostra = texto[:5000].splitlines()[0] if texto else ""
        sep = ";" if amostra.count(";") >= amostra.count(",") else ","
        return pd.read_csv(io.StringIO(texto), sep=sep, **kw)
    raise ValueError(f"não consegui decodificar o CSV: {ultimo}")


def parece_html(conteudo: bytes) -> bool:
    inicio = conteudo[:300].lstrip().lower()
    return inicio.startswith(b"<!doctype html") or inicio.startswith(b"<html") or b"<html" in inicio
