"""Testes do experimento de previsão (sem o Chronos-2). Rodar: python -m unittest -v"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

_spec = importlib.util.spec_from_file_location(
    "experimento_previsao", Path(__file__).resolve().parents[1] / "experimento" / "experimento_previsao.py")
exp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = exp  # o @dataclass do módulo consulta sys.modules
_spec.loader.exec_module(exp)


class TestBaselines(unittest.TestCase):
    def test_seasonal_naive_repete_ultimo_ciclo(self):
        h = np.array([1, 2, 3, 4, 5, 6], dtype=float)
        np.testing.assert_array_equal(exp.seasonal_naive(h, 5, 3), [4, 5, 6, 4, 5])
        np.testing.assert_array_equal(exp.seasonal_naive(h[:2], 3, 3), [2, 2, 2])  # histórico curto -> ingênuo

    def test_naive(self):
        np.testing.assert_array_equal(exp.naive(np.array([3.0, 7.0]), 3), [7, 7, 7])


class TestMetricas(unittest.TestCase):
    def test_mae_e_mase(self):
        y, yhat = np.array([1.0, 2.0]), np.array([2.0, 4.0])
        self.assertAlmostEqual(exp.mae(y, yhat), 1.5)
        hist = np.array([0, 1, 0, 3], dtype=float)  # |h[2:]-h[:-2]| = [0, 2] -> escala 1
        self.assertAlmostEqual(exp.mase(y, yhat, hist, 2), 1.5)

    def test_mase_indefinido(self):
        self.assertTrue(np.isnan(exp.mase(np.ones(2), np.ones(2), np.ones(10), 2)))  # escala zero
        self.assertTrue(np.isnan(exp.mase(np.ones(2), np.ones(2), np.ones(2), 2)))   # histórico curto


class TestJanelas(unittest.TestCase):
    def test_origens_sem_sobreposicao_ate_o_fim(self):
        o = exp.rolling_origins(n=500, horizon=24, n_windows=14, stride=24)
        self.assertEqual(len(o), 14)
        self.assertEqual(o[-1], 500 - 24)
        self.assertTrue(all(b - a == 24 for a, b in zip(o, o[1:])))


class TestFluxoCompleto(unittest.TestCase):
    def test_demo_sem_chronos(self):
        with tempfile.TemporaryDirectory() as t:
            exp.main(["--demo", "--skip-chronos", "--output", t, "--n-windows", "3"])
            out = Path(t)
            resumo = pd.read_csv(out / "resumo_modelos.csv")
            self.assertEqual(len(resumo), 3)
            self.assertIn("pct_series_vence_SN_diario", resumo.columns)
            janelas = pd.read_csv(out / "metricas_por_janela.csv")
            self.assertEqual(janelas["janela"].nunique(), 3)
            meta = json.loads((out / "execucao.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["dados_sinteticos"])
            for f in ("fig_mase_por_modelo.png", "fig_mae_por_passo.png", "fig_exemplo_previsao.png", "previsoes.csv"):
                self.assertTrue((out / f).exists(), f)


if __name__ == "__main__":
    unittest.main()
