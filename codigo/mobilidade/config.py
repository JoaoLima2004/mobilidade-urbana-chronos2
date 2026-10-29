"""Configuração lida de variáveis de ambiente (nenhuma credencial no código – RNF03)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    data_dir: Path
    apilib_token: str | None
    apilib_base_url: str
    infosiga_url: str | None
    lat: float
    lon: float
    timeout: int = 60
    tentativas: int = 3
    espera: float = 2.0  # segundos; dobra a cada tentativa

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            data_dir=Path(os.getenv("MOB_DATA_DIR", "dados")),
            apilib_token=os.getenv("APILIB_TOKEN") or None,
            apilib_base_url=os.getenv(
                "APILIB_BASE_URL", "https://gateway.apilib.prefeitura.sp.gov.br/cet/lentidao/v1"
            ).rstrip("/"),
            infosiga_url=os.getenv("INFOSIGA_URL") or None,
            lat=float(os.getenv("MOB_LAT", "-23.5505")),
            lon=float(os.getenv("MOB_LON", "-46.6333")),
        )
