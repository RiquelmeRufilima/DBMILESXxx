from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import AIRLINE_IMAGE_DIR, AIRLINE_UPLOAD_DIR, BASE_DIR
from ..models import Airline, CalculationField, CalculationType
from .travel_data import AIRLINE_OPTIONS


BUILTINS = [
    {
        "name": "LATAM Airlines",
        "slug": "latam",
        "legacy_code": "latam",
        "color": "#5E010D",
        "logo": "latam.png",
        "types": [
            {
                "name": "Milhas LATAM Pass",
                "slug": "latam-milhas",
                "legacy_key": "latam_milhas",
                "description": "Milhas e taxa por passageiro, exatamente como no sistema atual.",
                "fields": [
                    ("milhas", "Milhas necessárias por passageiro", "number", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "number", "0", 0, None, 0.01, None),
                    ("taxa", "Taxa de embarque por passageiro", "number", "0", 0, None, 0.01, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "number", "140", 0, None, 1, None),
                ],
            }
        ],
    },
    {
        "name": "GOL Linhas Aéreas",
        "slug": "gol",
        "legacy_code": "gol",
        "color": "#FF6B00",
        "logo": "gol.png",
        "types": [
            {
                "name": "Smiles (Milhas)",
                "slug": "gol-smiles",
                "legacy_key": "gol_smiles",
                "description": "Milhas e taxa informadas como total, sem multiplicar por passageiros.",
                "fields": [
                    ("milhas", "Milhas Smiles necessárias", "number", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "number", "0", 0, None, 0.01, None),
                    ("taxa", "Taxa de embarque", "number", "0", 0, None, 0.01, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "number", "175", 0, None, 1, None),
                ],
            },
            {
                "name": "Deságio",
                "slug": "gol-desagio",
                "legacy_key": "gol_desagio",
                "description": "Valor cheio menos o percentual de deságio.",
                "fields": [
                    ("valor_gol", "Valor cheio da passagem", "number", "0", 0, None, 0.01, None),
                    ("desagio", "Percentual de deságio", "percent", "0", 0, 100, 1, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "number", "175", 0, None, 1, None),
                ],
            },
        ],
    },
    {
        "name": "Azul Linhas Aéreas",
        "slug": "azul",
        "legacy_code": "azul",
        "color": "#00B0FF",
        "logo": "azul.png",
        "types": [
            {
                "name": "Pontos TudoAzul",
                "slug": "azul-pontos",
                "legacy_key": "azul_pontos",
                "description": "Pontos em milheiros + taxa, como no sistema atual.",
                "fields": [
                    ("milhas", "Pontos/Milhas totais em milheiros", "number", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "number", "0", 0, None, 0.01, None),
                    ("taxa", "Taxa de embarque", "number", "0", 0, None, 0.01, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "number", "175", 0, None, 1, None),
                ],
            },
            {
                "name": "Pontos + Dinheiro",
                "slug": "azul-pontos-dinheiro",
                "legacy_key": "azul_pontos_dinheiro",
                "description": "Mantém a regra atual de desconto, impostos e taxa de resgate por pax/trecho.",
                "fields": [
                    ("milhas", "Pontos/Milhas totais em milheiros", "number", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "number", "0", 0, None, 0.01, None),
                    ("valor_dinheiro", "Valor em dinheiro", "number", "0", 0, None, 0.01, None),
                    ("desconto_taxa", "Desconto no valor em dinheiro (%)", "percent", "10", 0, 100, 1, None),
                    ("taxas_impostos", "Taxas e impostos", "number", "0", 0, None, 0.01, None),
                    ("taxa_resgate_por_pax_trecho", "Taxa de resgate por pax/trecho", "number", "60", 0, None, 1, None),
                    ("numero_trechos", "Número de trechos", "integer", "1", 1, 20, 1, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "number", "175", 0, None, 1, None),
                ],
            },
        ],
    },
    {
        "name": "American Airlines",
        "slug": "american",
        "legacy_code": "american",
        "color": "#002D72",
        "logo": "american.png",
        "types": [
            {
                "name": "Milhas AAdvantage",
                "slug": "american-milhas",
                "legacy_key": "american_milhas",
                "description": "Milhas + taxa como total. A rota define o valor padrão da bagagem.",
                "fields": [
                    ("milhas", "Milhas AAdvantage necessárias", "number", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "number", "0", 0, None, 0.01, None),
                    ("taxa", "Taxa de embarque", "number", "0", 0, None, 0.01, None),
                    (
                        "rota_american",
                        "Tipo de rota",
                        "select",
                        "Brasil ↔ EUA",
                        None,
                        None,
                        None,
                        [
                            "Brasil ↔ EUA",
                            "EUA / Canadá / Caribe / México",
                            "América do Sul ↔ EUA",
                            "EUA ↔ Panamá / Colômbia / Peru / Equador",
                        ],
                    ),
                ],
            }
        ],
    },
    {
        "name": "Azul Pelo Mundo",
        "slug": "azulpelomundo",
        "legacy_code": "azulpelomundo",
        "color": "#0059FF",
        "logo": "azulpelomundo.png",
        "types": [
            {
                "name": "Pontos VoeAzul",
                "slug": "azulpelomundo-pontos",
                "legacy_key": "azulpelomundo_pontos",
                "description": "Pontos em milheiros + taxa, como no sistema atual.",
                "fields": [
                    ("milhas", "Pontos/Milhas totais em milheiros", "number", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "number", "0", 0, None, 0.01, None),
                    ("taxa", "Taxa de embarque", "number", "0", 0, None, 0.01, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "number", "175", 0, None, 1, None),
                ],
            },
            {
                "name": "Pontos + Dinheiro",
                "slug": "azulpelomundo-pontos-dinheiro",
                "legacy_key": "azulpelomundo_pontos_dinheiro",
                "description": "Mantém a regra atual de desconto, impostos e taxa de resgate por pax/trecho.",
                "fields": [
                    ("milhas", "Pontos/Milhas totais em milheiros", "number", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "number", "0", 0, None, 0.01, None),
                    ("valor_dinheiro", "Valor em dinheiro", "number", "0", 0, None, 0.01, None),
                    ("desconto_taxa", "Desconto no valor em dinheiro (%)", "percent", "10", 0, 100, 1, None),
                    ("taxas_impostos", "Taxas e impostos", "number", "0", 0, None, 0.01, None),
                    ("taxa_resgate_por_pax_trecho", "Taxa de resgate por pax/trecho", "number", "60", 0, None, 1, None),
                    ("numero_trechos", "Número de trechos", "integer", "1", 1, 20, 1, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "number", "175", 0, None, 1, None),
                ],
            },
        ],
    },
]


