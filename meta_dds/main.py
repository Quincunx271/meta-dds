'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import argparse
import logging
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Optional

import json5

from meta_dds import cmake
from meta_dds import toolchain as tc
from meta_dds.cmake import CMake, CMakeFileApiV1, FileApiQuery

logger = logging.getLogger(__name__)


def run_setup(toolchain: Optional[str], project: Path, output: Path):
    assert toolchain.is_file()
    assert project.is_dir()
    output.mkdir(exist_ok=True)
    gen_proj = output / '_project'
    gen_proj.mkdir(exist_ok=True)

    gen_toolchain = gen_proj / f'toolchain{toolchain.suffix}'
    shutil.copy(toolchain, gen_toolchain)


def setup_main(args: argparse.Namespace):
    run_setup(args.toolchain, args.project, args.output)


def run_cmake(cmake_exe: Path, project: Path, output: Path, toolchain: Optional[str]):
    cmake_exe = CMake(cmake_exe=cmake_exe, source_dir=project,
                      build_dir=output / '_cmake_build')
    configure_args = cmake.default_configure_args(cmake_exe.cmake_version)

    toolchain_contents = cmake.generate_toolchain(
        tc.get_dds_toolchain(toolchain))
    tc_file = output / 'cmake_toolchain.cmake'
    if not tc_file.exists() or tc_file.read_text() != toolchain_contents:
        logger.debug('%s toolchain file',
                     'Updating' if tc_file.exists() else 'Creating')
        tc_file.parent.mkdir(parents=True, exist_ok=True)
        tc_file.write_text(toolchain_contents)

    cmake_exe.configure(configure_args, toolchain=tc_file)

    cmake_query = CMakeFileApiV1(cmake=cmake_exe, client='meta-dds')

    codemodel, = cmake_query.query(FileApiQuery.CODEMODEL_V2)


def cmake_main(args: argparse.Namespace):
    run_cmake(args.cmake_exe, args.project, args.output, args.toolchain)


def main():
    parser = argparse.ArgumentParser(
        prog='meta-dds', description='Source tree reifying DDS wrapper')
    parser.add_argument('--cmake', default='cmake', dest='cmake_exe',
                        help='The path to the CMake executable')
    parser.add_argument('--dds', default='dds', dest='dds_exe',
                        help='The path to the DDS executable')
    parser.add_argument('--log-level', default='info', choices=('trace', 'debug', 'info',
                                                                'warn', 'error', 'critical', 'silent'), help='Set the meta-dds logging level.')
    subparsers = parser.add_subparsers()

    setup = subparsers.add_parser(
        'setup', help='Setup the project source tree')
    setup.add_argument('-t', '--toolchain', help='The DDS toolchain to use')
    setup.add_argument('-p', '--project', type=Path, default=Path.cwd(),
                       help='The project to build. If not given, uses the current working directory.')
    setup.add_argument('-o', '--out', '--output', type=Path, default=Path.cwd() / '_build',
                       dest='output', help='Directory where dds will write build results')
    setup.set_defaults(func=setup_main)

    cmake = subparsers.add_parser(
        'cmake', help='Package a CMake project into a source-dist')
    cmake.add_argument('-t', '--toolchain', default=None,
                       help='The DDS toolchain to use')
    cmake.add_argument('-p', '--project', type=Path, default=Path.cwd(),
                       help='The project to build. If not given, uses the current working directory.')
    cmake.add_argument('-o', '--out', '--output', type=Path, default=Path.cwd() / '_build',
                       dest='output', help='Directory where dds will write build results')
    cmake.set_defaults(func=cmake_main)

    args = parser.parse_args()

    logging.basicConfig(level=_map_log_level(args.log_level))
    try:
        args.func
    except AttributeError:
        parser.print_help()
        parser.exit(2)
    args.func(args)


def _map_log_level(name: str) -> int:
    return {
        'trace': logging.DEBUG,
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'warn': logging.WARN,
        'error': logging.ERROR,
        'critical': logging.CRITICAL,
        'silent': logging.NOTSET,
    }[name]


if __name__ == '__main__':
    main()
