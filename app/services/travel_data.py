from __future__ import annotations

import re
from urllib.parse import quote_plus

BR_AIRPORTS: dict[str, str] = {
    "AFL":"Alta Floresta","AJU":"Aracaju","AQA":"Araraquara","ARU":"Araçatuba","ATM":"Altamira","BEL":"Belém",
    "BPG":"Barra do Garças","BRA":"Barreiras","BSB":"Brasília","BVB":"Boa Vista","BVH":"Vilhena","BYO":"Bonito",
    "CAC":"Cascavel","CAU":"Caruaru","CGB":"Cuiabá","CGH":"São Paulo/Congonhas","CGR":"Campo Grande",
    "CKS":"Carajás/Parauapebas","CLV":"Caldas Novas","CMG":"Corumbá","CNF":"Belo Horizonte/Confins",
    "CWB":"Curitiba","CXJ":"Caxias do Sul","CZS":"Cruzeiro do Sul","DIQ":"Divinópolis","FLN":"Florianópolis",
    "FOR":"Fortaleza","GIG":"Rio de Janeiro/Galeão","GNM":"Guanambi","GRU":"São Paulo/Guarulhos","GYN":"Goiânia",
    "IGU":"Foz do Iguaçu","IMP":"Imperatriz","IOS":"Ilhéus","ITB":"Itaituba","IZA":"Juiz de Fora/Zona da Mata",
    "JDO":"Juazeiro do Norte","JJD":"Cruz/Jericoacoara","JJG":"Jaguaruna","JOI":"Joinville","JPA":"João Pessoa",
    "JPR":"Ji-Paraná","JTC":"Bauru/Arealva","LBR":"Lábrea","LDB":"Londrina","LEC":"Lençóis","MAB":"Marabá",
    "MAO":"Manaus","MBZ":"Maués","MCP":"Macapá","MCZ":"Maceió","MGF":"Maringá","MII":"Marília",
    "MNX":"Manicoré","MOC":"Montes Claros","MXQ":"Morro de São Paulo","NAT":"Natal","NVT":"Navegantes",
    "OAL":"Cacoal","OPS":"Sinop","PFB":"Passo Fundo","PIN":"Parintins","PMG":"Ponta Porã","PMW":"Palmas",
    "PNZ":"Petrolina","POA":"Porto Alegre","POJ":"Patos de Minas","PPB":"Presidente Prudente","PTO":"Pato Branco",
    "PVH":"Porto Velho","RAO":"Ribeirão Preto","RBB":"Borba","RBR":"Rio Branco","REC":"Recife","RIA":"Santa Maria",
    "ROO":"Rondonópolis","SDU":"Rio de Janeiro/Santos Dumont","SET":"Serra Talhada","SJK":"São José dos Campos",
    "SJL":"São Gabriel da Cachoeira","SJP":"São José do Rio Preto","SLZ":"São Luís","SMT":"Sorriso","SSA":"Salvador",
    "STM":"Santarém","TBT":"Tabatinga","TFF":"Tefé","THE":"Teresina","UBA":"Uberaba","UDI":"Uberlândia",
    "UMU":"Umuarama","UNA":"Una/Comandatuba","URG":"Uruguaiana","VCP":"Campinas/Viracopos","VDC":"Vitória da Conquista",
    "VIX":"Vitória","XAP":"Chapecó","AAX":"Araxá","GVR":"Governador Valadares","MEU":"Monte Dourado",
    "PET":"Pelotas","BPS":"Porto Seguro","GEL":"Santo Ângelo","FEN":"Fernando de Noronha","IPN":"Ipatinga",
    "PHB":"Parnaíba","CPV":"Campina Grande","DOU":"Dourados","RRJ":"Rio de Janeiro/Jacarepaguá","VAG":"Varginha",
}


