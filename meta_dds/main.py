'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import argparse
import logging
from meta_dds import error, logutils
from meta_dds.error import MetaDDSException
from meta_dds.dds_exe import DDS
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Optional

import json5

from meta_dds import cmake, exes, pkg_create, cli
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
    parser.add_argument('--color', '--colour', default='auto', choices=('no', 'yes', 'auto'),
                        help='Add color to meta-dds logging output. Default: auto (detect if terminal supports color).')
    subparsers = parser.add_subparsers()

    setup = subparsers.add_parser(
        'setup', help='Setup the project source tree')
    cli.add_arguments(setup, cli.toolchain, cli.project, cli.output)
    setup.set_defaults(func=setup_main)

    # This "cmake" should be the "setup" subcommand; it's setting up a project tree to be built by dds.
    cmake = subparsers.add_parser(
        'cmake', help='Instantiate a toolchain-dependent sdist from a Meta-DDS or CMake project')
    cli.add_arguments(cmake, cli.toolchain, cli.project, cli.output)
    cmake.set_defaults(func=cmake_main)

    pkg_create.setup_parser(subparsers.add_parser(
        'pkg-create', help='Package a Meta-DDS or CMake project into a meta-source-dist'))

    args = parser.parse_args()

    if args.log_level != 'silent':
        logging.basicConfig(level=_map_log_level(args.log_level))
        logging.root.handlers.clear()
        handler = logging.StreamHandler()
        handler.setLevel(_map_log_level(args.log_level))
        handler.setFormatter(logutils.get_formatter(
            logutils.ColorMode[args.color.upper()]))
        logging.root.addHandler(handler)

    exes.dds = DDS(args.dds_exe)
    with TemporaryDirectory(prefix='meta-dds-cmake-') as cmake_build_dir:
        exes.cmake = CMake(
            cmake_exe=args.cmake_exe,
            source_dir=args.project if hasattr(
                args, 'project') else Path.cwd(),
            build_dir=Path(cmake_build_dir),
        )

        try:
            args.func
        except AttributeError:
            parser.print_help()
            parser.exit(2)
        try:
            args.func(args)
        except MetaDDSException as ex:
            logging.critical(ex, exc_info=error.is_traceback())


def _map_log_level(name: str) -> int:
    return {
        'trace': logging.TRACE,
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'warn': logging.WARN,
        'error': logging.ERROR,
        'critical': logging.CRITICAL,
        'silent': logging.NOTSET,
    }[name]


if __name__ == '__main__':
    main()
