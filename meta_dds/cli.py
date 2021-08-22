'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

from argparse import ArgumentParser
from pathlib import Path
from typing import Callable


def toolchain(parser: ArgumentParser):
    parser.add_argument('-t', '--toolchain', default=None,
                        help='The DDS toolchain to use')


def project(parser: ArgumentParser):
    parser.add_argument('-p', '--project', type=Path, default=Path.cwd(),
                        help='The project to build. If not given, uses the current working directory.')


def output(parser: ArgumentParser):
    parser.add_argument('-o', '--out', '--output', type=Path, default=Path.cwd() / '_build',
                        dest='output', help='Directory where dds will write build results')


def add_arguments(parser: ArgumentParser, *args: Callable[[ArgumentParser], None]):
    for arg in args:
        arg(parser)
