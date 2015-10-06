"""WebSocket handler for Tornado."""
import json
import asyncio
import logging
import tornado.gen
import tornado.websocket
import tornado.ioloop


class MessagesHandler(tornado.websocket.WebSocketHandler):
    """Base WebSocket handler for Tornado.

    Default implementation works with authentication free channels,
    it just generates random channel identifier.

    Redefine :meth:`.get_channel` in subclass if you want to have
    channels identifiers based on authenticated user.

    """
    @property
    def loop(self):
        io_loop = tornado.ioloop.IOLoop.current()
        return io_loop.asyncio_loop

    def open(self):
        """Open WebSocket connection and add socket channel to messages center.

        It also performs :meth:`.authenticate` coroutine call, so
        :meth:`.get_channel` can rely on current authenticated
        user.

        """
        self.loop.create_task(self.open_async())

    @asyncio.coroutine
    def open_async(self):
        yield from self.authenticate()

        channel = self.get_channel()
        if channel:
            mc = self.get_messages_center()
            mc.add_socket(channel, self)
        else:
            io_loop = tornado.ioloop.IOLoop.current()
            io_loop.add_callback(self.on_auth_error)

    @asyncio.coroutine
    def authenticate(self):
        """Authenticate and load current user, asyncio coroutine.

        Default implementation is empty, so real authentication logic
        should be implemented in subclass.

        """
        return

    def on_close(self):
        """Remove handler from messages center."""
        self.get_messages_center().del_socket(self.get_channel(), self)

    def on_message(self, raw_message):
        """Process message to messages center."""
        self.loop.create_task(
            self.get_messages_center().process(raw_message, self))

    def on_auth_error(self):
        """Close connection on authorization error."""
        self.close(reason="Error: not authorized for channel access")

    def get_channel(self):
        """Get channel string identifier for connection. Method must be defined
        in subclass.

        Implementation example::

            class MyMessagesHandler(talkie.tornado.MessagesHandler):
                def get_channel(self):
                    if self.current_user:
                        return 'channel:%s' % self.current_user.id

        """
        raise NotImplementedError

    def get_messages_center(self):
        """Get messages center for WebSocket. Method must be defined
        in subclass.

        Implementation example::

            def get_messages_center(self):
                # bachata.RedisMessagesCenter instance
                return self.application.messages

        """
        raise NotImplementedError
