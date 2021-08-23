'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from meta_dds import exes
import re
from functools import partial
from pathlib import Path
from typing import Dict, Iterable, List, Optional, TypedDict, Union

import json5
from semver import VersionInfo

from meta_dds.error import MetaDDSException
from meta_dds.cmake import CMakeFileApiV1, FileApiQuery

import logging

_logger = logging.getLogger(__name__)


class BadPackageConfiguration(MetaDDSException):
    def __init__(self, message: str, project: Path):
        self.project = project
        super().__init__(message)


class BadCMakeLibSpecifier(BadPackageConfiguration):
    def __init__(self, message: str, cmake_lib: str, project: Path):
        self.cmake_lib = cmake_lib
        super().__init__(message, project=project)


class CannotInferPackageInfo(BadPackageConfiguration):
    def __init__(self, message: str, project: Path):
        super().__init__(message, project=project)

    @staticmethod
    def of(info: str, reason: str, flag: str, project: Path) -> 'CannotInferPackageInfo':
        return CannotInferPackageInfo(f'Unable to infer package {info}: {reason}. Pass an explicit {flag} flag.', project=project)


class _DependencySpecDict(TypedDict):
    name: str
    pkg_name: str  # find_package(<pkg_name>)


class DependencySpecDict(_DependencySpecDict, total=False):
    libs: List[str]
    configuration: Dict[str, str]


class MetaDDSDict(TypedDict, total=False):
    depends: List[Union[DependencySpecDict, str]]
    test_depends: List[Union[DependencySpecDict, str]]


# Additional property: ['meta_dds'] provides a MetaDDSDict.
# This cannot be properly implemented until TypedDict gets some sort of allow_extras
MetaPackageJSONDict = dict

DDSPackageJSONDict = dict


@dataclass
class Lib:
    dds_name: str
    cmake_name: str

    @staticmethod
    def parse(dds_pkg_name: str, cmake_name: str, project: Path) -> 'Lib':
        if '::' in cmake_name:
            libparts = cmake_name.split('::')
            if len(libparts) != 2:
                raise BadCMakeLibSpecifier(
                    f"Only one `::' allowed in CMake library. Given: ``{cmake_name}''", cmake_name, project=project)
            if libparts[0].lower() != dds_pkg_name:
                raise BadCMakeLibSpecifier(
                    f"``<package>`` must match corresponding DDS package in ``<package>::library''. Given: ``{cmake_name}''", cmake_name, project=project)

            libspec = libparts[1]
        else:
            libspec = cmake_name

        libspec = libspec.lower()
        dds_name = f'{dds_pkg_name}/{libspec}'

        return Lib(dds_name=dds_name, cmake_name=cmake_name)


@dataclass
class MetaDependency:
    name: str
    pkg_name: str
    version: VersionInfo
    configuration: Dict[str, str]
    libs: List[Lib]

    @staticmethod
    def extract(dep_or_json: Union[str, DependencySpecDict], project: Path) -> 'MetaDependency':
        if isinstance(dep_or_json, DependencySpecDict):
            pkg_id = dep_or_json['name']
            pkg_name = dep_or_json['pkg_name']
            configuration: Dict[str, str] = dep_or_json.get(
                'configuration', {})
            libs = dep_or_json.get('libs', [])
        else:
            pkg_id, libspec = dep_or_json.split(': ', maxsplit=1)
            pkg_name = None
            configuration: Dict[str, str] = {}
            libs = map(str.strip, libspec.split(','))

        name, version = pkg_id.split('@', maxsplit=1)
        name = name
        version = VersionInfo.parse(version)

        # FIXME: Use a proper exception
        assert name.islower()

        if pkg_name is None:
            pkg_name = name

        libs = map(partial(Lib.parse, name, project=project), libs)

        return MetaDependency(
            name=name,
            pkg_name=pkg_name,
            version=version,
            configuration=configuration,
            libs=list(libs),
        )


@dataclass
class PackageID:
    namespace: str
    name: str

    def __str__(self) -> str:
        return f'{self.namespace}/{self.name}'


@dataclass
class MetaPackageInfo:
    pkg_id: PackageID = None
    version: VersionInfo = None
    meta_depends: List[MetaDependency] = field(default_factory=list)
    meta_test_depends: List[MetaDependency] = field(default_factory=list)


class MetaPackage(ABC):
    def __init__(self, *,
                 project_dir: Path,
                 info: MetaPackageInfo,
                 build_adjust_script: Optional[Path] = None):
        self.project_dir = project_dir
        self.info = info
        self.build_adjust_script = build_adjust_script

    @staticmethod
    def _meta_build_dds(project: Path) -> Optional[Path]:
        if project.joinpath('meta_build.py').exists():
            return project / 'meta_build.py'
        return None


