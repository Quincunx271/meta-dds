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
from argparse import ArgumentParser
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, List, Optional, Union

from semver import VersionInfo

from meta_dds import logutils

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

    # TODO: Full CMake project sdist porter subcommand. A command that has none of this meta-sdist stuff.
