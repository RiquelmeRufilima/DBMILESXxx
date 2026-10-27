from pathlib import Path
import re
ROOT=Path(__file__).resolve().parent
models=ROOT/'app'/'models.py'
if not models.exists(): raise SystemExit('ERRO: execute na raiz do DBMILESX.')
text=models.read_text(encoding='utf-8')
changed=False
old='from sqlalchemy.orm import Mapped, mapped_column, relationship'
if old in text:
    text=text.replace(old,'from sqlalchemy.orm import Mapped, mapped_column, relationship as orm_relationship',1)
    text=re.sub(r'=\s*relationship\(', '= orm_relationship(', text)
    changed=True
if changed:
    models.write_text(text,encoding='utf-8')
    print('OK: conflito relationship corrigido em app/models.py')
else:
    print('INFO: app/models.py já não possui o conflito conhecido.')
