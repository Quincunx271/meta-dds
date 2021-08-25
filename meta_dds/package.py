'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

import dataclasses
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from sys import version
from textwrap import dedent
from typing import Dict, Iterable, List, Optional, Tuple, TypedDict, Union

import json5
from semver import VersionInfo

from meta_dds import exes, util
from meta_dds.cmake import CMake, CMakeFileApiV1, FileApiQuery
from meta_dds.errors import MetaDDSException
from meta_dds.logutils import EXIT_INTERNAL_ERROR, EXIT_USER_ERROR

_logger = logging.getLogger(__name__)


class BadPackageConfiguration(MetaDDSException):
    def __init__(self, message: str, project: Optional[Path] = None):
        self.project = project
        super().__init__(message)


class BadCMakeLibSpecifier(BadPackageConfiguration):
    def __init__(self, message: str, cmake_lib: str, project: Optional[Path] = None):
        self.cmake_lib = cmake_lib
        super().__init__(message, project=project)


class CannotInferPackageInfo(BadPackageConfiguration):
    def __init__(self, message: str, project: Optional[Path] = None):
        super().__init__(message, project=project)

    @staticmethod
    def of(info: str, reason: str, flag: str, project: Optional[Path] = None) -> 'CannotInferPackageInfo':
        return CannotInferPackageInfo(f'Unable to infer package {info}: {reason}. Pass an explicit {flag} flag.', project=project)


class _DependencySpecDict(TypedDict):
    name: str
    find_package_name: str  # find_package(<find_package_name>)


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
class PackageID:
    namespace: str
    name: str

    def __str__(self) -> str:
        return f'{self.namespace}::{self.name}'


@dataclass
class Lib:
    dds_name: str
    cmake_name: str

    @staticmethod
    def parse(dds_name: str, cmake_name: str) -> 'Lib':
        if cmake_name.count('::') > 1:
            raise BadCMakeLibSpecifier(
                f"Only one `::' allowed in CMake library. Given: ``{cmake_name}''", cmake_name)

        return Lib(dds_name=dds_name, cmake_name=cmake_name)


@dataclass
class FindPackageMap:
    find_package_name: str
    libs: List[Lib]

    @staticmethod
    def parse(find_package_name: str, library_map: Dict[str, str]) -> 'FindPackageMap':
        return FindPackageMap(
            find_package_name=find_package_name,
            libs=[Lib.parse(dds_name, cmake_name)
                  for dds_name, cmake_name in library_map.items()]
        )

    def library_map(self) -> Dict[str, str]:
        '''
        Format as a dict for writing to JSON
        '''
        return {lib.dds_name: lib.cmake_name for lib in self.libs}


@dataclass
class DDSDependency:
    pkg_id: PackageID
    version: VersionInfo

    @staticmethod
    def parse(id: str) -> 'DDSDependency':
        name, version_str = id.split('@', maxsplit=1)
        return DDSDependency(PackageID(None, name), VersionInfo.parse(version_str))

    def __str__(self) -> str:
        return f'{self.pkg_id.name}@{self.version}'


@dataclass
class MetaDependency:
    class JSON(TypedDict):
        '''
        {
            name: 'llvm@7.1.0',
            configuration: {
                'ENABLE_X86': 'ON',
            }
        }
        '''
        name: str
        configuration: Dict[str, str]

    dep: DDSDependency
    configuration: Dict[str, str]

    @staticmethod
    def parse(dep_or_json: Union[str, JSON]) -> 'MetaDependency':
        if isinstance(dep_or_json, str):
            pkg_name = dep_or_json
            configuration: Dict[str, str] = {}
        else:
            pkg_name = dep_or_json['name']
            configuration: Dict[str, str] = dep_or_json.get(
                'configuration', {})

        return MetaDependency(
            DDSDependency.parse(pkg_name),
            configuration=configuration,
        )

    def to_json(self) -> Union[str, JSON]:
        if self.configuration:
            return MetaDependency.JSON(
                name=str(self.dep),
                configuration=self.configuration
            )
        else:
            return str(self.dep)


