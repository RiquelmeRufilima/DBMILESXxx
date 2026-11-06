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

# Fusos dos aeroportos brasileiros (o Brasil não tem horário de verão desde 2019).
# Padrão -03:00; abaixo só as exceções. Usado para calcular a duração do voo
# quando o fuso não foi preenchido no cálculo.
BR_AIRPORT_CODES: frozenset[str] = frozenset(BR_AIRPORTS) | {"RIO", "SAO", "BHZ"}
BR_AIRPORT_UTC_OFFSETS: dict[str, str] = {
    # -04:00 — AM, RO, RR, MT, MS
    "MAO": "-04:00", "TBT": "-04:00", "PVH": "-04:00", "JPR": "-04:00", "BVH": "-04:00",
    "BVB": "-04:00", "CGB": "-04:00", "AFL": "-04:00", "BPG": "-04:00", "OPS": "-04:00",
    "ROO": "-04:00", "CGR": "-04:00", "CMG": "-04:00", "BYO": "-04:00",
    "DOU": "-04:00", "PMG": "-04:00", "TGQ": "-04:00", "PBQ": "-04:00", "OAL": "-04:00",
    # -05:00 — Acre
    "RBR": "-05:00", "CZS": "-05:00",
    # -02:00 — Fernando de Noronha
    "FEN": "-02:00",
}


def br_airport_utc_offset(code: str | None) -> str:
    """Fuso de um aeroporto brasileiro; vazio para aeroportos fora do Brasil."""
    code = str(code or "").strip().upper()
    if code not in BR_AIRPORT_CODES and code not in BR_AIRPORT_UTC_OFFSETS:
        return ""
    return BR_AIRPORT_UTC_OFFSETS.get(code, "-03:00")


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
    "STN":"Londres/Stansted", "LTN":"Londres/Luton", "LCY":"Londres/London City",
    "SEN":"Londres/Southend", "BVA":"Paris/Beauvais", "CIA":"Roma/Ciampino",
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

# Códigos IATA de CIDADE/REGIÃO: agrupam aeroportos (não são aeroportos).
# Na calculadora funcionam como filtro: ao escolher um deles, aparece a
# segunda seleção com os aeroportos específicos. "Portugal" é só um grupo
# de localização — POR não é código IATA, por isso o grupo não tem código.
IATA_CITY_GROUPS: list[dict] = [
    {"key": "NYC", "code": "NYC", "name": "Nova York", "airports": [
        {"code": "JFK", "name": "John F. Kennedy"}, {"code": "LGA", "name": "LaGuardia"}, {"code": "EWR", "name": "Newark"}]},
    {"key": "RIO", "code": "RIO", "name": "Rio de Janeiro", "airports": [
        {"code": "GIG", "name": "Galeão"}, {"code": "SDU", "name": "Santos Dumont"}]},
    {"key": "SAO", "code": "SAO", "name": "São Paulo", "airports": [
        {"code": "GRU", "name": "Guarulhos"}, {"code": "CGH", "name": "Congonhas"}, {"code": "VCP", "name": "Viracopos"}]},
    {"key": "LON", "code": "LON", "name": "Londres", "airports": [
        {"code": "LHR", "name": "Heathrow"}, {"code": "LGW", "name": "Gatwick"}, {"code": "STN", "name": "Stansted"},
        {"code": "LTN", "name": "Luton"}, {"code": "LCY", "name": "London City"}, {"code": "SEN", "name": "Southend"}]},
    {"key": "PAR", "code": "PAR", "name": "Paris", "airports": [
        {"code": "CDG", "name": "Charles de Gaulle"}, {"code": "ORY", "name": "Orly"}, {"code": "BVA", "name": "Beauvais"}]},
    {"key": "PT", "code": "", "name": "Portugal", "airports": [
        {"code": "OPO", "name": "Porto"}, {"code": "LIS", "name": "Lisboa"}, {"code": "FAO", "name": "Faro"},
        {"code": "BYJ", "name": "Beja"}, {"code": "CAT", "name": "Cascais"}, {"code": "BGC", "name": "Bragança"}]},
    {"key": "ROM", "code": "ROM", "name": "Roma", "airports": [
        {"code": "FCO", "name": "Fiumicino"}, {"code": "CIA", "name": "Ciampino"}]},
]
IATA_CITY_CODES: dict[str, str] = {
    group["code"]: f"{group['name']} (todos os aeroportos)" for group in IATA_CITY_GROUPS if group["code"]
}

