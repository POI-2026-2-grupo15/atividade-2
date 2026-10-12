"""Limites ASGI, inclusive antes de concluir o parsing multipart."""

from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.schemas import MIB


class ResourceLimits:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.active = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = 17 * MIB if scope["path"] in {"/hash", "/verify"} else 4096
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0"))
            if declared < 0:
                raise ValueError
        except ValueError:
            await JSONResponse({"detail": "Content-Length inválido"}, 400)(scope, receive, send)
            return
        if declared > limit:
            await JSONResponse({"detail": "Corpo da requisição excede o limite"}, 413)(scope, receive, send)
            return
        if self.active >= 8:
            await JSONResponse({"detail": "Worker ocupado"}, 503)(scope, receive, send)
            return
        received = 0
        exceeded = False

        async def bounded_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    detail = "Corpo da requisição excede o limite"
                    if headers.get(b"content-type", b"").startswith(b"multipart/form-data"):
                        # Starlette fecha os arquivos temporários neste caminho de erro.
                        raise MultiPartException(detail)
                    raise HTTPException(413, detail)
            return message

        async def bounded_send(message: Message) -> None:
            if exceeded and message["type"] == "http.response.start":
                # O parser converte MultiPartException em 400; tamanho exige 413.
                message = {**message, "status": 413}
            await send(message)

        self.active += 1
        try:
            await self.app(scope, bounded_receive, bounded_send)
        finally:
            self.active -= 1
