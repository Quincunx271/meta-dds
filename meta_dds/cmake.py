'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import json
import logging
import re
import shlex
import subprocess
import dataclasses
from argparse import ArgumentParser
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, List, Optional, Union

from semver import VersionInfo

from meta_dds import logutils
from meta_dds.tempfiles import TemporaryDirectory, TemporaryFile

_logger = logging.getLogger(__name__)


@dataclass
class CMake:
    cmake_exe: Union[str, Path]
    source_dir: Path
    build_dir: Path
    cmake_version: VersionInfo = None

    def __post_init__(self):
        if self.cmake_version is None:
            version_output = subprocess.run(
                [str(self.cmake_exe), '--version'], capture_output=True, check=True, text=True).stdout
            object.__setattr__(self, 'cmake_version', VersionInfo.parse(
                re.search(r'version (.*)', version_output).group(1)))

            _logger.trace('Found CMake version %s: %s',
                          self.cmake_version, self.cmake_exe)
        self.source_dir = self.source_dir.resolve()
        self.build_dir = self.build_dir.resolve()

    def configure(self, args={}, quiet=False, toolchain: Optional[Path] = None):
        cache_preload = self.build_dir / 'meta-dds-cmake-cache-preload.cmake'
        self.build_dir.mkdir(parents=True, exist_ok=True)
        cache_preload.write_text(generate_preloaded_cache_script(args))

        cmd = [
            str(self.cmake_exe),
            '-S', str(self.source_dir),
            '-B', str(self.build_dir),
            '-C', str(cache_preload)
        ]
        if toolchain is not None:
            cmd.extend(['--toolchain', str(toolchain.resolve())])

        _logger.trace('Configuring with command: %s%s%s',
                      logutils.defer(lambda: shlex.join(cmd)),
                      '\nAnd configuration values:\n' if args else '',
                      logutils.defer(lambda: '\t\n'.join(f'{key}={value}' for key, value in args.items())))
        if quiet:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        else:
            subprocess.run(cmd, check=True)

    def build(self, target: Optional[str] = None):
        cmd = [str(self.cmake_exe), '--build', str(self.build_dir)]
        if target is not None:
            cmd += ['--target', target]

        _logger.trace('Building with command: %s',
                      logutils.defer(lambda: shlex.join(cmd)))
        subprocess.run(cmd, check=True)


class FileApiQuery(Enum):
    CODEMODEL_V2 = 'codemodel-v2'
    CACHE_V2 = 'cache-v2'
    CMAKEFILES_V1 = 'cmakeFiles-v1'
    TOOLCHAINS_V1 = 'toolchains-v1'


@dataclass(frozen=True)
class CMakeFileApiV1:
    cmake: CMake
    client: str

    @property
    def api_dir(self) -> Path:
        return self.cmake.build_dir / '.cmake/api/v1'

    @property
    def client_id(self) -> str:
        return f'client-{self.client}'

    @property
    def query_dir(self) -> Path:
        return self.api_dir / f'query/{self.client_id}'

    @property
    def reply_dir(self) -> Path:
        return self.api_dir / 'reply'

    def reply_index_path(self) -> Path:
        indices = sorted(f for f in self.reply_dir.iterdir() if f.is_file()
                         and f.name.startswith('index-') and f.suffix == '.json')
        _logger.trace('Found reply index at %s', indices[-1])
        return indices[-1]

    def query(self, *queries: List[FileApiQuery]) -> List[Path]:
        self.query_dir.mkdir(parents=True, exist_ok=True)
        for query in queries:
            self.query_dir.joinpath(query.value).touch(exist_ok=True)

        _logger.trace('Querying CMake with %s', logutils.defer(
            lambda: ', '.join(f"`{q.value}'" for q in queries)))
        self.cmake.configure(quiet=True)

        index_path = self.reply_index_path()
        index = json.loads(index_path.read_text())
        replies = index['reply'][self.client_id]

        return [json.loads(self.reply_dir.joinpath(replies[query.value]['jsonFile']).read_text()) for query in queries]


@dataclass
class CMakeTargetInfo:
    public_include_dirs: List[Path] = field(default_factory=list)
    public_preprocessor_defines: Dict[str, str] = field(default_factory=dict)
    include_dirs: List[Path] = field(default_factory=list)
    source_files: List[Path] = field(default_factory=list)
    preprocessor_defines: Dict[str, str] = field(default_factory=dict)
    # CMake dependencies
    public_dependencies: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)