LOGO_FILENAME_ALIASES = {
    "gol.png": "gol2.png",
    "panamair.png": "paranair.png",
    "taag.png": "taag.jpg",
}


def _image_asset(filename: str) -> Path | None:
    """Localiza o logo oficial dentro de app/imagens.

    A pasta de imagens passa a ser a fonte principal das companhias. Mantemos
    aliases para arquivos cujo nome real difere do slug usado no cadastro.
    """
    names = [filename]
    alias = LOGO_FILENAME_ALIASES.get(filename)
    if alias:
        names.append(alias)
    for name in names:
        source = AIRLINE_IMAGE_DIR / name
        if source.exists() and source.is_file():
            return source
    return None


def _copy_logo(filename: str) -> str | None:
    source = _image_asset(filename)
    if source is not None:
        return f"imagens/{source.name}"

    # Compatibilidade com logos enviados manualmente em versões antigas.
    target = AIRLINE_UPLOAD_DIR / filename
    if target.exists():
        return str(target.relative_to(BASE_DIR)).replace("\\", "/")

    candidates = [BASE_DIR / filename, BASE_DIR.parent / filename]
    for source in candidates:
        if source.exists():
            target.write_bytes(source.read_bytes())
            return str(target.relative_to(BASE_DIR)).replace("\\", "/")
    return None


