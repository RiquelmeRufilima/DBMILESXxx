"""Pure tests of the optional route/stop feature; no DB or Neon access."""
from app.services.flight_itinerary import normalize_itinerary


ROUTES = [
    {"key": "outbound", "origin": "CNF", "destination": "FOR"},
    {"key": "return", "origin": "FOR", "destination": "CNF"},
]


def test_absent_does_not_add_cost_or_mandate_stop():
    item = normalize_itinerary(None, ROUTES)
    assert item["sides"] == []
    assert item["extra_bags_cost"] == 0
    assert item["charge_extra_bags"] is False


def test_direct_and_stops_are_independent():
    item = normalize_itinerary({"sides": [
        {"key": "outbound", "status": "stops", "stops": ["BSB"], "legs": [
            {"partner": "LATAM", "operator":"GOL", "fare": "Light", "cabin":"Econômica"},
            {"partner": "AZUL", "fare": "Flex", "cabin": "Executiva"},
        ]},
        {"key": "return", "status": "direct", "stops": ["GRU"], "legs": [{"partner":"GOL"}]},
    ]}, ROUTES)
    ida, volta = item['sides']
    assert ida['stops'] == ['BSB']
    assert [(x['origin'],x['destination']) for x in ida['legs']] == [('CNF','BSB'),('BSB','FOR')]
    assert ida['legs'][0]['operator'] == 'GOL'
    assert ida['legs'][1]['cabin'] == 'Executiva'
    assert volta['status'] == 'direct' and volta['stops'] == []
    assert len(volta['legs']) == 1 and volta['legs'][0]['partner'] == 'GOL'


def test_paid_bags_opt_in_and_price_is_not_double_charged_by_default():
    payload = {"sides": [{"key":"outbound", "status":"direct", "legs":[
        {"extra_bags":2,"extra_cost":160,"extra_sale":200,"extra_weight":23,"extra_passenger":"Cliente 1"}
    ]}]}
    no = normalize_itinerary(payload, ROUTES)
    assert no['charge_extra_bags'] is False
    assert no['extra_bags_cost'] == 320 and no['extra_bags_sale'] == 400
    assert no['sides'][0]['legs'][0]['extra_passenger'] == 'Cliente 1'
    payload['charge_extra_bags'] = True
    yes = normalize_itinerary(payload, ROUTES)
    assert yes['charge_extra_bags'] is True


def test_total_and_stop_wait_using_explicit_timezone():
    payload={"sides":[{"key":"outbound", "status":"stops", "stops":["BSB"], "legs":[
      {"departure":"2026-11-23T08:00", "origin_tz":"-03:00", "arrival":"2026-11-23T09:20", "destination_tz":"-03:00"},
      {"departure":"2026-11-23T11:00", "origin_tz":"-03:00", "arrival":"2026-11-23T13:30", "destination_tz":"-03:00"}
    ]}]}
    side=normalize_itinerary(payload,ROUTES)['sides'][0]
    assert side['wait_minutes']==[100]
    assert side['duration_minutes']==330
    payload['sides'][0]['legs'][0]['origin_tz']=''
    assert normalize_itinerary(payload,ROUTES)['sides'][0]['duration_minutes'] is None


def test_timezone_change_and_overnight():
    routes=[{"key":"outbound","origin":"FOR","destination":"LIS"}]
    item=normalize_itinerary({"sides":[{"key":"outbound","status":"direct","legs":[
        {"departure":"2026-11-23T23:00","origin_tz":"-03:00","arrival":"2026-11-24T10:00","destination_tz":"+00:00"}
    ]}]},routes)
    assert item['sides'][0]['duration_minutes']==480


def test_unknown_segment_and_malicious_values_ignored():
    item=normalize_itinerary({"charge_extra_bags": "true", "sides":[
      {"key":"return", "status":"stops", "stops":["<script>","GRU","ABC","CDF","DEF","XYZ"],
       "legs":[{"extra_bags":10**7,"extra_cost":"nan","operator":"<img onerror=...>"}]},
      {"key":"forged_company", "status":"direct", "legs":[{"extra_cost":999999}]}
    ]},ROUTES)
    assert len(item['sides'])==1
    assert item['sides'][0]['stops']==['GRU','ABC','CDF']
    assert item['sides'][0]['legs'][0]['extra_bags']<=10
    assert item['sides'][0]['legs'][0]['extra_cost']==0
    assert item['charge_extra_bags'] is False


def test_without_valid_stop_does_not_invent_connection():
    val=normalize_itinerary({"sides":[{"key":"outbound","status":"stops","stops":["", "CNF", "#"],"legs":[]}]},ROUTES)
    assert val['sides'][0]['status']=='direct'


def test_total_wait_not_invented_on_inverted_times():
    val=normalize_itinerary({"sides":[{"key":"outbound","status":"direct", "legs":[
      {"departure":"2026-11-23T12:00","origin_tz":"-03:00","arrival":"2026-11-23T11:00","destination_tz":"-03:00"}]}]},ROUTES)
    assert val['sides'][0]['duration_minutes'] is None
