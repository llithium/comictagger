from __future__ import annotations

import textwrap

WINDOWS_RAR_HELP = textwrap.dedent("""
                To write to CBR/RAR archives,
                you will need to have the tools from
                [WINRar](http://www.win-rar.com/download.html)
                installed. (ComicTagger only uses the command-line rar tool.)

                A restart is needed for a new path to take effect.
                """)

LINUX_RAR_HELP = textwrap.dedent("""
                To write to CBR/RAR archives,
                you will need to have the shareware rar tool from RARLab installed.
                Your package manager should have rar (e.g. "apt-get install rar"). If not, download it
                from [RARLab](https://www.rarlab.com/download.htm),
                and install in your path.

                A restart is needed for a new path to take effect.
                """)

MAC_RAR_HELP = textwrap.dedent("""
                To write to CBR/RAR archives,
                you will need the rar tool.  The easiest way to get this is
                to install [homebrew](https://brew.sh/).

                Once homebrew is installed, run:
                ```bash
                brew install rar
                ```

                A restart is needed for a new path to take effect.
                """)
