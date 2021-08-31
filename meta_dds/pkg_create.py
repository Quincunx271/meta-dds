'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import argparse
from pathlib import Path
from tarfile import TarFile, TarInfo
from tempfile import NamedTemporaryFile
from typing import Callable, List, Optional

import pathspec
from semver import VersionInfo

from meta_dds import cli
from meta_dds.package import (DDSDependency, FindPackageMap, Lib,
                              MetaDependency, MetaPackage, MetaPackageCMake)


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
        options=cli.parse_cmake_meta_info(args))


def setup_parser(parser: argparse.ArgumentParser):
    cli.add_arguments(parser, cli.project)
    parser.add_argument('-o', '--out', '--output', type=Path, default=None,
                        dest='output',
                        help='Destination path for the resulting meta source distribution archive.')
    cli.add_arguments(parser, cli.cmake_meta_info)
    parser.set_defaults(func=pkg_create_main)
