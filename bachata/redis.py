import asyncio
import aioredis
from . import base


class RedisMessagesCenter(base.BaseMessagesCenter):
    """Messages center on top of Redis LPUSH / BRPOP pattern.

    After creating messages center instance `init()` coroutine
    also must be called.

    :param loop: asyncio event loop
    :param conn_params: Redis connection params as dict
    :param reliable: Use reliable queue or simple queue, default is ``False``

    """
    def __init__(self, loop=None, conn_params=None, reliable=False):
        self.conn_params = conn_params
        queue_cls = ReliableRedisQueue if reliable else RedisQueue
        queue = queue_cls(loop=loop, conn_params=conn_params)
        super().__init__(loop=loop, queue=queue)

    @asyncio.coroutine
    def init(self):
        """Setup main Redis connection for queue."""
        yield from self.queue.connect()

    @asyncio.coroutine
    def done(self):
        yield from self.queue.close()


class RedisQueue(base.BaseQueue):
    """Messages queue on top of Redis LPUSH / BRPOP pattern.

    Schema description:

    1. Messages are LPUSH'ed to list with "{channel}" key.

    2. Receiver just listens for "{channel}" list updates
       with BRPOP.

    :param loop: asyncio event loop
    :param websocket: WebSocket handler instance
    :param conn_params: Redis connection params

    """
    CLOSE_COMMAND = '!'

    def __init__(self, loop=None, conn_params=None):
        self.loop = loop
        self.conn_params = conn_params

    def add_socket(self, channel, websocket, proto=None):
        """Register WebSocket for receiving messages from channel.

        :param channel: String channel identifier, based on user id or some hash string
        :param websocket: Tornado WebSocket handler instance
        :param proto: Messages protocol instance

        """
        websocket.is_closed = False
        ready_message = proto.make_message(type=proto.TRANS_READY)
        websocket.write_message(proto.dump_message(ready_message))
        self.loop.create_task(self.listen_queue(channel, websocket))

    def del_socket(self, channel, websocket, proto=None):
        """Unregister WebSocket from receiving messages from channel.

        :param channel: String channel identifier, based on user id or some hash string
        :param websocket: Tornado WebSocket handler instance
        :param proto: Messages protocol instance

        """
        websocket.is_closed = True
        self.loop.create_task(self.put_message(
            [channel], self.CLOSE_COMMAND, proto=proto))

    @asyncio.coroutine
    def connect(self):
        """Setup main Redis connection."""
        self.conn = yield from aioredis.create_redis(
            loop=self.loop, **self.conn_params)

    @asyncio.coroutine
    def close(self):
        self.conn.close()

    @asyncio.coroutine
    def put_message(self, channels, message, proto=None, from_channel=None):
        """Put messages on queue.

        :param channels: List of destination channels
        :param message: Message dict object
        :param proto: Messages protocol instance
        :param from_channel: Message from channel

        """
        if isinstance(message, str):
            raw_message = message
        else:
            raw_message = proto.dump_message(message)

        for ch in channels:
            yield from self.conn.lpush(ch, raw_message)

    @asyncio.coroutine
    def listen_queue(self, channel, websocket):
        """Start queue listener for channel and WebSocket connection."""
        redis_conn = yield from aioredis.create_redis(
            loop=self.loop, **self.conn_params)

        while True:
            val = yield from redis_conn.brpop(channel, timeout=10)
            if websocket.is_closed:
                redis_conn.close()
                return
            elif val:
                websocket.write_message(val[1])
            

