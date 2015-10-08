import json
import uuid
import asyncio
import websockets
import logging

log = logging.getLogger(__name__)

try:
    import tornado
except ImportError:
    tornado = None


if tornado:
    import tornado.web
    import tornado.testing
    import bachata
    import bachata.tornado
    import bachata.redis

    from tornado.ioloop import IOLoop
    IOLoop.configure('tornado.platform.asyncio.AsyncIOLoop')


    class TestApp(tornado.web.Application):
        def __init__(self, *args, **kwargs):
            self.reliable = kwargs.pop('reliable', False)
            self.io_loop = kwargs.pop('io_loop')
            self.is_init = False

            self.messages = bachata.redis.RedisMessagesCenter(
                loop=self.io_loop.asyncio_loop,
                conn_params={'address': ('localhost', 6379), 'db': 9},
                reliable=self.reliable)
            self.messages.add_route(bachata.DirectRoute())

            super().__init__(*args, **kwargs)

        @asyncio.coroutine
        def init(self):
            self.is_init = True
            yield from self.messages.init()

        @asyncio.coroutine
        def done(self):
            yield from self.messages.done()


    class MessagesTestWebSocket(bachata.tornado.MessagesHandler):
        def get_channel(self):
            if not hasattr(self, '_channel'):
                self._channel = self.get_argument('channel')
            log.debug("Connection channel=%s" % self._channel)
            return self._channel

        def get_messages_center(self):
            return self.application.messages

        def on_close(self):
            super().on_close()
            log.debug("Connection closed")


    class BaseTornadoTest(tornado.testing.AsyncHTTPTestCase):
        @property
        def loop(self):
            return self.io_loop.asyncio_loop

        def get_app(self):
            if not hasattr(self, '_app'):
                self._app = TestApp([
                    ('/messages', MessagesTestWebSocket),
                ], io_loop=self.io_loop)
            return self._app

        def get_ws_url(self, url):
            return self.get_url(url).replace('http://', 'ws://')

        @asyncio.coroutine
        def connect(self, ws_url):
            return (yield from websockets.connect(ws_url, loop=self.loop))

        def async(self, coroutine):
            def stop_with_error(exc):
                raise exc

            @asyncio.coroutine
            def run_async():
                yield from self._app.init()

                result = None
                try:
                    result = yield from coroutine
                except Exception as e:
                    self.io_loop.add_callback(stop_with_error, e)

                yield from self._app.done()

                yield from asyncio.sleep(0.1, loop=self.loop)

                self.stop(result)

            self.loop.create_task(run_async())

            return self.wait()


    class WebSocketConnTest(BaseTornadoTest):
        def test_ws_connection(self):
            ws_url = self.get_ws_url('/messages?channel=%s' % str(uuid.uuid4()))

            @asyncio.coroutine
            def test():
                ws_conn = yield from self.connect(ws_url)

                # ready
                conn_ok = yield from ws_conn.recv()
                self.assertEqual(json.loads(conn_ok)['type'], 1000)

                # ping
                msg = json.dumps({'type': 1001})
                yield from ws_conn.send(msg)

                # pong
                resp = yield from ws_conn.recv()
                self.assertEqual(json.loads(resp)['type'], 1002)

                yield from ws_conn.close()

            self.async(test())

        def test_direct_message(self):
            ch1 = str(uuid.uuid4())
            ch2 = str(uuid.uuid4())
            ws1_url = self.get_ws_url('/messages?channel=%s' % ch1)
            ws2_url = self.get_ws_url('/messages?channel=%s' % ch2)

            @asyncio.coroutine
            def test():
                ws1_conn = yield from self.connect(ws1_url)
                yield from ws1_conn.recv()

                ws2_conn = yield from self.connect(ws2_url)
                yield from ws2_conn.recv()

                # send
                msg = json.dumps({'type': 'test', 'dest': ch2, 'id': str(uuid.uuid4())})
                yield from ws1_conn.send(msg)

                # receive
                resp = yield from ws2_conn.recv()
                self.assertEqual(json.loads(resp)['type'], 'test')

                # close
                yield from ws1_conn.close()
                yield from ws2_conn.close()

            self.async(test())


    class WebSocketReliableTest(BaseTornadoTest):
        def get_app(self):
            return TestApp([
                ('/messages', MessagesTestWebSocket),
            ], io_loop=self.io_loop, reliable=True)

        def test_ws_connection(self):
            ws_url = self.get_ws_url('/messages?channel=%s' % str(uuid.uuid4()))

            @asyncio.coroutine
            def test():
                ws_conn = yield from self.connect(ws_url)

                # ready
                conn_ok = yield from ws_conn.recv()
                self.assertEqual(json.loads(conn_ok)['type'], 1000)

                # ping
                msg = json.dumps({'type': 1001})
                yield from ws_conn.send(msg)

                # pong
                resp = yield from ws_conn.recv()
                self.assertEqual(json.loads(resp)['type'], 1002)

                yield from ws_conn.close()

            self.async(test())

        def test_direct_message(self):
            ch1 = str(uuid.uuid4())
            ch2 = str(uuid.uuid4())
            ws1_url = self.get_ws_url('/messages?channel=%s' % ch1)
            ws2_url = self.get_ws_url('/messages?channel=%s' % ch2)

            @asyncio.coroutine
            def test():
                ws1_conn = yield from self.connect(ws1_url)
                yield from ws1_conn.recv()

                ws2_conn = yield from self.connect(ws2_url)
                yield from ws2_conn.recv()

                # send
                msg = json.dumps({'type': 'test', 'dest': ch2, 'id': str(uuid.uuid4())})
                yield from ws1_conn.send(msg)

                # send - confirm
                confirm1 = yield from ws1_conn.recv()
                confirm1_msg = json.loads(confirm1)
                self.assertEqual(confirm1_msg['type'], 100)

                # receive
                resp = yield from ws2_conn.recv()
                resp_msg = json.loads(resp)
                self.assertEqual(resp_msg['type'], 'test')

                # receive - confirm
                confirm2 = json.dumps({'type': 200, 'data': resp_msg['id']})
                yield from ws2_conn.send(confirm2)

                # delivery - confirm
                delivery = yield from ws1_conn.recv()
                delivery_msg = json.loads(delivery)
                self.assertEqual(delivery_msg['type'], 300)

                yield from ws1_conn.close()
                yield from ws2_conn.close()

            self.async(test())
