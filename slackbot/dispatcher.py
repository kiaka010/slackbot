# -*- coding: utf-8 -*-

from __future__ import absolute_import
import logging
import re
import time
import traceback
from functools import wraps

import six
from slackbot.manager import PluginsManager
from slackbot.utils import WorkerPool
from slackbot import settings

logger = logging.getLogger(__name__)


class MessageDispatcher(object):
    def __init__(self, slackclient, plugins, errors_to):
        self._client = slackclient
        self._pool = WorkerPool(self.dispatch_msg)
        self._plugins = plugins
        self._errors_to = None
        if errors_to:
            self._errors_to = self._client.find_channel_by_name(errors_to)
            if not self._errors_to:
                raise ValueError(
                    'Could not find errors_to recipient {!r}'.format(
                        errors_to))

        alias_regex = ''
        if getattr(settings, 'ALIASES', None):
            logger.info('using aliases %s', settings.ALIASES)
            alias_regex = '|(?P<alias>{})'.format('|'.join([re.escape(s) for s in settings.ALIASES.split(',')]))

        self.AT_MESSAGE_MATCHER = re.compile(r'^(?:\<@(?P<atuser>\w+)\>:?|(?P<username>\w+):{}) ?(?P<text>[\s\S]*)$'.format(alias_regex))

    def start(self):
        self._pool.start()

    def dispatch_msg(self, msg):
        category = msg[0]
        msg = msg[1]
        print (category)
        print (msg)
        if not self._dispatch_msg_handler(category, msg):
            logger.info('Handle not found, falling to default')
            if category == u'respond_to':
                if not self._dispatch_msg_handler('default_reply', msg):
                    self._default_reply(msg)
            elif category == u'listen_to':
                if not self._dispatch_msg_handler('default_listen', msg):
                    self._default_listen(msg)

    def _dispatch_msg_handler(self, category, msg):
        responded = False
        lookup = 'text'

        if 'text' not in msg and 'reaction' in msg:
            lookup = 'reaction'
        self._plugins.set_message(msg)
        for func, args in self._plugins.get_plugins(category, msg.get(lookup, None)):
            logger.info(func)
            logger.info(args)
            if func:
                responded = True
                try:
                    func(Message(self._client, msg), *args)
                except:
                    logger.exception(
                        'failed to handle message %s with plugin "%s"',
                        msg[lookup], func.__name__)
                    reply = u'[{}] I had a problem handling "{}"\n'.format(
                        func.__name__, msg[lookup])
                    tb = u'```\n{}\n```'.format(traceback.format_exc())
                    if self._errors_to:
                        # self._client.rtm_send_message(msg['channel'], reply)
                        self._client.rtm_send_message(self._errors_to,
                                                      '{}\n{}'.format(reply,
                                                                      tb))
                    # else:
                    #     self._client.rtm_send_message(msg['channel'],
                    #                                   '{}\n{}'.format(reply,
                    #                                                   tb))
        return responded

    def _on_new_member(self, member):
        self._pool.add_task(('member_joined', member))

    def _on_new_react(self, react):
        self._pool.add_task(('react_to', react))

    def _on_new_message(self, msg):
        # ignore edits
        subtype = msg.get('subtype', '')
        if subtype == u'message_changed':
            return

        botname = self._get_bot_name()
        try:
            msguser = self._client.users.get(msg['user'])
            username = msguser['name']
        except (KeyError, TypeError):
            if 'username' in msg:
                username = msg['username']
            else:
                return

        if username == botname or username == u'slackbot':
            return

        msg_respond_to = self.filter_text(msg)
        if msg_respond_to:
            self._pool.add_task(('respond_to', msg_respond_to))
        else:
            self._pool.add_task(('listen_from', msg))
            self._pool.add_task(('listen_to', msg))

    def _get_bot_id(self):
        return self._client.login_data['self']['id']

    def _get_bot_name(self):
        return self._client.login_data['self']['name']

    def filter_text(self, msg):
        full_text = msg.get('text', '') or ''
        channel = msg['channel']
        bot_name = self._get_bot_name()
        bot_id = self._get_bot_id()
        m = self.AT_MESSAGE_MATCHER.match(full_text)

        if channel[0] == 'C' or channel[0] == 'G':
            if not m:
                return

            matches = m.groupdict()

            atuser = matches.get('atuser')
            username = matches.get('username')
            text = matches.get('text')
            alias = matches.get('alias')

            if alias:
                atuser = bot_id

            if atuser != bot_id and username != bot_name:
                # a channel message at other user
                return

            logger.debug('got an AT message: %s', text)
            msg['text'] = text
        else:
            if m:
                msg['text'] = m.groupdict().get('text', None)
        return msg

    def loop(self):
        while True:
            events = self._client.rtm_read()
            for event in events:
                event_type = event.get('type')
                if event_type == 'message':
                    self._on_new_message(event)
                elif event_type == 'member_joined_channel':
                    self._on_new_member(event)
                elif event_type == 'reaction_added':
                    self._on_new_react(event)
                elif event_type in ['channel_created', 'channel_rename',
                                    'group_joined', 'group_rename',
                                    'im_created']:
                    channel = [event['channel']]
                    self._client.parse_channel_data(channel)
                elif event_type in ['team_join', 'user_change']:
                    user = [event['user']]
                    self._client.parse_user_data(user)
            time.sleep(1)

    def _default_listen(self, msg):
        default_listen = settings.DEFAULT_LISTEN
        if default_listen is not None:
            m = Message(self._client, msg)
            m.reply(default_listen)

    def _default_reply(self, msg):
        default_reply = settings.DEFAULT_REPLY
        if default_reply is None:
            default_reply = [
                u'Bad command "{}", You can ask me one of the following '
                u'questions:\n'.format(
                    msg['text']),
            ]
            default_reply += [
                u'    • `{0}` {1}'.format(p.pattern, v.__doc__ or "")
                for p, v in
                six.iteritems(self._plugins.commands['respond_to'])]
            # pylint: disable=redefined-variable-type
            default_reply = u'\n'.join(default_reply)

        m = Message(self._client, msg)
        m.reply(default_reply)


