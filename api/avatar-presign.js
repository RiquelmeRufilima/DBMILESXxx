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
  if (!payload || payload.v !== 1 || !payload.uid || !payload.pathname) {
    throw new Error('Autorização incompleta.');
  }
  if (Number(payload.exp || 0) < Math.floor(Date.now() / 1000)) {
    throw new Error('Autorização expirada.');
  }
  if (!String(payload.pathname).startsWith(`users/${Number(payload.uid)}/avatars/`)) {
    throw new Error('Destino do avatar inválido.');
  }

  const op = String(payload.op || 'put');
  if (!['put', 'get'].includes(op)) throw new Error('Operação inválida.');

  if (op === 'put') {
    if (!payload.ct || !['image/jpeg', 'image/png', 'image/webp'].includes(String(payload.ct))) {
      throw new Error('Formato de imagem não permitido.');
    }
  }
  return { ...payload, op };
}

async function makePresigned(payload) {
  const validUntil = Date.now() + 5 * 60 * 1000;

  if (payload.op === 'get') {
    const signedToken = await issueSignedToken({
      pathname: payload.pathname,
      operations: ['get'],
      validUntil,
    });
    return presignUrl(signedToken, {
      pathname: payload.pathname,
      operation: 'get',
      validUntil,
      useCache: false,
    });
  }

  const maxSize = Math.min(Number(payload.max || 10485760), 10 * 1024 * 1024);
  const signedToken = await issueSignedToken({
    pathname: payload.pathname,
    operations: ['put'],
    allowedContentTypes: [payload.ct],
    maximumSizeInBytes: maxSize,
    validUntil,
  });
  return presignUrl(signedToken, {
    pathname: payload.pathname,
    operation: 'put',
    validUntil,
  });
}

export default async function handler(request) {
  try {
    const url = new URL(request.url);

    if (request.method === 'GET' && url.searchParams.get('mode') === 'get') {
      const payload = verifyIntent(url.searchParams.get('intent'));
      if (payload.op !== 'get') throw new Error('Operação inválida.');
      const { presignedUrl } = await makePresigned(payload);
      return Response.redirect(presignedUrl, 302);
    }

    if (request.method !== 'POST') {
      return Response.json({ error: 'Método não permitido.' }, { status: 405 });
    }

    const body = await request.json();
    const payload = verifyIntent(body?.intent);
    if (payload.op !== 'put') throw new Error('Operação inválida.');
    const { presignedUrl } = await makePresigned(payload);
    return Response.json({ presignedUrl, pathname: payload.pathname });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : 'Falha ao preparar acesso ao Blob.' },
      { status: 400 },
    );
  }
}
