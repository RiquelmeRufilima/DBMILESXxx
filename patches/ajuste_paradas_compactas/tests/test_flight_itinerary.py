"""Testes puros da revisão compacta: paradas opcionais, sem duplicar bagagem/cálculo."""
from app.services.flight_itinerary import normalize_itinerary

ROUTES=[{'key':'outbound','origin':'REC','destination':'GIG'}, {'key':'return','origin':'GIG','destination':'REC'}]


def test_sem_preenchimento_nao_exige_paradas_nem_cria_custos():
    value=normalize_itinerary(None,ROUTES)
    assert value['sides']==[]
    assert value['charge_extra_bags'] is False
    assert value['extra_bags_cost']==0
    assert value['bags_applies_to']=='all'


def test_ida_com_parada_volta_direta_parcerias_distintas():
    data={'bags_applies_to':'outbound','sides':[
      {'key':'outbound','status':'stops','stops':['BSB'],'fare':'Flex','cabin':'Executiva','included_bags':'1',
       'legs':[{'partner':'LATAM'},{'partner':'GOL'}]},
      {'key':'return','status':'direct','stops':['GRU'],'fare':'Light','cabin':'Econômica','included_bags':'0',
       'legs':[{'partner':'AZUL'}]},
    ]}
    result=normalize_itinerary(data,ROUTES)
    ida,volta=result['sides']
    assert [(x['origin'],x['destination'],x['partner']) for x in ida['legs']]==[('REC','BSB','LATAM'),('BSB','GIG','GOL')]
    assert ida['fare']=='Flex' and ida['cabin']=='Executiva' and ida['included_bags']=='1'
    assert volta['status']=='direct' and len(volta['legs'])==1
    assert volta['fare']=='Light' and volta['included_bags']=='0'
    assert result['bags_applies_to']=='outbound'


def test_paradas_nao_criam_uma_bagagem_nova_para_cada_etapa():
    data={'charge_extra_bags':True, 'sides':[{'key':'outbound','status':'stops','stops':['BSB','GRU'],
      'legs':[{'extra_bags':5,'extra_cost':300,'extra_sale':400,'operator':'Outra', 'partner':'LATAM'},
              {'extra_bags':3,'extra_cost':200,'partner':'AZUL'}, {'extra_bags':1,'extra_cost':900,'partner':'GOL'}]}]}
    result=normalize_itinerary(data,ROUTES)
    assert len(result['sides'][0]['legs'])==3
    assert result['extra_bags_cost']==0 and result['extra_bags_sale']==0
    assert result['charge_extra_bags'] is False
    assert all('extra_bags' not in leg and 'operator' not in leg for leg in result['sides'][0]['legs'])


def test_bagagem_existente_pode_ser_designada_a_volta_sem_mudar_o_custo():
    item=normalize_itinerary({'bags_applies_to':'return','sides':[]},ROUTES)
    assert item['bags_applies_to']=='return' and item['extra_bags_cost']==0
    assert normalize_itinerary({'bags_applies_to':'forged'},ROUTES)['bags_applies_to']=='all'


def test_suporta_condicoes_anteriores_salvas_no_primeiro_trecho():
    item=normalize_itinerary({'sides':[{'key':'outbound','status':'direct','legs':[
       {'cabin':'Premium Economy','fare':'Standard','included_bags':2,'partner':'GOL'}
    ]}]},ROUTES)['sides'][0]
    assert item['cabin']=='Premium Economy' and item['fare']=='Standard' and item['included_bags']=='2'


def test_horarios_opcionais_sem_duracao_inventada():
    item=normalize_itinerary({'sides':[{'key':'outbound','status':'stops','stops':['BSB'],
       'legs':[{'departure':'2026-11-23T08:00'}, {'arrival':'2026-11-23T12:00'}]}]},ROUTES)['sides'][0]
    assert item['duration_minutes'] is None


def test_calcula_espera_e_duracao_quando_dados_completos():
    legs=[{'departure':'2026-11-23T08:00','arrival':'2026-11-23T09:20','origin_tz':'-03:00','destination_tz':'-03:00'},
          {'departure':'2026-11-23T11:00','arrival':'2026-11-23T13:30','origin_tz':'-03:00','destination_tz':'-03:00'}]
    side=normalize_itinerary({'sides':[{'key':'outbound','status':'stops','stops':['BSB'],'legs':legs}]},ROUTES)['sides'][0]
    assert side['wait_minutes']==[100] and side['duration_minutes']==330


def test_mudanca_de_fuso_e_madrugada():
    routes=[{'key':'one_way','origin':'FOR','destination':'LIS'}]
    item=normalize_itinerary({'sides':[{'key':'one_way','status':'direct','legs':[
       {'departure':'2026-11-23T23:00','origin_tz':'-03:00','arrival':'2026-11-24T10:00','destination_tz':'+00:00'}
    ]}]},routes)['sides'][0]
    assert item['duration_minutes']==480


def test_paradas_invalidas_nao_criam_trechos_falsos():
    side=normalize_itinerary({'sides':[{'key':'outbound','status':'stops','stops':['REC','<script>','BSB','GIG'],
      'legs':[{'partner':'LATAM'},{'partner':'GOL'}]}]},ROUTES)['sides'][0]
    assert side['stops']==['BSB'] and len(side['legs'])==2


def test_campos_desconhecidos_e_empresa_falsa_descartados():
    item=normalize_itinerary({'bags_applies_to':'some_other_company','sides':[
      {'key':'untrusted','status':'stops','stops':['BSB']},
      {'key':'outbound','status':'direct','legs':[{'operator':'<script>','partner':'LATAM'}]},
    ]},ROUTES)
    assert len(item['sides'])==1
    assert item['sides'][0]['legs'][0]['partner']=='LATAM'
    assert 'operator' not in item['sides'][0]['legs'][0]
    assert item['bags_applies_to']=='all'


def test_bagagem_zero_inteiro_nao_virar_desconhecida():
    side=normalize_itinerary({'sides':[{'key':'outbound','included_bags':0}]},ROUTES)['sides'][0]
    assert side['included_bags']=='0'