AIRPORTS: dict[str, str] = {**BR_AIRPORTS, **INTERNATIONAL_AIRPORTS, **PORTUGAL_AIRPORTS, **IATA_CITY_CODES}


def airport_city_label(code: str | None) -> str:
    """Nome amigável para exibir abaixo do código: "São Paulo (Guarulhos)"."""
    code = str(code or "").strip().upper()
    for group in IATA_CITY_GROUPS:
        if group["code"] and group["code"] == code:
            return group["name"]
        for airport in group["airports"]:
            if airport["code"] == code:
                return f"{group['name']} ({airport['name']})" if group["code"] else airport["name"]
    name = AIRPORTS.get(code, "")
    if "/" in name:
        city, _, airport = name.partition("/")
        return f"{city.strip()} ({airport.strip()})"
    return name
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
    # Companhias acrescentadas em 06/11/2026 (sem logo no catálogo: aparece só o nome).
    {"name":"Aer Lingus","slug":"aerlingus","logo":""},
    {"name":"Air Transat","slug":"airtransat","logo":""},
    {"name":"Air India","slug":"airindia","logo":""},
    {"name":"Austrian Airlines","slug":"austrian","logo":""},
    {"name":"Azores Airlines","slug":"azores","logo":""},
    {"name":"Brussels Airlines","slug":"brussels","logo":""},
    {"name":"Cathay Pacific","slug":"cathay","logo":""},
    {"name":"Edelweiss","slug":"edelweiss","logo":""},
    {"name":"Etihad Airways","slug":"etihad","logo":""},
    {"name":"EuroAtlantic Airways","slug":"euroatlantic","logo":""},
    {"name":"Finnair","slug":"finnair","logo":""},
    {"name":"Flybondi","slug":"flybondi","logo":""},
    {"name":"Iberojet","slug":"iberojet","logo":""},
    {"name":"JetBlue","slug":"jetblue","logo":""},
    {"name":"Level","slug":"level","logo":""},
    {"name":"LOT Polish Airlines","slug":"lot","logo":""},
    {"name":"Norse Atlantic Airways","slug":"norse","logo":""},
    {"name":"Paranair","slug":"paranair","logo":""},
    {"name":"Plus Ultra","slug":"plusultra","logo":""},
    {"name":"Saudia","slug":"saudia","logo":""},
    {"name":"Sky High","slug":"skyhigh","logo":""},
    {"name":"Virgin Atlantic","slug":"virgin","logo":""},
    {"name":"World2Fly","slug":"world2fly","logo":""},
    {"name":"Alaska Airlines","slug":"alaska","logo":""},
    {"name":"Air Arabia","slug":"airarabia","logo":""},
    {"name":"Air Premia","slug":"airpremia","logo":""},
    {"name":"Asiana Airlines","slug":"asiana","logo":""},
    {"name":"China Eastern","slug":"chinaeastern","logo":""},
    {"name":"China Southern","slug":"chinasouthern","logo":""},
    {"name":"EVA Air","slug":"eva","logo":""},
    {"name":"Thai Airways","slug":"thai","logo":""},
    {"name":"Vietnam Airlines","slug":"vietnam","logo":""},
    {"name":"Kenya Airways","slug":"kenya","logo":""},
    {"name":"EgyptAir","slug":"egyptair","logo":""},
    # Segundo lote (06/11/2026).
    {"name":"Azul Conecta","slug":"azulconecta","logo":""},
    {"name":"MAP Linhas Aéreas","slug":"map","logo":""},
    {"name":"Wingo","slug":"wingo","logo":""},
    {"name":"Volaris","slug":"volaris","logo":""},
    {"name":"Viva Aerobus","slug":"vivaaerobus","logo":""},
    {"name":"Spirit Airlines","slug":"spirit","logo":""},
    {"name":"Frontier Airlines","slug":"frontier","logo":""},
    {"name":"Southwest Airlines","slug":"southwest","logo":""},
    {"name":"Conviasa","slug":"conviasa","logo":""},
    {"name":"Estelar","slug":"estelar","logo":""},
    {"name":"Laser Airlines","slug":"laser","logo":""},
    {"name":"Avior Airlines","slug":"avior","logo":""},
    {"name":"Cubana de Aviación","slug":"cubana","logo":""},
    {"name":"Ryanair","slug":"ryanair","logo":""},
    {"name":"easyJet","slug":"easyjet","logo":""},
    {"name":"Vueling","slug":"vueling","logo":""},
    {"name":"Volotea","slug":"volotea","logo":""},
    {"name":"Transavia","slug":"transavia","logo":""},
    {"name":"Eurowings","slug":"eurowings","logo":""},
    {"name":"Wizz Air","slug":"wizzair","logo":""},
    {"name":"SAS Scandinavian","slug":"sas","logo":""},
    {"name":"Icelandair","slug":"icelandair","logo":""},
    {"name":"Aegean Airlines","slug":"aegean","logo":""},
    {"name":"Air Serbia","slug":"airserbia","logo":""},
    {"name":"Pegasus Airlines","slug":"pegasus","logo":""},
    {"name":"Binter","slug":"binter","logo":""},
    {"name":"Cabo Verde Airlines","slug":"caboverde","logo":""},
    {"name":"Air Senegal","slug":"airsenegal","logo":""},
    {"name":"Air Côte d'Ivoire","slug":"aircotedivoire","logo":""},
    {"name":"RwandAir","slug":"rwandair","logo":""},
    {"name":"Oman Air","slug":"omanair","logo":""},
    {"name":"Gulf Air","slug":"gulfair","logo":""},
    {"name":"flydubai","slug":"flydubai","logo":""},
    {"name":"Royal Jordanian","slug":"royaljordanian","logo":""},
    {"name":"Philippine Airlines","slug":"philippine","logo":""},
    {"name":"Malaysia Airlines","slug":"malaysia","logo":""},
    {"name":"Garuda Indonesia","slug":"garuda","logo":""},
    {"name":"Hainan Airlines","slug":"hainan","logo":""},
    {"name":"IndiGo","slug":"indigo","logo":""},
    {"name":"Virgin Australia","slug":"virginaustralia","logo":""},
    {"name":"Fiji Airways","slug":"fiji","logo":""},
]

