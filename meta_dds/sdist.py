'''
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
'''

'''
Describes the source distributions dealt with by meta-dds.
'''

import shutil
from typing import List
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from meta_dds.toolchain import DDSToolchain

class SDist:
    '''
    A "Source Distribution", or SDist, is a project setup consisting only of
    compilable files. This is what dds proper deals with.
    '''
    @abstractmethod
    def copy_to(self, dst: Path):
        ...

class ToolchainSpecificSDist(SDist):
    '''
    A toolchain specific SDist is an SDist for a particular toolchain. It is an
    invalid operation to distribute this as if it were toolchain-independent.
    '''
    pass

class SDistTemplate(ABC):
    '''
    A "Source Distribution Template", or SDistTemplate, is something that can
    be _instantiated_ to produce SDists. This may include running code
    generation tools.
    '''
    @abstractmethod
    def instantiate(self, toolchain: DDSToolchain) -> ToolchainSpecificSDist:
        ...

class PureSDist(ToolchainSpecificSDist, SDistTemplate):
    '''
    A pure SDist is a source distribution that doesn't care about the specifics
    of what it's being used for. This is what dds alone knows how to handle.
    Instantiation is a no-op.
    '''
    def instantiate(self, toolchain: Toolchain) -> PureSDist:
        return self

@dataclass(frozen=True)
class DirectorySDist(SDist):
    project_root: Path
    include_dirs: List[Path]
    source_dirs: List[Path]
    test_dirs: List[Path] = field(default_factory=list)

    def copy_to(self, dst: Path):
        src_dst = dst / 'src'
        include_dst = dst / 'include'
        test_dst = dst / 'test'
        for src_dir in self.source_dirs:
            shutil.copytree(src_dir, src_dst, dir_exist_ok=True)
        
        for include_dir in self.include_dirs:
            shutil.copytree(include_dir, include_dst, dir_exist_ok=True)

        for test_dir in self.test_dirs:
            shutil.copytree(test_dir, test_dst, dir_exist_ok=True)

@dataclass
class DirectoryPureSDist(PureSDist, DirectorySDist):
    pass
