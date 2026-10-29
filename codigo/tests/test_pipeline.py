"""Testes com respostas SIMULADAS (não acessam a internet). Rodar: python -m unittest -v"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

from mobilidade import http
from mobilidade.adapters.calendario import Calendario
from mobilidade.adapters.cet_api import CetLentidaoApi, extrair_registros
from mobilidade.adapters.cet_csv import CetLentidaoCsv
from mobilidade.adapters.infosiga import Infosiga
from mobilidade.adapters.openmeteo import OpenMeteo, blocos
from mobilidade.config import Config
from mobilidade.registro import RegistroExecucao, ultimas
from mobilidade.series import anexar_covariaveis, construir_series


class Resp:
    def __init__(self, payload=None, status=200, content=b""):
        self._p, self.status_code, self.content = payload, status, content

    def json(self):
        return self._p


def cfg(tmp, token="tok"):
    return Config(data_dir=Path(tmp), apilib_token=token, apilib_base_url="https://gw/cet/lentidao/v1",
                  infosiga_url=None, lat=-23.55, lon=-46.63, espera=0)


class TestCetApi(unittest.TestCase):
    def test_extrair_registros_formatos(self):
        self.assertEqual(extrair_registros([{"a": 1}]), [{"a": 1}])
        self.assertEqual(extrair_registros({"result": {"records": [{"a": 1}], "total": 1}}), [{"a": 1}])
        self.assertEqual(extrair_registros({"x": {"y": [{"a": 2}]}}), [{"a": 2}])
        self.assertEqual(extrair_registros({"sem": "lista"}), [])

    def test_paginacao_e_cabecalho(self):
        paginas = [[{"i": 1}, {"i": 2}], [{"i": 3}], []]
        chamadas = []

        def falso_get(url, params=None, headers=None, **kw):
            chamadas.append((url, dict(params), headers))
            return Resp(paginas[len(chamadas) - 1])

        with tempfile.TemporaryDirectory() as t, mock.patch("mobilidade.http.get", falso_get):
            res = CetLentidaoApi(cfg(t)).coletar([2018], limite=2)
            self.assertEqual(res.n_registros, 3)
            self.assertEqual([c[1]["offset"] for c in chamadas], [0, 2, 3])
            self.assertEqual(chamadas[0][0], "https://gw/cet/lentidao/v1/2018")
            self.assertEqual(chamadas[0][2]["Authorization"], "Bearer tok")
            self.assertEqual(len(CetLentidaoApi.ler(res.arquivos[0])), 3)
            self.assertTrue(res.arquivos[0].with_name(res.arquivos[0].name + ".meta.json").exists())

    def test_servidor_que_ignora_offset_nao_entra_em_loop(self):
        with tempfile.TemporaryDirectory() as t, mock.patch("mobilidade.http.get", lambda *a, **k: Resp([{"i": 1}])):
            res = CetLentidaoApi(cfg(t)).coletar([2018], limite=1)
            self.assertEqual(res.n_registros, 1)
            self.assertTrue(any("repetiu" in o for o in res.observacoes))

    def test_sem_token_e_ano_fora_do_periodo(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(http.FonteIndisponivel):
                CetLentidaoApi(cfg(t, token=None)).coletar([2018])
            res = CetLentidaoApi(cfg(t)).coletar([2023])
            self.assertEqual(res.n_registros, 0)
            self.assertIn("fora do período", res.observacoes[0])


class TestHttp(unittest.TestCase):
    def test_401_nao_repete_e_500_repete(self):
        with mock.patch("requests.get", return_value=Resp(status=401)) as g:
            with self.assertRaises(http.FonteIndisponivel):
                http.get("u", espera=0)
            self.assertEqual(g.call_count, 1)
        with mock.patch("requests.get", return_value=Resp(status=503)) as g:
            with self.assertRaises(http.FonteIndisponivel):
                http.get("u", tentativas=3, espera=0)
            self.assertEqual(g.call_count, 3)


class TestCsv(unittest.TestCase):
    def test_csv_latin1_ponto_e_virgula(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "l.csv"
            p.write_bytes("data;hora;trecho;lentidão\n01/02/2023;7;Marginal;3,5\n".encode("latin-1"))
            res = CetLentidaoCsv(cfg(t)).coletar(str(p))
            df = CetLentidaoCsv.ler(res.arquivos[0])
            self.assertEqual(list(df.columns), ["data", "hora", "trecho", "lentidão"])
            self.assertEqual(res.n_registros, 1)

    def test_html_de_captcha_e_rejeitado(self):
        html = b"<!DOCTYPE html><html><body>captcha</body></html>"
        with tempfile.TemporaryDirectory() as t, mock.patch("mobilidade.http.get", return_value=Resp(content=html)):
            with self.assertRaises(http.FonteIndisponivel):
                CetLentidaoCsv(cfg(t)).coletar("https://dados.prefeitura.sp.gov.br/x.csv")


class TestInfosiga(unittest.TestCase):
    def test_zip_filtra_sao_paulo_e_conta_por_dia(self):
        import zipfile
        csv = "Data Sinistro;Município;Latitude\n01/03/2024;SÃO PAULO;-23.5\n01/03/2024;São Paulo;-23.6\n02/03/2024;CAMPINAS;-22.9\n"
        with tempfile.TemporaryDirectory() as t:
            z = Path(t) / "dados_infosiga.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("sinistros_2022-2025.csv", csv.encode("latin-1"))
            df = Infosiga.ler_sinistros(z)
            self.assertEqual(len(df), 2)
            cont = Infosiga.contagem_diaria(df)
            self.assertEqual(int(cont["sinistros"].iloc[0]), 2)


class TestClimaCalendario(unittest.TestCase):
    def test_blocos_cobrem_o_intervalo(self):
        b = list(blocos(date(2023, 1, 1), date(2024, 12, 31)))
        self.assertEqual(b[0][0], date(2023, 1, 1))
        self.assertEqual(b[-1][1], date(2024, 12, 31))
        self.assertTrue(all((y - x).days < 366 for x, y in b))

    def test_openmeteo_parse(self):
        payload = {"hourly": {"time": ["2023-01-01T00:00", "2023-01-01T01:00"],
                              "temperature_2m": [20.1, 19.8], "precipitation": [0.0, None]}}
        with tempfile.TemporaryDirectory() as t, mock.patch("mobilidade.http.get", return_value=Resp(payload)):
            ad = OpenMeteo(cfg(t))
            res = ad.coletar(date(2023, 1, 1), date(2023, 1, 1))
            self.assertEqual(list(ad.tabela.columns), ["timestamp", "temperatura_c", "precipitacao_mm"])
            self.assertEqual(res.n_registros, 2)
            self.assertTrue(res.observacoes)  # avisa sobre a hora sem precipitação

    def test_calendario(self):
        itens = [{"date": "2024-01-01", "name": "Confraternização", "type": "national"}]
        with tempfile.TemporaryDirectory() as t, mock.patch("mobilidade.http.get", return_value=Resp(itens)):
            ad = Calendario(cfg(t))
            ad.coletar([2024])
            self.assertIn(pd.Timestamp("2024-01-25"), set(ad.tabela["data"]))  # municipal SP
            flags = ad.flags_diarios(ad.tabela, "2024-01-01", "2024-01-07")
            self.assertEqual(int(flags.loc[flags.data == "2024-01-01", "feriado"].iloc[0]), 1)
            self.assertEqual(int(flags.loc[flags.data == "2024-01-06", "fim_de_semana"].iloc[0]), 1)


class TestSeries(unittest.TestCase):
    def test_data_mais_hora_agregacao_e_qualidade(self):
        df = pd.DataFrame({
            "data": ["01/03/2024"] * 4 + ["xx"], "hora": ["7", "7", "8:30", "9", "9"],
            "trecho": ["A", "A", "A", "A", "A"], "km": ["2", "4", "5", "-1", "3"]})
        s, q = construir_series(df, col_serie="trecho", col_alvo="km", col_data="data", col_hora="hora")
        self.assertEqual(q["timestamps_invalidos"], 1)
        self.assertEqual(q["indicador_negativo"], 1)
        self.assertEqual(q["duplicados_serie_timestamp"], 1)
        # 07h: média(2,4)=3 ; 08h: 5 ; 09h: descartada (negativa) -> grade 07..08
        self.assertEqual(list(s["target"]), [3.0, 5.0])

    def test_grade_regular_com_lacuna_e_covariaveis(self):
        df = pd.DataFrame({"ts": ["2024-03-01 00:00", "2024-03-01 03:00"], "s": ["A", "A"], "y": [1, 2]})
        s, q = construir_series(df, col_serie="s", col_alvo="y", col_ts="ts")
        self.assertEqual(len(s), 4)
        self.assertEqual(int(s["target"].isna().sum()), 2)
        clima = pd.DataFrame({"timestamp": s["timestamp"], "temperatura_c": 20.0})
        cal = pd.DataFrame({"data": pd.date_range("2024-03-01", periods=1), "feriado": 0, "fim_de_semana": 0})
        f = anexar_covariaveis(s, clima, cal)
        self.assertTrue({"hora", "dia_semana", "temperatura_c", "feriado"} <= set(f.columns))
        self.assertEqual(len(f), 4)


    def test_base_de_eventos_ausente_como_zero(self):
        # dois trechos lentos do mesmo corredor|sentido às 07:00 (somam), um às 07:30, nada às 08:00/08:30
        df = pd.DataFrame({
            "data": ["02/01/2023 07:00", "02/01/2023 07:00", "02/01/2023 07:30", "02/01/2023 08:30"],
            "corredor": ["X", "X", "X", "Y"], "sentido": ["A/B", "A/B", "A/B", "C/D"],
            "tamanho": [1000, 500, 1000, 200]})
        s, q = construir_series(df, col_serie=["corredor", "sentido"], col_alvo="tamanho", col_ts="data",
                                ausente_como_zero=True, freq_coleta="30min", fator=0.001)
        x = s[s.series_id == "X | A/B"].set_index("timestamp")["target"]
        self.assertEqual(x.index[0], pd.Timestamp("2023-01-02 00:00"))  # grade começa no início do dia
        self.assertAlmostEqual(x[pd.Timestamp("2023-01-02 07:00")], (1.5 + 1.0) / 2)  # média das meias-horas
        self.assertEqual(x[pd.Timestamp("2023-01-02 08:00")], 0.0)
        self.assertEqual(int(s["target"].isna().sum()), 0)
        self.assertTrue(q["ausente_como_zero"])

    def test_selecao_por_dias_uteis(self):
        dias = pd.date_range("2023-01-02", "2023-01-06")  # seg-sex
        df = pd.DataFrame({"ts": list(dias) + [dias[0]], "s": ["A"] * 5 + ["B"], "y": 1})
        s, q = construir_series(df, col_serie="s", col_alvo="y", col_ts="ts", min_frac_dias_uteis=0.5)
        self.assertEqual(set(s["series_id"]), {"A"})
        self.assertEqual(q["selecao"]["series_mantidas"], 1)


class TestNumeros(unittest.TestCase):
    def test_virgula_decimal_e_milhar(self):
        from mobilidade.validacao import para_numero
        r = para_numero(pd.Series(["3,5", "1.234,5", "7", " 2,25 ", "abc"]))
        self.assertEqual(list(r.iloc[:4]), [3.5, 1234.5, 7.0, 2.25])
        self.assertTrue(pd.isna(r.iloc[4]))


class TestRegistro(unittest.TestCase):
    def test_log_ok_e_erro(self):
        with tempfile.TemporaryDirectory() as t:
            with RegistroExecucao(Path(t), "coleta", "x") as r:
                r.n_registros = 5
            with self.assertRaises(RuntimeError):
                with RegistroExecucao(Path(t), "coleta", "y"):
                    raise RuntimeError("falhou")
            e = ultimas(Path(t))
            self.assertEqual([x["status"] for x in e], ["ok", "erro"])
            self.assertEqual(e[1]["mensagem"], "falhou")


if __name__ == "__main__":
    unittest.main()
