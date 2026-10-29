"""Camadas de armazenamento: bruto (cópia fiel + manifesto) e tratado (Parquet ou CSV)."""
from __future__ import annotations

import hashlib
import json
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd


def salvar_bruto(data_dir: Path, fonte: str, nome: str, conteudo: bytes, meta: dict | None = None) -> Path:
    """Grava o conteúdo recebido sem alterações e um manifesto .meta.json (RNF06: rastreabilidade)."""
    pasta = Path(data_dir) / "bruto" / fonte
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%dT%H%M%S")
    destino = pasta / f"{carimbo}_{nome}"
    destino.write_bytes(conteudo)
    manifesto = {
        "fonte": fonte, "arquivo": destino.name, "bytes": len(conteudo),
        "sha256": hashlib.sha256(conteudo).hexdigest(),
        "coletado_em": datetime.now().isoformat(timespec="seconds"), **(meta or {}),
    }
    destino.with_name(destino.name + ".meta.json").write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return destino


def salvar_tabela(df: pd.DataFrame, caminho_sem_ext: Path) -> Path:
    """Parquet se o pyarrow estiver instalado; caso contrário CSV (com aviso)."""
    caminho_sem_ext = Path(caminho_sem_ext)
    caminho_sem_ext.parent.mkdir(parents=True, exist_ok=True)
    try:
        import pyarrow  # noqa: F401
        destino = caminho_sem_ext.with_suffix(".parquet")
        df.to_parquet(destino, index=False)
    except ImportError:
        warnings.warn("pyarrow não instalado: gravando CSV no lugar de Parquet.")
        destino = caminho_sem_ext.with_suffix(".csv")
        df.to_csv(destino, index=False)
    return destino


def ler_tabela(caminho: Path) -> pd.DataFrame:
    caminho = Path(caminho)
    if caminho.suffix == ".parquet":
        return pd.read_parquet(caminho)
    return pd.read_csv(caminho)


def achar_tabela(data_dir: Path, nome: str) -> Path | None:
    for ext in (".parquet", ".csv"):
        p = Path(data_dir) / "tratado" / f"{nome}{ext}"
        if p.exists():
            return p
    return None
