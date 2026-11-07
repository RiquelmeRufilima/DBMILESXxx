from __future__ import annotations

import json
from pathlib import Path

import logging

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from ..config import AIRLINE_IMAGE_DIR, AIRLINE_UPLOAD_DIR, BASE_DIR
from ..models import Airline, CalculationField, CalculationType, WebQuote
from .travel_data import AIRLINE_OPTIONS, NATIONAL_AIRLINE_SLUGS, NO_MILES_AIRLINE_SLUGS


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
                    ("milhas", "Milhas necessárias por passageiro", "miles", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "money", "0", 0, None, 0.01, None),
                    ("taxa", "Taxa de embarque por passageiro", "money", "0", 0, None, 0.01, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "money", "140", 0, None, 1, None),
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
                    ("milhas", "Milhas Smiles necessárias", "miles", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "money", "0", 0, None, 0.01, None),
                    ("taxa", "Taxa de embarque", "money", "0", 0, None, 0.01, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "money", "175", 0, None, 1, None),
                ],
            },
            {
                "name": "Deságio",
                "slug": "gol-desagio",
                "legacy_key": "gol_desagio",
                "description": "Valor cheio menos o percentual de deságio.",
                "fields": [
                    ("valor_gol", "Valor cheio da passagem", "money", "0", 0, None, 0.01, None),
                    ("desagio", "Percentual de deságio", "percent", "0", 0, 100, 1, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "money", "175", 0, None, 1, None),
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
                    ("milhas", "Pontos/Milhas totais em milheiros", "miles", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "money", "0", 0, None, 0.01, None),
                    ("taxa", "Taxa de embarque", "money", "0", 0, None, 0.01, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "money", "175", 0, None, 1, None),
                ],
            },
            {
                "name": "Pontos + Dinheiro",
                "slug": "azul-pontos-dinheiro",
                "legacy_key": "azul_pontos_dinheiro",
                "description": "Mantém a regra atual de desconto, impostos e taxa de resgate por pax/trecho.",
                "fields": [
                    ("milhas", "Pontos/Milhas totais em milheiros", "miles", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "money", "0", 0, None, 0.01, None),
                    ("valor_dinheiro", "Valor em dinheiro", "money", "0", 0, None, 0.01, None),
                    ("desconto_taxa", "Desconto no valor em dinheiro (%)", "percent", "10", 0, 100, 1, None),
                    ("taxas_impostos", "Taxas e impostos", "money", "0", 0, None, 0.01, None),
                    ("taxa_resgate_por_pax_trecho", "Taxa de resgate por pax/trecho", "money", "60", 0, None, 1, None),
                    ("numero_trechos", "Número de trechos", "integer", "1", 1, 20, 1, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "money", "175", 0, None, 1, None),
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
                    ("milhas", "Milhas AAdvantage necessárias", "miles", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "money", "0", 0, None, 0.01, None),
                    ("taxa", "Taxa de embarque", "money", "0", 0, None, 0.01, None),
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
                    ("milhas", "Pontos/Milhas totais em milheiros", "miles", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "money", "0", 0, None, 0.01, None),
                    ("taxa", "Taxa de embarque", "money", "0", 0, None, 0.01, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "money", "175", 0, None, 1, None),
                ],
            },
            {
                "name": "Pontos + Dinheiro",
                "slug": "azulpelomundo-pontos-dinheiro",
                "legacy_key": "azulpelomundo_pontos_dinheiro",
                "description": "Mantém a regra atual de desconto, impostos e taxa de resgate por pax/trecho.",
                "fields": [
                    ("milhas", "Pontos/Milhas totais em milheiros", "miles", "0", 0, None, 0.001, None),
                    ("milheiro", "Valor do milheiro", "money", "0", 0, None, 0.01, None),
                    ("valor_dinheiro", "Valor em dinheiro", "money", "0", 0, None, 0.01, None),
                    ("desconto_taxa", "Desconto no valor em dinheiro (%)", "percent", "10", 0, 100, 1, None),
                    ("taxas_impostos", "Taxas e impostos", "money", "0", 0, None, 0.01, None),
                    ("taxa_resgate_por_pax_trecho", "Taxa de resgate por pax/trecho", "money", "60", 0, None, 1, None),
                    ("numero_trechos", "Número de trechos", "integer", "1", 1, 20, 1, None),
                    ("bagagem_unitaria", "Bagagem adicional por unidade", "money", "175", 0, None, 1, None),
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
    # Mesmo código com outra extensão (euroatlantic.jpg, euroatlantic.webp...).
    from .airline_logos import find_logo_file

    found = find_logo_file(Path(filename).stem)
    return AIRLINE_IMAGE_DIR / found if found else None


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


SITE_VALUE_TYPE_NAME = "Valor cheio + desconto"
_OLD_SITE_VALUE_NAMES = {"Valor do site"}


def _auto_type_slugs(slug: str) -> set[str]:
    """Tipos criados automaticamente pelo catálogo (não pelo administrador)."""
    return {f"{slug}-padrao", f"{slug}-valor-site"}


def _site_value_type(slug: str) -> dict:
    """Cotação pelo valor cheio do site, com desconto opcional."""
    return {
        "name": SITE_VALUE_TYPE_NAME, "slug": f"{slug}-valor-site", "legacy_key": "valor_site",
        "description": "Companhia sem programa de milhas: valor cheio do site menos o desconto (%) informado.",
        "fields": [
            ("valor_site", "Valor cheio (site)", "money", "0", 0, None, 0.01, None),
            ("desconto_site", "Desconto (%)", "percent", "0", 0, 100, 1, None),
            ("bagagem_unitaria", "Bagagem adicional por unidade", "money", "0", 0, None, 1, None),
        ],
    }


def _generic_airline_builtin(item: dict[str, str]) -> dict:
    slug = item["slug"]
    if slug in NO_MILES_AIRLINE_SLUGS:
        types = [_site_value_type(slug)]
    else:
        types = [{
            "name": "Cálculo padrão", "slug": f"{slug}-padrao", "legacy_key": None,
            "description": "Regra genérica editável: (milhas * milheiro) + taxa. Pode ser usada como base para cotações manuais.",
            "fields": [
                ("milhas", "Milhas/pontos", "number", "0", 0, None, 0.001, None),
                ("milheiro", "Valor do milheiro", "money", "0", 0, None, 0.01, None),
                ("taxa", "Taxa", "number", "0", 0, None, 0.01, None),
                ("bagagem_unitaria", "Bagagem adicional por unidade", "money", "0", 0, None, 1, None),
            ],
        }]
    return {
        "name": item["name"], "slug": slug, "legacy_code": None, "color": "#26c5e6", "logo": item.get("logo") or f"{slug}.png",
        "types": types,
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
    if token in NATIONAL_AIRLINE_SLUGS:
        return "national"
    return "international"


EXTRA_BUILTINS = []
_existing_slugs = {item["slug"] for item in BUILTINS}
for _item in AIRLINE_OPTIONS:
    if _item["slug"] not in _existing_slugs:
        EXTRA_BUILTINS.append(_generic_airline_builtin(_item))


logger = logging.getLogger(__name__)


def _expected_catalog() -> list[dict]:
    return BUILTINS + EXTRA_BUILTINS


def _new_calc_type(type_item: dict, *, is_default: bool) -> CalculationType:
    calc_type = CalculationType(
        name=type_item["name"],
        slug=type_item["slug"],
        description=type_item["description"],
        formula="(milhas * milheiro) + taxa",
        apply_mode="total",
        legacy_key=type_item["legacy_key"],
        active=True,
        is_default=is_default,
    )
    _fill_fields(calc_type, type_item)
    return calc_type


def _fill_fields(calc_type: CalculationType, type_item: dict) -> None:
    for field_index, field_data in enumerate(type_item["fields"]):
        key, label, field_type, default, min_value, max_value, step, options = field_data
        calc_type.fields.append(
            CalculationField(
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


def seed_builtin_airlines(db: Session) -> int:
    """Cria/completa as companhias padrão. Retorna quantos itens foram criados.

    Carrega tudo em uma única consulta (importante no Neon/Vercel, onde cada
    ida ao banco custa caro) e só insere o que estiver faltando.
    """
    existing = {
        airline.slug: airline
        for airline in db.scalars(
            select(Airline)
            .where(Airline.builtin.is_(True))
            .options(selectinload(Airline.calculation_types).selectinload(CalculationType.fields))
        ).all()
    }
    created = 0
    for item in _expected_catalog():
        airline = existing.get(item["slug"])
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
            existing[item["slug"]] = airline
            created += 1
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

        created += _reconcile_types(db, airline, item)
    db.commit()
    return created


def _type_in_use(db: Session, calc_type: CalculationType) -> bool:
    if calc_type.id is None:
        return False
    return db.scalar(select(WebQuote.id).where(WebQuote.calculation_type_id == calc_type.id).limit(1)) is not None


def _reconcile_types(db: Session, airline: Airline, item: dict) -> int:
    """Deixa os tipos automáticos da companhia de acordo com o catálogo.

    Companhia com programa de milhas → "Cálculo padrão" (milhas).
    Companhia sem programa → só "Valor cheio + desconto".
    O tipo automático que não vale mais sai da lista (fica guardado se alguma
    cotação já o usou). Tipos criados pelo administrador não são mexidos.
    """
    created = 0
    by_slug = {calc.slug: calc for calc in airline.calculation_types}
    expected_slugs = [type_item["slug"] for type_item in item["types"]]
    for type_item in item["types"]:
        calc_type = by_slug.get(type_item["slug"])
        if calc_type is None:
            calc_type = _new_calc_type(type_item, is_default=False)
            airline.calculation_types.append(calc_type)
            by_slug[calc_type.slug] = calc_type
            created += 1
        elif not calc_type.fields:
            _fill_fields(calc_type, type_item)
        if calc_type.slug in _auto_type_slugs(item["slug"]):
            calc_type.active = True
        if type_item.get("legacy_key") == "valor_site":
            if calc_type.name in _OLD_SITE_VALUE_NAMES:
                calc_type.name = type_item["name"]
                calc_type.description = type_item["description"]
            for field in calc_type.fields:
                if field.key == "valor_site" and field.label == "Valor total no site":
                    field.label = "Valor cheio (site)"
    for stale_slug in _auto_type_slugs(item["slug"]) - set(expected_slugs):
        stale = by_slug.get(stale_slug)
        if stale is None:
            continue
        stale.is_default = False
        if stale.active and not _type_in_use(db, stale):
            stale.active = False
    active_types = [calc for calc in airline.calculation_types if calc.active]
    if not any(calc.is_default for calc in active_types):
        first = by_slug.get(expected_slugs[0]) if expected_slugs else None
        if first is not None:
            for calc in airline.calculation_types:
                calc.is_default = calc is first
    return created


def _catalog_needs_update(db: Session) -> bool:
    rows = db.execute(
        select(Airline.slug, CalculationType.slug, CalculationType.active, CalculationType.name, CalculationType.is_default)
        .join(CalculationType, CalculationType.airline_id == Airline.id, isouter=True)
        .where(Airline.builtin.is_(True))
    ).all()
    have_airlines = {row[0] for row in rows}
    # Logo colocada depois na pasta app/imagens: atualiza a companhia sem logo.
    from .airline_logos import find_logo_file

    sem_logo = db.scalars(
        select(Airline.slug).where(Airline.builtin.is_(True), (Airline.logo_path.is_(None)) | (Airline.logo_path == ""))
    ).all()
    if any(find_logo_file(slug) for slug in sem_logo):
        return True
    types = {row[1]: (bool(row[2]), row[3], bool(row[4])) for row in rows if row[1]}
    for item in _expected_catalog():
        if item["slug"] not in have_airlines:
            return True
        expected = {t["slug"] for t in item["types"]}
        for slug in expected:
            state = types.get(slug)
            if state is None or not state[0] or state[1] in _OLD_SITE_VALUE_NAMES:
                return True
        for stale in _auto_type_slugs(item["slug"]) - expected:
            # Tipo antigo ainda como padrão: precisa ser trocado. (Se só ficou
            # ativo por já ter cotações, não precisa reprocessar a cada início.)
            if stale in types and types[stale][0] and types[stale][2]:
                return True
    return False


_CATALOG_READY = False


def ensure_catalog_airlines(db: Session) -> None:
    """Garante no banco as companhias do catálogo (uma vez por processo).

    Na Vercel o startup não roda o seed; por isso as companhias novas do
    catálogo nunca chegavam ao Neon. A verificação é uma consulta leve; só
    quando falta algo o seed completo roda (com trava no PostgreSQL para dois
    acessos simultâneos não duplicarem a companhia).
    """
    global _CATALOG_READY
    if _CATALOG_READY:
        return
    try:
        missing = _catalog_needs_update(db)
        if missing:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(740611)"))
            created = seed_builtin_airlines(db)
            logger.info("Catálogo de companhias completado: %s itens criados.", created)
        _CATALOG_READY = True
    except Exception:  # nunca derruba a tela por causa do catálogo
        db.rollback()
        logger.exception("Não foi possível completar o catálogo de companhias.")
