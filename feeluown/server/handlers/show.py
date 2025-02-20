"""
feeluown.cmds.show
~~~~~~~~~~~~~~~~~

处理 ``show`` 命令::

    show fuo://               # 列出所有 provider
    show fuo://local/songs    # 显示本地所有歌曲
    show fuo://local/songs/1  # 显示一首歌的详细信息
"""
import logging
from functools import wraps
from urllib.parse import urlparse

from feeluown.utils.utils import to_readall_reader
from feeluown.utils.router import Router, NotFound
from feeluown.library import NotSupported, ProviderV2, ProviderFlags as PF
from feeluown.models.uri import NS_TYPE_MAP, TYPE_NS_MAP
from feeluown.models import ModelType

from .base import AbstractHandler
from .excs import CmdException

logger = logging.getLogger(__name__)


router = Router()
route = router.route


class ShowHandler(AbstractHandler):
    cmds = 'show'

    def handle(self, cmd):
        if cmd.args:
            furi = cmd.args[0]
        else:
            furi = 'fuo://'
        r = urlparse(furi)
        path = f'/{r.netloc}{r.path}'
        logger.debug(f'请求 path: {path}')
        try:
            rv = router.dispatch(path, {'library': self.library,
                                        'session': self.session})
        except NotFound:
            raise CmdException(f'path {path} not found') from None
        except NotSupported as e:
            raise CmdException(str(e)) from None
        return rv


def get_model_or_raise(provider, model_type, model_id):
    # pylint: disable=redefined-outer-name
    model = None
    ns = TYPE_NS_MAP[model_type]
    # FIXME: use library.check_flags
    if isinstance(provider, ProviderV2):
        if provider.check_flags(model_type, PF.get):
            model = provider.model_get(model_type, model_id)
    else:
        model_cls = provider.get_model_cls(model_type)
        model = model_cls.get(model_id)
    if model is None:
        raise CmdException(
            f'{ns}:{model_id} not found in provider:{provider.identifier}')
    return model


def use_provider(func):
    @wraps(func)
    def wrapper(req, **kwargs):
        provider_id = kwargs.pop('provider')
        provider = req.ctx['library'].get(provider_id)
        if provider is None:
            raise CmdException(f'provider:{provider_id} not found')
        return func(req, provider, **kwargs)
    return wrapper


def create_model_handler(ns, model_type):
    @route(f'/<provider>/{ns}/<model_id>')
    @use_provider
    def handle(req, provider, model_id):
        # special cases:
        # fuo://<provider>/users/me -> show current logged user
        if model_type == ModelType.user:
            if model_id == 'me':
                user = getattr(provider, '_user', None)
                if user is None:
                    raise CmdException(
                        f'log in provider:{provider.identifier} first')
                return user
        model = get_model_or_raise(provider, model_type, model_id)
        return model


@route('/')
def list_providers(req):
    return req.ctx['library'].list()


@route('/server/sessions/me')
def current_session(req):
    """
    Currently only used for debugging.
    """
    session = req.ctx['session']
    options = session.options
    result = []
    result.append(f'   rpc_version: {options.rpc_version}')
    result.append(f'pubsub_version: {options.pubsub_version}')
    return '\n'.join(result)


for ns_, model_type_ in NS_TYPE_MAP.items():
    create_model_handler(ns_, model_type_)


@route('/<provider>/songs/<sid>/lyric')
@use_provider
def lyric_(req, provider, sid):
    song = get_model_or_raise(provider, ModelType.song, sid)
    library = req.ctx['library']
    lyric = library.song_get_lyric(song)
    if lyric is None:
        return ''
    return lyric.content


@route('/<provider>/playlists/<pid>/songs')
@use_provider
def playlist_songs(req, provider, pid):
    playlist = get_model_or_raise(provider, ModelType.playlist, pid)
    return to_readall_reader(playlist, 'songs').readall()


@route('/<provider>/artists/<aid>/albums')
@use_provider
def albums_of_artist(req, provider, aid):
    """show all albums of an artist identified by artist id"""
    artist = get_model_or_raise(provider, ModelType.artist, aid)
    return to_readall_reader(artist, 'albums').readall()
