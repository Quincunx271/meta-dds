/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/.
 */

#include "./package.hpp"

#include <boost/leaf/common.hpp>
#include <dds/error/errors.hpp>
#include <dds/sdist/package.hpp>
#include <dds/util/log.hpp>
#include <fmt/format.h>
#include <json5/parse_data.hpp>
#include <semester/walk.hpp>

using namespace meta_dds;

namespace {
using require_obj   = semester::require_type<json5::data::mapping_type>;
using require_array = semester::require_type<json5::data::array_type>;
using require_str   = semester::require_type<std::string>;
}  // namespace

package_manifest package_manifest::load(const json5::data& data, std::string_view) {
    try {
        package_manifest ret;

        using namespace semester::walk_ops;
        const auto push_depends_obj_kv = [&](std::string key, auto&& dat) {
            dds::dependency pending_dep;
            if (!dat.is_string()) {
                return walk.reject("Dependency object values should be strings");
            }
            try {
                auto            rng = semver::range::parse_restricted(dat.as_string());
                dds::dependency dep{std::move(key), {rng.low(), rng.high()}};
                ret.depends.push_back(std::move(dep));
            } catch (const semver::invalid_range&) {
                dds::throw_user_error<dds::errc::invalid_version_range_string>(
                    "Invalid version range string '{}' in dependency declaration for "
                    "'{}'",
                    dat.as_string(),
                    key);
            }
            return walk.accept;
        };

        const auto str_to_dependency
            = [](const std::string& s) { return dds::dependency::parse_depends_string(s); };

        const auto dependency = [&](auto& depends, std::string_view key_name) {
            return [&](auto&& dat) {
                if (dat.is_object()) {
                    return mapping{push_depends_obj_kv}(dat);
                } else if (dat.is_string()) {
                    return put_into{std::back_inserter(depends), str_to_dependency}(dat);
                } else {
                    return walk.reject(
                        fmt::format("`{}' should be an array of strings or objects", key_name));
                }
            };
        };

        const auto meta_dependency = [&](auto& depends, std::string_view key_name) {
            return [&](auto&& dat) {
                if (dat.is_object()) {
                    return mapping{push_depends_obj_kv}(dat);
                } else if (dat.is_string()) {
                    return put_into{std::back_inserter(depends), str_to_dependency}(dat);
                } else {
                    return walk.reject(
                        fmt::format("`{}' should be an array of strings or objects", key_name));
                }
            };
        };

        walk(data,
             require_obj{"Root of package manifest should be a JSON object"},
             mapping{
                 if_key{"depends",
                        require_array{"`depends' should be an array of dependencies"},
                        for_each{dependency(ret.depends, "depends")}},
                 if_key{"test_depends",
                        require_array{"`test_depends' should be an array of dependencies"},
                        for_each{dependency(ret.test_depends, "test_depends")}},
                 required_key{
                     "meta_dds",
                     "Do you really need meta-dds? Consider using dds proper. If you need the "
                     "build script, add an empty meta_dds: {} object in your meta_package.json5",
                     mapping{
                         if_key{"depends",
                                require_array{
                                    "`meta_dds.depends' should be an array of dependencies"},
                                for_each{meta_dependency(ret.meta_depends, "meta_dds.depends")}},
                         if_key{"test_depends",
                                require_array{
                                    "`meta_dds.test_depends' should be an array of dependencies"},
                                for_each{meta_dependency(ret.meta_test_depends,
                                                         "meta_dds.test_depends")}},
                     }},
             });

        return ret;
    } catch (const semester::walk_error& e) {
        // FIXME: use meta_dds error.
        dds::throw_user_error<dds::errc::invalid_pkg_manifest>(e.what());
    }
}

package_manifest package_manifest::load_from_json5_str(std::string_view content,
                                                       std::string_view input_name) {
    DDS_E_SCOPE(dds::e_package_manifest_path{std::string(input_name)});
    try {
        auto data = json5::parse_data(content);
        return load(data, input_name);
    } catch (const json5::parse_error& err) {
        // FIXME: use meta_dds error.
        BOOST_LEAF_THROW_EXCEPTION(dds::user_error<dds::errc::invalid_pkg_manifest>(
                                       "Invalid package manifest JSON5 document"),
                                   err,
                                   boost::leaf::e_file_name{std::string(input_name)});
    }
}

package_manifest package_manifest::load_from_file(dds::path_ref fpath) {
    DDS_E_SCOPE(dds::e_package_manifest_path{fpath.string()});
    auto content = dds::slurp_file(fpath);
    return load_from_json5_str(content, fpath.string());
}