def _generic_airline_builtin(item: dict[str, str]) -> dict:
    slug = item["slug"]
    return {
        "name": item["name"], "slug": slug, "legacy_code": None, "color": "#26c5e6", "logo": item.get("logo") or f"{slug}.png",
        "types": [{
            "name": "Cálculo padrão", "slug": f"{slug}-padrao", "legacy_key": None,
            "description": "Regra genérica editável: (milhas * milheiro) + taxa. Pode ser usada como base para cotações manuais.",
            "fields": [
                ("milhas", "Milhas/pontos", "number", "0", 0, None, 0.001, None),
                ("milheiro", "Valor do milheiro", "number", "0", 0, None, 0.01, None),
                ("taxa", "Taxa", "number", "0", 0, None, 0.01, None),
                ("bagagem_unitaria", "Bagagem adicional por unidade", "number", "0", 0, None, 1, None),
            ],
        }],
    }

def _builtin_market_scope(slug: str) -> str:
    """Perfil inicial editável das companhias padrão.

    O valor descreve em que tipo de operação a companhia costuma ser usada no
    sistema, não a nacionalidade jurídica dela. Administradores podem alterar
    isso depois na tela da companhia.
    """
    token = str(slug or "").strip().lower()
    if token in {"azul", "gol", "latam"}:
        return "both"
    if token in {"voepass"}:
        return "national"
    return "international"


EXTRA_BUILTINS = []
_existing_slugs = {item["slug"] for item in BUILTINS}
for _item in AIRLINE_OPTIONS:
    if _item["slug"] not in _existing_slugs:
        EXTRA_BUILTINS.append(_generic_airline_builtin(_item))


def seed_builtin_airlines(db: Session) -> None:
    for item in BUILTINS + EXTRA_BUILTINS:
        airline = db.scalar(select(Airline).where(Airline.slug == item["slug"], Airline.builtin.is_(True)))
        if airline is None:
            airline = Airline(
                name=item["name"],
                slug=item["slug"],
                color=item["color"],
                engine_type="legacy",
                legacy_code=item["legacy_code"],
                market_scope=_builtin_market_scope(item["slug"]),
                partner_airlines_json="[]",
                builtin=True,
                active=True,
                logo_path=_copy_logo(item["logo"]),
            )
            db.add(airline)
            db.flush()
        else:
            # Não sobrescreve uma identidade visual ou perfil operacional que
            # o administrador já editou.
            if str(getattr(airline, "market_scope", "") or "") not in {"national", "international", "both"}:
                airline.market_scope = _builtin_market_scope(item["slug"])
            if not getattr(airline, "partner_airlines_json", None):
                airline.partner_airlines_json = "[]"
            if not airline.logo_path:
                resolved_logo = _copy_logo(item["logo"])
                if resolved_logo:
                    airline.logo_path = resolved_logo

        existing_types = {calc.slug: calc for calc in airline.calculation_types}
        for index, type_item in enumerate(item["types"]):
            calc_type = existing_types.get(type_item["slug"])
            if calc_type is None:
                calc_type = CalculationType(
                    airline_id=airline.id,
                    name=type_item["name"],
                    slug=type_item["slug"],
                    description=type_item["description"],
                    formula="(milhas * milheiro) + taxa",
                    apply_mode="total",
                    legacy_key=type_item["legacy_key"],
                    active=True,
                    is_default=index == 0,
                )
                db.add(calc_type)
                db.flush()

            if not calc_type.fields:
                for field_index, field_data in enumerate(type_item["fields"]):
                    key, label, field_type, default, min_value, max_value, step, options = field_data
                    db.add(
                        CalculationField(
                            calculation_type_id=calc_type.id,
                            key=key,
                            label=label,
                            field_type=field_type,
                            default_value=str(default) if default is not None else None,
                            required=False,
                            min_value=min_value,
                            max_value=max_value,
                            step=step,
                            options_json=json.dumps(options, ensure_ascii=False) if options else None,
                            order_index=field_index,
                        )
                    )
    db.commit()
