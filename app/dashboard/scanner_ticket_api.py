"""SC03 bounded local ticket commands. Same-origin middleware remains owner."""
import asyncio
from aiohttp import web
from .local_security import read_json, PublicRequestError
from app.comparison.scanner_tickets import Tickets, TicketError, selector
from app.comparison.calculation_control import CalculationStopped


def mount(app, scanner):
    def fresh_selected(capture):
        try:
            return scanner._capture_selected(capture)
        except (TicketError,CalculationStopped):
            raise
        except Exception:
            # A failed fresh proof must withdraw action authority. Never expose
            # database exception text or leave an old successful status ready.
            raise TicketError('ticket_current_proof_unavailable') from None
    tickets=Tickets(scanner.projection,fresh_selected=fresh_selected,stopped=scanner.stopped,
                    current_selected=getattr(scanner,'_selection_snapshot',None),
                    collection_stopped=(lambda:scanner.collection_stopped)
                        if hasattr(scanner,'collection_stopped') else None)
    sweep=None
    async def cleanup():
        while True:
            await asyncio.sleep(1)
            tickets.cleanup()
    def start():
        nonlocal sweep
        scanner.start()
        scanner._withdraw_if_stopped()
        if sweep is None:sweep=asyncio.create_task(cleanup())
    async def post(req):
        try:
            if req.query:raise TicketError('ticket_query_invalid')
            command=await read_json(req,max_size=4096)
            start()
            return web.json_response(await tickets.command(command))
        except TicketError as exc:
            return web.json_response(dict(error=str(exc),provider_requests=0),status=409)
        except (ValueError,TypeError,PublicRequestError):
            # Fixed errors only; never echo arbitrary input/financial exceptions.
            return web.json_response(dict(error='ticket_command_rejected',provider_requests=0),status=409)
    async def get(req):
        try:
            if set(req.query)!={'client_id','ticket_id'} or any(len(v)>64 for v in req.query.values()):
                raise TicketError('ticket_query_invalid')
            start()
            return web.json_response(tickets.inspect(req.query['client_id'],req.query['ticket_id']))
        except (TicketError,ValueError,TypeError):
            return web.json_response(dict(error='ticket_not_available',provider_requests=0),status=409)
    async def bind(req):
        try:
            fields={'server_id','epoch','row_id','dependency_revision','economic_revision'}
            if set(req.query)!=fields or any(len(v)>256 for v in req.query.values()):raise TicketError('ticket_binding_invalid')
            start()
            p=scanner.projection
            with p.lock:
                if scanner.stopped() or p.stopped:
                    raise TicketError('ticket_stopped' if p.stopped else 'ticket_current_proof_unavailable')
                row=p.rows.get(req.query['row_id'])
                if row is None or p.server_id!=req.query['server_id'] or p.epoch!=req.query['epoch'] or any(row[k]!=req.query[k] for k in ('dependency_revision','economic_revision')):
                    raise TicketError('ticket_selection_changed')
                bound=selector(p,row)
                _,reason=tickets._capture(bound,initial=True)
                if reason:raise TicketError('ticket_selection_'+reason)
            return web.json_response(dict(version='predict-ticket-selection-1',selection=bound,provider_requests=0))
        except TicketError as exc:
            return web.json_response(dict(error=str(exc),provider_requests=0),status=409)
    async def close(app):
        if sweep:
            sweep.cancel()
            try:await sweep
            except asyncio.CancelledError:pass
        await tickets.close()
    app.router.add_get('/api/scanner/ticket/binding',bind)
    app.router.add_post('/api/scanner/ticket',post)
    app.router.add_get('/api/scanner/ticket',get)
    app.on_cleanup.append(close)
    return tickets