class ReliableRedisQueue(RedisQueue):
    """Reliable messages queue on top of Redis BRPOPLPUSH pattern.

    Storage schema description:

    1. Every message is stored as single value with key
       "{channel}:{message id}" with expire time.

    2. Incoming messages queue is represented via list of messages
       ids: [{message id 1}, {message id 2}, ...]

    3. Incoming queue key is "{channel}", waiting delivery confirmation
    queue key is "{channel}:wait"

    :param loop: asyncio event loop
    :param websocket: WebSocket handler instance
    :param conn_params: Redis connection params

    """
    @asyncio.coroutine
    def put_message(self, channels, message, proto=None, from_channel=None):
        """Put messages on queue.

        :param channels: List of destination channels
        :param message: Message dict object
        :param proto: Messages protocol instance
        :param from_channel: Message from channel

        """
        if isinstance(message, dict):
            message_dump = proto.dump_message(message)
        else:
            message_dump = None

        for channel in channels:
            # Store every message which has ID within separate list,
            # also store from channel with message as 2-nd list item.
            if message_dump and ('id' in message):
                message_key = '%s:%s' % (channel, message['id'])
                queue_data = message_key
                values = (message_dump, from_channel or '')
                yield from self.conn.rpush(message_key, *values)
            # If message has no ID or is not dict itself,
            # then just pass it as is.
            else:
                queue_data = message_dump or message

            # Put message ID or raw message on queue
            yield from self.conn.lpush(channel, queue_data)

    @asyncio.coroutine
    def check_delivered(self, channel, message_id):
        """Check if message is delivered.

        """
        message_key = '%s:%s' % (channel, message_id)
        llen = yield from self.conn.llen(message_key)
        return llen == 0

    @asyncio.coroutine
    def pop_delivered(self, channel, message_id, proto=None):
        """Pop delivered message by ID.

        Remove message by key "{channel}:{message id}" and remove
        that key from waiting queue.

        :param channel: Channel reveived message
        :param message_id: Message ID
        :param proto: Messages protocol instance
        :return: Tuple (delivered message, from channel)

        """
        message_key = '%s:%s' % (channel, message_id)
        wait_queue = '%s:wait' % channel
        raw_message = yield from self.conn.lpop(message_key)
        from_channel = yield from self.conn.lpop(message_key)

        yield from self.conn.lrem(wait_queue, 1, message_key)

        if raw_message:
            message = proto.load_message(raw_message.decode('utf-8'))
            return message, from_channel.decode('utf-8')

    @asyncio.coroutine
    def listen_queue(self, channel, websocket):
        """Start queue listener for channel and WebSocket connection.

        Send wait queue first to deliver messages that was not delivered
        on previous session. Then start listening for new messages. Every
        message with ID is send through WebSocket and put on wait queue.
        After delivery confirmation message is removed from wait queue,
        see :meth:`.pop_delivered` method.

        """
        redis_conn = yield from aioredis.create_redis(
            loop=self.loop, **self.conn_params)

        # Send wait queue first
        wait_queue = '%s:wait' % channel
        yield from self._send_wait_queue(
            wait_queue, redis_conn, channel, websocket)

        # Wait for new messages and send
        while True:
            raw = yield from redis_conn.brpoplpush(
                channel, wait_queue)

            if not raw:
                continue

            val = raw.decode('utf-8')

            if val == self.CLOSE_COMMAND:
                yield from redis_conn.lrem(wait_queue, 0, self.CLOSE_COMMAND)
                redis_conn.close()
                return
            else:
                pop_wait = yield from self._write_message(
                    redis_conn, val, channel, websocket)
                if pop_wait:
                    yield from redis_conn.lpop(wait_queue)

    @asyncio.coroutine
    def _send_wait_queue(self, wait_queue, redis_conn, channel, websocket):
        """Send messages from waiting queue.

        :param wait_queue: Wait queue key
        :param redis_conn: Redis connection
        :param channel: Message channel
        :param websocket: WebSocket connection

        """
        wait_messages = yield from redis_conn.lrange(wait_queue, 0, -1)
        for raw in reversed(wait_messages):
            val = raw.decode('utf-8')
            if val.startswith(channel):
                yield from self._write_message(
                    redis_conn, val, channel, websocket)
            else:
                # Actually we should not be here, if everything works fine!
                # But due to [old] bugs there could be trash messages on wait
                # queue, so we just clean them up.
                # TODO: place WARNING here
                yield from self.conn.lrem(wait_queue, 1, val)

    @asyncio.coroutine
    def _write_message(self, redis_conn, msg_or_id, channel, websocket):
        """Write message to WebSocket output by ID or raw value.

        Messages with confirmation are stored separatelly
        and only their id is passed to queue. Messages
        without delivery confirmation are just sent as is.

        :param redis_conn: Redis connection
        :param msg_or_id: Message ID or dump to str
        :param channel: Message channel
        :param websocket: WebSocket connection
        :return: `True` if message should be removed from wait
                 queue, because doesn't need confirmation.

        """
        # get by id and send
        if msg_or_id.startswith(channel):
            message_dump = yield from redis_conn.lindex(msg_or_id, 0)
            if message_dump:
                websocket.write_message(message_dump)
        # just send
        else:
            websocket.write_message(msg_or_id)
            return True
