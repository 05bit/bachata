"""Basic messages protocol and design guide.

Messages are presented via JSON strings for sending through network
and via standard dict objects for local dispatching.

Messages in Bachata can be of two types:

1. Data messages
2. Transport messages


Data messages
-------------

Data messages are generic messages with any users data. Format is very
simple yet flexible, and here's a basic pattern::

    {
        "id": (str) Message ID,
        "type": (str) Message type,
        "time": (int) Unix-style timestamp in milliseconds,
        "data": (str) / (obj) String or object,
        "from": (str, optional) Sender, may be empty for messages "by system"
        "dest": (str, optional) Destination, may be empty if it's non-adressed
        "sign": (str, optional) Signature
    }

All fields format except "time" are left for programmers choice!

Here are some ideas on schema design:

1. "id" can be UUID v4, integer number as string or any other unique string

2. "type" field values will be used by routers for filtering, i.e.
   router for direct messages will pick ``"type": "direct"`` messages,
   router for group chats will pick ``"type": "group"`` messages, etc.
   **This field must be a string! Integers are reserved for
   transport messages.**

3. "dest" is a destination identifier, which router should understand,
   i.e. for direct messages it may be user ID, for group chat messages
   it may be group chat ID, etc.

4. "data" could be ``{"text": "some message text"}`` for text messages,
   ``{"location": 33.034:55.0234}`` for geographic location messages,
   may be a mix of many fields ``{"text": "hi!", "image": "http://..."}``,
   etc.

5. "sign" field could be hash of data concatenated with secret token,
   which is transferred once when user is authenticated, and can be
   generated and checked both on server and client for preventing
   unauthorized sending.

There are no really de-facto standard protocols which are simple and
at the same time comprehensive, so feel free to design your own!

Maybe later we'll have some best practices section or even a kind of
recommended schema, who knows.


Transport messages
------------------

Transport messages are necessary for reliable delivery. Receiver client
will notify server on receiving, server will notify senders on deliver,
etc.

**Transport messages have integer type field!**

They have very simple format::

    {
        "type": (int) Transport type,
        "data": (str) Message ID,
        "sign": (str, optional) Signature
    }

Types description table:

======= =================================================================
Type    Description
------- -----------------------------------------------------------------
100     server => sender, server has received message for delivery
------- -----------------------------------------------------------------
200     server <= receiver, receiver has got message
------- -----------------------------------------------------------------
300     server => sender, server has delivered message
------- -----------------------------------------------------------------
1000    server => client, connection "ready" message
------- -----------------------------------------------------------------
1001    "ping" message, should be responded with "pong"
------- -----------------------------------------------------------------
1002    "pong" message, should be sent in response to "ping"
======= =================================================================

"""
import json

__all__ = ('BaseProtocol',)


class BaseProtocol:
    """Basics for messages loading, dumping and format validation."""

    TRANS_READY = 1000 # connected
    TRANS_PING = 1001 # ping
    TRANS_PONG = 1002 # pong
    TRANS_SERV_GOT_IT = 100 # SERVER => SENDER, start sending
    TRANS_RECV_GOT_IT = 200 # SERVER <= RECEIVER, received
    TRANS_DELIVERED = 300 # SERVER => SENDER, delivered
    TRANS_TYPES = (
        TRANS_PING, TRANS_PONG,
        TRANS_SERV_GOT_IT, TRANS_RECV_GOT_IT,
        TRANS_DELIVERED)

    def load_message(self, raw_message):
        """Load message to dict from str."""
        message = json.loads(raw_message)
        return message

    def make_message(self, id=None, type=None, time=None, dest=None,
                     from_=None, sign=None, data=None):
        """Create new message dict."""
        msg = {}
        if id: msg['id'] = str(id)
        if type: msg['type'] = type
        if time: msg['time'] = time
        if data: msg['data'] = data
        if dest: msg['dest'] = str(dest)
        if sign: msg['sign'] = str(sign)
        if from_: msg['from'] = str(from_)
        return msg

    def dump_message(self, message):
        """Dump message to str."""
        return json.dumps(message)
