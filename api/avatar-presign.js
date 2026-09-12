import crypto from 'node:crypto';
import { issueSignedToken, presignUrl } from '@vercel/blob';

function b64urlDecode(value) {
  const padded = String(value || '').replace(/-/g, '+').replace(/_/g, '/');
  const pad = '='.repeat((4 - (padded.length % 4)) % 4);
  return Buffer.from(padded + pad, 'base64');
}

function verifyIntent(intent) {
  const [body, signature] = String(intent || '').split('.', 2);
  if (!body || !signature) throw new Error('Autorização de upload inválida.');
  const secret = process.env.SECRET_KEY;
  if (!secret) throw new Error('SECRET_KEY não configurada.');

  const expected = crypto.createHmac('sha256', secret).update(body, 'ascii').digest();
  const received = b64urlDecode(signature);
  if (expected.length !== received.length || !crypto.timingSafeEqual(expected, received)) {
    throw new Error('Autorização de upload inválida.');
  }

  const payload = JSON.parse(b64urlDecode(body).toString('utf8'));
  if (!payload || payload.v !== 1 || !payload.uid || !payload.pathname || !payload.ct) {
    throw new Error('Autorização de upload incompleta.');
  }
  if (Number(payload.exp || 0) < Math.floor(Date.now() / 1000)) {
    throw new Error('Autorização de upload expirada.');
  }
  if (!String(payload.pathname).startsWith(`users/${Number(payload.uid)}/avatars/`)) {
    throw new Error('Destino do avatar inválido.');
  }
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(String(payload.ct))) {
    throw new Error('Formato de imagem não permitido.');
  }
  return payload;
}

export default async function handler(request) {
  if (request.method !== 'POST') {
    return Response.json({ error: 'Método não permitido.' }, { status: 405 });
  }

  try {
    const body = await request.json();
    const payload = verifyIntent(body?.intent);
    const maxSize = Math.min(Number(payload.max || 10485760), 10 * 1024 * 1024);
    const validUntil = Date.now() + 5 * 60 * 1000;

    const signedToken = await issueSignedToken({
      pathname: payload.pathname,
      operations: ['put'],
      allowedContentTypes: [payload.ct],
      maximumSizeInBytes: maxSize,
      validUntil,
    });

    const { presignedUrl } = await presignUrl(signedToken, {
      pathname: payload.pathname,
      operation: 'put',
      validUntil,
    });

    return Response.json({ presignedUrl, pathname: payload.pathname });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : 'Falha ao preparar upload.' },
      { status: 400 },
    );
  }
}
