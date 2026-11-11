"""robots.txt, sitemap.xml e llms.txt (gerados na hora, com o domínio certo)."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

from ..services import seo

router = APIRouter(tags=["seo"])

# Guardados 1 dia na CDN do Vercel: quase não gastam execuções da função.
_CACHE = {
    "Cache-Control": "public, max-age=3600",
    "Vercel-CDN-Cache-Control": "max-age=86400",
}


@router.api_route("/robots.txt", methods=["GET", "HEAD"], include_in_schema=False)
def robots_txt():
    return PlainTextResponse(seo.robots_txt(), headers=_CACHE)


@router.api_route("/sitemap.xml", methods=["GET", "HEAD"], include_in_schema=False)
def sitemap_xml():
    return Response(seo.sitemap_xml(), media_type="application/xml", headers=_CACHE)


@router.api_route("/llms.txt", methods=["GET", "HEAD"], include_in_schema=False)
def llms_txt():
    return PlainTextResponse(seo.llms_txt(), media_type="text/markdown; charset=utf-8", headers=_CACHE)
