"""Main messages router."""
import asyncio
from  . import proto as base_proto


class BaseRoute:
    """Base messages route class.

    Routes are registered in messages center, every route is
    responsible for delivering single messages type, i.e.
    direct users messages, group chat messages, system
    notifications, etc.

    """
    @asyncio.coroutine
    def process(self, message, websocket=None, proto=None):
        """Process message and return receiver channel for the message.

        Scenarios:

        - If method returns ``None``, message is simply passed to next
          router in chain.
        - If method returns non-empty channel string, then message will
          be sent to that channel.
        - If method returns ``True``, then routing chain should be stopped
          for this message.

        :param message: Arbitrary message object.
        :param proto: Messages protocol instance
        :returns: String channel identifier or ``True`` or ``None``

        """
        raise NotImplementedError

    @asyncio.coroutine
    def post_process(self, message, to_channel=None, queue=None):
        """Post process message after putting it on delivery queue.

        Scenarios examples:

        - Test if message was delivered after certain timeout and
          notify via another channel (email, APNS, SMS) if not.
        - Send extra service message right after main message.
        - etc.
        """
        pass


class BaseQueue:
    """Base messages queue class."""

    def add_socket(self, channel, websocket, proto=None):
        """Register WebSocket for receiving messages from channel.

        Method implementation has to write 'ready' transport message
        on success or close WebSocket connection.

        :param channel: String channel identifier, based on user id or some
                        hash string
        :param websocket: Tornado WebSocket handler instance

        """
        raise NotImplementedError

    def del_socket(self, channel, websocket, proto=None):
        """Unregister WebSocket from receiving messages from channel.

        :param channel: String channel identifier, based on user id or some
                        hash string
        :param websocket: Tornado WebSocket handler instance
        :param proto: Messages protocol instance

        """
        raise NotImplementedError

    @asyncio.coroutine
    def put_message(self, channels, message, proto=None, from_channel=None):
        """Put messages on queue.

        :param channels: List of destination channels
        :param message: Message dict object
        :param proto: Messages protocol instance
        :param from_channel: Message from channel

        """
        raise NotImplementedError

    @asyncio.coroutine
    def check_delivered(self, channel, message_id):
        """Check if message is delivered.

        Default implementation always returns True, assuming
        no messages tracking is implemented initially.
        """
        return True

    @asyncio.coroutine
    def pop_delivered(self, channel, message_id, proto=None):
        """Mark message as delivered by ID.

        Default implementation is empty.

        :param channel: Channel reveived message
        :param message_id: Message ID
        :param proto: Messages protocol instance

        """
        pass