@dataclass
class MetaPackageInfo:
    class _JSON(TypedDict):
        name: str
        namespace: str
        version: str

    class JSON(_JSON, total=False):
        '''
        {
            name: 'llvm',
            namespace: 'llvm',
            version: '7.1.0',
            find_package: 'LLVM',
            library_map: {
                'llvm': 'llvm::llvm',
            },
            depends: ['zlib@1.2.3'],
            meta_depends: ['ylib@2.3.4'],
        }
        '''
        find_package: str
        library_map: Dict[str, str]
        depends: List[str]
        meta_depends: List[Union[str, MetaDependency.JSON]]

    pkg_id: PackageID
    version: VersionInfo
    find_package_map: FindPackageMap
    depends: List[DDSDependency] = field(default_factory=list)
    meta_depends: List[MetaDependency] = field(default_factory=list)

    @staticmethod
    def parse(json: JSON) -> 'MetaPackageInfo':
        return MetaPackageInfo(
            pkg_id=PackageID(json['namespace'], json['name']),
            version=VersionInfo.parse(json['version']),
            find_package_map=FindPackageMap.parse(
                find_package_name=json.get('find_package', json['name']),
                library_map=json.get(
                    'library_map', {json['name']: f"{json['namespace']}::{json['name']}"})
            ),
            depends=json.get('depends', []),
            meta_depends=json.get('meta_depends', []),
        )

    def to_json(self) -> JSON:
        '''
        Format as a dict for writing to JSON
        '''
        return MetaPackageInfo.JSON(
            name=self.pkg_id.name,
            namespace=self.pkg_id.namespace,
            version=str(self.version),
            find_package=self.find_package_map.find_package_name,
            library_map=self.find_package_map.library_map(),
            depends=list(map(str, self.depends)),
            meta_depends=list(map(MetaDependency.to_json, self.meta_depends)),
        )


@dataclass
class MetaPackage(ABC):
    info: MetaPackageInfo
    test_depends: List[DDSDependency] = field(default_factory=list)
    meta_test_depends: List[MetaDependency] = field(default_factory=list)

    def psuedofiles(self) -> Iterable[Tuple[str, str]]:
        return []

    @staticmethod
    def load(project: Path, options: 'MetaPackageCMake.Options' = None) -> 'MetaPackage':
        if project.joinpath('meta_package.json5').is_file():
            return MetaPackageDDS.parse(json5.loads(project.joinpath('meta_package.json5').read_text()))
        elif project.joinpath('CMakeLists.txt').is_file():
            # TODO: Should this have its own build_dir too?
            cmake_exe = dataclasses.replace(exes.cmake, source_dir=project)

            if project.joinpath('meta_package.info.json5').is_file():
                return MetaPackageCMake(
                    info=MetaPackageInfo.parse(json5.loads(
                        project.joinpath('meta_package.info.json5').read_text())),
                    cmake_exe=cmake_exe,
                )

            if options is None:
                options = MetaPackageCMake.Options()
            return MetaPackageCMake.load(cmake_exe, options)

        raise BadPackageConfiguration(
            f'Project has neither a meta_package.json or CMakeLists.txt: {project}', project=project)


