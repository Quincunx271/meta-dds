'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''


import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import json5

from meta_dds import paths
from meta_dds.logutils import EXIT_USER_ERROR

DDSToolchain = dict

_logger = logging.getLogger(__name__)


def _default_dds_toolchain_paths() -> Iterable[Path]:
    return (
        Path.cwd() / 'toolchain.json5',
        Path.cwd() / 'toolchain.jsonc',
        Path.cwd() / 'toolchain.json',
        paths.dds_config_dir() / 'toolchain.json5',
        paths.dds_config_dir() / 'toolchain.jsonc',
        paths.dds_config_dir() / 'toolchain.json',
        paths.user_home_dir() / 'toolchain.json5',
        paths.user_home_dir() / 'toolchain.jsonc',
        paths.user_home_dir() / 'toolchain.json',
    )


def get_default_dds_toolchain() -> DDSToolchain:
    for tc in _default_dds_toolchain_paths():
        if tc.is_file():
            _logger.trace('Found default toolchain: %s', tc)
            return json5.loads(tc.read_text())

    _logger.error("Unable to find a default toolchain. " +
                  "Either specify a toolchain or provide a ``default toolchain''")
    exit(EXIT_USER_ERROR)


def get_builtin_toolchain(toolchain: str) -> DDSToolchain:
    '''
    Parse the builtin toolchain `toolchain`

    Ported from the DDS-proper `toolchain::get_builtin()` function
    '''
    assert toolchain[0] == ':'
    toolchain = [toolchain[1:]]

    result = {}

    def get_prefix(prefix: str, default=None):
        if toolchain[0].startswith(prefix):
            toolchain[0] = toolchain[0][len(prefix):]
            return prefix

        return default

    result['debug'] = bool(get_prefix('debug:'))

    def handle_prefix(key: str, prefix: str) -> bool:
        if prefix_val := get_prefix(prefix):
            result[key] = prefix_val[:-1]

        return bool(prefix_val)

    handle_prefix('compiler_launcher', 'ccache:')
    for cpp_ver in ('98', '03', '11', '14', '17', '20', '23'):
        if handle_prefix('cxx_version', f'c++{cpp_ver}:'):
            if cpp_ver == '23':
                _logger.warn(
                    'DDS does not support C++%s at this time', cpp_ver)
            break

    if toolchain[0].startswith('gcc') or toolchain[0].startswith('clang'):
        is_gcc = bool(get_prefix('gcc'))
        is_clang = bool(get_prefix('clang'))
        assert is_gcc or is_clang

        c_compiler_base, cxx_compiler_base, compiler_id = ('gcc', 'g++', 'gnu') if is_gcc else (
            'clang', 'clang++', 'clang')

        if get_prefix('-'):
            version = int(toolchain[0])
            toolchain[0] = ''
            if version not in (7, 8, 9, 10, 11, 12, 13):
                _logger.warn(
                    'Compiler version may be unsupported for %s: %i', compiler_id, version)

            suffix = f'-{version}'
        else:
            suffix = ''

        c_compiler_name = f'{c_compiler_base}{suffix}'
        cxx_compiler_name = f'{cxx_compiler_base}{suffix}'

        if toolchain[0]:
            _logger.error(
                "Unknown remaining builtin toolchain suffix: `%s'", toolchain[0])
            exit(EXIT_USER_ERROR)

        result['c_compiler'] = c_compiler_name
        result['cxx_compiler'] = cxx_compiler_name
        result['compiler_id'] = compiler_id
    elif toolchain[0] == 'msvc':
        result['c_compiler'] = 'cl.exe'
        result['cxx_compiler'] = 'cl.exe'
        result['compiler_id'] = 'msvc'
    else:
        _logger.error(
            "Unknown compiler in builtin toolchain: `%s'", toolchain[0])
        exit(EXIT_USER_ERROR)

    return result


def get_dds_toolchain(dds_tcfile: Optional[str]) -> DDSToolchain:
    if not dds_tcfile:
        return get_default_dds_toolchain()
    if dds_tcfile.startswith(':'):
        return get_builtin_toolchain(dds_tcfile)
    with open(dds_tcfile, 'r') as f:
        return json5.load(f)


def _removeprefix(s: str, prefix: str) -> str:
    if s.startswith(prefix):
        return s[len(prefix):]
    else:
        return s


