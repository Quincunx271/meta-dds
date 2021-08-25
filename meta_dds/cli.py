'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

from argparse import ArgumentParser
from enum import Enum, auto
from pathlib import Path
from typing import Callable


class IfExists(Enum):
    FAIL = 'fail'
    SKIP = 'skip'
    REPLACE = 'replace'


def if_exists(parser: ArgumentParser, default: IfExists = IfExists.FAIL, *, help: str):
    parser.add_argument('--if-exists', type=IfExists, choices=('replace', 'skip', 'fail'),
                        default=default.value, help=help)


def toolchain(parser: ArgumentParser):
    parser.add_argument('-t', '--toolchain', default=None,
                        help='The DDS toolchain to use.')


def project(parser: ArgumentParser):
    parser.add_argument('-p', '--project', type=Path, default=Path.cwd(),
                        help='The project to build. Default: the current working directory.')


def output(parser: ArgumentParser):
    parser.add_argument('-o', '--out', '--output', type=Path, default=Path.cwd() / '_build',
                        dest='output', help=f"Directory where dds will write build results. Default: `./_build'.")


def add_arguments(parser: ArgumentParser, *args: Callable[[ArgumentParser], None]):
    for arg in args:
        arg(parser)
