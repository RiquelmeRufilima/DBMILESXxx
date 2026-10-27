# Reservas pelo localizador (Amadeus)

## Onde aparece
- **Menu → Reservas**: lista no estilo MilhasPix + botão **Adicionar** (escolhe a companhia e informa o localizador).
- **Cotação → aba Orçamento → "Incluir via localizador"**: mesma janela. A reserva também fica registrada em
  Reservas (com a descrição "Cotação q0006 – Cliente").

Campos pedidos por companhia (editar em `app/services/reservations/airlines.py`):
- LATAM: nº da compra + último sobrenome
- GOL: localizador + aeroporto de origem + último sobrenome
- Azul: localizador + aeroporto de origem
- TAP: localizador + sobrenome completo
- Demais: localizador + último sobrenome

## Hoje (sem conector ativo)
A reserva é salva como **"Aguardando sincronização"**. Na cotação, o voo abre pré-preenchido
(companhia, localizador/nº da compra, origem, link de check-in e sobrenome na observação) para completar.

## Para ligar a busca automática
As APIs **Self-Service** do Amadeus foram desligadas em **17/07/2026** — as chaves
`AMADEUS_CLIENT_ID/SECRET` antigas não funcionam mais. A busca por localizador (PNR) exige o
**Amadeus Enterprise** (operação `PNR_Retrieve`), com contrato e **Office ID** da agência.

1. Contratar o Amadeus Enterprise (ou verificar se a consolidadora oferece acesso).
2. No Vercel → Settings → Environment Variables:
   ```
   RESERVATION_PROVIDER=amadeus_enterprise
   AMADEUS_ENT_ENDPOINT=...
   AMADEUS_ENT_OFFICE_ID=...
   AMADEUS_ENT_USER=...
   AMADEUS_ENT_PASSWORD=...
   ```
   (Também dá para ligar só para uma companhia: `RESERVATION_PROVIDER_GOL=amadeus_enterprise`.)
3. Implementar o método `lookup` de `AmadeusEnterpriseProvider` em
   `app/services/reservations/providers.py` (os passos e o formato de retorno estão comentados ali).
   Tela, validação, limite de tentativas, gravação e conversão para o voo da cotação já estão prontos.

Observação: o `PNR_Retrieve` normalmente só traz reservas que a agência enxerga no GDS (emitidas pelo
Office ID ou compartilhadas com ele). Emissões feitas direto no site da companhia (ex.: com milhas) podem
precisar de outro conector; basta criar uma classe nova e registrar com `register_provider`.
