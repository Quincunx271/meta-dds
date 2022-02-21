'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import dataclasses
import logging
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Iterable, Optional

from meta_dds import cli, exes
from meta_dds.tempfiles import TemporaryDirectory
from meta_dds.cmake import CMakeFileApiV1, FileApiQuery
from meta_dds.toolchain import (DDSToolchain, generate_toolchain,
                                get_dds_toolchain)
from meta_dds.cmake_sdist import CMakeSDistTemplate
from meta_dds.util import IfExists
from meta_dds.package import Lib, MetaPackage, MetaPackageCMake

_logger = logging.getLogger(__name__)



def forge(project: Path, output: Path, toolchain: Optional[str], scratch_dir: Path = None,
          options: Optional[MetaPackageCMake.Options] = None, if_exists: IfExists = IfExists.FAIL):
    toolchain: DDSToolchain = get_dds_toolchain(toolchain)
    cmake_toolchain_contents: str = generate_toolchain(toolchain)

    with TemporaryDirectory(scratch_dir=scratch_dir) as d:
        sdist_template = CMakeSDistTemplate(name=None, cmakelists_dir=project, options=options, scratch_dir=d / 'cmake')
        sdist: SDist = sdist_template.instantiate(toolchain, d)

        exes.dds.pkg().create(project=sdist.project_root, output=output, if_exists=if_exists)


def forge_main(args: Namespace):
    forge(args.project, args.output, args.toolchain,
          scratch_dir=args.scratch_dir, options=cli.parse_cmake_meta_info(args), if_exists=args.if_exists)


def setup_parser(parser: ArgumentParser):
    cli.add_arguments(parser, cli.toolchain, cli.project,
                      cli.output, cli.cmake_meta_info)
    cli.if_exists(parser, help='What to do if the sdist tar.gz already exists')
    parser.add_argument('--scratch-dir', type=Path, default=None,
                        help='Path to configure as a CMake build directory in the process of forging an sdist')
    parser.set_defaults(func=forge_main)
