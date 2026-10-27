from pathlib import Path
ROOT=Path(__file__).resolve().parent
main=ROOT/'app'/'main.py'; templates=ROOT/'app'/'templates'
if not main.exists(): raise SystemExit('ERRO: execute na raiz do DBMILESX.')
text=main.read_text(encoding='utf-8')
if 'DBMILESX_PRIVATE_CHAT_V3' not in text:
    block='\n# DBMILESX_PRIVATE_CHAT_V3\nfrom .routers import private_chat as _private_chat\napp.include_router(_private_chat.router)\n\n'
    anchor='# Rotas de emergência ficam por último.'
    if anchor in text:text=text.replace(anchor,block+anchor,1)
    else:
        pos=text.find('@app.get("/health")')
        if pos<0: raise SystemExit('ERRO: ponto seguro não encontrado em main.py')
        text=text[:pos]+block+text[pos:]
    main.write_text(text,encoding='utf-8')
count=0
for html in templates.rglob('*.html'):
    raw=html.read_text(encoding='utf-8'); new=raw.replace('href="/company/chat"','href="/chat"')
    if new!=raw: html.write_text(new,encoding='utf-8'); count+=1
print('OK: chat instalado. Templates atualizados:',count)
