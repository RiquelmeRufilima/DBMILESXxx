"""Conectores de busca de reserva ("tomadas").

Todo conector recebe um ReservationQuery e devolve um ReservationResult no
MESMO formato, então a tela e o banco não mudam quando trocamos de fornecedor.

Qual conector usar é decidido por variável de ambiente (no Vercel):
  RESERVATION_PROVIDER=manual                 padrão para todas as companhias
  RESERVATION_PROVIDER_LATAM=amadeus_enterprise   (exemplo de exceção por cia)

Conectores disponíveis hoje:
  manual              Salva a reserva como "aguardando sincronização".
  amadeus_enterprise  Esqueleto pronto para o Amadeus Enterprise (exige contrato).
                      Ver o passo a passo em docs/RESERVAS_AMADEUS.md.

Observação importante: o portal Amadeus Self-Service (test.api.amadeus.com)
foi desativado em 17/07/2026, e mesmo antes ele NÃO buscava reservas feitas no
site das companhias pelo localizador. Por isso o conector Amadeus aqui é o
Enterprise (SOAP/REST com Office ID), que precisa de contrato com a Amadeus.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReservationQuery:
    airline_slug: str
    airline_name: str
    locator: str = ""
    purchase_number: str = ""
    last_name: str = ""
    origin: str = ""


@dataclass
class ReservationResult:
    """Formato único de resposta.

    status:
      found         reserva encontrada (passengers/flights preenchidos)
      not_found     companhia respondeu que não existe
      unavailable   conector não ativo/configurado (reserva fica pendente)
      error         falha temporária (tentar de novo depois)

    flights: lista no mesmo formato usado pela agenda de Voos:
      {"kind": "ida"|"volta"|"trecho", "origin": "FOR", "destination": "GRU",
       "departure_date": "2026-11-10", "departure_time": "10:55",
       "arrival_date": "...", "arrival_time": "...", "flight_number": "LA3973",
       "airline": "LATAM Airlines", "locator": "ABC123", "status": "Confirmado"}
    passengers: [{"name": "Maria Silva", "type": "ADT"}]
    """
    status: str
    message: str = ""
    booking_status: str = ""
    passengers: list[dict[str, Any]] = field(default_factory=list)
    flights: list[dict[str, Any]] = field(default_factory=list)
    total_value: float | None = None
    currency: str | None = None
    raw: dict[str, Any] | None = None


class ReservationProvider:
    name = "base"
    label = "Conector"

    def is_configured(self) -> bool:
        return False

    async def lookup(self, query: ReservationQuery) -> ReservationResult:  # pragma: no cover - interface
        raise NotImplementedError


class ManualProvider(ReservationProvider):
    """Sem busca automática: a reserva fica salva para sincronizar depois."""

    name = "manual"
    label = "Manual"

    def is_configured(self) -> bool:
        return True

    async def lookup(self, query: ReservationQuery) -> ReservationResult:
        return ReservationResult(
            status="unavailable",
            message="Reserva salva. A busca automática ainda não está ativada para esta companhia.",
        )


class AmadeusEnterpriseProvider(ReservationProvider):
    """Esqueleto para o Amadeus Enterprise (PNR Retrieve).

    Variáveis esperadas (fornecidas pela Amadeus no contrato):
      AMADEUS_ENT_ENDPOINT    URL do Web Services (WSAP) ou gateway REST
      AMADEUS_ENT_OFFICE_ID   Office ID da agência (ex.: FORBR28AA)
      AMADEUS_ENT_USER / AMADEUS_ENT_PASSWORD  credenciais do usuário de serviço

    Só recupera reservas (PNRs) que a agência consegue acessar no GDS — em
    geral as emitidas pelo próprio Office ID ou compartilhadas com ele.
    """

    name = "amadeus_enterprise"
    label = "Amadeus Enterprise"

    def __init__(self) -> None:
        self.endpoint = os.getenv("AMADEUS_ENT_ENDPOINT", "").strip()
        self.office_id = os.getenv("AMADEUS_ENT_OFFICE_ID", "").strip()
        self.user = os.getenv("AMADEUS_ENT_USER", "").strip()
        self.password = os.getenv("AMADEUS_ENT_PASSWORD", "")

    def is_configured(self) -> bool:
        return bool(self.endpoint and self.office_id and self.user and self.password)

    async def lookup(self, query: ReservationQuery) -> ReservationResult:
        if not self.is_configured():
            return ReservationResult(
                status="unavailable",
                message="Amadeus Enterprise ainda não configurado (faltam as credenciais do contrato).",
            )
        # PONTO DE IMPLEMENTAÇÃO:
        # 1. Autenticar (Security_Authenticate / sessão stateful ou token REST).
        # 2. Chamar PNR_Retrieve com o localizador (query.locator).
        # 3. Conferir o sobrenome (query.last_name) contra os passageiros.
        # 4. Converter itinerário -> ReservationResult.flights (formato acima).
        # 5. Encerrar a sessão (Security_SignOut).
        return ReservationResult(
            status="unavailable",
            message="Conector Amadeus Enterprise configurado, mas a chamada PNR_Retrieve ainda não foi implementada.",
        )


_PROVIDERS: dict[str, type[ReservationProvider]] = {
    ManualProvider.name: ManualProvider,
    AmadeusEnterpriseProvider.name: AmadeusEnterpriseProvider,
}


def register_provider(provider_cls: type[ReservationProvider]) -> None:
    """Permite acrescentar novos conectores (ex.: um serviço de terceiros)."""
    _PROVIDERS[provider_cls.name] = provider_cls


def provider_for(airline_slug: str) -> ReservationProvider:
    specific = os.getenv(f"RESERVATION_PROVIDER_{airline_slug.upper()}", "").strip().lower()
    default = os.getenv("RESERVATION_PROVIDER", "manual").strip().lower()
    cls = _PROVIDERS.get(specific) or _PROVIDERS.get(default) or ManualProvider
    return cls()


def providers_status() -> list[dict[str, Any]]:
    return [{"name": cls.name, "label": cls.label, "configured": cls().is_configured()} for cls in _PROVIDERS.values()]
