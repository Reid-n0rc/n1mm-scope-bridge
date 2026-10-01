# SPDX-License-Identifier: GPL-3.0-only
# SPDX-FileCopyrightText: 2026 Reid Crowe, N0RC
"""One module per CLI command, discovered automatically (issue #44).

A command module defines:

- ``NAME``: the command name, for example ``"run"``
- ``HELP``: one-line help shown in ``--help``
- ``ORDER``: an int that sets its position in ``--help`` (lower first)
- ``register(subparsers) -> argparse.ArgumentParser``: adds its parser
- ``run(args, ctx) -> int``: does the work and returns the exit code

Adding a command means adding a module here, its tests
(``tests/cli/test_cli_<name>.py``), and its page (``docs/user/cli/<name>.md``).
No shared file changes. Frozen builds must collect these modules explicitly
(PyInstaller: ``collect_submodules("n1mm_scope_bridge.cli.commands")``).
"""
