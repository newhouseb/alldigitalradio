import os
from setuptools import setup

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name = "alldigitalradio",
    version = "0.0.1",
    author = "Ben Newhouse",
    author_email = "newhouseb@gmail.com",
    description = ("A toolkit for building all digital radios in nmigen"),
    license = "Apache 2.0",
    keywords = "nmigen rf radio",
    packages=['alldigitalradio'],
    long_description=read('README.md'),
)
