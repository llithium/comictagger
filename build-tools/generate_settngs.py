from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import tempfile

import settngs

import comictaggerlib.main


def generate() -> str:
    app = comictaggerlib.main.App()
    app.load_plugins(app.initial_arg_parser.parse_known_args()[0])
    app.register_settings(True)
    imports, types = settngs.generate_dict(app.manager.definitions)
    imports2, types2 = settngs.generate_ns(app.manager.definitions)
    i = imports.splitlines()
    i.extend(set(imports2.splitlines()) - set(i))
    os.linesep
    return (os.linesep * 2).join((os.linesep.join(i), types2, types))


if __name__ == "__main__":
    src = generate()
    output_path = pathlib.Path("./comictaggerlib/ctsettings/settngs_namespace.py")
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as temporary_directory:
            generated_path = pathlib.Path(temporary_directory) / output_path.name
            generated_path.write_text(src, encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "isort",
                    "--af",
                    "--add-import",
                    "from __future__ import annotations",
                    str(generated_path),
                ],
                check=True,
            )
            subprocess.run([sys.executable, "-m", "black", str(generated_path)], check=True)
            generated = generated_path.read_text(encoding="utf-8")
        if output_path.read_text(encoding="utf-8") != generated:
            print(f"{output_path} is out of date; run the format environment to regenerate it")
            raise SystemExit(1)
    else:
        output_path.write_text(src, encoding="utf-8")
        print(src, end="")