@dataclass
class MetaPackageDDS(MetaPackage):
    '''
    {
        depends: [
            'nlohmann-json@3.10.0'
        ],
        ...
        meta_dds: {
            depends: [
                "freetype@2.11.0: freetype::freetype", // "Macro" for:
                {
                    name: 'freetype@2.11.0',
                    find_package: 'freetype', // same as before the @
                    library_map: {
                        'freetype': 'freetype::freetype',
                    }
                },
                {
                    name: 'llvm@7.1.0',
                    find_package: 'LLVM',
                    library_map: {
                        'llvm': 'llvm::llvm',
                    },
                    configuration: {
                        'HAS_FREETYPE': 'TRUE' // Not relevant for LLVM, but demonstrative
                    }
                },
            ],
            find_package_map: {
                'nlohmann-json': {
                    find_package: 'nlohmann_json',
                    library_map: {
                        'nlohmann-json': 'nlohmann_json::nlohmann_json'
                    }
                },
            },
            // At some point, list executable dependencies which can be found by the depends...
            executables: [
                "llvm-tblgen@11.1.0"
            ]
        }
    }

    The inner JSON here
    '''

    dds_package_json: DDSPackageJSONDict = None

    # Additional property: ['meta_dds'] provides a MetaDDSDict.
    # This cannot be properly implemented until TypedDict gets some sort of allow_extras
    JSON = dict

    def __post_init__(self):
        if self.dds_package_json is None:
            _logger.critical(
                'Internal Error: MetaPackageDDS.dds_package_json must be initialized')
            exit(EXIT_INTERNAL_ERROR)

    @staticmethod
    def parse(json: JSON) -> 'MetaPackageDDS':
        meta_json: MetaDDSDict = json['meta_dds']
        find_package_map = meta_json.get('find_package_map', {})
        main_find_package_map = find_package_map.get(json['name'], {})

        dds_json = json.copy()
        del dds_json['meta_dds']

        return MetaPackageDDS(
            info=MetaPackageInfo.parse(util.del_nones(MetaPackageInfo.JSON(
                name=json['name'],
                namespace=json['namespace'],
                version=json['version'],
                find_package=main_find_package_map.get('find_package'),
                library_map=main_find_package_map.get('library_map'),
                depends=list(
                    map(DDSDependency.parse, json.get('depends', []))),
                meta_depends=list(
                    map(MetaDependency.parse, json.get('meta_depends', []))),
            ))),
            test_depends=list(
                map(DDSDependency.parse, json.get('test_depends', []))),
            meta_test_depends=list(
                map(MetaDependency.parse, json.get('meta_test_depends', []))),
            dds_package_json=dds_json,
        )


@dataclass
class MetaPackageCMake(MetaPackage):
    cmake_exe: CMake = None

    def __post_init__(self):
        if self.cmake_exe is None:
            _logger.critical(
                'Internal Error: MetaPackageCMake.cmake_exe must be initialized')
            exit(EXIT_INTERNAL_ERROR)

    # Overrides to give a meta_package.info.json5 so that we don't have to re-infer.
    def psuedofiles(self) -> Iterable[Tuple[str, str]]:
        yield ('meta_package.info.json5', json.dumps(self.info.to_json(), indent=2))

    @dataclass
    class Options:
        name: Optional[str] = None
        namespace: Optional[str] = None
        version: Optional[VersionInfo] = None
        find_package_map: Optional[FindPackageMap] = None
        depends: Optional[List[DDSDependency]] = None
        meta_depends: Optional[List[MetaDependency]] = None

    @staticmethod
    def load(cmake_exe: CMake, options: Options) -> 'MetaPackageCMake':
        if options.name is None:
            file_api = CMakeFileApiV1(cmake_exe, 'meta-dds')
            codemodel, = file_api.query(FileApiQuery.CODEMODEL_V2)
            options.name = codemodel['configurations'][0]['projects'][0]['name']
            _logger.info('Inferred package name as %s', options.name)

        if options.namespace is None:
            options.namespace = options.name
            _logger.info('Inferred package namespace as %s', options.namespace)

        if options.version is None:
            cmakecache = cmake_exe.build_dir / 'CMakeCache.txt'
            if not cmakecache.is_file():
                cmake_exe.configure()
                if not cmakecache.is_file():
                    raise CannotInferPackageInfo.of(
                        'version', 'No CMakeCache.txt generated', '--version',
                        project=cmake_exe.source_dir)

            m = re.search(r'^CMAKE_PROJECT_VERSION:STATIC=(.*)$',
                          cmakecache.read_text(), flags=re.MULTILINE)
            if not m:
                raise CannotInferPackageInfo.of(
                    'version', 'No VERSION in project() command', '--version',
                    project=cmake_exe.source_dir)
            options.version = VersionInfo.parse(m.group(1))
            _logger.info('Inferred package version as %s', options.version)

        if options.find_package_map is None:
            raise CannotInferPackageInfo.of(
                'find_package map', 'Unimplemented', '--find-package-name and --libraries')

        if options.depends is None:
            raise CannotInferPackageInfo.of(
                'depends', 'Unimplemented', '--depends')

        if options.meta_depends is None:
            raise CannotInferPackageInfo.of(
                'meta_depends', 'Unimplemented', '--meta-depends')

        return MetaPackageCMake(
            info=MetaPackageInfo(
                pkg_id=PackageID(options.namespace, options.name),
                version=options.version,
                find_package_map=options.find_package_map,
                depends=options.depends,
                meta_depends=options.meta_depends,
            ),
            cmake_exe=cmake_exe,
        )
