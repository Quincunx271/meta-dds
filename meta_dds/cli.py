'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Callable

from semver import VersionInfo

from meta_dds.package import (DDSDependency, FindPackageMap, Lib,
                              MetaDependency, MetaPackageCMake)
from meta_dds.util import IfExists


def if_exists(parser: ArgumentParser, default: IfExists = IfExists.FAIL, *, help: str):
    parser.add_argument('--if-exists', type=IfExists, choices=IfExists,
                        metavar=f"{{{','.join(x.value for x in IfExists)}}}",
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


def cmake_meta_info(parser: ArgumentParser):
    cmake_opts = parser.add_argument_group(
        'CMake Project Options', description='Supply information on the package (if CMake). Default: inferred from the CMake project.')
    cmake_opts.add_argument(
        '--name', help="The package name. Default: inferred from the CMake project's project() call.")
    cmake_opts.add_argument(
        '--namespace', help='A namespace for the package. Default: The same value as --name.')
    cmake_opts.add_argument(
        '--pkg-version', type=VersionInfo.parse, help="The package version. Default: inferred from the CMake project's project() call.")
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


def parse_cmake_meta_info(args: Namespace) -> MetaPackageCMake.Options:
    return MetaPackageCMake.Options(
        name=args.name,
        namespace=args.namespace,
        version=args.pkg_version,
        find_package_map=FindPackageMap(
            find_package_name=args.find_package_name,
            libs=[Lib.parse(dds_name.strip(), cmake_name.strip())
                  for dds_name, cmake_name in (spec.split('=') for spec in args.libraries.split(','))]
            if args.libraries else [],
        ) if args.find_package_name else None,
        depends=[DDSDependency.parse(x.strip()) for x in
                 args.depends.split(',')] if args.depends else [],
        meta_depends=[MetaDependency.parse(x.strip()) for x in
                      args.meta_depends.split(',')] if args.meta_depends else [],
    )


def add_arguments(parser: ArgumentParser, *args: Callable[[ArgumentParser], None]):
    for arg in args:
        arg(parser)
