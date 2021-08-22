/*
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/.
 */

#include "./options.hpp"

#include <dds/toolchain/toolchain.hpp>
#include <debate/enum.hpp>
#include <fansi/styled.hpp>

using meta_dds::cli::options;

namespace {
struct setup {
    options& opts;

    debate::argument if_exists_arg{
        .long_spellings = {"if-exists"},
        .help           = "What to do if the resource already exists",
        .valname        = "{replace,skip,fail}",
        .action         = debate::put_into(opts.dds_options.if_exists),
    };

    debate::argument if_missing_arg{
        .long_spellings = {"if-missing"},
        .help           = "What to do if the resource does not exist",
        .valname        = "{fail,ignore}",
        .action         = debate::put_into(opts.dds_options.if_missing),
    };

    debate::argument toolchain_arg{
        .long_spellings  = {"toolchain"},
        .short_spellings = {"t"},
        .help            = "The toolchain to use when building",
        .valname         = "<file-or-id>",
        .action          = debate::put_into(opts.dds_options.toolchain),
    };

    debate::argument project_arg{
        .long_spellings  = {"project"},
        .short_spellings = {"p"},
        .help            = "The project to build. If not given, uses the current working directory",
        .valname         = "<project-path>",
        .action          = debate::put_into(opts.dds_options.project_dir),
    };

    debate::argument no_warn_arg{
        .long_spellings = {"no-warn", "no-warnings"},
        .help           = "Disable build warnings",
        .nargs          = 0,
        .action         = debate::store_true(opts.dds_options.disable_warnings),
    };

    debate::argument out_arg{
        .long_spellings  = {"out", "output"},
        .short_spellings = {"o"},
        .help            = "Path to the output",
        .valname         = "<path>",
        .action          = debate::put_into(opts.dds_options.out_path),
    };

    debate::argument jobs_arg{
        .long_spellings  = {"jobs"},
        .short_spellings = {"j"},
        .help            = "Set the maximum number of parallel jobs to execute",
        .valname         = "<job-count>",
        .action          = debate::put_into(opts.dds_options.jobs),
    };

    debate::argument repoman_repo_dir_arg{
        .help     = "The directory of the repository to manage",
        .valname  = "<repo-dir>",
        .required = true,
        .action   = debate::put_into(opts.repoman.repo_dir),
    };

    void setup_pkg_cmd(debate::argument_parser& parser) noexcept {
        parser.add_argument(toolchain_arg.dup());
    }

    void setup_repoman_cmd(debate::argument_parser& parser) noexcept {
        parser.add_argument(toolchain_arg.dup());
    }

    void setup_dds_cmd(debate::argument_parser& parser) noexcept {
        opts.dds_options.setup_parser(parser);
    }

    void setup_main_commands(debate::subparser_group& group) noexcept {
        setup_pkg_cmd(group.add_parser({
            .name = "pkg",
            .help = "Manage meta-packages and package remotes",
        }));
        setup_repoman_cmd(group.add_parser({
            .name = "repoman",
            .help = "Manage a meta-dds repository",
        }));
        setup_dds_cmd(group.add_parser({
            .name = "dds",
            .help = "Run DDS",
        }));
    }
};
}  // namespace

dds::toolchain options::load_toolchain() const { return dds_options.load_toolchain(); }

void options::setup_parser(debate::argument_parser& parser) noexcept {
    parser.add_argument({
        .long_spellings  = {"log-level"},
        .short_spellings = {"l"},
        .help            = ""
                           "Set the dds logging level. One of 'trace', 'debug', 'info', \n"
                           "'warn', 'error', 'critical', or 'silent'",
        .valname         = "<level>",
        .action          = debate::put_into(log_level),
    });

    setup(*this).setup_main_commands(parser.add_subparsers({
        .description = "The operation to perform",
        .action      = debate::put_into(subcommand),
    }));
}
