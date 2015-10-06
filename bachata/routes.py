import asyncio
from . import base
from . import proto as base_proto


class DirectRoute(base.BaseRoute):
    @asyncio.coroutine
    def process(self, message, websocket=None, proto=None):
        if 'dest' in message:
            # Automatically set message sender's channel
            # if websocket:
            #     message['from'] = websocket.get_channel()
            return message['dest']
