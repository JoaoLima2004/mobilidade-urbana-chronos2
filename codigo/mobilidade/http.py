"""Cliente HTTP com repetição e erro único (FonteIndisponivel) – RNF04."""
from __future__ import annotations

import time

import requests


class FonteIndisponivel(Exception):
    """A fonte externa não respondeu ou recusou o acesso."""


def get(url, *, params=None, headers=None, timeout=60, tentativas=3, espera=2.0):
    ultimo: Exception | None = None
    for i in range(tentativas):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as e:  # rede/timeout
            ultimo = e
        else:
            if r.status_code in (401, 403):
                raise FonteIndisponivel(f"acesso negado ({r.status_code}) em {url}; confira o token/credenciais")
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = RuntimeError(f"HTTP {r.status_code}")
            elif r.status_code >= 400:
                raise FonteIndisponivel(f"HTTP {r.status_code} em {url}")
            else:
                return r
        if i < tentativas - 1:
            time.sleep(espera * (2 ** i))
    raise FonteIndisponivel(f"{url}: {ultimo}")
