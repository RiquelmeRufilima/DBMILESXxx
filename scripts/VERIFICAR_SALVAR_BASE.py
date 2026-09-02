from app.main import app
paths = []
for r in app.routes:
    path = getattr(r, 'path', '')
    methods = sorted(getattr(r, 'methods', []) or [])
    if path.startswith('/calculations'):
        paths.append((path, methods))
print('Rotas /calculations carregadas:')
for path, methods in paths:
    print(' ', ','.join(methods), path)
if not any(path == '/calculations/base/save' and 'POST' in methods for path, methods in paths):
    print('\nERRO: POST /calculations/base/save NAO foi registrada.')
    raise SystemExit(1)
print('\nOK: POST /calculations/base/save registrada.')
