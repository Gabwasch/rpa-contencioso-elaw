import random

import pytest

from elaw import cnj


def test_numero_gerado_tem_digitos_verificadores_validos():
    rng = random.Random(42)
    for _ in range(200):
        n = cnj.gerar(rng.randint(0, 9_999_999), rng.randint(1990, 2030), rng.randint(1, 9),
                      rng.randint(1, 27), rng.randint(0, 9999))
        assert cnj.validar(n), n


def test_formula_mod97_confere_com_o_calculo_manual():
    # DD = 98 - (NNNNNNN AAAA J TR OOOO 00 mod 97)
    seq, ano, j, tr, origem = "1234567", "2026", "8", "26", "0001"
    esperado = 98 - int(seq + ano + j + tr + origem + "00") % 97
    assert cnj.digitos_verificadores(seq, ano, j, tr, origem) == f"{esperado:02d}"
    assert int(seq + ano + j + tr + origem + f"{esperado:02d}") % 97 == 1   # propriedade ISO 7064


def test_digito_trocado_invalida_o_numero():
    n = cnj.gerar(9_123_456, 2026, 8, 21, 42)
    d = cnj.so_digitos(n)
    trocado = d[:3] + str((int(d[3]) + 1) % 10) + d[4:]
    assert not cnj.validar(trocado)
    assert not cnj.validar("123")


def test_formatar_e_extrair_do_nome_de_arquivo():
    n = cnj.gerar(9_000_001, 2026, 8, 16, 1234)
    assert cnj.formatar(cnj.so_digitos(n)) == n
    assert cnj.extrair(f"Contestação - {n}.pdf") == n
    assert cnj.extrair(f"peca_{cnj.so_digitos(n)}_final.pdf") == n      # 20 dígitos colados
    assert cnj.extrair("sem número nenhum") is None
    with pytest.raises(ValueError):
        cnj.formatar("1234")


def test_mesmo_processo_ignora_pontuacao():
    n = cnj.gerar(9_555_000, 2026, 8, 13, 7)
    assert cnj.mesmo_processo(n, cnj.so_digitos(n))
    assert not cnj.mesmo_processo(n, cnj.gerar(9_555_001, 2026, 8, 13, 7))
    assert not cnj.mesmo_processo(n, None)
