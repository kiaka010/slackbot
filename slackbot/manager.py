# -*- coding: utf-8 -*-

import os
import logging
from glob import glob
from six import PY2
from importlib import import_module
from slackbot import settings
from slackbot.utils import to_utf8

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
        for matcher in self.commands[category]:
            if isinstance(matcher, tuple):
                match, user, channel = matcher
                logger.info(match)
                # if not a direct message
                # and a set channel not specified
                # and the message channel is in the blacklist
                logger.info(self.message)
                if category not in ['respond_to', 'default_reply'] and channel is None and self.message['channel'] in settings.CHANNEL_BLACK_LIST:
                    logger.debug("Black Listed channel & override not found")
                    yield None, None
                    continue

                if channel is not None and channel != self.message['channel']:
                    logger.debug('Channel set But Doesnt Match')
                    yield None, None
                    continue
                if user is not None and user != self.message['user']:
                    logger.debug('User set But Doesnt Match')
                    yield None, None
                    continue
                logger.info("pebcak")
                m = match.search(text)
                if m:
                    has_matching_plugin = True
                    yield self.commands[category][matcher], to_utf8(m.groups())
            else:
                if category not in ['respond_to', 'default_reply'] and self.message['channel'] in settings.CHANNEL_BLACK_LIST:
                    logger.debug("Black Listed channel & override not found in matcher")
                    yield None, None
                    continue

                m = matcher.search(text)
                if m:
                    has_matching_plugin = True
                    yield self.commands[category][matcher], to_utf8(m.groups())

        if not has_matching_plugin:
            yield None, None