class ToolchainGenerator:
    def __init__(self, dds_toolchain: DDSToolchain):
        self.result = []
        self.dds_toolchain = dds_toolchain

    @property
    def compiler_id(self) -> str:
        return self.dds_toolchain['compiler_id']

    @property
    def is_gnu_like(self) -> bool:
        return self.compiler_id in ('gnu', 'clang')

    @property
    def is_msvc(self) -> bool:
        return self.compiler_id == 'msvc'

    def nl(self):
        self.result.append('')  # we '\n'.join, so empty string = newline

    def set(self, var: str, value):
        name, var_type = (var.split(':', maxsplit=1) + ['STRING'])[:2]

        self.result.append(f'set({name} "{value}" CACHE {var_type} "")')

    def __unwrap_list(self, val):
        if isinstance(val, list):
            return ' '.join(val)
        else:
            return val

    def cset(self, var: str, fmt, *keys):
        if isinstance(fmt, str):
            fmt = fmt.format

        if any(key in self.dds_toolchain for key in keys):
            key_vals = [self.__unwrap_list(
                self.dds_toolchain.get(key, '')) for key in keys]
            self.set(var, fmt(*key_vals))

    def generate(self):
        DEFAULT_CXX_COMPILER = {
            'gnu': 'g++',
            'clang': 'clang++',
            'msvc': 'cl.exe',
        }
        DEFAULT_C_COMPILER = {
            'gnu': 'gcc',
            'clang': 'clang',
            'msvc': 'cl.exe',
        }

        dds_toolchain = self.dds_toolchain

        self.set('CMAKE_CXX_COMPILER:PATH', dds_toolchain.get(
            'cxx_compiler', DEFAULT_CXX_COMPILER[self.compiler_id]))
        self.set('CMAKE_C_COMPILER:PATH', dds_toolchain.get(
            'c_compiler', DEFAULT_C_COMPILER[self.compiler_id]))

        self.cset('CMAKE_CXX_STANDARD',
                  lambda std: _removeprefix(std, 'c++'), 'cxx_version')
        self.cset('CMAKE_C_STANDARD',
                  lambda std: _removeprefix(std, 'c'), 'c_version')
        self.set('CMAKE_CXX_EXTENSIONS:BOOL', str('gnu' in dds_toolchain.get(
            'lang_version_flag_template', '')).upper() if self.is_gnu_like else 'FALSE')
        self.nl()

        self.set('CMAKE_POSITION_INDEPENDENT_CODE:BOOL', 'YES')
        self.nl()

    def get(self) -> str:
        return '\n'.join(self.result) + '\n'


class ExtractSDistToolchainGenerator(ToolchainGenerator):
    def generate(self):
        super().generate()

        if self.dds_toolchain.get('debug', False):
            self.set('CMAKE_BUILD_TYPE', 'Debug')
        elif self.dds_toolchain.get('optimize', False):
            self.set('CMAKE_BUILD_TYPE', 'Release')