# Aeroportos internacionais mais usados nas emissões da agência.
# BR_AIRPORTS é mantido por compatibilidade com as telas antigas, mas agora
# também contém estes códigos para que origem e destino tenham autocomplete
# nacional e internacional em todo o sistema.
INTERNATIONAL_AIRPORTS: dict[str, str] = {
    "ATL":"Atlanta/Hartsfield-Jackson", "AMS":"Amsterdã/Schiphol", "ATH":"Atenas", "BCN":"Barcelona/El Prat",
    "BOG":"Bogotá/El Dorado", "BOS":"Boston/Logan", "BRU":"Bruxelas", "BUE":"Buenos Aires (todos)",
    "CDG":"Paris/Charles de Gaulle", "CLT":"Charlotte", "CUN":"Cancún", "DCA":"Washington/Reagan",
    "DFW":"Dallas/Fort Worth", "DOH":"Doha/Hamad", "DXB":"Dubai", "EWR":"Nova York/Newark",
    "EZE":"Buenos Aires/Ezeiza", "FCO":"Roma/Fiumicino", "FRA":"Frankfurt", "HND":"Tóquio/Haneda",
    "HKG":"Hong Kong", "IAD":"Washington/Dulles", "IAH":"Houston/George Bush", "ICN":"Seul/Incheon",
    "JFK":"Nova York/JFK", "LAS":"Las Vegas", "LAX":"Los Angeles", "LGA":"Nova York/LaGuardia",
    "LHR":"Londres/Heathrow", "LIM":"Lima/Jorge Chávez", "LIS":"Lisboa", "MAD":"Madri/Barajas",
    "MCO":"Orlando", "MEX":"Cidade do México", "MIA":"Miami", "MUC":"Munique",
    "MXP":"Milão/Malpensa", "NRT":"Tóquio/Narita", "ORY":"Paris/Orly", "PTY":"Cidade do Panamá/Tocumen",
    "PUJ":"Punta Cana", "SCL":"Santiago do Chile", "SDQ":"Santo Domingo", "SFO":"São Francisco",
    "SIN":"Singapura/Changi", "SYD":"Sydney", "TLV":"Tel Aviv/Ben Gurion", "YYZ":"Toronto/Pearson",
    "YUL":"Montreal/Trudeau", "YVR":"Vancouver", "ZRH":"Zurique", "OPO":"Porto",
    "VIE":"Viena", "CPH":"Copenhague", "IST":"Istambul", "SAW":"Istambul/Sabiha Gökçen",
    "JNB":"Joanesburgo", "CPT":"Cidade do Cabo", "ADD":"Adis Abeba", "CAI":"Cairo",
    "RAK":"Marrakech", "CMN":"Casablanca", "NBO":"Nairóbi", "AUH":"Abu Dhabi",
    "DEL":"Nova Délhi", "BOM":"Mumbai", "BKK":"Bangkok/Suvarnabhumi", "KUL":"Kuala Lumpur",
    "PEK":"Pequim/Capital", "PVG":"Xangai/Pudong", "CAN":"Guangzhou", "MNL":"Manila",
    "AKL":"Auckland", "MEL":"Melbourne", "PER":"Perth", "SVO":"Moscou/Sheremetyevo",
    "DUB":"Dublin", "EDI":"Edimburgo", "MAN":"Manchester", "LGW":"Londres/Gatwick",
    "VCE":"Veneza", "NAP":"Nápoles", "FLR":"Florença", "GVA":"Genebra",
    "PRG":"Praga", "BUD":"Budapeste", "WAW":"Varsóvia", "OSL":"Oslo",
    "ARN":"Estocolmo/Arlanda", "HEL":"Helsinque", "KEF":"Reiquiavique/Keflavík", "MVD":"Montevidéu",
    "ASU":"Assunção", "AEP":"Buenos Aires/Aeroparque", "COR":"Córdoba", "MDZ":"Mendoza",
    "UIO":"Quito", "GYE":"Guayaquil", "MDE":"Medellín", "CTG":"Cartagena",
    "CUR":"Curaçao", "AUA":"Aruba", "NAS":"Nassau", "HAV":"Havana",
}
# Aeroportos e aeródromos civis portugueses com código IATA.
# Inclui Portugal continental, Madeira e todos os aeroportos dos Açores.
PORTUGAL_AIRPORTS: dict[str, str] = {
    "LIS":"Lisboa/Humberto Delgado",
    "OPO":"Porto/Francisco Sá Carneiro",
    "FAO":"Faro/Algarve",
    "BYJ":"Beja/Alentejo",
    "BGC":"Bragança",
    "BGZ":"Braga",
    "CAT":"Cascais/Tires",
    "CHV":"Chaves",
    "CBP":"Coimbra/Bissaya Barreto",
    "COV":"Covilhã",
    "PRM":"Portimão",
    "VRL":"Vila Real",
    "VSE":"Viseu/Gonçalves Lobato",
    "QLR":"Leiria/Gândara",
    "QPS":"Ponte de Sor",
    "SIE":"Sines",
    "FNC":"Madeira/Cristiano Ronaldo",
    "PXO":"Porto Santo",
    "PDL":"Ponta Delgada/João Paulo II",
    "TER":"Terceira/Lajes",
    "SMA":"Santa Maria",
    "HOR":"Horta",
    "PIX":"Pico",
    "FLW":"Flores",
    "SJZ":"São Jorge",
    "GRW":"Graciosa",
    "CVU":"Corvo",
}

