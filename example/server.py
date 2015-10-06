"""Basic example of Bachata usage.
"""
import os
import sys
import asyncio
import tornado.ioloop
import tornado.httpserver
import tornado.web
import bachata
import bachata.tornado
import bachata.redis

APP_HOST = ('127.0.0.1', 8000)
REDIS_HOST = ('127.0.0.1', 6379)
REDIS_DB = 0

# Note 1: we have to setup Tornado-asyncio bridge
from tornado.ioloop import IOLoop
IOLoop.configure('tornado.platform.asyncio.AsyncIOLoop')

import logging
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
log = logging.getLogger('example')


class Application(tornado.web.Application):
    # Note 2: we'll need asyncio loop instance and we should get it
    # through "bridge" method
    @property
    def loop(self):
        if not hasattr(self, '_loop'):
            io_loop = tornado.ioloop.IOLoop.current()
            self._loop = io_loop.asyncio_loop
        return self._loop

    # Note 3: init messages center
    @asyncio.coroutine
    def init_async(self):
        self.messages = bachata.redis.RedisMessagesCenter(
            loop=self.loop,
            conn_params={'address': REDIS_HOST, 'db': REDIS_DB},
            reliable=True)
        self.messages.add_route(SimpleRoute())
        yield from self.messages.init()


class HomePage(tornado.web.RequestHandler):
    def get(self):
        self.render("index.html")


class MessagesHandler(bachata.tornado.MessagesHandler):
    # Note 4: we define simple channel logic, in real apps
    # channel identifier can be get from authenticated user ID
    def get_channel(self):
        if not hasattr(self, '_channel'):
            self._channel = self.get_argument('channel')
            log.debug("New chat channel: %s" % self._channel)
        return self._channel

    # Note 5: we MUST define this method, default implementation is empty!
    def get_messages_center(self):
        return self.application.messages

    def on_close(self):
        super().on_close()
        log.debug("Chat closed: %s", self._channel)


class SimpleRoute(bachata.BaseRoute):
    @asyncio.coroutine
    def process(self, message, websocket=None, proto=None):
        if 'dest' in message:
            log.debug(message)
            if websocket:
                message['from'] = websocket.get_channel()
            return message['dest']


if __name__ == '__main__':
    app = Application(
        [
            (r'/', HomePage),
            (r'/messages', MessagesHandler),
        ],
        debug=True)

    log.info("Running server at http://%s:%s" % APP_HOST)

    server = tornado.httpserver.HTTPServer(app)
    server.bind(APP_HOST[1], APP_HOST[0])
    server.start()

    try:
        app.loop.run_until_complete(app.init_async())
        app.loop.run_forever()
    except KeyboardInterrupt:
        print("")
        log.info("Server stopped. Bye!")
