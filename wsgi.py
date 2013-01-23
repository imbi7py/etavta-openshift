from __future__ import unicode_literals

from werkzeug.exceptions import NotFound
from clastic import Application, Middleware
from clastic.render.mako_templates import MakoRenderFactory

from schedule import Schedule, fm, ALL_LEGS

from localtime import get_pacific_time
from fetch import RAW_SCHED_DIR, get_newest_sched_dir


def home(schedule):
    #return {'pre_content': pformat([s for s in schedule.stations])}
    return {}


def parse_date_params(start_date, start_time):
    from datetime import datetime, date, time
    return None

def get_stops(schedule, name_index, station_name, sdate=None, stime=None):
    start_dt = parse_date_params(sdate, stime)
    start_dt = get_pacific_time(start_dt)
    station_name = name_index[station_name]
    stops = schedule.get_stops(station_name, start_dt)
    return {'stops': stops}


def not_found(*a, **kw):
    raise NotFound()


class ConstantsMiddleware(Middleware):
    def __init__(self, **kw):
        self.constants = kw

    def render(self, next, context):
        context.update(self.constants)
        return next()

CONSTANTS = {'LEGS': ALL_LEGS}


class HTTPCacheMiddleware(Middleware):
    cache_attrs = ('max_age', 's_maxage', 'no_cache', 'no_store',
                   'no_transform', 'must_revalidate', 'proxy_revalidate',
                   'public', 'private')
    def __init__(self,
                 max_age=None,
                 s_maxage=None,
                 no_cache=None,
                 no_store=None,
                 no_transform=None,
                 must_revalidate=None,
                 proxy_revalidate=None,
                 public=None,
                 private=None,
                 use_etags=True):
        for attr in self.cache_attrs:
            setattr(self, attr, locals()[attr])
        self.use_etags = use_etags

    def request(self, next, request):
        resp = next()
        if hasattr(resp, 'cache_control'):
            for attr in self.cache_attrs:
                cache_val = getattr(self, attr, None)
                if cache_val:
                    setattr(resp.cache_control, attr, cache_val)
            if self.use_etags and not resp.is_streamed:
                # TODO: do streamed responses too?
                resp.add_etag()
                resp.make_conditional(request)
        return resp


from gzip import GzipFile
from StringIO import StringIO
def compress(data, level=6):
    out = StringIO()
    f = GzipFile(fileobj=out, mode='wb', compresslevel=level)
    f.write(data)
    f.close()
    return out.getvalue()


class GzipMiddleware(Middleware):
    def __init__(self, compress_level=6):
        self.compress_level = compress_level

    def request(self, next, request):
        resp = next()
        # TODO: shortcut redirects/304s/responses without content?
        resp.vary.add('Accept-Encoding')
        if resp.content_encoding or not request.accept_encodings['gzip']:
            return resp

        if 'msie' in request.user_agent.browser:
            if not (resp.content_type.startswith('text/') or
                    'javascript' in resp.content_type):
                return resp

        if resp.is_streamed:
            return resp  # TODO
        else:
            comp_content = compress(resp.data, self.compress_level)
            if len(comp_content) >= len(resp.data):
                return resp
            resp.response = [comp_content]
            resp.content_length = len(comp_content)

        resp.content_encoding = 'gzip'
        # TODO: regenerate etag?
        return resp


def create_app(schedule_dir, template_dir):
    schedule = Schedule.from_directory(schedule_dir)
    resources = {'schedule': schedule,
                 'name_index': fm}
    subroutes = [('/', home, 'station_list.html'),
                 ('/<path:station_name>', get_stops, 'stop_times.html'),
                 ('/favicon.ico', not_found)]

    mako_response = MakoRenderFactory(template_dir)
    cc_mw = HTTPCacheMiddleware(max_age=30, must_revalidate=True)
    middlewares = [ConstantsMiddleware(**CONSTANTS), cc_mw, GzipMiddleware()]
    subapp = Application(subroutes, resources, mako_response, middlewares)

    routes = [('/', subapp), ('/v2/', subapp)]
    app = Application(routes)
    return app

sched_path = get_newest_sched_dir(RAW_SCHED_DIR)
if not sched_path:
    raise Exception('no schedules found')
application = create_app(sched_path, './templates')


if __name__ == '__main__':
    application.serve()
