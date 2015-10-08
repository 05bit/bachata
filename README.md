**Bachata** is a chat server toolkit on top of [asyncio](https://docs.python.org/3.4/library/asyncio.html) and [Tornado](http://www.tornadoweb.org/en/stable/).

[![ReadTheDocs badge][readthedocs]](http://bachata.readthedocs.org/en/latest/)

[readthedocs]: https://readthedocs.org/projects/bachata/badge/?version=latest

- Requires Python 3.3+
- Requires Tornado running on asyncio event loop
- Implements simple messages queue on Redis LPUSH / BRPOP
- Implements reliable messages delivery on Redis BRPOPLPUSH pattern
- Uses WebSockets for messages transport
- Uses JSON messages format
- Simple layer for custom messages routing

Install
=======

```
pip install bachata
```

Documentation
=============

<http://bachata.readthedocs.org/en/latest/>

Example
=======

See basic working example in the [./example](./example) dir.