class MetaPackageDDS(MetaPackage):
    '''
    {
        ...
        meta_dds: {
            depends: [
                "freetype@2.11.0: freetype::freetype",
                { name: 'llvm@7.1.0', pkg_name: 'LLVM', libs: ['llvm::llvm'], configuration: {'HAS_FREETYPE': 'TRUE'} },
            ],
            // At some point, list executable dependencies which can be found by the depends...
            executables: [
                "llvm-tblgen@11.1.0"
            ]
        }
    }

    The inner JSON here
    '''

    def __init__(self, *,
                 project_dir: Path,
                 info: MetaPackageInfo,
                 dds_package_json: DDSPackageJSONDict,
                 build_adjust_script: Optional[Path] = None):
        super().__init__(project_dir=project_dir, info=info,
                         build_adjust_script=build_adjust_script)
        self.dds_package_json = dds_package_json


class MetaPackageCMake(MetaPackage):
    def __init__(self, *,
                 project_dir: Path,
                 info: MetaPackageInfo,
                 cmakelists: Path,
                 build_adjust_script: Optional[Path] = None):
        super().__init__(project_dir=project_dir, info=info,
                         build_adjust_script=build_adjust_script)
        self.cmakelists = cmakelists


def load_json5(project: Path, package_json_path: Path) -> MetaPackage:
    with open(package_json_path, 'r') as f:
        raw_json: MetaPackageJSONDict = json5.load(f)
        meta_dds_json: MetaDDSDict = raw_json['meta_dds']
        del raw_json['meta_dds']

    return MetaPackageDDS(
        project_dir=project,
        info=MetaPackageInfo(
            pkg_id=PackageID(raw_json['namespace'], raw_json['name']),
            version=VersionInfo.parse(raw_json['version']),
            meta_depends=list(
                map(MetaDependency, meta_dds_json['depends'])),
            meta_test_depends=list(
                map(MetaDependency, meta_dds_json['test_depends'])),
        ),
        dds_package_json=raw_json,
        build_adjust_script=MetaPackage._meta_build_dds(project),
    )


def load_cmake(project: Path, cmakelists: Path, pkg_info: MetaPackageInfo = None) -> MetaPackage:
    if pkg_info is None:
        pkg_info = MetaPackageInfo()

    if pkg_info.pkg_id.name is None:
        file_api = CMakeFileApiV1(exes.cmake, 'meta-dds')
        codemodel, = file_api.query(FileApiQuery.CODEMODEL_V2)
        name = codemodel['configurations'][0]['projects'][0]['name']
        pkg_info.pkg_id.name = name
        _logger.info('Inferred package name as %s', name)

    if pkg_info.pkg_id.namespace is None:
        pkg_info.pkg_id.namespace = pkg_info.pkg_id.name
        _logger.info('Inferred package namespace as %s', pkg_info.pkg_id.name)

    cmakecache = exes.cmake.build_dir / 'CMakeCache.txt'
    if pkg_info.version is None:
        if not cmakecache.is_file():
            raise CannotInferPackageInfo.of(
                'version', 'No CMakeCache.txt generated', '--version', project=project)

        m = re.search(r'^CMAKE_PROJECT_VERSION:STATIC=(.*)$',
                      cmakecache.read_text(), flags=re.MULTILINE)
        if not m:
            raise CannotInferPackageInfo.of(
                'version', 'No VERSION in project() command', '--version', project=project)
        pkg_info.version = VersionInfo.parse(m.group(1))
        _logger.info('Inferred package version as %s', pkg_info.version)

    return MetaPackageCMake(
        project_dir=project,
        info=pkg_info,
        cmakelists=cmakelists,
        build_adjust_script=MetaPackage._meta_build_dds(project),
    )


def load_meta_package(project: Path, pkg_info: Optional[MetaPackageInfo] = None) -> MetaPackage:
    if project.joinpath('meta_package.json5').is_file():
        return load_json5(project, project / 'meta_package.json5')
    elif project.joinpath('CMakeLists.txt').is_file():
        return load_cmake(project, project / 'CMakeLists.txt', pkg_info=pkg_info)

    raise BadPackageConfiguration(
        f'Project has neither a meta_package.json or CMakeLists.txt: {project}', project=project)


MetaPackage.load_json5 = load_json5
MetaPackage.load_cmake = load_cmake
MetaPackage.load = load_meta_package
