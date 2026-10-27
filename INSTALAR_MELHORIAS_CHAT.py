from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent
APP = ROOT / 'app'
BASE = APP / 'templates' / 'base.html'
CHAT_TEMPLATES = [APP / 'templates' / 'company' / 'chat.html', APP / 'templates' / 'chat' / 'index.html']
COMPANY = APP / 'templates' / 'company' / 'dashboard.html'
STATIC = APP / 'static' / 'js'
SOURCE = ROOT / 'app' / 'static' / 'js'
FILES = ['private-chat-enhanced.js', 'chat-notifications.js']

def fail(msg):
    print('ERRO:', msg)
    raise SystemExit(1)

def backup(path):
    if path.exists():
        b = path.with_suffix(path.suffix + '.bak_chat_20261017')
        if not b.exists():
            shutil.copy2(path, b)

if not BASE.exists():
    fail('Execute este instalador na raiz do DBMILESX.')

STATIC.mkdir(parents=True, exist_ok=True)
for name in FILES:
    src = SOURCE / name
    if not src.exists():
        fail(f'Arquivo ausente no pacote: {src}')
    dst = STATIC / name
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    else:
        print(f'INFO: {name} já está no local correto; cópia ignorada.')

backup(BASE)
text = BASE.read_text(encoding='utf-8')
marker = 'chat-notifications.js?v=20261017'
if marker not in text:
    line = '  {% if user %}<script src="/static/js/chat-notifications.js?v=20261017" defer></script>{% endif %}\n'
    anchor = '{% block scripts %}{% endblock %}'
    if anchor in text:
        text = text.replace(anchor, line + anchor, 1)
    elif '</body>' in text:
        text = text.replace('</body>', line + '</body>', 1)
    else:
        fail('Não encontrei ponto seguro em base.html.')
BASE.write_text(text, encoding='utf-8')

found_chat = False
for path in CHAT_TEMPLATES:
    if not path.exists():
        continue
    found_chat = True
    backup(path)
    html = path.read_text(encoding='utf-8')
    html = re.sub(
        r'(<form\b[^>]*\bid=["\'](?:dbmChatForm|dbmCompose)["\'][^>]*)(>)',
        lambda m: m.group(1) + (' data-no-loader="1"' if 'data-no-loader' not in m.group(1) else '') + m.group(2),
        html, count=1, flags=re.I
    )
    enhanced = '<script src="/static/js/private-chat-enhanced.js?v=20261017" defer></script>'
    if enhanced not in html:
        pos = html.rfind('{% endblock %}')
        if pos >= 0:
            html = html[:pos] + enhanced + '\n' + html[pos:]
        else:
            html += '\n' + enhanced + '\n'
    path.write_text(html, encoding='utf-8')

if not found_chat:
    print('AVISO: nenhum template de chat conhecido foi encontrado. O som global ainda foi instalado.')

if COMPANY.exists():
    backup(COMPANY)
    html = COMPANY.read_text(encoding='utf-8')
    marker = 'DBMILESX_MEMBER_CHAT_BUTTONS_V1'
    if marker not in html:
        block = r'''
{# DBMILESX_MEMBER_CHAT_BUTTONS_V1 #}
<style>
.company-member-chat-button{display:inline-flex;align-items:center;justify-content:center;gap:6px;margin-left:auto;padding:7px 10px;border-radius:10px;border:1px solid color-mix(in srgb,var(--cyan) 42%,var(--border));background:color-mix(in srgb,var(--cyan) 10%,var(--panel-2));color:var(--text);font-size:.75rem;font-weight:900;text-decoration:none;white-space:nowrap}
.company-member-chat-button:hover{background:color-mix(in srgb,var(--cyan) 18%,var(--panel-2))}
@media(max-width:920px){.company-member-chat-button{width:100%;margin:8px 0 0}}
</style>
<script type="application/json" id="dbmCompanyChatMembers">
[
{% for member in members %}
  {"id":{{ member.id }},"email":{{ member.email|tojson }},"name":{{ member.name|tojson }},"contact_id":{{ (member.contact_id or '')|tojson }},"is_me":{{ 'true' if member.id == user.id else 'false' }}}{{ "," if not loop.last else "" }}
{% endfor %}
]
</script>
<script>
(() => {
  const dataNode=document.getElementById('dbmCompanyChatMembers');
  if(!dataNode) return;
  let members=[]; try{members=JSON.parse(dataNode.textContent||'[]')}catch(_){return}
  for(const member of members){
    if(member.is_me || !member.contact_id) continue;
    const candidates=[...document.querySelectorAll('article,div,li')].filter(el=>{
      const text=(el.textContent||'');
      return text.includes(member.email) && text.includes(member.name);
    });
    if(!candidates.length) continue;
    candidates.sort((a,b)=>a.getBoundingClientRect().width-b.getBoundingClientRect().width);
    const card=candidates[0];
    if(card.querySelector('.company-member-chat-button')) continue;
    const link=document.createElement('a');
    link.className='company-member-chat-button';
    link.href='/company/chat?contact='+encodeURIComponent(member.contact_id);
    link.dataset.noLoader='1';
    link.innerHTML='💬 <span>Iniciar conversa</span>';
    card.appendChild(link);
  }
})();
</script>
'''
        pos = html.rfind('{% endblock %}')
        if pos >= 0:
            html = html[:pos] + block + '\n' + html[pos:]
        else:
            html += block
        COMPANY.write_text(html, encoding='utf-8')
else:
    print('AVISO: app/templates/company/dashboard.html não encontrado; botão não foi instalado.')

print('OK - melhorias instaladas:')
print('  - som de nova mensagem em qualquer tela logada')
print('  - envio instantâneo sem loader global')
print('  - botão Iniciar conversa nos membros da empresa')
print('')
print('Agora faça:')
print('git add app/templates/base.html app/templates/company app/templates/chat app/static/js')
print('git commit -m "Melhora chat com som envio instantaneo e conversa por membro"')
print('git push')
