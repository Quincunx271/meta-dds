'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

from argparse import ArgumentParser

from meta_dds import cli


def setup_parser(parser: ArgumentParser):
    cli.add_arguments(parser, cli.project, cli.toolchain, cli.output)
