/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/.
 */

#pragma once

#include <dds/deps.hpp>
#include <dds/util/fs.hpp>
#include <json5/data.hpp>

#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace meta_dds {
struct meta_dependency {
    dds::dependency                                  dep;
    std::vector<std::pair<std::string, std::string>> cmake_config;
};

/**
 * \brief Represents a `meta_package.json5` file
 */
struct package_manifest {
    /// The dependencies declared with the `depends` fields, if any.
    std::vector<dds::dependency> depends;
    /// The dependencies declared with the `test_depends` fields, if any.
    std::vector<dds::dependency> test_depends;

    /// The dependencies declared with the `meta_dds.depends` fields, if any.
    std::vector<meta_dependency> meta_depends;
    /// The dependencies declared with the 'meta_dds.test_depends' fields, if any.
    std::vector<meta_dependency> meta_test_depends;

    static package_manifest load(const json5::data& data, std::string_view fpath = "<memory>");
    static package_manifest load_from_json5_str(std::string_view, std::string_view input_name);
    static package_manifest load_from_file(dds::path_ref);
};
}  // namespace meta_dds
