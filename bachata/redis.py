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
        self.loop.create_task(self.listen_queue(channel, websocket))
        ready_message = proto.make_message(type=proto.TRANS_READY)
        websocket.write_message(proto.dump_message(ready_message))

    def del_socket(self, channel, websocket, proto=None):
        """Unregister WebSocket from receiving messages from channel.

        :param channel: String channel identifier, based on user id or some hash string
        :param websocket: Tornado WebSocket handler instance
        :param proto: Messages protocol instance

        """
        websocket.is_closed = True
        self.loop.create_task(self.put_message([channel], '', proto=proto))

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
        raw_message = proto.dump_message(message)

        for channel in channels:
            # Store every message which has ID within separate list,
            # also store from channel with message as 2-nd list item.
            if isinstance(message, dict) and ('id' in message):
                message_key = '%s:%s' % (channel, message['id'])
                queue_data = message_key
                values = (raw_message, from_channel or '')
                yield from self.conn.rpush(message_key, *values)
            # If message has no ID or is not dict itself,
            # then just pass it as is.
            else:
                queue_data = raw_message

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
        """Start queue listener for channel and WebSocket connection."""
        redis_conn = yield from aioredis.create_redis(
            loop=self.loop, **self.conn_params)

        while True:
            wait_queue = '%s:wait' % channel
            val = yield from redis_conn.brpoplpush(channel, wait_queue,
                                                   timeout=10)
            if websocket.is_closed:
                redis_conn.close()
                return
            elif val:
                val_str = val.decode('utf-8')

                # Messages with confirmation are stored separatelly
                # and only their id is passed to queue. Messages
                # without delivery confirmation are just sent as is.
                # So, in the first case message id is popped from list
                # and in the second case raw message is popped.

                if val_str.startswith(channel): # get by id and send
                    raw_message = yield from redis_conn.lindex(val_str, 0)
                    if raw_message:
                        websocket.write_message(raw_message)
                else: # just send
                    yield from redis_conn.lpop(wait_queue)
                    websocket.write_message(val_str)
