import crypto from 'node:crypto';
import { issueSignedToken, presignUrl } from '@vercel/blob';

function b64urlDecode(value) {
  const padded = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
  const pad = '='.repeat((4 - (padded.length % 4)) % 4);
  return Buffer.from(padded + pad, 'base64');
}

function verifyIntent(intent) {
  const [body, signature] = String(intent || '').split('.', 2);
  if (!body || !signature) throw new Error('Autorização inválida.');
  const secret = process.env.SECRET_KEY;
  if (!secret) throw new Error('SECRET_KEY não configurada.');

  const expected = crypto.createHmac('sha256', secret).update(body, 'ascii').digest();
  const received = b64urlDecode(signature);
  if (expected.length !== received.length || !crypto.timingSafeEqual(expected, received)) {
    throw new Error('Autorização inválida.');
  }

  const payload = JSON.parse(b64urlDecode(body).toString('utf8'));
  if (!payload || payload.v !== 1 || !payload.uid || !payload.pathname || !payload.op) {
    throw new Error('Autorização incompleta.');
  }
  if (Number(payload.exp || 0) < Math.floor(Date.now() / 1000)) {
    throw new Error('Autorização expirada.');
  }
  if (!String(payload.pathname).startsWith(`users/${Number(payload.uid)}/avatars/`)) {
    throw new Error('Destino do avatar inválido.');
  }
  if (!['put', 'get'].includes(payload.op)) throw new Error('Operação inválida.');
  if (payload.op === 'put' && !['image/jpeg', 'image/png', 'image/webp'].includes(String(payload.ct))) {
    throw new Error('Formato de imagem não permitido.');
  }
  return payload;
}

async function makePresigned(payload) {
  const validUntil = Date.now() + 5 * 60 * 1000;
  const tokenOptions = {
    pathname: payload.pathname,
    operations: [payload.op],
    validUntil,
  };
  if (payload.op === 'put') {
    tokenOptions.allowedContentTypes = [payload.ct];
    tokenOptions.maximumSizeInBytes = Math.min(Number(payload.max || 10485760), 10 * 1024 * 1024);
  }
  const signedToken = await issueSignedToken(tokenOptions);
  return presignUrl(signedToken, {
    pathname: payload.pathname,
    operation: payload.op,
    validUntil,
    ...(payload.op === 'get' ? { useCache: false } : {}),
  });
}

export default async function handler(request) {
  try {
    if (request.method === 'GET') {
      const url = new URL(request.url);
      const payload = verifyIntent(url.searchParams.get('intent'));
      if (payload.op !== 'get') return Response.json({ error: 'Operação inválida.' }, { status: 400 });
      const { presignedUrl } = await makePresigned(payload);
      return Response.redirect(presignedUrl, 307);
    }

    if (request.method === 'POST') {
      const body = await request.json();
      const payload = verifyIntent(body?.intent);
      if (payload.op !== 'put') return Response.json({ error: 'Operação inválida.' }, { status: 400 });
      const { presignedUrl } = await makePresigned(payload);
      return Response.json({ presignedUrl, pathname: payload.pathname });
    }

    return Response.json({ error: 'Método não permitido.' }, { status: 405 });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : 'Falha ao preparar o Blob.' },
      { status: 400 },
    );
  }
}
