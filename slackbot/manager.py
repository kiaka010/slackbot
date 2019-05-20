# -*- coding: utf-8 -*-

import os
import logging
from glob import glob
from six import PY2
from importlib import import_module
from slackbot import settings
from slackbot.utils import to_utf8
import itertools
logger = logging.getLogger(__name__)


class PluginsManager(object):
    def __init__(self):
        pass

    message = None
    user = None
    def set_message(self, message):
        self.message = message

    def set_user(self, user):
        self.user = user


    commands = {
        'member_joined': {},
        'respond_to': {},
        'listen_from': {},
        'listen_to': {},
        'react_to': {},
        'default_reply': {},
        'default_listen': {}
    }

    def init_plugins(self):
        if hasattr(settings, 'PLUGINS'):
            plugins = settings.PLUGINS
        else:
            plugins = 'slackbot.plugins'

        for plugin in plugins:
            self._load_plugins(plugin)

    def _load_plugins(self, plugin):
        logger.info('loading plugin "%s"', plugin)
        path_name = None

        if PY2:
            import imp

            for mod in plugin.split('.'):
                if path_name is not None:
                    path_name = [path_name]
                _, path_name, _ = imp.find_module(mod, path_name)
        else:
            from importlib.util import find_spec as importlib_find

            path_name = importlib_find(plugin)
            try:
                path_name = path_name.submodule_search_locations[0]
            except TypeError:
                path_name = path_name.origin

        module_list = [plugin]
        if not path_name.endswith('.py'):
            module_list = glob('{}/[!_]*.py'.format(path_name))
            module_list = ['.'.join((plugin, os.path.split(f)[-1][:-3])) for f
                           in module_list]
        for module in module_list:
            try:
                import_module(module)
            except:
                # TODO Better exception handling
                logger.exception('Failed to import %s', module)

    def get_plugins(self, category, text):
        has_matching_plugin = False
        if text is None:
            text = ''

        def get_match(mmmm, texts):
            logger.info(mmmm)
            logger.info(category)
            logger.info(self.commands[category][mmmm])
            logger.info(hasattr(self.commands[category][mmmm], 'match_all'))
            if mmmm in self.commands[category] and hasattr(self.commands[category][mmmm], 'match_all') and self.commands[category][mmmm].match_all:
                return mmmm.finditer(texts)
            if isinstance(mmmm, tuple):
                match, _ = mmmm
                return match.search(texts)
            return mmmm.search(texts)


        for matcher in self.commands[category]:
            if isinstance(matcher, tuple):
                match, user, channel = matcher
                # if not a direct message
                # and a set channel not specified
                # and the message channel is in the blacklist
                if category not in ['respond_to', 'default_reply'] and channel is None:
                    if 'channel' in self.message and self.message['channel'] in settings.CHANNEL_BLACK_LIST:
                        # logger.debug("Black Listed channel & override not found")
                        yield None, None
                        continue

                    elif 'item' in self.message and 'channel' in self.message['item'] and self.message['item']['channel'] in settings.CHANNEL_BLACK_LIST:
                        # logger.debug("Black Listed channel & override not found")
                        yield None, None
                        continue

                if channel is not None and channel != self.message['channel']:
                    # logger.debug('Channel set But Doesnt Match')
                    yield None, None
                    continue
                if user is not None and user != self.message['user']:
                    # logger.debug('User set But Doesnt Match')
                    yield None, None
                    continue
                m = get_match(matcher, text)

                if m:
                    has_matching_plugin = True
                    yield self.commands[category][matcher], to_utf8(m.groups())
            else:
                if category not in ['respond_to', 'default_reply']:
                    if 'channel' in self.message and self.message['channel'] in settings.CHANNEL_BLACK_LIST:
                        # logger.debug("Black Listed channel & override not found in matcher")
                        yield None, None
                        continue

                    elif 'item' in self.message and 'channel' in self.message['item'] and self.message['item']['channel'] in settings.CHANNEL_BLACK_LIST:
                        # logger.debug("Black Listed channel & override not found in matcher")
                        yield None, None
                        continue

                m = get_match(matcher, text)
                if m and hasattr(self.commands[category][matcher], 'match_all') and self.commands[category][matcher].match_all:
                    match_groups = []
                    for group in m:
                        match_groups.append(to_utf8(group.groups()))
                    if match_groups:
                        has_matching_plugin = True
                        match_groups.sort()
                        match_groups = list(match_groups for match_groups,_ in itertools.groupby(match_groups))
                        yield self.commands[category][matcher], match_groups
                elif m:
                    has_matching_plugin = True
                    yield self.commands[category][matcher], to_utf8(m.groups())

        if not has_matching_plugin:
            yield None, None