AIRPORTS: dict[str, str] = {**BR_AIRPORTS, **INTERNATIONAL_AIRPORTS, **PORTUGAL_AIRPORTS}
BR_AIRPORTS = AIRPORTS

AIRLINE_OPTIONS: list[dict[str, str]] = [
    {"name":"Aerolíneas Argentinas","slug":"aerolineas","logo":"aerolineas.png"},
    {"name":"Aeromexico","slug":"aeromexico","logo":"aeromexico.png"},
    {"name":"Air Canada","slug":"aircanada","logo":"aircanada.png"},
    {"name":"Air China","slug":"airchina","logo":"airchina.png"},
    {"name":"Air Europa","slug":"aireuropa","logo":"aireuropa.png"},
    {"name":"Air France","slug":"airfrance","logo":"airfrance.png"},
    {"name":"Air New Zealand","slug":"airnewzealand","logo":"airnewzealand.png"},
    {"name":"Amaszonas","slug":"amaszonas","logo":"amaszonas.png"},
    {"name":"American Airlines","slug":"american","logo":"american.png"},
    {"name":"ANA","slug":"ana","logo":"ana.png"},
    {"name":"Arajet","slug":"arajet","logo":"arajet.png"},
    {"name":"Avianca","slug":"avianca","logo":"avianca.png"},
    {"name":"Azul Linhas Aéreas","slug":"azul","logo":"azul.png"},
    {"name":"Boliviana de Aviación","slug":"boa","logo":"boa.png"},
    {"name":"British Airways","slug":"british","logo":"british.png"},
    {"name":"Condor","slug":"condor","logo":"condor.png"},
    {"name":"Copa Airlines","slug":"copa","logo":"copa.png"},
    {"name":"Delta Air Lines","slug":"delta","logo":"delta.png"},
    {"name":"El Al","slug":"elal","logo":"elal.png"},
    {"name":"Emirates","slug":"emirates","logo":"emirates.png"},
    {"name":"Ethiopian Airlines","slug":"ethiopian","logo":"ethiopian.png"},
    {"name":"GOL Linhas Aéreas","slug":"gol","logo":"gol.png"},
    {"name":"Iberia","slug":"iberia","logo":"iberia.png"},
    {"name":"ITA Airways","slug":"ita","logo":"ita.png"},
    {"name":"Japan Airlines","slug":"jal","logo":"jal.png"},
    {"name":"JetSMART","slug":"jetsmart","logo":"jetsmart.png"},
    {"name":"KLM","slug":"klm","logo":"klm.png"},
    {"name":"Korean Air","slug":"koreanair","logo":"koreanair.png"},
    {"name":"LATAM Airlines","slug":"latam","logo":"latam.png"},
    {"name":"Lufthansa","slug":"lufthansa","logo":"lufthansa.png"},
    {"name":"Panama Air","slug":"panamair","logo":"panamair.png"},
    {"name":"Qantas","slug":"qantas","logo":"qantas.png"},
    {"name":"Qatar Airways","slug":"qatar","logo":"qatar.png"},
    {"name":"Royal Air Maroc","slug":"royalairmaroc","logo":"royalairmaroc.png"},
    {"name":"Singapore Airlines","slug":"singapore","logo":"singapore.png"},
    {"name":"SKY Airline","slug":"sky","logo":"sky.png"},
    {"name":"South African Airways","slug":"southafrican","logo":"southafrican.png"},
    {"name":"Swiss","slug":"swiss","logo":"swiss.png"},
    {"name":"TAAG Angola Airlines","slug":"taag","logo":"taag.png"},
    {"name":"TAP Air Portugal","slug":"tap","logo":"tap.png"},
    {"name":"Turkish Airlines","slug":"turkish","logo":"turkish.png"},
    {"name":"United Airlines","slug":"united","logo":"united.png"},
    {"name":"Voepass","slug":"voepass","logo":"voepass.png"},
]