CHECKIN_LINKS: dict[str, str] = {
    "euroatlantic":"https://www.euroatlantic.pt/","azores":"https://www.azoresairlines.pt/pt/check-in","flybondi":"https://flybondi.com/br",
    "paranair":"https://www.paranair.com/","etihad":"https://www.etihad.com/pt-br/manage/check-in","finnair":"https://www.finnair.com/br-pt/check-in",
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

# Apelidos das companhias acrescentadas em 06/11/2026 (reconhece o nome digitado).
ALIASES.update({
    "euroatlantic": "euroatlantic", "euroatlantic airways": "euroatlantic", "euro atlantic": "euroatlantic",
    "azores airlines": "azores", "azores": "azores", "sata": "azores",
    "flybondi": "flybondi", "paranair": "paranair", "etihad": "etihad", "etihad airways": "etihad",
    "finnair": "finnair", "aer lingus": "aerlingus", "air transat": "airtransat", "air india": "airindia",
    "austrian": "austrian", "austrian airlines": "austrian", "brussels airlines": "brussels", "cathay pacific": "cathay",
    "edelweiss": "edelweiss", "iberojet": "iberojet", "jetblue": "jetblue", "lot polish": "lot", "norse atlantic": "norse",
    "plus ultra": "plusultra", "saudia": "saudia", "virgin atlantic": "virgin", "world2fly": "world2fly",
    "alaska airlines": "alaska", "air arabia": "airarabia", "air premia": "airpremia", "asiana": "asiana",
    "china eastern": "chinaeastern", "china southern": "chinasouthern", "eva air": "eva", "thai airways": "thai",
    "vietnam airlines": "vietnam", "kenya airways": "kenya", "egyptair": "egyptair", "sky high": "skyhigh",
})


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

# Apelidos do segundo lote (06/11/2026).
ALIASES.update({
    'azul conecta': 'azulconecta',
    'azulconecta': 'azulconecta',
    'map linhas aéreas': 'map',
    'map': 'map',
    'wingo': 'wingo',
    'volaris': 'volaris',
    'viva aerobus': 'vivaaerobus',
    'vivaaerobus': 'vivaaerobus',
    'spirit airlines': 'spirit',
    'spirit': 'spirit',
    'frontier airlines': 'frontier',
    'frontier': 'frontier',
    'southwest airlines': 'southwest',
    'southwest': 'southwest',
    'conviasa': 'conviasa',
    'estelar': 'estelar',
    'laser airlines': 'laser',
    'laser': 'laser',
    'avior airlines': 'avior',
    'avior': 'avior',
    'cubana de aviación': 'cubana',
    'cubana': 'cubana',
    'ryanair': 'ryanair',
    'easyjet': 'easyjet',
    'vueling': 'vueling',
    'volotea': 'volotea',
    'transavia': 'transavia',
    'eurowings': 'eurowings',
    'wizz air': 'wizzair',
    'wizzair': 'wizzair',
    'sas scandinavian': 'sas',
    'sas': 'sas',
    'icelandair': 'icelandair',
    'aegean airlines': 'aegean',
    'aegean': 'aegean',
    'air serbia': 'airserbia',
    'airserbia': 'airserbia',
    'pegasus airlines': 'pegasus',
    'pegasus': 'pegasus',
    'binter': 'binter',
    'cabo verde airlines': 'caboverde',
    'caboverde': 'caboverde',
    'air senegal': 'airsenegal',
    'airsenegal': 'airsenegal',
    "air côte d'ivoire": 'aircotedivoire',
    'aircotedivoire': 'aircotedivoire',
    'rwandair': 'rwandair',
    'oman air': 'omanair',
    'omanair': 'omanair',
    'gulf air': 'gulfair',
    'gulfair': 'gulfair',
    'flydubai': 'flydubai',
    'royal jordanian': 'royaljordanian',
    'royaljordanian': 'royaljordanian',
    'philippine airlines': 'philippine',
    'philippine': 'philippine',
    'malaysia airlines': 'malaysia',
    'malaysia': 'malaysia',
    'garuda indonesia': 'garuda',
    'garuda': 'garuda',
    'hainan airlines': 'hainan',
    'hainan': 'hainan',
    'indigo': 'indigo',
    'virgin australia': 'virginaustralia',
    'virginaustralia': 'virginaustralia',
    'fiji airways': 'fiji',
    'fiji': 'fiji',
    'tudoazul conecta': 'azulconecta',
    'wizz': 'wizzair',
    'scandinavian': 'sas',
    'cabo verde': 'caboverde',
    'tacv': 'caboverde',
    "air cote d'ivoire": 'aircotedivoire',
    'air cote d ivoire': 'aircotedivoire',
    'air côte d ivoire': 'aircotedivoire',
})

# Companhias sem programa de milhas utilizável na agência: a cotação é feita
# pelo valor total do site com desconto opcional (tipo "Valor do site").
NO_MILES_AIRLINE_SLUGS: frozenset[str] = frozenset({
    "amaszonas", "arajet", "condor", "jetsmart", "panamair", "voepass", "sky",
    "euroatlantic", "flybondi", "paranair", "iberojet", "norse", "plusultra", "world2fly",
    "skyhigh", "airpremia", "airtransat", "level", "airarabia",
    "map", "wingo", "volaris", "vivaaerobus", "conviasa", "estelar", "laser", "avior", "cubana",
    "ryanair", "easyjet", "wizzair", "volotea", "pegasus",
    "caboverde", "airsenegal", "aircotedivoire", "indigo",
})

# Companhias de operação nacional (Brasil).
NATIONAL_AIRLINE_SLUGS: frozenset[str] = frozenset({"voepass", "azulconecta", "map"})
