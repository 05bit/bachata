"""
Toolkit for chats on top of asyncio and Tornado.
"""
from setuptools import setup
import bachata

__version__ = bachata.__version__

setup(
    name="bachata",
    version=__version__,
    author="Alexey Kinev",
    author_email='rudy@05bit.com',
    url='https://github.com/05bit/bachata',
    description=__doc__,
    license='Apache',
    zip_safe=False,
    install_requires=(
        'tornado>=4.2.1',
        'aioredis>=0.2.3',
        'websockets>=2.6',
    ),
    py_modules=[
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