CHECKIN_LINKS: dict[str, str] = {
    "aerolineas":"https://www.aerolineas.com.ar/check-in","aeromexico":"https://aeromexico.com/pt-br/check-in",
    "aircanada":"https://www.aircanada.com/ca/en/aco/home/ssci.html","airchina":"https://www.airchina.com/",
    "aireuropa":"https://www.aireuropa.com/br/pt/aea/gestoes/check-in.html","airfrance":"https://wwws.airfrance.com.br/check-in",
    "airnewzealand":"https://www.airnewzealand.com/check-in-online","amaszonas":"https://www.amaszonas.com/",
    "american":"https://www.aa.com/checkin","ana":"https://www.ana.co.jp/en/jp/guide/boarding-procedures/checkin/",
    "arajet":"https://www.arajet.com/","avianca":"https://www.avianca.com/pt/gerencie-sua-reserva/check-in-online/",
    "azul":"https://www.voeazul.com.br/check-in","boa":"https://www.boa.bo/",
    "british":"https://www.britishairways.com/travel/olcilandingpageauthreq/public/en_br","condor":"https://www.condor.com/",
    "copa":"https://www.copaair.com/pt-gs/check-in/","delta":"https://www.delta.com/us/en/check-in-security/overview",
    "elal":"https://www.elal.com/","emirates":"https://www.emirates.com/br/english/manage-booking/online-check-in/",
    "ethiopian":"https://www.ethiopianairlines.com/br/services/online-check-in","gol":"https://b2c.voegol.com.br/check-in",
    "iberia":"https://www.iberia.com/br/check-in-online/","ita":"https://www.ita-airways.com/en_br/fly-ita/check-in.html",
    "jal":"https://www.jal.co.jp/ar/en/inter/boarding/online-checkin/","jetsmart":"https://jetsmart.com/br/pt/check-in",
    "klm":"https://www.klm.com.br/check-in","koreanair":"https://www.koreanair.com/",
    "latam":"https://www.latamairlines.com/br/pt/check-in","lufthansa":"https://www.lufthansa.com/br/pt/check-in-online",
    "qantas":"https://www.qantas.com/","qatar":"https://www.qatarairways.com/pt-br/services-checking-in.html",
    "royalairmaroc":"https://www.royalairmaroc.com/","singapore":"https://www.singaporeair.com/en_UK/br/travel-info/check-in/online-mobile-checkin/",
    "sky":"https://www.skyairline.com/","southafrican":"https://www.flysaa.com/","swiss":"https://www.swiss.com/br/en/fly/check-in/online-check-in",
    "taag":"https://www.taag.com/","tap":"https://www.flytap.com/pt-br/check-in-online",
    "turkish":"https://www.turkishairlines.com/en-int/flights/manage-booking/online-check-in/","united":"https://www.united.com/en/us/checkin",
    "voepass":"https://www.voepass.com.br/",
}

ALIASES: dict[str, str] = {
    "aerolineas":"aerolineas","aerolíneas":"aerolineas","argentina":"aerolineas","aeromexico":"aeromexico","aeroméxico":"aeromexico",
    "air canada":"aircanada","air china":"airchina","air europa":"aireuropa","air france":"airfrance","air new zealand":"airnewzealand",
    "amaszonas":"amaszonas","amazonas":"amaszonas","american":"american","aadvantage":"american","aa":"american","ana":"ana","arajet":"arajet",
    "avianca":"avianca","azul":"azul","tudoazul":"azul","voeazul":"azul","boa":"boa","boliviana":"boa","british":"british",
    "british airways":"british","condor":"condor","copa":"copa","delta":"delta","el al":"elal","elal":"elal","emirates":"emirates",
    "ethiopian":"ethiopian","gol":"gol","smiles":"gol","iberia":"iberia","ita":"ita","ita airways":"ita","jal":"jal","japan airlines":"jal",
    "jetsmart":"jetsmart","klm":"klm","korean":"koreanair","korean air":"koreanair","latam":"latam","latam airlines":"latam","lufthansa":"lufthansa",
    "qantas":"qantas","qatar":"qatar","royal air maroc":"royalairmaroc","royalairmaroc":"royalairmaroc","singapore":"singapore",
    "singapore airlines":"singapore","sky":"sky","south african":"southafrican","southafrican":"southafrican","swiss":"swiss","taag":"taag",
    "tap":"tap","tap air portugal":"tap","turkish":"turkish","united":"united","voepass":"voepass",
}

def airline_key(name: str | None) -> str:
    text = (name or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[^a-záàâãéèêíïóôõöúüçñ0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in ALIASES:
        return ALIASES[text]
    for token, key in sorted(ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if token and token in text:
            return key
    return ""

def checkin_link_for_airline(airline_name: str | None, locator: str | None = None, purchase_number: str | None = None) -> str:
    key = airline_key(airline_name)
    if key and CHECKIN_LINKS.get(key):
        return CHECKIN_LINKS[key]
    airline_text = str(airline_name or "").strip()
    if airline_text:
        return f"https://www.google.com/search?q={quote_plus(airline_text + ' check-in')}"
    return ""

def airport_city(code_or_text: str | None) -> str:
    text = (code_or_text or "").strip().upper()
    if not text:
        return ""
    match = re.search(r"\b([A-Z]{3})\b", text)
    code = match.group(1) if match else text[:3]
    return BR_AIRPORTS.get(code, "")
