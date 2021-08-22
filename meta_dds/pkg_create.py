'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import argparse
from dataclasses import dataclass
from pathlib import Path
from tarfile import TarFile, TarInfo
from typing import Callable, List, Optional
import fnmatch

from semver import VersionInfo
import pathspec

from meta_dds import cli, exes
from meta_dds.cmake import CMake
from meta_dds.dds_exe import DDS
from meta_dds.package import MetaPackage, MetaPackageInfo, PackageID


@dataclass
class PkgInfoArgs:
    name: Optional[str]
    version: Optional[VersionInfo]
    namespace: Optional[str]
    depends: List[str]
    meta_depends: List[str]


def pkg_create(project: Path, output: Optional[Path], info: PkgInfoArgs):
    pkg = MetaPackage.load(project,
                           MetaPackageInfo(
                               pkg_id=PackageID(info.namespace, info.name),
                               version=info.version,
                               meta_depends=info.meta_depends,
                               meta_test_depends=[],
                           ))
    if output is None:
        output = Path(f'{pkg.info.pkg_id.name}@{pkg.info.version}.tar.gz')
    if project.joinpath('.gitignore').is_file():
        spec = pathspec.PathSpec.from_lines(
            'gitwildmatch', project.joinpath('.gitignore').read_text().splitlines())

        def additional_filter(info: TarInfo) -> TarInfo:
            if spec.match_file(info.name):
                return None
            return info
    else:
        def additional_filter(info: TarInfo) -> TarInfo: return info

    with TarFile.open(output, 'w:gz') as tar:
        def simple_filter(info: TarInfo) -> TarInfo:
            if info.name in ('.git',):
                return None
            return info

        def multi_filter(*filters: List[Callable[[TarInfo], TarInfo]]) -> Callable[[TarInfo], TarInfo]:
            def f(info: TarInfo) -> TarInfo:
                for filter in filters:
                    info = filter(info)
                    if info is None:
                        return None
                return info
            return f

        tar.add(project, arcname='', filter=multi_filter(
            simple_filter, additional_filter))


def pkg_create_main(args: argparse.Namespace):
    pkg_create(
        project=args.project,
        output=args.output,
        info=PkgInfoArgs(
            args.name,
            args.version,
            args.namespace,
            [x.strip() for x in args.depends.split(',')] if args.depends else [],
            [x.strip() for x in args.meta_depends.split(
                ',')] if args.meta_depends else [],
        ))


def setup_parser(parser: argparse.ArgumentParser):
    cli.add_arguments(parser, cli.project)
    parser.add_argument('-o', '--out', '--output', type=Path, default=None,
                        dest='output',
                        help='Destination path for the resulting meta source distribution archive')

    info = parser.add_argument_group(
        'info', description='Supply information on the package (if CMake). If not present, this is inferred from the CMake project.')
    info.add_argument(
        '--name', help='The package name (inferred from the project() call in CMake)')
    info.add_argument(
        '--version', type=VersionInfo.parse, help='The package version (inferred from the project() call in CMake)')
    info.add_argument(
        '--namespace', help='A namespace for the package (default same as name)')
    info.add_argument(
        '--depends', help='A comma separated list of DDS dependencies')
    info.add_argument(
        '--meta-depends', help='A comma separated list of meta-dds dependencies (formatted in the same manner as meta_package.json)')

    parser.set_defaults(func=pkg_create_main)
