'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import dataclasses
import difflib
import json
import logging
import shutil
from argparse import ArgumentParser, Namespace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable, Optional

from meta_dds import cli, exes
from meta_dds.cmake import CMakeFileApiV1, FileApiQuery
from meta_dds.errors import MetaDDSException
from meta_dds.package import Lib, MetaPackage, MetaPackageCMake
from meta_dds.toolchain import (DDSToolchain, generate_toolchain,
                                get_dds_toolchain)
from meta_dds.util import IfExists

_logger = logging.getLogger(__name__)


class NotACMakeTarget(MetaDDSException):
    def __init__(self, cmake_target: str, cmake_targets: Iterable[str]):
        close = difflib.get_close_matches(cmake_target, cmake_targets)
        did_you_mean = ''
        if close:
            if len(close) == 1:
                did_you_mean = f" Did you mean `{close[0]}'?"
            elif len(close) == 2:
                did_you_mean = f" Did you mean one of `{close[0]}' or `{close[1]}'?"
            else:
                close_quoted = [f"`{x}'" for x in close[:-1]]
                did_you_mean = f" Did you mean one of {', '.join(close_quoted)}, or {close_quoted[-1]}?"

        self.cmake_target = cmake_target
        self.close_matches = close

        super().__init__(
            f"Could not find `{cmake_target}' in the CMake project.{did_you_mean}")


def forge(project: Path, output: Path, toolchain: Optional[str], scratch_dir: Path = None,
          options: Optional[MetaPackageCMake.Options] = None, if_exists: IfExists = IfExists.FAIL):
    toolchain: DDSToolchain = get_dds_toolchain(toolchain)
    cmake_toolchain_contents: str = generate_toolchain(toolchain)
    pkg = MetaPackage.load(project, options)

    with TemporaryDirectory(prefix='meta-dds-') as d:
        scratch_dir = scratch_dir or Path(d)
        if scratch_dir.exists():
            shutil.rmtree(scratch_dir)
        scratch_dir.mkdir(parents=True)
        cmake_exe = dataclasses.replace(
            exes.cmake, source_dir=project, build_dir=scratch_dir / 'cmake_build')
        dds_pkg_dir = scratch_dir / 'dds_pkg'
        dds_pkg_dir.mkdir(exist_ok=True)
        dds_pkg_lib_dir = dds_pkg_dir / 'libs'
        dds_pkg_lib_dir.mkdir(exist_ok=True)

        dds_pkg_dir.joinpath('package.json').write_text(json.dumps({
            'name': pkg.info.pkg_id.name,
            'namespace': pkg.info.pkg_id.namespace,
            'version': str(pkg.info.version),
            # TODO: the rest of it
        }, indent=2))

        cmake_toolchain = scratch_dir / 'toolchain.cmake'
        cmake_toolchain.write_text(cmake_toolchain_contents)

        cmake_exe.configure(toolchain=cmake_toolchain)

        file_api = CMakeFileApiV1(cmake_exe, 'meta-dds')
        codemodel, = file_api.query(FileApiQuery.CODEMODEL_V2)
        targets = codemodel['configurations'][0]['targets']
        targets_map = {target['name']: target for target in targets}
        main_src_dir = Path(codemodel['paths']['source']).resolve()
        pkg_name = pkg.info.pkg_id.name

        pkg_libs = pkg.libraries()
        if not pkg_libs:
            pkg_libs = [
                Lib(dds_name=pkg_name, cmake_name=f'{pkg_name}::{pkg_name}')]
            _logger.info("Inferred library map of DDS `%s' -> CMake `%s'",
                         pkg_libs[0].dds_name, pkg_libs[0].cmake_name)

        for lib in pkg_libs:
            try:
                cmake_target = targets_map[lib.cmake_name]
            except KeyError:
                raise NotACMakeTarget(lib.cmake_name, targets_map.keys())

            lib_dir = dds_pkg_lib_dir / lib.dds_name
            lib_dir.mkdir(exist_ok=True)
            lib_dir.joinpath('library.json').write_text(json.dumps({
                'name': lib.dds_name,
            }, indent=2))

            inc_dir = lib_dir / 'include'
            src_dir = lib_dir / 'src'

            inc_dir.mkdir(exist_ok=True)
            src_dir.mkdir(exist_ok=True)

            target_info = json.loads(file_api.reply_dir.joinpath(
                cmake_target['jsonFile']).read_text())
            compile_groups = target_info['compileGroups']

            defines = []  # Any -D...s that we have to add
            for compile_info in compile_groups:
                if 'defines' in compile_info:
                    def_str_builder = ['#pragma once']
                    for define in compile_info['defines']:
                        define = define['define']
                        if '=' in define:
                            # `=` is not part of a valid identifier. Thus, if present, the first must denote the value of the preprocessor definition.
                            name, value = define.split('=', maxsplit=2)
                        else:
                            name = define
                            value = ''
                        def_str_builder.append(f'#define {name} {value}')

                    def_str = '\n'.join(def_str_builder)
                    hash = sha256(def_str.encode('utf-8')).hexdigest()
                    define_file = src_dir / \
                        f'meta-dds.{pkg_name}.{hash}.predefine.h'
                    define_file.write_text(def_str)

                    defines.append(define_file)
                else:
                    defines.append(None)

            include_dirs = sum(
                (compile_info['includes'] for compile_info in compile_groups), start=[])
            for include in include_dirs:
                include_dir = Path(include['path'])
                assert include_dir.is_absolute()
                shutil.copytree(include_dir, inc_dir, dirs_exist_ok=True)

            sources = [src for src in target_info['sources']
                       if 'compileGroupIndex' in src]
            for source in sources:
                source_path = main_src_dir.joinpath(source['path'])
                assert source_path.is_file(), 'Cannot package build-time generated source files yet'
                dst_path = src_dir.joinpath(source['path'])
                _logger.trace("Copying source file `%s' to `%s'",
                              source['path'], dst_path)
                dst_path.parent.mkdir(parents=True, exist_ok=True)
                compile_group_index = source['compileGroupIndex']
                shutil.copy(source_path, dst_path)

                if defines[compile_group_index]:
                    dst_text = dst_path.read_text()
                    dst_path.write_text(
                        f'#include "{defines[compile_group_index].name}"\n' + dst_text)

        exes.dds.pkg().create(project=dds_pkg_dir, output=output, if_exists=if_exists)


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