def unicode_compact(func):
    """
    Make sure the first parameter of the decorated method to be a unicode
    object.
    """

    @wraps(func)
    def wrapped(self, text, *a, **kw):
        if not isinstance(text, six.text_type):
            text = text.decode('utf-8')
        return func(self, text, *a, **kw)

    return wrapped


class Message(object):
    def __init__(self, slackclient, body):
        self._client = slackclient
        self._body = body
        self._plugins = PluginsManager()
        self._plugins.set_message(body)
        self._plugins.set_user(self._get_user_id())

    def _get_user_id(self):
        if 'user' in self._body:
            return self._body['user']

        return self._client.find_user_by_name(self._body['username'])

    @unicode_compact
    def _gen_at_message(self, text):
        text = u'<@{}>: {}'.format(self._get_user_id(), text)
        return text

    @unicode_compact
    def get_user(self, user_id):
        return self._client.get_user(user_id)

    @unicode_compact
    def gen_reply(self, text):
        chan = self._body['channel']
        if chan.startswith('C') or chan.startswith('G'):
            return self._gen_at_message(text)
        else:
            return text

    @unicode_compact
    def reply_webapi(self, text, attachments=None, as_user=True, in_thread=None):
        """
            Send a reply to the sender using Web API

            (This function supports formatted message
            when using a bot integration)

            If the message was send in a thread, answer in a thread per default.
        """
        if in_thread is None:
            in_thread = 'thread_ts' in self.body

        if in_thread:
            return self.send_webapi(text, attachments=attachments, as_user=as_user, thread_ts=self.thread_ts)
        else:
            text = self.gen_reply(text)
            return self.send_webapi(text, attachments=attachments, as_user=as_user)

    @unicode_compact
    def send_webapi(self, text, attachments=None, as_user=True, thread_ts=None):
        """
            Send a reply using Web API

            (This function supports formatted message
            when using a bot integration)
        """
        return self._client.send_message(
            self._body['channel'],
            text,
            attachments=attachments,
            as_user=as_user,
            thread_ts=thread_ts)

    @unicode_compact
    def reply(self, text, in_thread=None):
        """
            Send a reply to the sender using RTM API

            (This function doesn't supports formatted message
            when using a bot integration)

            If the message was send in a thread, answer in a thread per default.
        """
        if in_thread is None:
            in_thread = 'thread_ts' in self.body

        if in_thread:
            return self.send(text, thread_ts=self.thread_ts)
        else:
            text = self.gen_reply(text)
            return self.send(text)

    @unicode_compact
    def direct_reply(self, text):
        """
            Send a reply via direct message using RTM API

        """
        channel_id = self._client.open_dm_channel(self._get_user_id())
        self._client.rtm_send_message(channel_id, text)

    @unicode_compact
    def send_channel_message(self, channel, message, attachments=None):
        return self._client.send_message(
            channel=channel,
            message=message,
            attachments=attachments
        )

    @unicode_compact
    def send(self, text, thread_ts=None):
        """
            Send a reply using RTM API

            (This function doesn't supports formatted message
            when using a bot integration)
        """
        return self._client.rtm_send_message(self._body['channel'], text, thread_ts=thread_ts)

    def pin(self, channel=None, ts=None):

        if channel is None:
            channel = self._body['channel']
        if ts is None:
            ts = self._body['ts']

        self._client.pin(
            channel=channel,
            timestamp=ts
        )

    def get_pins(self, channel=None):
        if channel is None:
            channel = self._body['channel']

        return self._client.get_pins(
            channel=channel
        )

    def delete_message(self, channel=None, ts=None):

        if channel is None:
            channel = self._body['item']['channel']

        if ts is None:
            ts = self._body['item']['ts']

        self._client.chat_delete(
            channel=channel,
            ts=ts
        )

    def unpin(self, channel=None, ts=None):

        if channel is None:
            channel = self._body['channel']

        if ts is None:
            ts = self._body['ts']

        self._client.unpin(
            channel=channel,
            timestamp=ts
        )

    def get_group_message(self, channel, thread_ts):
        return self._client.get_group_message(
            channel=channel,
            thread_ts=thread_ts
        )

    def get_group_info(self, channel):
        return self._client.get_group_info(
            channel=channel
        )

    def get_message(self, channel, ts):
        return self._client.get_group_history(
            channel=channel,
            limit=1,
            inclusive=1,
            oldest=ts,
            latest=ts,
        )

    def get_group_history(self, channel):
        return self._client.get_group_history(
            channel=channel
        )
    # def get_pins(self):
    #     return self._client.list_pins(
    #         channel=self._body['channel']
    #     )

    def send_react(self, emojiname, channel, ts):
        """
           React to a message using the web api
        """
        self._client.react_to_message(
            emojiname=emojiname,
            channel=channel,
            timestamp=ts)

    def remove_react(self, emojiname):
        """
             React to a message using the web api
        """
        self._client.remove_react_to_message(
            emojiname=emojiname,
            channel=self._body['channel'],
            timestamp=self._body['ts'])

    def react(self, emojiname):
        """
           React to a message using the web api
        """

        self._client.react_to_message(
            emojiname=emojiname,
            channel=self._body['channel'],
            timestamp=self._body['ts'])

    @property
    def channel(self):
        return self._client.get_channel(self._body['channel'])

    @property
    def body(self):
        return self._body

    @property
    def user(self):
        return self._client.get_user(self._body['user'])

    @property
    def thread_ts(self):
        try:
            thread_ts = self.body['thread_ts']
        except KeyError:
            thread_ts = self.body['ts']

        return thread_ts

    def docs_reply(self, command=None):

        if command is not None:
            for _, v in six.iteritems(self._plugins.commands['respond_to']):
                if v.__name__ == command:
                    reply = u'    • `{0}` {1}'.format(v.__name__, v.__doc__ or '')
                    return reply
            return 'No command found under %s' % command
        else:
            reply = [u'    • `{0}`'.format(v.__name__)
                     for _, v in
                     six.iteritems(self._plugins.commands['respond_to'])]
            return u'\n'.join(reply)
