'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Dict, Iterable, List, Optional, TypedDict, Union

import json5
from semver import VersionInfo

from meta_dds.error import MetaDDSException


class BadCMakeLibSpecifier(MetaDDSException):
    def __init__(self, message: str, cmake_lib: str):
        self.cmake_lib = cmake_lib
        super().__init__(message)

    @staticmethod
    def format(message: str, cmake_lib: str) -> 'BadCMakeLibSpecifier':
        return BadCMakeLibSpecifier(message=f'{message}: {cmake_lib}', cmake_lib=cmake_lib)


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


@dataclass(frozen=True)
class Lib:
    dds_name: str
    cmake_name: str

    @staticmethod
    def parse(dds_pkg_name: str, cmake_name: str) -> 'Lib':
        if '::' in cmake_name:
            libparts = cmake_name.split('::')
            if len(libparts) != 2:
                raise BadCMakeLibSpecifier(
                    f"Only one `::' allowed in CMake library. Given: ``{cmake_name}''", cmake_name)
            if libparts[0].lower() != dds_pkg_name:
                raise BadCMakeLibSpecifier(
                    f"``<package>`` must match corresponding DDS package in ``<package>::library''. Given: ``{cmake_name}''", cmake_name)

            libspec = libparts[1]
        else:
            libspec = cmake_name

        libspec = libspec.lower()
        dds_name = f'{dds_pkg_name}/{libspec}'

        return Lib(dds_name=dds_name, cmake_name=cmake_name)


@dataclass(frozen=True)
class MetaDependency:
    name: str
    pkg_name: str
    version: VersionInfo
    configuration: Dict[str, str]
    libs: List[Lib]

    @staticmethod
    def extract(dep_or_json: Union[str, DependencySpecDict]) -> 'MetaDependency':
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

        libs = map(partial(Lib.parse, name), libs)

        return MetaDependency(
            name=name,
            pkg_name=pkg_name,
            version=version,
            configuration=configuration,
            libs=list(libs),
        )


@dataclass(frozen=True)
class MetaPackageJSON:
    '''
    {
        ...
        meta_dds: {
            depends: [
                "freetype@2.11.0: freetype::freetype",
                { name: 'llvm@7.1.0', pkg_name: 'LLVM', libs: ['llvm::llvm'], configuration: {'LLVM_ENABLE_ASSERTIONS': 'ON'} },
            ],
            // At some point, list executable dependencies which can be found by the depends...
            exectables: [
                "llvm-tblgen@11.1.0"
            ]
        }
    }
    '''

    raw_json: MetaPackageJSONDict

    def dds_package_json(self) -> dict:
        result = self.__json.copy()
        del result['meta_dds']
        return result

    @property
    def meta_dds(self) -> MetaDDSDict:
        return self.__json['meta_dds']

    def meta_depends(self) -> Iterable[MetaDependency]:
        return map(MetaDependency, self.meta_dds['depends'])

    def meta_test_depends(self) -> Iterable[MetaDependency]:
        return map(MetaDependency, self.meta_dds['test_depends'])


@dataclass(frozen=True)
class MetaPackage:
    package_json: MetaPackageJSON
    build_adjust_script: Optional[Path]


def load_meta_package(package_json_path: Path, meta_build_dds_path: Path) -> MetaPackage:
    with open(package_json_path, 'r') as f:
        package_json = MetaPackageJSON(json5.load(f))

    return MetaPackage(package_json, meta_build_dds_path if meta_build_dds_path.exists() else None)