def query_cmake_target(cmake: CMake, toolchain, target: str) -> CMakeTargetInfo:
    result = CMakeTargetInfo()
    PROPERTIES = {
        'INTERFACE_COMPILE_DEFINITIONS': result.public_preprocessor_defines,
        'INTERFACE_INCLUDE_DIRECTORIES': result.public_include_dirs,
        'INTERFACE_SYSTEM_INCLUDE_DIRECTORIES': result.public_include_dirs,
        'SOURCES': result.source_files,
        'INCLUDE_DIRECTORIES': result.include_dirs,
        'COMPILE_DEFINITIONS': result.preprocessor_defines,
        'LINK_LIBRARIES': result.dependencies,
        'INTERFACE_LINK_LIBRARIES': result.public_dependencies,
    }
    from meta_dds import toolchain as tc
    cmake_toolchain_contents: str = tc.generate_toolchain(toolchain)
    with TemporaryFile() as file, TemporaryDirectory(scratch_dir=cmake.build_dir / '.meta_dds_query') as tmpdir:
        project_dir = cmake.source_dir.resolve()
        cmakelists_contents = [f'''
        project(QueryProject)

        set(str)
        add_subdirectory("{project_dir}" "${{CMAKE_CURRENT_BINARY_DIR}}/project")
        ''']

        for property_name in PROPERTIES.keys():
            cmakelists_contents.append(f'''
                get_target_property(VAR {target} {property_name})
                if(VAR)
                    string(APPEND str "{property_name}=${{VAR}}\\n")
                    message(STATUS "{property_name}=${{VAR}}\\n")
                endif()
            ''')

        cmakelists_contents.append(f'''
        string(REGEX REPLACE "\\\\$<LINK_ONLY:([^>]*)>" "" str "${{str}}")
        file(GENERATE OUTPUT "{file}" CONTENT "${{str}}"
            TARGET {target})
        ''')

        cmake_toolchain = tmpdir / 'toolchain.cmake'
        cmake_toolchain.write_text(cmake_toolchain_contents)

        cmakelist = tmpdir / 'CMakeLists.txt'
        cmakelist.write_text('\n'.join(cmakelists_contents))

        cmake = dataclasses.replace(
            cmake, source_dir=tmpdir, build_dir=tmpdir / 'cmake_build')
        cmake.configure(toolchain=cmake_toolchain)

        contents = file.read_text()
        _logger.trace('Raw contents: %s', contents)

    for line in contents.splitlines():
        prop, value = line.split('=', maxsplit=1)
        prop = PROPERTIES[prop]
        if isinstance(prop, list):
            prop += [v for v in value.split(';') if v]
        else:
            assert isinstance(prop, dict)
            for item in (v for v in value.split(';') if v):
                defs = item.split('=', maxsplit=1)
                if len(defs) == 1:
                    defs.append('1')
                k, v = defs
                prop[k] = v

    return CMakeTargetInfo(
        public_preprocessor_defines=result.public_preprocessor_defines,
        preprocessor_defines=result.preprocessor_defines,
        public_include_dirs=[Path(x) for x in set(result.public_include_dirs)],
        include_dirs=[Path(x) for x in set(result.include_dirs)],
        source_files=[Path(x) for x in set(result.source_files)],
        public_dependencies=[x for x in set(result.public_dependencies) if '/' not in x and '.' not in x],
        dependencies=[x for x in set(result.dependencies) if '/' not in x and '.' not in x],
    )



def default_configure_args(cmake_version: VersionInfo) -> Dict[str, str]:
    return {
        # Deprecated option 3.16+:
        'CMAKE_FIND_PACKAGE_NO_PACKAGE_REGISTRY': 'YES',
        'CMAKE_FIND_PACKAGE_NO_SYSTEM_PACKAGE_REGISTRY': 'YES',
        'CMAKE_FIND_PACKAGE_NO_PACKAGE_REGISTRY': 'YES',
        # Replaced by:
        'CMAKE_FIND_USE_PACKAGE_REGISTRY': 'NO',
        'CMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY': 'NO',
        'CMAKE_FIND_USE_PACKAGE_REGISTRY': 'NO',

        # Other options
        'CMAKE_FIND_USE_CMAKE_ENVIRONMENT_PATH': 'NO',
        'CMAKE_FIND_USE_CMAKE_PATH': 'NO',
        'CMAKE_FIND_USE_CMAKE_SYSTEM_PATH': 'NO',

        'CMAKE_FIND_NO_INSTALL_PREFIX': 'YES',
        'CMAKE_FIND_PACKAGE_PREFER_CONFIG': 'YES',

        'CMAKE_FIND_ROOT_PATH': '',
        'CMAKE_FIND_ROOT_PATH_MODE_INCLUDE': 'ONLY',
        'CMAKE_FIND_ROOT_PATH_MODE_LIBRARY': 'ONLY',
        'CMAKE_FIND_ROOT_PATH_MODE_PACKAGE': 'ONLY',
    }


def generate_preloaded_cache_script(cache_values: Dict[str, str]) -> str:
    return '\n'.join(f'set({key} [======[{value}]======] CACHE STRING "")' for key, value in cache_values.items())


def setup_parser(parser: ArgumentParser):
    # Prevents circular import error; only used for setting up argparse.
    from meta_dds import cmake_forge_sdist

    subparsers = parser.add_subparsers()

    cmake_forge_sdist.setup_parser(subparsers.add_parser(
        'forge-sdist', help='Instantiate a toolchain-dependent sdist from a Meta-DDS or CMake project.'))

    from meta_dds import cli
    cmake_query_target = subparsers.add_parser('query-target')
    def query(args):
        from meta_dds import exes, toolchain
        with TemporaryDirectory(scratch_dir=args.scratch_dir) as f:
            cmake_exe = dataclasses.replace(exes.cmake, source_dir=args.project, build_dir=f)
            print(query_cmake_target(cmake_exe, toolchain.get_dds_toolchain(args.toolchain), args.target))
    cmake_query_target.set_defaults(func=query)
    cli.add_arguments(cmake_query_target, cli.project, cli.toolchain, cli.scratch_dir)
    cmake_query_target.add_argument('--target', help='', required=True)
    # TODO: Full CMake project sdist porter subcommand. A command that has none of this meta-sdist stuff.
