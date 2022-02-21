'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import shutil
import json
import difflib
import logging
import dataclasses
from dataclasses import dataclass
from typing import Optional, Iterable
from pathlib import Path
from hashlib import sha256

from meta_dds import exes, cmake
from meta_dds.errors import MetaDDSException
from meta_dds.cmake import CMakeFileApiV1, FileApiQuery
from meta_dds.tempfiles import TemporaryDirectory
from meta_dds.sdist import SDistTemplate, ToolchainSpecificSDist
from meta_dds.toolchain import DDSToolchain, generate_toolchain
from meta_dds.package import Lib, MetaPackage, MetaPackageCMake

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


@dataclass
class CMakeSDistTemplate(SDistTemplate):
    cmakelists_dir: Path
    scratch_dir: Optional[Path] = None
    options: Optional[MetaPackageCMake.Options] = None

    def instantiate(self, toolchain: DDSToolchain, tmp_dir: Path) -> ToolchainSpecificSDist:
        tmp_dir.mkdir(parents=True, exist_ok=True)

        cmake_toolchain_contents: str = generate_toolchain(toolchain)
        with TemporaryDirectory(scratch_dir=self.scratch_dir) as scratch_dir:
            cmake_exe = dataclasses.replace(
                exes.cmake, source_dir=self.cmakelists_dir, build_dir=scratch_dir / 'cmake_build')
            cmake_toolchain = scratch_dir / 'toolchain.cmake'
            cmake_toolchain.write_text(cmake_toolchain_contents)

            cmake_exe.configure(toolchain=cmake_toolchain)

            pkg = MetaPackageCMake.load(cmake_exe, self.options)

            dds_pkg_dir = tmp_dir / 'dds_pkg'
            dds_pkg_dir.mkdir(exist_ok=True)
            dds_pkg_lib_dir = dds_pkg_dir / 'libs'
            dds_pkg_lib_dir.mkdir(exist_ok=True)

            dds_pkg_dir.joinpath('package.json').write_text(json.dumps({
                'name': pkg.info.pkg_id.name,
                'namespace': pkg.info.pkg_id.namespace,
                'version': str(pkg.info.version),
                # TODO: the rest of it
            }, indent=2))

            file_api = CMakeFileApiV1(cmake_exe, 'meta-dds')
            codemodel, = file_api.query(FileApiQuery.CODEMODEL_V2)
            targets = next(iter(codemodel['configurations']))['targets']
            targets_map = {target['name']: target for target in targets}
            _logger.trace('Found CMake targets: %s', targets_map)
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
                    cmake_targetx = targets_map[lib.cmake_name]
                    cmake_target = cmake.CMakeTargetInfo()

                    target_info = json.loads(file_api.reply_dir.joinpath(
                        cmake_targetx['jsonFile']).read_text())
                    compile_groups = target_info['compileGroups']

                    for compile_info in compile_groups:
                        if 'defines' in compile_info:
                            for define in compile_info['defines']:
                                define = define['define']
                                if '=' in define:
                                    # `=` is not part of a valid identifier. Thus, if present, the first must denote the value of the preprocessor definition.
                                    name, value = define.split('=', maxsplit=2)
                                else:
                                    name = define
                                    value = '1'
                                cmake_target.preprocessor_defines[name] = value

                    include_dirs = sum(
                        (compile_info['includes'] for compile_info in compile_groups), start=[])
                    for include in include_dirs:
                        include_dir = Path(include['path'])
                        assert include_dir.is_absolute()
                        cmake_target.public_include_dirs.append(include_dir)

                    sources = [src for src in target_info['sources']
                               if 'compileGroupIndex' in src]
                    for source in sources:
                        source_path = main_src_dir.joinpath(source['path'])
                        assert source_path.is_file(), 'Cannot package build-time generated source files yet'
                        cmake_target.source_files.append(source['path'])

                except KeyError:
                    cmake_target = cmake.query_cmake_target(cmake_exe, toolchain=toolchain, target=lib.cmake_name)
                    # raise NotACMakeTarget(lib.cmake_name, targets_map.keys())

                lib_dir = dds_pkg_lib_dir / lib.dds_name
                lib_dir.mkdir(exist_ok=True)
                lib_dir.joinpath('library.json').write_text(json.dumps({
                    'name': lib.dds_name,
                }, indent=2))

                inc_dir = lib_dir / 'include'
                src_dir = lib_dir / 'src'

                inc_dir.mkdir(exist_ok=True)
                src_dir.mkdir(exist_ok=True)

                defines = []  # Any -D...s that we have to add
                for define, value in cmake_target.preprocessor_defines.items():
                    def_str_builder = ['#pragma once']
                    def_str_builder.append(f'#define {define} {value}')

                    def_str = '\n'.join(def_str_builder)
                    hash = sha256(def_str.encode('utf-8')).hexdigest()
                    define_file = src_dir / \
                        f'meta-dds.{pkg_name}.{hash}.predefine.h'
                    define_file.write_text(def_str)
                    defines.append(define_file)

                for include_dir in cmake_target.public_include_dirs:
                    assert include_dir.is_absolute()
                    shutil.copytree(include_dir, inc_dir, dirs_exist_ok=True)

                for source in cmake_target.source_files:
                    dst_path = src_dir.joinpath(source)
                    _logger.trace("Copying source file `%s' to `%s'", source, dst_path)
                    source_path = main_src_dir / source
                    dst_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(source_path, dst_path)

                    dst_text = dst_path.read_text()
                    dst_path.write_text(
                            ''.join(f'#include "{define}\n' for define in defines)
                            + dst_text)

        return ToolchainSpecificSDist(name=pkg_name, project_root=dds_pkg_dir)