class FullCMakeCompileToolchainGenerator(ToolchainGenerator):
    def generate(self):
        super().generate()

        self.cset('CMAKE_CXX_FLAGS', '{0} {1}', 'flags', 'cxx_flags')
        self.cset('CMAKE_C_FLAGS', '{0} {1}', 'flags', 'c_flags')
        self.cset('CMAKE_EXE_LINKER_FLAGS', '{}', 'link_flags')
        self.cset('CMAKE_MODULE_LINKER_FLAGS', '{}', 'link_flags')
        self.cset('CMAKE_SHARED_LINKER_FLAGS', '{}', 'link_flags')
        self.cset('CMAKE_STATIC_LINKER_FLAGS', '{}', 'link_flags')
        self.nl()

        self.cset('CMAKE_CXX_LINK_EXECUTABLE',
                  self.link_exe_for('CXX'), 'link_executable')
        self.cset('CMAKE_C_LINK_EXECUTABLE',
                  self.link_exe_for('C'), 'link_executable')
        self.cset('CMAKE_CXX_CREATE_STATIC_LIBRARY',
                  self.create_ar_for('CXX'), 'create_archive')
        self.cset('CMAKE_C_CREATE_STATIC_LIBRARY',
                  self.create_ar_for('C'), 'create_archive')
        self.cset('CMAKE_CXX_COMPILE_OBJECT',
                  self.compile_obj_for('CXX'), 'cxx_compile_file')
        self.cset('CMAKE_C_COMPILE_OBJECT',
                  self.compile_obj_for('C'), 'c_compile_file')
        self.nl()

        self.cset('CMAKE_CXX_COMPILER_LAUNCHER:PATH',
                  '{}', 'compiler_launcher')
        self.cset('CMAKE_C_COMPILER_LAUNCHER:PATH', '{}', 'compiler_launcher')
        self.nl()

        self.cset('CMAKE_CXX_STANDARD',
                  lambda std: std.removeprefix('c++'), 'cxx_version')
        self.cset('CMAKE_C_STANDARD',
                  lambda std: std.removeprefix('c'), 'c_version')
        self.set('CMAKE_CXX_EXTENSIONS:BOOL', str('gnu' in self.dds_toolchain.get(
            'lang_version_flag_template', '')).upper() if self.is_gnu_like else 'FALSE')
        self.nl()

        self.set('CMAKE_POSITION_INDEPENDENT_CODE:BOOL', 'YES')
        self.nl()

        self.set('CMAKE_BUILD_TYPE', 'MetaDDS')

        self.set('CMAKE_CXX_FLAGS_METADDS',
                 f'{self.dbg_flags()} {self.opt_flags()} {self.rt_flags()}')
        self.set('CMAKE_C_FLAGS_METADDS',
                 f'{self.dbg_flags()} {self.opt_flags()} {self.rt_flags()}')
        self.set('CMAKE_EXE_LINKER_FLAGS_METADDS', f'')
        self.set('CMAKE_SHARED_LINKER_FLAGS_METADDS', f'')
        self.set('CMAKE_STATIC_LINKER_FLAGS_METADDS', f'')

    def link_exe_for(self, lang: str):
        def f(val: str):
            return (val.replace('<compiler>', f'<CMAKE_{lang}_COMPILER>')
                    .replace('[in]', '<OBJECTS>')
                    .replace('[out]', '<TARGET>')
                    .replace('[flags]', f'<FLAGS> <CMAKE_{lang}_LINK_FLAGS> <LINK_FLAGS> <LINK_LIBRARIES>'))

        return f

    def create_ar_for(self, lang: str):
        def f(val: str):
            return (re.sub(r'\b(ar)\b', '<CMAKE_AR>', val)
                    .replace('[in]', '<OBJECTS>')
                    .replace('[out]', '<TARGET>')
                    .replace('[flags]', f'<LINK_FLAGS>'))

        return f

    def compile_obj_for(self, lang: str):
        def f(val: str):
            return (val.replace('<compiler>', f'<CMAKE_{lang}_COMPILER>')
                    .replace('[in]', '<SOURCE>')
                    .replace('[out]', '<OBJECT>')
                    .replace('[flags]', f'<DEFINES> <INCLUDES> <FLAGS>'))

        return f

    def dbg_flags(self):
        if 'debug' not in self.dds_toolchain:
            return ''

        if self.dds_toolchain['debug'] == 'split':
            return '/Zi /FS' if self.is_msvc else '-gsplit-dwarf'
        elif self.dds_toolchain['debug'] == True or self.dds_toolchain['debug'] == 'embedded':
            return '/Z7' if self.is_msvc else '-g'
        else:
            return ''

    def opt_flags(self):
        if self.dds_toolchain.get('optimize', False):
            return '/O2' if self.is_msvc else '-O2'

    def rt_flags(self):
        if 'runtime' not in self.dds_toolchain:
            return ''

        is_static = self.dds_toolchain['runtime'].get(
            'static', True if self.is_msvc else False)
        is_debug = self.dds_toolchain['runtime'].get(
            'debug', True if self.is_msvc and self.dds_toolchain.get('debug', True) else False)

        if self.is_msvc:
            TD = 'T' if is_static else 'D'
            d = 'd' if is_debug else ''
            return f'/M{TD}{d}'
        elif self.is_gnu_like:
            static = '-static-libgcc -static-libstdc++' if is_static else ''
            debug = '-D_GLIBCXX_DEBUG -D_LIBCPP_DEBUG=1' if is_debug else ''
            return f'{static} {debug}'
        else:
            return ''


def generate_toolchain(dds_toolchain: DDSToolchain) -> str:
    tcg = ExtractSDistToolchainGenerator(dds_toolchain)
    tcg.generate()
    return tcg.get()


def generate_toolchain_for_full_cmake_compile(dds_toolchain: DDSToolchain) -> str:
    tcg = FullCMakeCompileToolchainGenerator(dds_toolchain)
    tcg.generate()
    return tcg.get()