class BaseMessagesCenter:
    """Messages center provides top-level messages routing.

    :param loop: asyncio event loop
    :param queue: Messages queue instance
    :param proto: Messages protocol instance or :class:`.BaseProtocol`
                  instance will be used by default

    Attributes:

    - `.proto`: :class:`BaseProtocol` or subclass instance
    - `.loop`: asyncio event loop
    - `.queue`: :class:`BaseQueue` subclass instance
    - `.routes`: routes objects list

    """
    def __init__(self, loop=None, proto=None, queue=None):
        assert queue, "Error, queue argument not specified."
        self.loop = loop or asyncio.get_event_loop()
        self.proto = proto or base_proto.BaseProtocol()
        self.queue = queue
        self.routes = []

    def add_socket(self, channel, websocket):
        """Register WebSocket for receiving messages from channel.

        :param channel: String channel identifier, based on user id or some hash string
        :param websocket: Tornado WebSocket handler instance

        """
        self.queue.add_socket(channel, websocket, proto=self.proto)

    def del_socket(self, channel, websocket):
        """Unregister WebSocket from receiving messages from channel.

        :param channel: String channel identifier, based on user id or some hash string
        :param websocket: Tornado WebSocket handler instance

        """
        self.queue.del_socket(channel, websocket, proto=self.proto)

    def add_route(self, route):
        """Add messages route to routing chain, see :class:`.BaseRoute`

        Message routes are processed in the same order as they added.

        :param route: Route instance

        """
        assert (not route in self.routes), ("Error, route %s is already added." % route)
        self.routes.append(route)

    def del_route(self, route):
        """Remove message route, see :class:`.BaseRoute`

        :param route: Route instance

        """
        self.routes.remove(route)

    @asyncio.coroutine
    def transport(self, message=None, websocket=None):
        """Process transport layer for messages.

        Performs reliable delivery process, notifies sender on successful
        message delivery.

        :param message: Data or transport message to process
        :param websocket: WebSocket which has received message to process

        """
        assert message and websocket, ("Error, message and websocket"
                                       "arguments are required!")

        # Process messages with transport types.
        if message['type'] in self.proto.TRANS_TYPES:
            # Ping (type=1001), say 'pong'
            if message['type'] == self.proto.TRANS_PING: 
                yield from self._transport_ping(message, websocket)
            # Received (type=200)
            elif message['type'] == self.proto.TRANS_RECV_GOT_IT:
                yield from self._transport_gotit(message, websocket)
        # Respond to data message, start delivery
        else:
            yield from self._transport_start(message, websocket)

    @asyncio.coroutine
    def _transport_ping(self, message, websocket):
        """Process ping type=1001 transport message."""
        pong = self.proto.make_message(type=self.proto.TRANS_PONG)
        websocket.write_message(pong)

    @asyncio.coroutine
    def _transport_start(self, message, websocket):
        """Respond to sender on message delivery start, e.g.
        when server first gets message for delivery, it says
        'Got It' type=100."""
        got_it = self.proto.make_message(
            type=self.proto.TRANS_SERV_GOT_IT, data=message['id'])
        websocket.write_message(got_it)

    @asyncio.coroutine
    def _transport_gotit(self, message, websocket):
        """Process 'Got It' type=200 transport message.

        Pop and mark message as delivered by ID, and then
        notify message sender on successful delivery.

        """
        message_id = message['data']
        channel = websocket.get_channel()
        delivered = yield from self.queue.pop_delivered(
            channel, message_id, proto=self.proto)

        if delivered:
            delivered_message, from_channel = delivered[0], delivered[1]
            notify_message = self.proto.make_message(
                type=self.proto.TRANS_DELIVERED,
                data=delivered_message['id'])
            yield from self.queue.put_message([from_channel],
                                              notify_message,
                                              proto=self.proto)

    @asyncio.coroutine
    def process(self, raw_or_message, websocket=None):
        """Process message to routing chain and send to WebSockets.

        Message is passed to registered routes, they return receivers
        channels and then message is sent to that channels.

        :param raw_or_message: Raw message string or message dict
        :param websocket: WebSocket connection handler received new message,
                          this is optional parameter, because message could
                          also be created at server internally

        """
        try:
            if isinstance(raw_or_message, str):
                message = self.proto.load_message(raw_or_message)
            else:
                message = raw_or_message
        except ValueError as e:
            # TODO: handle message format errors
            print("Error,", e)
            return

        # Transport layer
        if websocket:
            yield from self.transport(message=message, websocket=websocket)
            # Stop processing if it's a transport message
            if message['type'] in self.proto.TRANS_TYPES:
                return

        # Data message
        destinations = []
        for route in self.routes:
            to_channel = yield from route.process(message, websocket, proto=self.proto)
            if to_channel is True:
                break
            elif isinstance(to_channel, str):
                destinations.append((route, to_channel))

        # Put on delivery queue
        if destinations:
            from_channel = websocket.get_channel() if websocket else None
            to_channels = [d[1] for d in destinations]
            yield from self.queue.put_message(to_channels, message,
                                              proto=self.proto,
                                              from_channel=from_channel)

        # Post process message
        for (route, to_channel) in destinations:
            self.loop.create_task(route.post_process(message,
                                                     to_channel,
                                                     queue=self.queue))

