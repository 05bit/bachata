"""**Bachata** is a chat server toolkit on top of `asyncio`_ and `Tornado`_.

.. _Tornado: http://www.tornadoweb.org/en/stable/
.. _asyncio: https://docs.python.org/3.4/library/asyncio.html

Overview
--------

- Requires Python 3.3+
- Requires Tornado running on asyncio event loop
- Implements simple messages queue on Redis LPUSH / BRPOP
- Implements reliable messages delivery on Redis BRPOPLPUSH pattern
- JSON messages format
- Custom messages routing

"""
from setuptools import setup

with open('bachata/__init__.py') as file:
    for line in file:
        if line.startswith('__version__'):
            __version__ = line.split('=')[1].strip().strip("'").strip('"')
            break

setup(
    name="bachata",
    version=__version__,
    author="Alexey Kinev",
    author_email='rudy@05bit.com',
    url='https://github.com/05bit/bachata',
    description="Bachata is a chat server toolkit on top of asyncio and Tornado.",
    long_description=__doc__,
    license='Apache',
    zip_safe=False,
    install_requires=[
        'tornado>=4.2.1',
        'aioredis>=0.2.3',
        'websockets>=2.6',
    ],
    packages=[
        'bachata',
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3',
    ],
    test_suite='bachata.tests',
)
