/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/.
 */

#pragma once

#include <dds/cli/options.hpp>
#include <dds/util/log.hpp>
#include <debate/argument_parser.hpp>

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

namespace meta_dds {
namespace fs = std::filesystem;
}

namespace meta_dds::cli {
/**
 * \brief Top-level meta-dds subcommands
 */
enum class subcommand {
    _none_,
    dds,
    pkg,
    repoman,
};

/**
 * @brief 'meta-dds pkg' subcommands
 */
enum class pkg_subcommand {
    _none_,
    ls,
    get,
    create,
    import,
    repo,
    search,
};

/**
 * @brief 'meta-dds repoman' subcommands
 */
enum class repoman_subcommand {
    _none_,
    init,
    import,
    add,
    remove,
    ls,
};

using dds::cli::if_exists;
using dds::cli::if_missing;
using dds_subcommand = dds::cli::subcommand;

struct options {
    using path       = fs::path;
    using opt_path   = std::optional<fs::path>;
    using string     = std::string;
    using opt_string = std::optional<std::string>;

    path cmake_exe;
    path dds_exe;

    // The top-most selected subcommand
    cli::subcommand subcommand;

    // DDS top-level options.
    dds::cli::options dds_options;

    dds::log::level& log_level = dds_options.log_level;

    /**
     * @brief Load a dds toolchain as specified by the user, or a default.
     * @return dds::toolchain
     */
    dds::toolchain load_toolchain() const;

    /**
     * @brief Parameters specific to 'meta-dds pkg'
     */
    struct {
        /// The 'meta-dds pkg' subcommand
        pkg_subcommand subcommand;
    } pkg;

    /**
     * @brief Parameters specific to 'meta-dds repoman'
     */
    struct {
        /// Shared parameter between repoman subcommands: The directory we are acting upon
        path repo_dir;

        /// The actual operation we are performing on the repository dir
        repoman_subcommand subcommand;

        /// Options for 'meta-dds repoman init'
        struct {
            /// The name of the new repository. If not provided, a random one will be generated
            opt_string name;
        } init;

        /// Options for 'meta-dds repoman import'
        struct {
            /// sdist tarball file paths to import into the repository
            std::vector<fs::path> files;
        } import;

        /// Options for 'meta-dds repoman add'
        struct {
            std::string url_str;
            std::string description;
        } add;

        /// Options for 'meta-dds repoman remove'
        struct {
            /// Package IDs of packages to remove
            std::vector<string> pkgs;
        } remove;
    } repoman;

    /**
     * @brief Attach arguments and subcommands to the given argument parser, binding those arguments
     * to the values in this object.
     */
    void setup_parser(debate::argument_parser& parser) noexcept;
};
}  // namespace meta_dds::cli
