"""Garantias básicas contra regressão do cadastro de passageiros."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def source(name):return (ROOT/name).read_text(encoding='utf-8')


def test_backend_separa_pagantes_e_persiste_criancas():
    body=source('app/routers/calculations.py')
    assert 'form.get("adults")' in body
    assert 'form.get("children")' in body
    assert 'group.children = children' in body
    assert 'group_children=group_children' in body


def test_modelo_de_criancas_e_adulto_na_pagina():
    models=source('app/models.py')
    assert 'class QuoteGroup(Base):' in models
    group=models.split('class QuoteGroup(Base):',1)[1].split('\nclass ',1)[0]
    assert 'children: Mapped[int]' in group
    page=source('app/templates/calculations/new.html')
    assert 'id="paxAdults"' in page
    assert 'id="paxChildren"' in page
    assert 'id="paxTotal"' in page
