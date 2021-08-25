'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import argparse
import fnmatch
from dataclasses import dataclass
from pathlib import Path
from tarfile import TarFile, TarInfo
from tempfile import NamedTemporaryFile
from typing import Callable, List, Optional

import pathspec
from semver import VersionInfo

from meta_dds import cli, exes
from meta_dds.cmake import CMake
from meta_dds.dds_exe import DDS
from meta_dds.package import DDSDependency, FindPackageMap, Lib, MetaDependency, MetaPackage, MetaPackageCMake, MetaPackageInfo, PackageID


def pkg_create(project: Path, output: Optional[Path], options: Optional[MetaPackageCMake.Options] = None):
    pkg = MetaPackage.load(project, options)
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

        for (filename, memfile) in pkg.psuedofiles():
            with NamedTemporaryFile(prefix='meta-dds-tar-mem-') as f:
                f.write(memfile.encode('utf-8'))
                f.flush()
                f.seek(0)
                tar.add(f.name, filename, recursive=False)


def pkg_create_main(args: argparse.Namespace):
    pkg_create(
        project=args.project,
        output=args.output,
        options=MetaPackageCMake.Options(
            name=args.name,
            namespace=args.namespace,
            version=args.version,
            find_package_map=FindPackageMap(
                find_package_name=args.find_package_name,
                libs=sum([[Lib.parse(dds_name.strip(), cmake_name.strip()) for dds_name, cmake_name in spec.split('=')]
                          for spec in args.libraries.split(',')]) if args.libraries else [],
            ) if args.find_package_name else None,
            depends=[DDSDependency.parse(x.strip()) for x in
                     args.depends.split(',')] if args.depends else [],
            meta_depends=[MetaDependency.parse(x.strip()) for x in
                          args.meta_depends.split(',')] if args.meta_depends else [],
        ))


def setup_parser(parser: argparse.ArgumentParser):
    cli.add_arguments(parser, cli.project)
    parser.add_argument('-o', '--out', '--output', type=Path, default=None,
                        dest='output',
                        help='Destination path for the resulting meta source distribution archive.')

    cmake_opts = parser.add_argument_group(
        'CMake Project Options', description='Supply information on the package (if CMake). Default: inferred from the CMake project.')
    cmake_opts.add_argument(
        '--name', help="The package name. Default: inferred from the CMake project's project() call.")
    cmake_opts.add_argument(
        '--namespace', help='A namespace for the package. Default: The same value as --name.')
    cmake_opts.add_argument(
        '--version', type=VersionInfo.parse, help="The package version. Default: inferred from the CMake project's project() call.")
    cmake_opts.add_argument(
        '--find-package-name',
        metavar='PACKAGE',
        help='The name of the package when found by find_package(PACKAGE). Required for CMake packages.')
    cmake_opts.add_argument(
        '--libraries',
        metavar="'DDS1=CMAKE1,DDS2=CMAKE2,...'",
        help='A comma separated list of DDS_NAME=CMAKE_NAME pairs, specifying the libraries in the CMake project and how they correspond with DDS library names.')
    cmake_opts.add_argument(
        '--depends', help='A comma separated list of DDS dependencies.')
    cmake_opts.add_argument(
        '--meta-depends', help="""A comma separated list of meta-dds dependencies formatted in the same manner as meta_package.json, i.e. either in the format of a DDS dependency or as a JSON5 object '{ name: DEP_NAME, configuration: { "CMAKE_CONFIG_VAR": "VALUE", ... } }'.""")

    parser.set_defaults(func=pkg_create_main)
