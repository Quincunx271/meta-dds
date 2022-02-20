'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import argparse
from argparse import ArgumentParser
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from meta_dds import cli
from meta_dds.sdist import SDistTemplate, SDist, DirectoryPureSDist
from meta_dds.toolchain import DDSToolchain, get_dds_toolchain


@dataclass
class BuildSetup:
    build_dir: Path
    toolchain: DDSToolchain
    sdists: List[SDistTemplate] = field(default_factory=list)

    @property
    def _meta_projects_dir(self) -> Path:
        return self.build_dir / '_meta_projects'

    def _setup_meta_projects(self) -> List[SDist]:
        self._meta_projects_dir.mkdir(parents=True)
        return [sdist.instantiate(self.toolchain, self._meta_projects_dir / sdist.name)
                for sdist in self.sdists]

    def setup(self):
        self._setup_meta_projects()

def build_setup_main(args: argparse.Namespace):
    sdist = DirectoryPureSDist(args.project, [args.project / 'include'], [args.project / 'src'], [args.project / 'test'])
    setup = BuildSetup(build_dir = args.output, sdists=(sdist,), toolchain=get_dds_toolchain(args.toolchain))
    setup.setup()


def setup_parser(parser: ArgumentParser):
    cli.add_arguments(parser, cli.project, cli.toolchain, cli.output)
    parser.set_defaults(func=build_setup_main)
